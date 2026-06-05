@echo off
echo.
echo ============================================================
echo   WhatsApp Update -- Ambiente de Teste  WAHA-lite
echo   Toca do Coelho
echo ============================================================
echo.

:: Resolve raiz do projeto a partir da pasta scripts\
pushd "%~dp0.."
set "PROJ_ROOT=%CD%"
popd

:: ---------------------------------------------------------------------------
:: Localiza node.exe
:: ---------------------------------------------------------------------------
set NODE_EXE=

if exist "%PROJ_ROOT%\node.exe" (
    set "NODE_EXE=%PROJ_ROOT%\node.exe"
    echo [INFO] node.exe encontrado na pasta do projeto.
    goto node_found
)

node --version >nul 2>nul
if errorlevel 1 goto no_node

set NODE_EXE=node
echo [INFO] Node.js encontrado no PATH.
goto node_found

:no_node
echo [ERRO] Node.js nao encontrado.
echo.
echo  Opcao A: instale o Node.js LTS em https://nodejs.org
echo  Opcao B: baixe node.exe e coloque na pasta raiz do projeto
echo           https://nodejs.org/dist/v24.16.0/win-x64/node.exe
echo.
pause
exit /b 1

:node_found

:: ---------------------------------------------------------------------------
:: Verifica waha-lite.js
:: ---------------------------------------------------------------------------
set "SCRIPT_DIR=%PROJ_ROOT%\waha-lite"

if not exist "%SCRIPT_DIR%\waha-lite.js" (
    echo [ERRO] waha-lite\waha-lite.js nao encontrado.
    echo        Rode este script a partir da pasta raiz do projeto.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------------------
:: Instala dependencias npm se necessario
:: ---------------------------------------------------------------------------
if exist "%SCRIPT_DIR%\node_modules\express" goto start_server

echo [INFO] Instalando dependencias npm...
npm --version >nul 2>nul
if errorlevel 1 (
    echo [ERRO] npm nao encontrado. Instale o Node.js completo em https://nodejs.org
    pause
    exit /b 1
)
pushd "%SCRIPT_DIR%"
npm install
popd

if not exist "%SCRIPT_DIR%\node_modules\express" (
    echo [ERRO] Falha ao instalar dependencias.
    pause
    exit /b 1
)

:start_server

:: ---------------------------------------------------------------------------
:: Inicia o WAHA-lite
:: ---------------------------------------------------------------------------
echo [1/2] Iniciando WAHA-lite...

set WAHA_PORT=3001
set WAHA_API_KEY=toca-test-key-2024
set WAHA_SESSION_NAME=default
set "WAHA_DATA_DIR=%APPDATA%\toca-do-coelho\waha-sessions"

if not exist "%WAHA_DATA_DIR%" mkdir "%WAHA_DATA_DIR%"

start "WAHA-lite" "%NODE_EXE%" "%SCRIPT_DIR%\waha-lite.js"

echo [2/2] Aguardando WAHA-lite inicializar...
timeout /t 10 /nobreak > nul

echo.
echo ============================================================
echo   WAHA-lite pronto: http://localhost:3001
echo.
echo   Configure no WhatsApp Update:
echo     URL da API : http://localhost:3001
echo     API Key    : toca-test-key-2024
echo     Sessao     : default
echo.
echo   Clique em "Salvar e Conectar" e escaneie o QR com
echo   seu WhatsApp (igual ao WhatsApp Web).
echo.
echo   O WAHA-lite usa o Chrome ou Edge ja instalado no PC.
echo ============================================================
echo.

set /p ABRIR="Abrir o Toca do Coelho no navegador agora? [S/n]: "
if /i "%ABRIR%" neq "n" start http://localhost:3000

echo.
echo Para PARAR o WAHA-lite: feche a janela "WAHA-lite" na barra de tarefas.
echo.
pause
