@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo   WhatsApp Update -- Ambiente de Teste
echo   Toca do Coelho
echo ============================================================
echo.

:: Procura o Docker em locais comuns do Windows
set DOCKER_EXE=
where docker >nul 2>nul
if %errorlevel% equ 0 set DOCKER_EXE=docker

if "%DOCKER_EXE%"=="" (
    if exist "%PROGRAMFILES%\Docker\Docker\resources\bin\docker.exe" (
        set "DOCKER_EXE=%PROGRAMFILES%\Docker\Docker\resources\bin\docker.exe"
        echo [INFO] Docker encontrado em Program Files
    )
)
if "%DOCKER_EXE%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Docker\Docker\resources\bin\docker.exe" (
        set "DOCKER_EXE=%LOCALAPPDATA%\Programs\Docker\Docker\resources\bin\docker.exe"
        echo [INFO] Docker encontrado em AppData Local
    )
)

if "%DOCKER_EXE%"=="" (
    echo [ERRO] Docker Desktop nao encontrado.
    echo.
    echo  Para testar o WhatsApp Update, instale o Docker Desktop:
    echo  https://www.docker.com/products/docker-desktop/
    echo.
    echo  Apos instalar, ABRA o Docker Desktop, aguarde o icone
    echo  ficar verde na bandeja do sistema, e rode este script novamente.
    pause
    exit /b 1
)

:: Verifica se o Docker daemon esta respondendo
"%DOCKER_EXE%" info >nul 2>nul
if %errorlevel% neq 0 (
    echo [AVISO] Docker encontrado mas nao esta rodando.
    echo [INFO]  Tentando iniciar o Docker Desktop...

    if exist "%PROGRAMFILES%\Docker\Docker\Docker Desktop.exe" (
        start "" "%PROGRAMFILES%\Docker\Docker\Docker Desktop.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe" (
        start "" "%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe"
    ) else (
        echo [AVISO] Nao foi possivel iniciar automaticamente.
        echo         Abra o Docker Desktop manualmente e aguarde o icone verde.
    )

    echo [INFO] Aguardando Docker inicializar (max 90s)...
    set TENTATIVAS=0
    :aguardar_docker
    timeout /t 6 /nobreak > nul
    "%DOCKER_EXE%" info >nul 2>nul
    if %errorlevel% equ 0 goto docker_pronto
    set /a TENTATIVAS+=1
    echo [INFO] Aguardando... (%TENTATIVAS%/15)
    if %TENTATIVAS% lss 15 goto aguardar_docker

    echo.
    echo [ERRO] Docker nao respondeu em 90 segundos.
    echo        Abra o Docker Desktop manualmente e aguarde o icone
    echo        verde na bandeja antes de tentar novamente.
    pause
    exit /b 1
)

:docker_pronto
echo [OK] Docker esta rodando.
echo.

:: Verifica se docker compose (v2) esta disponivel; tenta docker-compose (v1) como fallback
set COMPOSE_CMD="%DOCKER_EXE%" compose
"%DOCKER_EXE%" compose version >nul 2>nul
if %errorlevel% neq 0 (
    where docker-compose >nul 2>nul
    if %errorlevel% equ 0 (
        set COMPOSE_CMD=docker-compose
        echo [INFO] Usando docker-compose v1
    ) else (
        echo [ERRO] Plugin docker compose nao encontrado.
        echo        Atualize o Docker Desktop para a versao mais recente.
        pause
        exit /b 1
    )
)

echo [1/2] Iniciando Evolution API (primeira vez pode demorar para baixar a imagem)...
%COMPOSE_CMD% -f docker-compose.evolution.yml up -d

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Falha ao iniciar o container.
    echo        Certifique-se de rodar este script a partir da pasta raiz do projeto
    echo        (onde fica o arquivo docker-compose.evolution.yml).
    pause
    exit /b 1
)

echo.
echo [2/2] Aguardando Evolution API inicializar...
timeout /t 10 /nobreak > nul

echo.
echo ============================================================
echo   Evolution API pronta: http://localhost:8080
echo.
echo   Configure no WhatsApp Update (AutoToca > botao do lado):
echo.
echo     URL da API : http://localhost:8080
echo     API Key    : toca-test-key-2024
echo     Instancia  : toca-whatsapp
echo.
echo   Clique em "Salvar e Conectar", depois escaneie o QR
echo   com seu WhatsApp (igual ao WhatsApp Web).
echo ============================================================
echo.

set /p ABRIR="Abrir o Toca do Coelho no navegador agora? [S/n]: "
if /i "%ABRIR%" neq "n" (
    start http://localhost:3000
)

echo.
echo Para PARAR a Evolution API depois do teste:
echo   %COMPOSE_CMD% -f docker-compose.evolution.yml down
echo.
pause
