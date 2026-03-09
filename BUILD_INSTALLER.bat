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
    echo   pyinstaller --noconfirm --onedir --name TocaDoCoelho --icon coelho_icon_transparent.ico --add-data "app.py;." --add-data "public;public" --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --hidden-import app launcher.py
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

REM -------------------------------------------------------
REM Baixar Tesseract OCR para bundling (se ainda não existe)
REM -------------------------------------------------------
set TESSERACT_SETUP=tools\tesseract-ocr-w64-setup.exe
set TESSERACT_URL=https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe

if not exist "tools" mkdir tools

if not exist "%TESSERACT_SETUP%" (
    echo [INFO] Baixando Tesseract OCR (~48MB) para inclusão no instalador...
    echo [INFO] Isso é feito apenas uma vez. Por favor aguarde...
    echo.
    powershell -Command "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%TESSERACT_URL%' -OutFile '%TESSERACT_SETUP%' }"
    if %ERRORLEVEL% EQU 0 (
        echo [OK] Tesseract baixado com sucesso: %TESSERACT_SETUP%
    ) else (
        echo [AVISO] Falha ao baixar Tesseract. O instalador será gerado sem OCR.
        echo [AVISO] O iToca ainda funcionará para PDFs com texto digital.
        del "%TESSERACT_SETUP%" 2>nul
    )
    echo.
) else (
    echo [OK] Tesseract já disponível em: %TESSERACT_SETUP%
    echo.
)

REM Compilar instalador
echo [INFO] Compilando instalador...
"%NSIS_PATH%" /V4 installer.nsi

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Instalador compilado com sucesso!
    echo [OK] Arquivo: TocaDoCoelho-1.0.0-Setup.exe
    echo.
    if exist "%TESSERACT_SETUP%" (
        echo [INFO] Tesseract OCR incluído - PDFs escaneados serão lidos automaticamente.
    ) else (
        echo [AVISO] Tesseract OCR NAO incluído - apenas PDFs com texto digital serão lidos.
    )
    echo.
) else (
    echo.
    echo [ERRO] Erro ao compilar instalador!
    echo.
)

pause
