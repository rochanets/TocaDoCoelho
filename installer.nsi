; Toca do Coelho - Instalador Windows (NSIS)
; =============================================

!include "MUI2.nsh"
!include "x64.nsh"

; Configurações básicas
Name "Toca do Coelho - Registro de Atividades"
OutFile "TocaDoCoelho-1.0.0-Setup.exe"
InstallDir "$PROGRAMFILES\TocaDoCoelho"
InstallDirRegKey HKCU "Software\TocaDoCoelho" "InstallPath"

; Variáveis
Var StartMenuFolder

; Interface
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_STARTMENU "Application" $StartMenuFolder
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "PortugueseBR"

; Descrições de seção
LangString DESC_SecApp ${LANG_PORTUGUESEBR} "Instala o Toca do Coelho com runtime embutido (sem depender de Python no PC)"
LangString DESC_SecShortcuts ${LANG_PORTUGUESEBR} "Cria atalhos no Menu Iniciar e Área de Trabalho"

Section "Instalar Toca do Coelho" SecApp
    SetOutPath "$INSTDIR"

    ; Binário gerado pelo PyInstaller (modo onedir)
    ; Esperado em: dist\TocaDoCoelho\TocaDoCoelho.exe
    File /r "dist\TocaDoCoelho\*.*"
    File "README.md"
    File "coelho_icon_transparent.ico"

    ; -------------------------------------------------------
    ; Tesseract OCR - Instalação silenciosa e automática
    ; O instalador do Tesseract (UB-Mannheim) deve estar em:
    ;   tools\tesseract-ocr-w64-setup.exe
    ; Gerado pelo script BUILD_INSTALLER.bat antes do empacotamento
    ; -------------------------------------------------------
    IfFileExists "$EXEDIR\tools\tesseract-ocr-w64-setup.exe" 0 SkipTesseract
        DetailPrint "Instalando Tesseract OCR (reconhecimento de texto em documentos)..."
        ; /VERYSILENT = sem janelas
        ; /NORESTART  = não reinicia o PC
        ; /DIR        = instala dentro da pasta do Toca do Coelho
        ; /COMPONENTS = instala apenas o core + idiomas PT e EN
        ExecWait '"$EXEDIR\tools\tesseract-ocr-w64-setup.exe" /VERYSILENT /NORESTART /DIR="$INSTDIR\tesseract" /COMPONENTS="tesseract,por,eng"'
        DetailPrint "Tesseract OCR instalado com sucesso."
    SkipTesseract:

    ; Criar diretório de dados do usuário
    CreateDirectory "$APPDATA\toca-do-coelho"

    ; Salvar caminho de instalação no registro
    WriteRegStr HKCU "Software\TocaDoCoelho" "InstallPath" "$INSTDIR"
    WriteRegStr HKCU "Software\TocaDoCoelho" "Version" "1.0.0"

    ; Criar entrada em Adicionar/Remover Programas
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayName" "Toca do Coelho - Registro de Atividades"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayVersion" "1.0.0"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "Publisher" "Toca do Coelho"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayIcon" "$INSTDIR\coelho_icon_transparent.ico"

    ; Criar desinstalador
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Criar Atalhos" SecShortcuts
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application

    CreateDirectory "$SMPROGRAMS\$StartMenuFolder"

    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Toca do Coelho.lnk" \
        "$INSTDIR\TocaDoCoelho.exe" \
        "" \
        "$INSTDIR\coelho_icon_transparent.ico" \
        0 \
        SW_SHOWNORMAL

    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk" \
        "$INSTDIR\uninstall.exe"

    !insertmacro MUI_STARTMENU_WRITE_END

    CreateShortCut "$DESKTOP\Toca do Coelho.lnk" \
        "$INSTDIR\TocaDoCoelho.exe" \
        "" \
        "$INSTDIR\coelho_icon_transparent.ico" \
        0 \
        SW_SHOWNORMAL

SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"

    !insertmacro MUI_STARTMENU_GETFOLDER Application $StartMenuFolder
    Delete "$SMPROGRAMS\$StartMenuFolder\Toca do Coelho.lnk"
    Delete "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk"
    RMDir "$SMPROGRAMS\$StartMenuFolder"

    Delete "$DESKTOP\Toca do Coelho.lnk"

    ; Dados em %APPDATA% são preservados por padrão
    DeleteRegKey HKCU "Software\TocaDoCoelho"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} $(DESC_SecApp)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecShortcuts} $(DESC_SecShortcuts)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
