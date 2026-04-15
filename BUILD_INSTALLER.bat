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
