@echo off
chcp 65001 >nul
cls

echo.
echo ========================================================
echo   COMPILAR INSTALADOR - TOCA DO COELHO
echo ========================================================
echo.

REM Verificar se build PyInstaller existe
if not exist "dist\TocaDoCoelho\TocaDoCoelho.exe" (
    echo [ERRO] Build não encontrado!
    echo.
    echo Gere primeiro o executável com PyInstaller:
    echo   pyinstaller --noconfirm --onedir --name TocaDoCoelho --icon coelho_icon_transparent.ico --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 launcher.py
    echo.
    pause
    exit /b 1
)

REM Verificar se NSIS está instalado
if not exist "C:\Program Files\NSIS\makensis.exe" (
    if not exist "C:\Program Files (x86)\NSIS\makensis.exe" (
        echo [ERRO] NSIS não está instalado!
        echo.
        echo Baixe em: https://nsis.sourceforge.io/Download
        echo.
        pause
        exit /b 1
    )
)

REM Encontrar NSIS
if exist "C:\Program Files\NSIS\makensis.exe" (
    set NSIS_PATH=C:\Program Files\NSIS\makensis.exe
) else (
    set NSIS_PATH=C:\Program Files (x86)\NSIS\makensis.exe
)

echo [INFO] NSIS encontrado em: %NSIS_PATH%
echo.

REM Compilar instalador
echo [INFO] Compilando instalador...
"%NSIS_PATH%" /V4 installer.nsi

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [✓] Instalador compilado com sucesso!
    echo [✓] Arquivo: TocaDoCoelho-1.0.0-Setup.exe
    echo.
) else (
    echo.
    echo [✗] Erro ao compilar instalador!
    echo.
)

pause
