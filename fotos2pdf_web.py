#!/usr/bin/env python3
"""
Interfaz web local para fotos2pdf.py (deben estar en la misma carpeta).
    python fotos2pdf_web.py
Se abre http://127.0.0.1:8765 en el navegador. Todo se procesa en tu PC (nada se sube a internet).
"""
import json, sys, os, io, glob, threading, webbrowser, tempfile, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import cv2
import fotos2pdf as f2p

PORT = 8765
TMP = Path(tempfile.mkdtemp(prefix="f2p_web_"))
S = {"estado": "reposo", "total": 0, "hechas": 0, "paginas": [], "dudosas": [], "errores": [],
     "pdf": None, "msg": ""}
LOCK = threading.Lock()


def trabajo(carpeta, modo, calidad, ocr, lang, salida, libro):
    import img2pdf
    try:
        fotos = sorted(p for p in Path(carpeta).iterdir() if p.suffix.lower() in f2p.EXTS)
        if not fotos:
            raise RuntimeError("No hay imágenes en esa carpeta.")
        f2p.LIBRO = bool(libro)
        shutil.rmtree(TMP, ignore_errors=True); TMP.mkdir(parents=True)
        with LOCK:
            S.update(estado="procesando", total=len(fotos), hechas=0, paginas=[], dudosas=[], errores=[], pdf=None, msg="")
        rutas = []
        ext = "png" if modo == "bn" else "jpg"

        def tarea(par):
            i, f = par
            im, dud = f2p.procesar(f, modo)
            dst = TMP / f"{i:04d}.{ext}"
            cv2.imwrite(str(dst), im, [cv2.IMWRITE_PNG_COMPRESSION, 9] if ext == "png" else [cv2.IMWRITE_JPEG_QUALITY, calidad])
            h, w = im.shape[:2]; e = 300 / max(h, w)
            cv2.imwrite(str(TMP / f"t{i:04d}.jpg"), cv2.resize(im, None, fx=e, fy=e, interpolation=cv2.INTER_AREA))
            return str(dst), dud

        with ThreadPoolExecutor(max_workers=f2p.hilos_auto()) as ex:
            futs = [(i, f, ex.submit(tarea, (i, f))) for i, f in enumerate(fotos, 1)]
            for i, f, fu in futs:
                try:
                    dst, dud = fu.result()
                    rutas.append(dst)
                    with LOCK:
                        S["paginas"].append({"n": i, "nombre": f.name, "dudosa": dud})
                        if dud: S["dudosas"].append(f.name)
                except Exception as ex_:
                    with LOCK: S["errores"].append(f"{f.name}: {ex_}")
                with LOCK: S["hechas"] = i
        with LOCK: S["estado"] = "creando_pdf"
        pdf = Path(salida) if salida else Path(carpeta) / "resultado.pdf"
        pdf.write_bytes(img2pdf.convert(rutas))
        if ocr:
            with LOCK: S["estado"] = "ocr"
            tmp_pdf = pdf.with_suffix(".ocr.pdf")
            try:
                r = subprocess.run([sys.executable, "-m", "ocrmypdf", "-l", lang, "--optimize", "1", str(pdf), str(tmp_pdf)],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    tmp_pdf.replace(pdf)
                else:
                    S["msg"] = "OCR no se pudo aplicar (revisa Tesseract y Ghostscript): " + (r.stderr or "")[-300:] + " — PDF guardado sin capa de texto."
            except Exception as e_:
                S["msg"] = f"OCR no disponible ({e_}). PDF guardado sin capa de texto."
        with LOCK: S.update(estado="listo", pdf=str(pdf))
    except Exception as ex:
        with LOCK: S.update(estado="error", msg=str(ex))


# ---------------- Modo "pantallazos pegados" (index.html) ----------------
from PIL import Image
PASTE = Path(tempfile.mkdtemp(prefix="f2p_paste_"))
P = {"estado": "reposo", "hechas": 0, "total": 0, "pdf": None, "msg": "", "ocr_ok": None}
PLOCK = threading.Lock()
_NEXT = [0]


def guardar_como():
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
    d = filedialog.asksaveasfilename(title="¿Dónde guardo el PDF?", defaultextension=".pdf",
                                     initialfile="pantallazos.pdf", filetypes=[("PDF", "*.pdf")])
    r.destroy()
    return d


def subir_imagen(data):
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P") and (im.mode != "P" or "transparency" in im.info):
        im = im.convert("RGBA"); fondo = Image.new("RGB", im.size, "white"); fondo.paste(im, mask=im.split()[3]); im = fondo
    else:
        im = im.convert("RGB")
    with PLOCK:
        _NEXT[0] += 1; i = _NEXT[0]
    im.save(PASTE / f"{i:05d}.png")
    t = im.copy(); t.thumbnail((240, 240)); t.save(PASTE / f"t{i:05d}.jpg", quality=80)
    return i


def entorno_ocr():
    """PATH ampliado con las rutas habituales de Tesseract y Ghostscript en Windows."""
    env = os.environ.copy()
    extra = [r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"]
    extra += glob.glob(r"C:\Program Files\gs\gs*\bin") + glob.glob(r"C:\Program Files (x86)\gs\gs*\bin")
    env["PATH"] = os.pathsep.join([e for e in extra if os.path.isdir(e)] + [env.get("PATH", "")])
    return env


def trabajo_pegado(ids, ruta, ocr, lang, jpeg, calidad):
    import img2pdf
    try:
        with PLOCK:
            P.update(estado="preparando", total=len(ids), hechas=0, pdf=None, msg="", ocr_ok=None)
        rutas = []
        for n, i in enumerate(ids, 1):
            src = PASTE / f"{i:05d}.png"
            if jpeg:
                dst = PASTE / f"{i:05d}.jpg"
                Image.open(src).convert("RGB").save(dst, "JPEG", quality=calidad, optimize=True)
                rutas.append(str(dst))
            else:
                rutas.append(str(src))
            with PLOCK: P["hechas"] = n
        with PLOCK: P["estado"] = "creando_pdf"
        pdf = Path(ruta); pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(img2pdf.convert(rutas, layout_fun=img2pdf.get_fixed_dpi_layout_fun((150, 150))))
        if ocr:
            with PLOCK: P["estado"] = "ocr"
            tmp_pdf = pdf.with_suffix(".ocr.pdf")
            try:
                r = subprocess.run([sys.executable, "-m", "ocrmypdf", "-l", lang, "--output-type", "pdf",
                                    "--optimize", "1", str(pdf), str(tmp_pdf)],
                                   capture_output=True, text=True, env=entorno_ocr())
                if r.returncode == 0:
                    tmp_pdf.replace(pdf)
                    with PLOCK: P["ocr_ok"] = True
                else:
                    with PLOCK:
                        P["ocr_ok"] = False
                        P["msg"] = "OCR no se pudo aplicar (revisa Tesseract, idioma y Ghostscript): " + (r.stderr or "")[-400:] + " — PDF guardado sin capa de texto."
            except Exception as e_:
                with PLOCK:
                    P["ocr_ok"] = False
                    P["msg"] = f"OCR no disponible ({e_}). PDF guardado sin capa de texto."
        with PLOCK: P.update(estado="listo", pdf=str(pdf))
    except Exception as ex:
        with PLOCK: P.update(estado="error", msg=str(ex))


def elegir_carpeta():
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
    d = filedialog.askdirectory(title="Carpeta con las fotos"); r.destroy()
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            idx = Path(__file__).with_name("index.html")
            self._send(200, idx.read_bytes() if idx.exists() else HTML, "text/html; charset=utf-8")
        elif self.path == "/carpetas":
            self._send(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/guardar_como":
            self._send(200, json.dumps({"ruta": guardar_como()}))
        elif self.path == "/estado_p":
            with PLOCK: self._send(200, json.dumps(P))
        elif self.path.startswith("/pthumb/"):
            p = PASTE / Path(self.path[8:]).name
            if p.exists(): self._send(200, p.read_bytes(), "image/png" if p.suffix == ".png" else "image/jpeg")
            else: self._send(404, "")
        elif self.path == "/pdf_p":
            if P["pdf"] and Path(P["pdf"]).exists(): self._send(200, Path(P["pdf"]).read_bytes(), "application/pdf")
            else: self._send(404, "")
        elif self.path == "/estado":
            with LOCK: self._send(200, json.dumps(S))
        elif self.path == "/carpeta":
            self._send(200, json.dumps({"ruta": elegir_carpeta()}))
        elif self.path.startswith("/img/"):
            p = TMP / Path(self.path[5:]).name
            if p.exists(): self._send(200, p.read_bytes(), "image/jpeg")
            else: self._send(404, "")
        elif self.path == "/pdf":
            if S["pdf"] and Path(S["pdf"]).exists(): self._send(200, Path(S["pdf"]).read_bytes(), "application/pdf")
            else: self._send(404, "")
        else:
            self._send(404, "")

    def do_POST(self):
        if self.path == "/subir":
            data = self.rfile.read(int(self.headers["Content-Length"]))
            try:
                self._send(200, json.dumps({"id": subir_imagen(data)}))
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}))
        elif self.path == "/borrar":
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            for pat in (f"{int(d['id']):05d}.*", f"t{int(d['id']):05d}.jpg"):
                for f in PASTE.glob(pat): f.unlink(missing_ok=True)
            self._send(200, "{}")
        elif self.path == "/vaciar":
            for f in PASTE.iterdir(): f.unlink(missing_ok=True)
            with PLOCK: P.update(estado="reposo", pdf=None, msg="", ocr_ok=None)
            self._send(200, "{}")
        elif self.path == "/generar":
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if P["estado"] in ("preparando", "creando_pdf", "ocr"):
                return self._send(409, json.dumps({"error": "ya en curso"}))
            if not d.get("ids") or not d.get("ruta"):
                return self._send(400, json.dumps({"error": "faltan datos"}))
            threading.Thread(target=trabajo_pegado, args=([int(i) for i in d["ids"]], d["ruta"], bool(d.get("ocr")),
                             d.get("lang", "spa"), bool(d.get("jpeg", True)), int(d.get("calidad", 90))), daemon=True).start()
            self._send(200, "{}")
        elif self.path == "/iniciar":
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if S["estado"] in ("procesando", "creando_pdf", "ocr"):
                return self._send(409, json.dumps({"error": "ya en curso"}))
            threading.Thread(target=trabajo, args=(d["carpeta"], d["modo"], int(d.get("calidad", 82)),
                             bool(d["ocr"]), d.get("lang", "spa"), d.get("salida", ""), bool(d.get("libro"))), daemon=True).start()
            self._send(200, "{}")


