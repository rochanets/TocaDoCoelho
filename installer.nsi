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
LangString DESC_SecApp ${LANG_PORTUGUESEBR} "Instala o Toca do Coelho e todas as dependências"
LangString DESC_SecShortcuts ${LANG_PORTUGUESEBR} "Cria atalhos no Menu Iniciar e Área de Trabalho"

; =============================================
; SEÇÃO DE INSTALAÇÃO
; =============================================

Section "Instalar Toca do Coelho" SecApp
    SetOutPath "$INSTDIR"
    
    ; Copiar arquivos
    File "app.py"
    File "launcher.py"
    File "requirements.txt"
    File "README.md"
    File "toca_coelho_icon.ico"
    
    ; Copiar pasta public
    SetOutPath "$INSTDIR\public"
    File /r "public\*.*"
    
    ; Criar diretório de dados
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
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayIcon" "$INSTDIR\toca_coelho_icon.ico"
    
    ; Criar desinstalador
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; Instalar dependências Python
    SetOutPath "$INSTDIR"
    ExecWait '"$SYSDIR\cmd.exe" /c "$SYSDIR\python.exe" -m pip install -q -r requirements.txt'
    
SectionEnd

Section "Criar Atalhos" SecShortcuts
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    
    ; Criar pasta no Menu Iniciar
    CreateDirectory "$SMPROGRAMS\$StartMenuFolder"
    
    ; Atalho no Menu Iniciar
    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Toca do Coelho.lnk" \
        "$SYSDIR\python.exe" \
        "$INSTDIR\launcher.py" \
        "$INSTDIR\toca_coelho_icon.ico" \
        0 \
        SW_SHOW \
        "" \
        "Abrir Toca do Coelho - Registro de Atividades"
    
    ; Atalho para desinstalar
    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk" \
        "$INSTDIR\uninstall.exe"
    
    !insertmacro MUI_STARTMENU_WRITE_END
    
    ; Atalho na Área de Trabalho
    CreateShortCut "$DESKTOP\Toca do Coelho.lnk" \
        "$SYSDIR\python.exe" \
        "$INSTDIR\launcher.py" \
        "$INSTDIR\toca_coelho_icon.ico" \
        0 \
        SW_SHOW \
        "" \
        "Abrir Toca do Coelho - Registro de Atividades"
    
SectionEnd

; =============================================
; SEÇÃO DE DESINSTALAÇÃO
; =============================================

Section "Uninstall"
    ; Remover arquivos
    Delete "$INSTDIR\app.py"
    Delete "$INSTDIR\launcher.py"
    Delete "$INSTDIR\requirements.txt"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\toca_coelho_icon.ico"
    Delete "$INSTDIR\uninstall.exe"
    
    ; Remover pasta public
    RMDir /r "$INSTDIR\public"
    
    ; Remover diretório de instalação
    RMDir "$INSTDIR"
    
    ; Remover atalhos
    !insertmacro MUI_STARTMENU_GETFOLDER Application $StartMenuFolder
    Delete "$SMPROGRAMS\$StartMenuFolder\Toca do Coelho.lnk"
    Delete "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk"
    RMDir "$SMPROGRAMS\$StartMenuFolder"
    
    ; Remover atalho da Área de Trabalho
    Delete "$DESKTOP\Toca do Coelho.lnk"
    
    ; Remover entrada do registro
    DeleteRegKey HKCU "Software\TocaDoCoelho"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho"
    
SectionEnd

; =============================================
; DESCRIÇÕES
; =============================================

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} $(DESC_SecApp)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecShortcuts} $(DESC_SecShortcuts)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
