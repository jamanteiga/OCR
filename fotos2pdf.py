#!/usr/bin/env python3
"""
fotos2pdf.py - Carpeta de fotos (HEIC/JPG/PNG) -> enderezar + limpiar -> UN solo PDF (opcional: con OCR).

Instalación (una vez, en el PC):
    pip install pillow pillow-heif opencv-python numpy img2pdf
    (opcional OCR)  pip install ocrmypdf   + instalar Tesseract (con idioma spa) y Ghostscript

Uso:
    python fotos2pdf.py CARPETA_FOTOS salida.pdf
    python fotos2pdf.py CARPETA_FOTOS salida.pdf --modo gris --ocr --lang spa
Modos: color (por defecto, fondo blanqueado) | gris | bn (blanco y negro, ideal texto)
Las páginas salen en orden alfabético del nombre de archivo (IMG_0001, IMG_0002...).
Las páginas dudosas (no se detectó el folio) se listan al final para revisarlas.
"""
import argparse, sys, os, tempfile, shutil, subprocess
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    print("Aviso: sin pillow-heif no se leerán .HEIC (pip install pillow-heif)")

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
MAXDIM = 3000  # lado máximo de trabajo (px); suficiente para ~300 ppp en A4


def cargar(path):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > MAXDIM:
        im.thumbnail((MAXDIM, MAXDIM), Image.LANCZOS)
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def ordenar_pts(p):
    s, d = p.sum(1), np.diff(p, axis=1).ravel()
    return np.array([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]], np.float32)


def encontrar_folio(img):
    """Devuelve 4 puntos del folio o None."""
    h, w = img.shape[:2]
    esc = 800 / max(h, w)
    peq = cv2.resize(img, None, fx=esc, fy=esc)
    g = cv2.GaussianBlur(cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    candidatos = []
    # 1) umbral Otsu (folio claro sobre fondo más oscuro) 2) bordes Canny
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    ed = cv2.dilate(cv2.Canny(g, 40, 120), np.ones((5, 5), np.uint8))
    for m in (th, ed):
        cnts, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:3]:
            if cv2.contourArea(c) < 0.25 * peq.shape[0] * peq.shape[1]:
                continue
            ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(ap) == 4 and cv2.isContourConvex(ap):
                candidatos.append(ap.reshape(4, 2).astype(np.float32))
                break
        if candidatos:
            break
    if not candidatos:
        return None
    return ordenar_pts(candidatos[0] / esc)


def perspectiva(img, pts):
    tl, tr, br, bl = pts
    W = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    H = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(pts, dst), (W, H), flags=cv2.INTER_CUBIC)


