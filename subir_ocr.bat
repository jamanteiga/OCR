@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
rem ================================================================
rem  Sube C:\Users\jaman\Documents\PROYECTOS\OCR a github.com/jamanteiga/OCR
rem  - Sobrescribe lo que ya exista en el repositorio (rama main)
rem  - Deja GitHub Pages activado para usar la app en movil, tablet y PC
rem  Uso: doble clic.  (con el argumento "auto" no hace pausa al final)
rem ================================================================
set "CARPETA=C:\Users\jaman\Documents\PROYECTOS\OCR"
set "USUARIO=jamanteiga"
set "REPOSITORIO=OCR"
set "RAMA=main"
set "REMOTO=https://github.com/%USUARIO%/%REPOSITORIO%.git"
set "WEB=https://%USUARIO%.github.io/%REPOSITORIO%/"

cd /d "%CARPETA%" 2>nul
if errorlevel 1 (
  echo ERROR: no existe la carpeta %CARPETA%
  goto :fin
)
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git no esta instalado. Descargalo en https://git-scm.com/download/win
  goto :fin
)
if not exist "index.html" (
  echo ERROR: falta index.html en %CARPETA%
  echo Copia ahi el contenido del zip fotos2pdf-repo.zip y vuelve a ejecutar.
  goto :fin
)

echo [1/5] Preparando archivos...
rem Evita que GitHub Pages procese el sitio con Jekyll
if not exist ".nojekyll" type nul > ".nojekyll"
rem Nueva version del service worker en cada subida: asi moviles y tablets descargan la ultima app
if exist "sw.js" powershell -NoProfile -Command "$f=(Resolve-Path 'sw.js').Path;$t=[IO.File]::ReadAllText($f);$v=Get-Date -Format yyyyMMddHHmmss;$q=[char]39;$t=[regex]::Replace($t,'VERSION = [^;]+;','VERSION = '+$q+'fotos2pdf-'+$v+$q+';');[IO.File]::WriteAllText($f,$t,(New-Object Text.UTF8Encoding($false)))"

echo [2/5] Configurando git...
if not exist ".git" git init >nul 2>&1
git checkout -B %RAMA% >nul 2>&1
git config core.autocrlf false
git config user.name >nul 2>&1 || git config user.name "%USUARIO%"
git config user.email >nul 2>&1 || git config user.email "%USUARIO%@users.noreply.github.com"
git remote get-url origin >nul 2>&1
if errorlevel 1 (git remote add origin %REMOTO%) else (git remote set-url origin %REMOTO%)

echo [3/5] Sincronizando con el repositorio...
git fetch origin %RAMA% >nul 2>&1
if not errorlevel 1 git reset --soft origin/%RAMA% >nul 2>&1
git add -A
git commit -m "Actualizacion %date% %time%" >nul 2>&1

echo [4/5] Subiendo a GitHub...
git push -u origin %RAMA%
if errorlevel 1 (
  echo El envio normal ha fallado; se sobrescribe el contenido remoto...
  git push -u origin %RAMA% --force
  if errorlevel 1 (
    echo.
    echo ERROR: no se pudo subir. Revisa la conexion y que hayas iniciado sesion en GitHub.
    echo Si se abre una ventana de GitHub, inicia sesion una vez y vuelve a ejecutar este archivo.
    goto :fin
  )
)

echo [5/5] Activando GitHub Pages...
set "TOKEN="
> "%TEMP%\f2p_cred.txt" (echo protocol=https&echo host=github.com&echo.)
for /f "tokens=1,* delims==" %%a in ('git credential fill ^< "%TEMP%\f2p_cred.txt" 2^>nul') do if /i "%%a"=="password" set "TOKEN=%%b"
del "%TEMP%\f2p_cred.txt" >nul 2>&1
set "PAGES=no"
if defined TOKEN (
  curl -s -o nul -w "%%{http_code}" -X POST -H "Authorization: Bearer %TOKEN%" -H "Accept: application/vnd.github+json" https://api.github.com/repos/%USUARIO%/%REPOSITORIO%/pages -d "{\"source\":{\"branch\":\"%RAMA%\",\"path\":\"/\"}}" > "%TEMP%\f2p_code.txt" 2>nul
  set /p CODIGO=<"%TEMP%\f2p_code.txt"
  del "%TEMP%\f2p_code.txt" >nul 2>&1
  if "!CODIGO!"=="201" set "PAGES=ok"
  if "!CODIGO!"=="409" set "PAGES=ok"
  rem si ya existia, se asegura rama y carpeta
  curl -s -o nul -X PUT -H "Authorization: Bearer %TOKEN%" -H "Accept: application/vnd.github+json" https://api.github.com/repos/%USUARIO%/%REPOSITORIO%/pages -d "{\"source\":{\"branch\":\"%RAMA%\",\"path\":\"/\"}}" >nul 2>&1
)
set "TOKEN="

echo.
echo ================================================================
echo  SUBIDA COMPLETADA
if "%PAGES%"=="ok" (
  echo  GitHub Pages activado.
) else (
  echo  No se pudo activar Pages automaticamente. Hazlo una sola vez en:
  echo  https://github.com/%USUARIO%/%REPOSITORIO%/settings/pages
  echo  Source: Deploy from a branch - Branch: %RAMA% - Folder: /root - Save
)
echo.
echo  App ^(movil, tablet y PC^):  %WEB%
echo  La primera publicacion tarda 1-2 minutos; las siguientes, unos segundos.
echo  Movil/tablet: abre la direccion y "Anadir a pantalla de inicio" / "Instalar".
echo ================================================================

:fin
if /i not "%~1"=="auto" pause
endlocal
