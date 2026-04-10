!include "MUI2.nsh"
!include "x64.nsh"

!ifndef APP_VERSION
!define APP_VERSION "1.0.0"
!endif

Name "Toca do Coelho - Registro de Atividades"
OutFile "TocaDoCoelho-${APP_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES\TocaDoCoelho"
InstallDirRegKey HKCU "Software\TocaDoCoelho" "InstallPath"

Var StartMenuFolder

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_STARTMENU "Application" $StartMenuFolder
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "PortugueseBR"

LangString DESC_SecApp ${LANG_PORTUGUESEBR} "Instala o Toca do Coelho"
LangString DESC_SecShortcuts ${LANG_PORTUGUESEBR} "Cria atalhos na Área de Trabalho e no Menu Iniciar"
LangString DESC_SecAutoStart ${LANG_PORTUGUESEBR} "Iniciar o Toca do Coelho automaticamente quando o Windows ligar"

Section "Instalar Toca do Coelho" SecApp
    SetOutPath "$INSTDIR"
    File /r "dist\TocaDoCoelho\*.*"
    File "README.md"
    File "coelho_icon_transparent.ico"

    CreateDirectory "$APPDATA\toca-do-coelho"

    WriteRegStr HKCU "Software\TocaDoCoelho" "InstallPath" "$INSTDIR"
    WriteRegStr HKCU "Software\TocaDoCoelho" "Version" "${APP_VERSION}"

    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayName" "Toca do Coelho"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "InstallLocation" "$INSTDIR"

    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Criar Atalhos" SecShortcuts
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateDirectory "$SMPROGRAMS\$StartMenuFolder"
    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Toca.lnk" "$INSTDIR\TocaDoCoelho.exe" "" "$INSTDIR\coelho_icon_transparent.ico" 0 SW_SHOWNORMAL
    CreateShortCut "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk" "$INSTDIR\uninstall.exe"
    !insertmacro MUI_STARTMENU_WRITE_END
    CreateShortCut "$DESKTOP\Toca.lnk" "$INSTDIR\TocaDoCoelho.exe" "" "$INSTDIR\coelho_icon_transparent.ico" 0 SW_SHOWNORMAL
SectionEnd

Section /o "Iniciar com o Windows" SecAutoStart
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TocaDoCoelho" '"$INSTDIR\TocaDoCoelho.exe"'
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    !insertmacro MUI_STARTMENU_GETFOLDER Application $StartMenuFolder
    Delete "$SMPROGRAMS\$StartMenuFolder\Toca.lnk"
    Delete "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk"
    RMDir "$SMPROGRAMS\$StartMenuFolder"
    Delete "$DESKTOP\Toca.lnk"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TocaDoCoelho"
    DeleteRegKey HKCU "Software\TocaDoCoelho"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} $(DESC_SecApp)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecShortcuts} $(DESC_SecShortcuts)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecAutoStart} $(DESC_SecAutoStart)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