def enderezar_por_texto(img):
    """Fallback: corrige la inclinación pequeña a partir de las líneas de texto."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(cv2.GaussianBlur(g, (5, 5), 0), 255,
                               cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    coords = cv2.findNonZero(cv2.dilate(bw, np.ones((3, 25), np.uint8)))
    if coords is None:
        return img
    ang = cv2.minAreaRect(coords)[-1]
    ang = ang - 90 if ang > 45 else ang
    if abs(ang) < 0.3 or abs(ang) > 15:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _binaria(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    e = 1000 / max(g.shape)
    g = cv2.resize(g, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
    bw = cv2.adaptiveThreshold(cv2.GaussianBlur(g, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    m = int(0.03 * min(bw.shape))
    return (bw[m:-m, m:-m] > 0).astype(np.float32)


def _cv(v):
    return v.std() / (v.mean() + 1e-6)


def _giro_osd(img):
    """Orientación con Tesseract OSD (fiable). Devuelve grados horarios a girar, o None."""
    import shutil, subprocess, re, os
    exe = shutil.which("tesseract")
    if not exe:
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(c):
                exe = c
                break
    if not exe:
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    e = 1600 / max(g.shape)
    if e < 1:
        g = cv2.resize(g, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.png")
        cv2.imwrite(p, g)
        try:
            r = subprocess.run([exe, p, "stdout", "--psm", "0"], capture_output=True, text=True, timeout=60)
        except Exception:
            return None
    m = re.search(r"Rotate:\s*(\d+)", r.stdout)
    c = re.search(r"Orientation confidence:\s*([\d.]+)", r.stdout)
    if not m or not c or float(c.group(1)) < 1.5:
        return None
    return int(m.group(1))


def _giro_heuristico(img):
    """Sin Tesseract: líneas horizontales/verticales por perfiles; arriba/abajo por ascendentes."""
    bw = _binaria(img)
    if bw.sum() < 500:
        return 0
    vertical = _cv(bw.sum(0)) > 1.15 * _cv(bw.sum(1))   # las líneas de texto van en columnas
    if vertical:
        bw = np.rot90(bw, -1)  # 90 horario; luego se decide si está boca abajo
    p = cv2.GaussianBlur(bw.sum(1).reshape(-1, 1), (1, 1), 0).ravel()
    p = np.convolve(p, np.ones(5) / 5, mode="same")
    activa = p > 0.06 * p.max()
    arriba = abajo = 0.0
    i, n = 0, len(p)
    while i < n:
        if activa[i]:
            j = i
            while j < n and activa[j]:
                j += 1
            if 8 <= j - i <= 80:
                b = bw[i:j].sum(1)
                nucleo = np.where(b > 0.5 * b.max())[0]   # altura de las minúsculas
                arriba += b[:nucleo[0]].sum()              # ascendentes y mayúsculas
                abajo += b[nucleo[-1] + 1:].sum()          # descendentes
            i = j
        else:
            i += 1
    boca_abajo = abajo > 1.12 * arriba and (abajo + arriba) > 0
    if vertical:
        return 270 if boca_abajo else 90
    return 180 if boca_abajo else 0


def orientar(img):
    g = _giro_osd(img)
    if g is None:
        g = _giro_heuristico(img)
    if g == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if g == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if g == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def limpiar(img, modo):
    # quita sombras/degradados: divide por el fondo estimado
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = max(31, (min(g.shape) // 20) | 1)
    fondo = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), k)
    if modo == "color":
        fondo3 = cv2.cvtColor(fondo, cv2.COLOR_GRAY2BGR)
        out = cv2.divide(img, fondo3, scale=255)
        return np.clip((out.astype(np.float32) - 110) * (255 / 125.0), 0, 255).astype(np.uint8)
    norm = cv2.divide(g, fondo, scale=255)
    if modo == "gris":
        return np.clip((norm.astype(np.float32) - 110) * (255 / 125.0), 0, 255).astype(np.uint8)
    return cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 22)


AUTOGIRO = True

def hilos_auto():
    return max(1, (os.cpu_count() or 2) // 2) if LIBRO else 1


LIBRO = False   # True = fotos de libro: aplanar la curvatura de la hoja


def dewarp_libro(img):
    """Aplana una hoja curvada con page-dewarp (pip install page-dewarp). Devuelve gris o None."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "pag.jpg")
        cv2.imwrite(src, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        try:
            r = subprocess.run([sys.executable, "-m", "page_dewarp", "-o", d, "-nb", "1",
                                "-x", "15", "-y", "10", "-tw", "90", "-sw", "90", src],
                               capture_output=True, text=True, timeout=300)
        except Exception:
            return None
        out = os.path.join(d, "pag_thresh.png")
        if r.returncode != 0 or not os.path.exists(out):
            return None
        g = cv2.imread(out, cv2.IMREAD_GRAYSCALE)
        return g


def recortar_pagina(g):
    """Recorta al bloque de texto de la página principal: busca líneas de texto largas
    (la hoja vecina solo aporta fragmentos cortos) y se queda con su caja + margen."""
    h, w = g.shape
    k = max(31, (min(g.shape) // 20) | 1)
    fondo = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), k)
    n = cv2.divide(g, fondo, scale=255)
    ink = (n < 150).astype(np.uint8) * 255
    kx = max(3, int(0.02 * w)) | 1
    lin = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 1)))
    lin = cv2.morphologyEx(lin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    nc, _, st, _ = cv2.connectedComponentsWithStats(lin, connectivity=8)
    cajas = [(x, y, x + ww, y + hh) for x, y, ww, hh, a in st[1:]
             if ww >= 0.22 * w and 0.006 * h <= hh <= 0.07 * h]
    if len(cajas) < 3:
        return g
    c = np.array(cajas)
    # percentiles: los fragmentos de la hoja vecina quedan como valores atípicos
    x0, x1 = int(np.percentile(c[:, 0], 20)), int(np.percentile(c[:, 2], 80))
    y0, y1 = int(c[:, 1].min()), int(c[:, 3].max())
    px, py = int(0.04 * w), int(0.03 * h)
    x0, x1 = max(0, x0 - px), min(w, x1 + px)
    y0, y1 = max(0, y0 - py), min(h, y1 + py)
    if (x1 - x0) * (y1 - y0) < 0.30 * w * h:
        return g
    return g[y0:y1, x0:x1]


def procesar(path, modo):
    img = cargar(path)
    if LIBRO:
        if AUTOGIRO:
            img = orientar(img)
        g = dewarp_libro(img)
        if g is not None:
            g = recortar_pagina(g)
            return limpiar(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), modo), False
        # si falla el aplanado, se sigue con el método normal y se marca como dudosa
        return limpiar(img, modo), True
    pts = encontrar_folio(img)
    dudosa = pts is None
    if not dudosa:
        img = perspectiva(img, pts)
    img = enderezar_por_texto(img)
    if AUTOGIRO:
        img = orientar(img)
    return limpiar(img, modo), dudosa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta")
    ap.add_argument("salida")
    ap.add_argument("--modo", choices=["color", "gris", "bn"], default="color")
    ap.add_argument("--calidad", type=int, default=82, help="calidad JPEG (color/gris)")
    ap.add_argument("--ocr", action="store_true", help="añadir capa de texto con ocrmypdf")
    ap.add_argument("--lang", default="spa")
    ap.add_argument("--libro", action="store_true", help="fotos de libro: aplanar la curvatura de las hojas (necesita page-dewarp)")
    ap.add_argument("--hilos", type=int, default=0, help="paginas en paralelo (0 = automatico)")
    ap.add_argument("--sin-giro", action="store_true", help="no girar automáticamente según el texto")
    a = ap.parse_args()
    global AUTOGIRO, LIBRO
    AUTOGIRO = not a.sin_giro
    LIBRO = a.libro

    import img2pdf
    fotos = sorted(p for p in Path(a.carpeta).iterdir() if p.suffix.lower() in EXTS)
    if not fotos:
        sys.exit("No hay imágenes en la carpeta.")
    tmp = Path(tempfile.mkdtemp(prefix="f2p_"))
    salidas, dudosas = [], []
    ext = "png" if a.modo == "bn" else "jpg"

    def tarea(par):
        i, f = par
        im, dud = procesar(f, a.modo)
        dst = tmp / f"{i:04d}.{ext}"
        cv2.imwrite(str(dst), im, [cv2.IMWRITE_PNG_COMPRESSION, 9] if ext == "png" else [cv2.IMWRITE_JPEG_QUALITY, a.calidad])
        return str(dst), dud

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=a.hilos or hilos_auto()) as ex:
        futs = [(i, f, ex.submit(tarea, (i, f))) for i, f in enumerate(fotos, 1)]
        for i, f, fu in futs:
            try:
                dst, dud = fu.result()
            except Exception as e:
                print(f"[{i}/{len(fotos)}] ERROR {f.name}: {e}")
                continue
            if dud:
                dudosas.append(f.name)
            salidas.append(dst)
            print(f"[{i}/{len(fotos)}] {f.name}{'  (revisar)' if dud else ''}")

    bruto = Path(a.salida)
    with open(bruto, "wb") as fh:
        fh.write(img2pdf.convert(salidas))
    if a.ocr:
        tmp_pdf = bruto.with_suffix(".ocr.pdf")
        try:
            r = subprocess.run([sys.executable, "-m", "ocrmypdf", "-l", a.lang, "--optimize", "1", str(bruto), str(tmp_pdf)])
            if r.returncode == 0:
                tmp_pdf.replace(bruto)
            else:
                print("OCR falló; se deja el PDF sin capa de texto.")
        except Exception as e:
            print("OCR no disponible:", e)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nListo: {bruto}  ({len(salidas)} páginas)")
    if dudosas:
        print("Revisar (no se detectó el folio, solo se limpió):", ", ".join(dudosas))


if __name__ == "__main__":
    main()
