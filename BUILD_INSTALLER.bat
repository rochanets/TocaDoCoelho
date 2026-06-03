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
