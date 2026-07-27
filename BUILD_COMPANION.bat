@echo off
setlocal

cd /d "%~dp0"

python -m pip install -r requirements-companion.txt pyinstaller
if errorlevel 1 exit /b 1

pyinstaller --noconfirm --clean --onefile --console ^
  --name TocaCompanion ^
  --collect-all playwright ^
  --add-data "public\assets\autotoca\robot-cursor.apng;public\assets\autotoca" ^
  --add-data "version.txt;." ^
  toca_companion.py
if errorlevel 1 exit /b 1

echo.
echo Toca Companion gerado em dist\TocaCompanion.exe
endlocal