HTML = r"""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fotos → PDF</title>
<style>
:root{--bg:#f6f7f9;--c:#fff;--t:#1c2330;--m:#667085;--a:#2457d6;--b:#d8dce3;--ok:#177a43;--w:#b54708}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:15px system-ui,Segoe UI,sans-serif}
main{max-width:980px;margin:24px auto;padding:0 16px}h1{font-size:22px;margin:0 0 16px}
.card{background:var(--c);border:1px solid var(--b);border-radius:10px;padding:16px;margin-bottom:16px}
label{display:block;font-weight:600;margin:10px 0 4px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:220px;padding:8px 10px;border:1px solid var(--b);border-radius:6px;font:inherit}
select,button{padding:8px 12px;border:1px solid var(--b);border-radius:6px;font:inherit;background:#fff}
button.p{background:var(--a);color:#fff;border-color:var(--a);font-weight:600;cursor:pointer}button:disabled{opacity:.5}
.bar{height:10px;background:#e6e9ef;border-radius:6px;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;width:0;background:var(--a);transition:width .2s}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
.g{border:1px solid var(--b);border-radius:6px;overflow:hidden;background:#fff;font-size:12px;color:var(--m)}
.g img{width:100%;display:block;aspect-ratio:3/4;object-fit:contain;background:#eef0f4;cursor:zoom-in}.g div{padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g.d{border-color:var(--w)}.g.d div{color:var(--w);font-weight:600}.m{color:var(--m)}.ok{color:var(--ok);font-weight:600}.er{color:#b42318}
#big{position:fixed;inset:0;background:#000d;display:none;align-items:center;justify-content:center;z-index:9}#big img{max-width:95vw;max-height:95vh;background:#fff}
</style><main>
<h1>Fotos → PDF (enderezar y limpiar) &nbsp;<a href="/" style="font-size:14px">← Pantallazos pegados</a></h1>
<div class="card">
 <label>Carpeta con las fotos</label>
 <div class="row"><input type="text" id="carpeta" placeholder="C:\Users\...\Fotos iCloud\lote1"><button onclick="elegir()">Examinar…</button></div>
 <div class="row" style="margin-top:6px">
  <div><label>Modo</label><select id="modo"><option value="color">Color (fondo blanqueado)</option><option value="gris">Gris</option><option value="bn">Blanco y negro (texto)</option></select></div>
  <div><label>Calidad JPEG</label><input type="text" id="calidad" value="82" style="min-width:0;width:70px"></div>
  <div><label>&nbsp;</label><label style="font-weight:400;margin:0"><input type="checkbox" id="libro" checked> Fotos de libro (aplanar hojas)</label></div>
  <div><label>&nbsp;</label><label style="font-weight:400;margin:0"><input type="checkbox" id="ocr"> OCR (texto buscable)</label></div>
  <div><label>Idioma OCR</label><input type="text" id="lang" value="spa" style="min-width:0;width:80px"></div>
 </div>
 <label>PDF de salida (opcional)</label><input type="text" id="salida" style="width:100%" placeholder="vacío = resultado.pdf dentro de la carpeta de fotos">
 <div class="row" style="margin-top:14px"><button class="p" id="go" onclick="iniciar()">Procesar y crear PDF</button><span id="st" class="m"></span></div>
 <div class="bar"><i id="pb"></i></div>
 <div id="fin"></div>
</div>
<div class="card"><b>Páginas procesadas</b> <span class="m">(en naranja: no se detectó el folio; revísalas. Clic para ampliar)</span><div class="grid" id="grid" style="margin-top:10px"></div></div>
<div id="big" onclick="this.style.display='none'"><img></div>
</main>
<script>
const $=i=>document.getElementById(i);let pintadas=0;
async function elegir(){$('st').textContent='Abriendo selector…';const r=await (await fetch('/carpeta')).json();if(r.ruta)$('carpeta').value=r.ruta.replace(/\//g,'\\');$('st').textContent=''}
async function iniciar(){if(!$('carpeta').value)return alert('Indica la carpeta');pintadas=0;$('grid').innerHTML='';$('fin').innerHTML='';
 await fetch('/iniciar',{method:'POST',body:JSON.stringify({carpeta:$('carpeta').value,modo:$('modo').value,calidad:$('calidad').value,ocr:$('ocr').checked,libro:$('libro').checked,lang:$('lang').value,salida:$('salida').value})});poll()}
function ampliar(n){const b=$('big');b.querySelector('img').src='/img/'+n;b.style.display='flex'}
async function poll(){const s=await (await fetch('/estado')).json();
 const lab={reposo:'',procesando:`Procesando ${s.hechas}/${s.total}`,creando_pdf:'Creando PDF…',ocr:'Aplicando OCR (puede tardar)…',listo:'Terminado',error:'Error'}[s.estado];
 $('st').textContent=lab;$('pb').style.width=(s.total?100*s.hechas/s.total:0)+'%';$('go').disabled=['procesando','creando_pdf','ocr'].includes(s.estado);
 for(;pintadas<s.paginas.length;pintadas++){const p=s.paginas[pintadas],n=String(p.n).padStart(4,'0');
  const d=document.createElement('div');d.className='g'+(p.dudosa?' d':'');
  d.innerHTML=`<img src="/img/t${n}.jpg" onclick="ampliar('${n}.${$('modo').value=='bn'?'png':'jpg'}')"><div>${p.n}. ${p.nombre}${p.dudosa?' ⚠':''}</div>`;$('grid').appendChild(d)}
 let f='';if(s.msg)f+=`<p class="er">${s.msg}</p>`;if(s.errores.length)f+=`<p class="er">Errores: ${s.errores.join('; ')}</p>`;
 if(s.estado=='listo')f+=`<p class="ok">PDF guardado en: ${s.pdf} · <a href="/pdf" target="_blank">Abrir PDF</a></p>`;$('fin').innerHTML=f;
 if(['procesando','creando_pdf','ocr'].includes(s.estado))setTimeout(poll,600)}
poll();
</script></html>"""

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Abre http://127.0.0.1:{PORT}  (Ctrl+C para salir)")
    threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
