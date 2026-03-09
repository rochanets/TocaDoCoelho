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

echo [INFO] Compilando instalador...
cd /d "%CD%"
"%NSIS_EXE%" /V4 installer.nsi

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Instalador gerado com sucesso!
    echo [OK] Arquivo: TocaDoCoelho-1.0.0-Setup.exe
    echo.
) else (
    echo.
    echo [ERRO] Falha na compilacao do NSIS
    echo.
)

pause
