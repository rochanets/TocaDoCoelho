@echo off
chcp 65001 >nul
cls

echo.
echo ========================================================
echo   EXPORTADOR DE EMAILS DO OUTLOOK — Toca do Coelho
echo ========================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado no PATH.
    echo        Instale o Python em https://python.org
    pause
    exit /b 1
)

:: Verificar pywin32
python -c "import win32com.client" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Instalando dependencia pywin32...
    pip install pywin32
    if %ERRORLEVEL% NEQ 0 (
        echo [ERRO] Falha ao instalar pywin32.
        pause
        exit /b 1
    )
    echo [OK] pywin32 instalado.
    echo.
)

:: Perguntar o periodo
set /p DIAS="Quantos dias exportar? [Enter para 60]: "
if "%DIAS%"=="" set DIAS=60

echo.
echo [INFO] Exportando emails dos ultimos %DIAS% dias...
echo [INFO] O Outlook sera acessado em segundo plano. Aguarde.
echo.

:: Rodar o script com upload automatico para o Toca (se estiver rodando)
python outlook_export.py --days %DIAS% --upload

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Concluido!
) else (
    echo.
    echo [AVISO] O script finalizou com avisos. Veja as mensagens acima.
)

echo.
pause
