# Fotos y pantallazos → PDF con OCR (PWA)

Aplicación web que funciona 100 % en el dispositivo (sin servidor; nada se sube a internet).

- **Cámara**: botón *Activar cámara* → *Capturar* tantas veces como haga falta (1000+). Cada foto se guarda al instante en el dispositivo (IndexedDB), así que no se pierde si se cierra la app. Alternativa: *Cámara del sistema* (cámara nativa del móvil).
- **Pantallazos**: Ctrl+V, arrastrar o elegir imágenes.
- **Generar PDF…** → un único PDF (o partes de 200/400 páginas) con OCR en español, inglés o ambos. Pregunta dónde guardarlo (Chrome/Edge en ordenador). En móvil, al terminar: *Guardar / compartir* → *Guardar en Archivos*.
- Instalable como app (PWA) y disponible sin conexión.

## Archivos
```
index.html              app completa (~18 MB: pdf-lib + Tesseract.js + datos spa/eng incluidos)
manifest.webmanifest    datos de la PWA
sw.js                   service worker (modo sin conexión)
icons/                  iconos
```

## Publicar en GitHub Pages
1. Sube todo el contenido (con la carpeta `icons`) a la raíz del repositorio.
2. *Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main` / `(root)` → Save*.
3. Abre `https://<usuario>.github.io/<repositorio>/` (HTTPS imprescindible para la cámara y la PWA).

## Instalar
- **iPhone (Safari)**: Compartir → *Añadir a pantalla de inicio*.
- **Android (Chrome)**: menú ⋮ → *Instalar aplicación*.
- **Ordenador (Chrome/Edge)**: icono de instalar en la barra de direcciones.

## Actualizar
Al cambiar `index.html`, sube el número de `VERSION` en `sw.js` (p. ej. `fotos2pdf-v2`) para que los dispositivos descarguen la nueva versión.

## Consejos
- Durante el OCR de cientos de páginas mantén la pantalla encendida y la app en primer plano (la app pide al sistema no apagar la pantalla).
- En móvil, con más de ~400 páginas usa «Dividir el PDF» en partes para no agotar la memoria.
- Para guardar un PDF grande en el móvil el sistema muestra la hoja de compartir; elige *Guardar en Archivos*.

## Licencias
[pdf-lib](https://pdf-lib.js.org/) (MIT), [Tesseract.js](https://github.com/naptha/tesseract.js) (Apache-2.0), datos `tessdata_best_int` (Apache-2.0).
