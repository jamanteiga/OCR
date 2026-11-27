@echo off
cd /d "%~dp0"
rem PATH limpio (evita el error WinError 448 con carpetas de Scoop)
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.dirname(sys.executable))"') do set "PYDIR=%%i"
set "PATH=%PYDIR%;%PYDIR%\Scripts;C:\Windows\System32;C:\Windows"
echo Instalando dependencias (una sola vez)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo.& echo ERROR instalando las librerias basicas. Copia el mensaje de arriba.& pause& exit /b 1)
echo.
echo Instalando "aplanado de libro" (page-dewarp)...
python -m pip install page-dewarp
if errorlevel 1 (echo.& echo AVISO: no se pudo instalar page-dewarp. Sin el, no se aplanan las hojas de libro. Copia el mensaje de arriba.)
echo.
echo Instalando OCR (opcional; si falla, puedes ignorarlo)...
python -m pip install ocrmypdf
echo.
echo Listo. Ahora usa 2_INICIAR.bat
pause
