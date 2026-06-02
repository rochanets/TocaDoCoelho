@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo   WhatsApp Update — Ambiente de Teste
echo   Toca do Coelho
echo ============================================================
echo.

where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Docker nao encontrado. Instale o Docker Desktop:
    echo        https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo [1/2] Iniciando Evolution API via Docker...
docker compose -f docker-compose.evolution.yml up -d

if %errorlevel% neq 0 (
    echo [ERRO] Falha ao iniciar container. Verifique se o Docker Desktop esta rodando.
    pause
    exit /b 1
)

echo.
echo [2/2] Aguardando Evolution API inicializar...
timeout /t 5 /nobreak > nul

echo.
echo ============================================================
echo   Evolution API pronta em: http://localhost:8080
echo.
echo   Configure no WhatsApp Update (AutoToca):
echo     URL:      http://localhost:8080
echo     API Key:  toca-test-key-2024
echo     Instancia: toca-whatsapp
echo.
echo   Depois clique em "Conectar" e escaneie o QR code
echo   com o seu WhatsApp.
echo ============================================================
echo.

set /p ABRIR="Deseja abrir o Toca do Coelho agora? [S/n]: "
if /i "%ABRIR%" neq "n" (
    start http://localhost:3000
)

echo.
echo Para parar a Evolution API: docker compose -f docker-compose.evolution.yml down
echo.
pause
