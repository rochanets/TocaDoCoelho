@echo off
cls

echo.
echo ========================================================
echo   COMPILAR INSTALADOR - TOCA DO COELHO
echo ========================================================
echo.

if not exist "dist\TocaDoCoelho\TocaDoCoelho.exe" (
    echo [ERRO] Executavel nao encontrado
    pause
    exit /b 1
)

echo [OK] Executavel encontrado
echo.

:: ---------------------------------------------------------------------------
:: Credenciais embarcadas: se o PyInstaller rodar sem
::   --add-data "bundled_credentials.py;."  --hidden-import bundled_credentials
:: o arquivo fica de fora e a falha e SILENCIOSA: o instalador sai normal, mas
:: toda instalacao nova abre o Account Planning com "A chave da Tavily nao esta
:: configurada". Melhor quebrar aqui do que descobrir no PC do usuario.
:: ---------------------------------------------------------------------------
if not exist "dist\TocaDoCoelho\_internal\bundled_credentials.py" (
    echo [ERRO] bundled_credentials.py nao foi embarcado no build.
    echo        A chave da Tavily nao chegaria ao usuario final.
    echo.
    echo        Confira se o arquivo existe na raiz do projeto:
    echo            copy bundled_credentials.example.py bundled_credentials.py
    echo        e refaca o PyInstaller com as flags da secao 3.1 do
    echo        PASSO_A_PASSO_BUILD_CMD.md:
    echo            --add-data "bundled_credentials.py;." --hidden-import bundled_credentials
    pause
    exit /b 1
)

echo [OK] Credenciais embarcadas encontradas
echo.

:: ---------------------------------------------------------------------------
:: WAHA-lite: node.exe portavel + dependencias npm
:: ---------------------------------------------------------------------------
echo [INFO] Verificando Node.js portavel (node.exe)...

if not exist "node.exe" (
    echo [INFO] Baixando node.exe v24 LTS para Windows x64...
    powershell -Command "Invoke-WebRequest -Uri 'https://nodejs.org/dist/v24.16.0/win-x64/node.exe' -OutFile 'node.exe'" 2>nul
    if not exist "node.exe" (
        :: Fallback: curl (disponivel no Windows 10+)
        curl -L "https://nodejs.org/dist/v24.16.0/win-x64/node.exe" -o "node.exe" 2>nul
    )
    if not exist "node.exe" (
        echo [ERRO] Falha ao baixar node.exe. Verifique a conexao e tente novamente.
        pause
        exit /b 1
    )
    echo [OK] node.exe baixado.
) else (
    echo [OK] node.exe ja presente.
)

echo [INFO] Verificando dependencias do WAHA-lite...

if not exist "waha-lite\node_modules\express" (
    echo [INFO] Instalando dependencias npm do WAHA-lite...
    where npm >nul 2>nul
    if %errorlevel% neq 0 (
        echo [ERRO] npm nao encontrado. Instale o Node.js LTS em https://nodejs.org
        echo        (necessario apenas para compilar o instalador, nao para uso do app)
        pause
        exit /b 1
    )
    pushd waha-lite
    npm install --omit=optional 2>nul || npm install
    popd
    if not exist "waha-lite\node_modules\express" (
        echo [ERRO] Falha ao instalar dependencias npm do WAHA-lite.
        pause
        exit /b 1
    )
    echo [OK] Dependencias do WAHA-lite instaladas.
) else (
    echo [OK] Dependencias do WAHA-lite ja instaladas.
)

echo.

:: ---------------------------------------------------------------------------
:: OCR: Tesseract portavel instalado junto ao app
:: ---------------------------------------------------------------------------
echo [INFO] Verificando instalador do Tesseract OCR...

if not exist "tools" mkdir "tools"

if not exist "tools\tesseract-ocr-w64-setup.exe" (
    echo [INFO] Baixando Tesseract OCR para Windows x64...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe' -OutFile 'tools\tesseract-ocr-w64-setup.exe'" 2>nul
    if not exist "tools\tesseract-ocr-w64-setup.exe" (
        curl -L "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe" -o "tools\tesseract-ocr-w64-setup.exe" 2>nul
    )
    if not exist "tools\tesseract-ocr-w64-setup.exe" (
        echo [ERRO] Falha ao baixar o Tesseract OCR. Verifique a conexao e tente novamente.
        pause
        exit /b 1
    )
    echo [OK] Tesseract OCR baixado.
) else (
    echo [OK] Instalador do Tesseract OCR ja presente.
)

echo.

set NSIS_EXE=C:\Program Files (x86)\NSIS\makensis.exe

if not exist "%NSIS_EXE%" (
    set NSIS_EXE=C:\Program Files\NSIS\makensis.exe
)

if not exist "%NSIS_EXE%" (
    echo [ERRO] NSIS nao encontrado
    pause
    exit /b 1
)

echo [OK] NSIS encontrado
echo.

set "APP_VERSION=%TOCA_APP_VERSION%"
if "%APP_VERSION%"=="" set "APP_VERSION=1.0.0"

echo [INFO] Versao do build: %APP_VERSION%
echo %APP_VERSION%> "dist\TocaDoCoelho\version.txt"
if not exist "dist\TocaDoCoelho\version.txt" (
    echo [ERRO] Nao foi possivel gerar dist\TocaDoCoelho\version.txt
    pause
    exit /b 1
)

echo [INFO] Compilando instalador...
cd /d "%CD%"
"%NSIS_EXE%" /V4 /DAPP_VERSION=%APP_VERSION% installer.nsi

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Instalador gerado com sucesso!
    echo [OK] Arquivo: TocaDoCoelho-%APP_VERSION%-Setup.exe
    echo.
) else (
    echo.
    echo [ERRO] Falha na compilacao do NSIS
    echo.
)

pause
