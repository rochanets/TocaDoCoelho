@echo off
chcp 65001 >nul
cls

echo.
echo ========================================================
echo   INSTALAR TOCA DO COELHO - REGISTRO DE ATIVIDADES
echo ========================================================
echo.

REM Verificar se Python está instalado
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [✗] Python não está instalado ou não está no PATH!
    echo.
    echo Baixe Python em: https://www.python.org/downloads/
    echo IMPORTANTE: Marque "Add Python to PATH" durante a instalação
    echo.
    pause
    exit /b 1
)

echo [✓] Python encontrado
echo.

REM Criar pasta de instalação
set INSTALL_DIR=%PROGRAMFILES%\TocaDoCoelho
echo [INFO] Instalando em: %INSTALL_DIR%
mkdir "%INSTALL_DIR%" 2>nul

REM Copiar arquivos
echo [INFO] Copiando arquivos...
copy app.py "%INSTALL_DIR%" >nul
copy launcher_improved.py "%INSTALL_DIR%" >nul
copy requirements.txt "%INSTALL_DIR%" >nul
copy coelho_icon_transparent.ico "%INSTALL_DIR%" >nul
copy "Toca do Coelho.exe" "%INSTALL_DIR%" >nul 2>nul

REM Copiar pasta public
xcopy public "%INSTALL_DIR%\public" /E /I /Y >nul

echo [✓] Arquivos copiados
echo.

REM Instalar dependências Python
echo [INFO] Instalando dependências Python...
python -m pip install -q -r "%INSTALL_DIR%\requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [✗] Erro ao instalar dependências!
    pause
    exit /b 1
)
echo [✓] Dependências instaladas
echo.

REM Criar atalho na Área de Trabalho
echo [INFO] Criando atalho na Área de Trabalho...

REM Usar VBScript para criar atalho
set DESKTOP=%USERPROFILE%\Desktop

(
    echo Set oWS = WScript.CreateObject("WScript.Shell"^)
    echo sLinkFile = "%DESKTOP%\Toca do Coelho.lnk"
    echo Set oLink = oWS.CreateShortcut(sLinkFile^)
    echo oLink.TargetPath = "%INSTALL_DIR%\Toca do Coelho.exe"
    echo oLink.WorkingDirectory = "%INSTALL_DIR%"
    echo oLink.IconLocation = "%INSTALL_DIR%\coelho_icon_transparent.ico"
    echo oLink.Description = "Toca do Coelho - Registro de Atividades"
    echo oLink.Save
) > "%TEMP%\create_shortcut.vbs"

cscript "%TEMP%\create_shortcut.vbs" >nul
del "%TEMP%\create_shortcut.vbs"

echo [✓] Atalho criado na Área de Trabalho
echo.

REM Criar entrada em Adicionar/Remover Programas
echo [INFO] Registrando no Windows...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" /v DisplayName /d "Toca do Coelho - Registro de Atividades" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" /v DisplayVersion /d "1.0.0" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" /v InstallLocation /d "%INSTALL_DIR%" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" /v DisplayIcon /d "%INSTALL_DIR%\coelho_icon_transparent.ico" /f >nul

echo [✓] Registrado no Windows
echo.

echo ========================================================
echo   [✓] INSTALAÇÃO CONCLUÍDA COM SUCESSO!
echo ========================================================
echo.
echo   Um atalho foi criado na sua Área de Trabalho
echo   Duplo clique nele para abrir o Toca do Coelho
echo.
echo ========================================================
echo.

pause
