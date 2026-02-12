@echo off
chcp 65001 >nul
cls

echo.
echo ================================================
echo   TOCA DO COELHO - Gestao de Clientes
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado
    echo.
    echo Por favor, instale o Python a partir de:
    echo https://www.python.org/downloads/
    echo.
    echo IMPORTANTE: Marque a opcao "Add Python to PATH" durante a instalacao
    echo.
    pause
    exit /b 1
)

echo [OK] Python encontrado
echo [INFO] Iniciando servidor...
echo.

python app.py

if errorlevel 1 (
    echo.
    echo [ERRO] Erro ao iniciar o servidor
    pause
    exit /b 1
)
