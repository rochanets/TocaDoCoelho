@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
echo.
echo ============================================================
echo   WhatsApp Update -- Ambiente de Teste (WAHA-lite)
echo   Toca do Coelho
echo ============================================================
echo.

:: ---------------------------------------------------------------------------
:: Localiza o Node.js: primeiro node.exe na raiz do projeto, depois no PATH
:: ---------------------------------------------------------------------------
set "PROJ_ROOT=%~dp0.."
set NODE_EXE=

if exist "%PROJ_ROOT%\node.exe" (
    set "NODE_EXE=%PROJ_ROOT%\node.exe"
    echo [INFO] node.exe encontrado na pasta do projeto.
    goto :node_found
)

where node >nul 2>nul
if !errorlevel! equ 0 (
    set NODE_EXE=node
    echo [INFO] Node.js encontrado no PATH.
    goto :node_found
)

echo [ERRO] Node.js nao encontrado.
echo.
echo  Opcao A: instale o Node.js LTS em https://nodejs.org
echo  Opcao B: baixe node.exe em https://nodejs.org/dist/v24.16.0/win-x64/node.exe
echo           e coloque na pasta raiz do projeto (junto com launcher.py).
echo.
pause
exit /b 1

:node_found

:: ---------------------------------------------------------------------------
:: Verifica se o waha-lite.js existe
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
if not exist "%SCRIPT_DIR%\node_modules\express" (
    echo [INFO] Instalando dependencias npm (primeira vez)...
    where npm >nul 2>nul
    if !errorlevel! neq 0 (
        echo [ERRO] npm nao encontrado. Instale o Node.js completo (nao apenas node.exe isolado).
        echo        Baixe em https://nodejs.org e instale normalmente.
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
)

:: ---------------------------------------------------------------------------
:: Inicia o WAHA-lite
:: ---------------------------------------------------------------------------
echo [1/2] Iniciando WAHA-lite (Node.js, sem Docker)...

set WAHA_PORT=3001
set WAHA_API_KEY=toca-test-key-2024
set WAHA_SESSION_NAME=default
set "WAHA_DATA_DIR=%APPDATA%\toca-do-coelho\waha-sessions"

if not exist "%WAHA_DATA_DIR%" mkdir "%WAHA_DATA_DIR%"

start "WAHA-lite" "%NODE_EXE%" "%SCRIPT_DIR%\waha-lite.js"

echo.
echo [2/2] Aguardando WAHA-lite inicializar...
timeout /t 10 /nobreak > nul

echo.
echo ============================================================
echo   WAHA-lite pronto: http://localhost:3001
echo.
echo   Configure no WhatsApp Update:
echo.
echo     URL da API : http://localhost:3001
echo     API Key    : toca-test-key-2024
echo     Sessao     : default
echo.
echo   Clique em "Salvar e Conectar" e escaneie o QR com
echo   seu WhatsApp (igual ao WhatsApp Web).
echo.
echo   O WAHA-lite usa o Chrome ou Edge ja instalado no PC.
echo   Se nenhum for encontrado, instale o Chrome:
echo     https://www.google.com/chrome
echo ============================================================
echo.

set /p ABRIR="Abrir o Toca do Coelho no navegador agora? [S/n]: "
if /i "!ABRIR!" neq "n" (
    start http://localhost:3000
)

echo.
echo Para PARAR o WAHA-lite: feche a janela "WAHA-lite" na barra de tarefas.
echo.
pause
