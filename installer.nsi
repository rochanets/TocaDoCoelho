!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

!ifndef APP_VERSION
!define APP_VERSION "1.0.0"
!endif

Name "Toca do Coelho - Registro de Atividades"
OutFile "TocaDoCoelho-${APP_VERSION}-Setup.exe"

; Instalação per-user, SEM elevação UAC. Instalar em $PROGRAMFILES exigia admin e,
; em contas sem esse privilégio, o UAC pedia credenciais de OUTRA conta — o instalador
; inteiro passava a rodar como ela, e tudo que é por usuário (registro HKCU, atalhos,
; autostart e o banco criado pelo "Iniciar agora" da página final) ia para o perfil
; errado. Após reiniciar, o app abria com banco vazio e sumia de "Aplicativos instalados".
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\TocaDoCoelho"

Var StartMenuFolder
Var OldInstallDir

; Lê o destino da instalação anterior para migrá-la: o layout antigo (Program Files)
; é removido best-effort na seção de instalação. Não usamos InstallDirRegKey porque
; ele reaproveitaria o caminho antigo como destino padrão — e sem elevação a gravação
; em Program Files falharia.
Function .onInit
    ReadRegStr $OldInstallDir HKCU "Software\TocaDoCoelho" "InstallPath"
FunctionEnd

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_STARTMENU "Application" $StartMenuFolder
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES

; Ao concluir, oferece reabrir o app automaticamente (usado pela atualização automática)
!define MUI_FINISHPAGE_RUN "$INSTDIR\TocaDoCoelho.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Iniciar o Toca do Coelho agora"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "PortugueseBR"

LangString DESC_SecApp ${LANG_PORTUGUESEBR} "Instala o Toca do Coelho"
LangString DESC_SecShortcuts ${LANG_PORTUGUESEBR} "Cria atalhos na Área de Trabalho e no Menu Iniciar"
LangString DESC_SecAutoStart ${LANG_PORTUGUESEBR} "Iniciar o Toca do Coelho automaticamente quando o Windows ligar"

Section "Instalar Toca do Coelho" SecApp
    ; Encerra qualquer instância em execução para liberar os arquivos bloqueados
    ; (essencial para a atualização automática, que dispara o instalador com o app aberto).
    DetailPrint "Encerrando instância em execução do Toca do Coelho..."
    nsExec::Exec 'taskkill /F /IM TocaDoCoelho.exe /T'
    ; O node.exe (WAHA-lite) é lançado como processo independente (não filho), então
    ; o /T acima não o captura — é necessário encerrá-lo explicitamente para liberar
    ; o arquivo antes que o instalador tente sobrescrevê-lo.
    DetailPrint "Encerrando WAHA-lite (node.exe)..."
    nsExec::Exec 'powershell -NoProfile -Command "Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''*TocaDoCoelho*'' } | Stop-Process -Force"'
    Sleep 2500

    ; Migração do layout antigo: remove a cópia anterior (ex.: C:\Program Files\
    ; TocaDoCoelho), best effort. Sem permissão de escrita (usuário sem admin) o RMDir
    ; falha em silêncio e a pasta antiga vira apenas peso morto — atalhos e registro
    ; passam a apontar para a instalação nova de qualquer forma. Só remove se a pasta
    ; realmente contém o app, para nunca apagar um diretório arbitrário vindo do registro.
    ${If} $OldInstallDir != ""
    ${AndIf} $OldInstallDir != $INSTDIR
    ${AndIf} ${FileExists} "$OldInstallDir\TocaDoCoelho.exe"
        DetailPrint "Removendo instalação anterior em $OldInstallDir..."
        RMDir /r "$OldInstallDir"
    ${EndIf}

    SetOutPath "$INSTDIR"
    File /r "dist\TocaDoCoelho\*"
    File "README.md"
    File "coelho_icon_transparent.ico"

    ; OCR local para comprovantes/PDFs escaneados. O Python usa pytesseract
    ; como wrapper, mas o binario tesseract.exe precisa existir na maquina do
    ; usuario. Instalamos uma copia per-user dentro do proprio app.
    !if /FileExists "tools\tesseract-ocr-w64-setup.exe"
        SetOutPath "$INSTDIR\tools"
        File "tools\tesseract-ocr-w64-setup.exe"
        DetailPrint "Instalando Tesseract OCR local..."
        ExecWait '"$INSTDIR\tools\tesseract-ocr-w64-setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="$INSTDIR\tesseract"' $0
        ${If} $0 != 0
            DetailPrint "Aviso: instalador do Tesseract retornou codigo $0. OCR local pode ficar indisponivel."
        ${EndIf}
    !else
        !warning "tools\tesseract-ocr-w64-setup.exe ausente no build: OCR local ficara indisponivel no instalador."
    !endif

    ; WhatsApp Update: mini-servidor Node.js (sem Docker).
    ; node.exe   = Node.js portátil (baixado de nodejs.org/dist/.../node.exe antes do build).
    ; waha-lite/ = servidor + node_modules (rodar "npm install" em waha-lite/ antes do build).
    ;
    ; ATENÇÃO: esta verificação TEM de ser em tempo de COMPILAÇÃO (!if /FileExists), e NÃO
    ; em tempo de execução (IfFileExists). O comando 'File' empacota o arquivo no instalador
    ; durante a compilação; já um 'IfFileExists' com caminho relativo roda na MÁQUINA DO
    ; USUÁRIO e é avaliado a partir do diretório de trabalho do instalador (em geral
    ; C:\Windows\System32 após a elevação UAC), onde node.exe e waha-lite NUNCA existem.
    ; Resultado do bug antigo: o guard pulava a extração, os arquivos ficavam embutidos no
    ; instalador mas jamais eram gravados em $INSTDIR, e o WhatsApp Update nunca subia em
    ; produção (sem Docker). Com !if /FileExists a checagem ocorre no build (raiz do projeto,
    ; onde node.exe e waha-lite existem) e a extração passa a ser incondicional na instalação.
    !if /FileExists "node.exe"
        SetOutPath "$INSTDIR"
        File "node.exe"
    !else
        !warning "node.exe ausente no build: WhatsApp Update (WAHA-lite) ficara indisponivel no instalador."
    !endif

    !if /FileExists "waha-lite\waha-lite.js"
        SetOutPath "$INSTDIR\waha-lite"
        File /r "waha-lite\*"
    !else
        !warning "waha-lite\waha-lite.js ausente no build: WhatsApp Update ficara indisponivel no instalador."
    !endif

    SetOutPath "$INSTDIR"

    CreateDirectory "$APPDATA\toca-do-coelho"

    WriteRegStr HKCU "Software\TocaDoCoelho" "InstallPath" "$INSTDIR"
    WriteRegStr HKCU "Software\TocaDoCoelho" "Version" "${APP_VERSION}"

    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayName" "Toca do Coelho"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho" "InstallLocation" "$INSTDIR"

    ; Se "Iniciar com o Windows" já estava ativo, reaponta para o novo caminho do exe
    ; (o antigo pode ter sido removido na migração acima).
    ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TocaDoCoelho"
    ${If} $0 != ""
        WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TocaDoCoelho" '"$INSTDIR\TocaDoCoelho.exe"'
    ${EndIf}

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
    ; Encerra o WAHA-lite (processo Node.js), se estiver rodando
    nsExec::Exec 'taskkill /F /IM node.exe /FI "WINDOWTITLE eq waha-lite*"'
    RMDir /r "$INSTDIR"
    !insertmacro MUI_STARTMENU_GETFOLDER Application $StartMenuFolder
    Delete "$SMPROGRAMS\$StartMenuFolder\Toca.lnk"
    Delete "$SMPROGRAMS\$StartMenuFolder\Desinstalar.lnk"
    RMDir "$SMPROGRAMS\$StartMenuFolder"
    Delete "$DESKTOP\Toca.lnk"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TocaDoCoelho"

    ; Remove a política de auto-instalação da extensão AutoToca (Chrome/Edge/Brave).
    ; O app grava, sob Software\TocaDoCoelho\ExtForcelist, uma marca por política:
    ; nome = a subchave da política, dado = o índice que criamos naquela lista.
    ReadRegStr $0 HKCU "Software\TocaDoCoelho\ExtForcelist" "Software\Policies\Google\Chrome\ExtensionInstallForcelist"
    ${If} $0 != ""
        DeleteRegValue HKCU "Software\Policies\Google\Chrome\ExtensionInstallForcelist" "$0"
    ${EndIf}
    ReadRegStr $0 HKCU "Software\TocaDoCoelho\ExtForcelist" "Software\Policies\Microsoft\Edge\ExtensionInstallForcelist"
    ${If} $0 != ""
        DeleteRegValue HKCU "Software\Policies\Microsoft\Edge\ExtensionInstallForcelist" "$0"
    ${EndIf}
    ReadRegStr $0 HKCU "Software\TocaDoCoelho\ExtForcelist" "Software\Policies\BraveSoftware\Brave-Browser\ExtensionInstallForcelist"
    ${If} $0 != ""
        DeleteRegValue HKCU "Software\Policies\BraveSoftware\Brave-Browser\ExtensionInstallForcelist" "$0"
    ${EndIf}

    DeleteRegKey HKCU "Software\TocaDoCoelho"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TocaDoCoelho"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} $(DESC_SecApp)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecShortcuts} $(DESC_SecShortcuts)
    !insertmacro MUI_DESCRIPTION_TEXT ${SecAutoStart} $(DESC_SecAutoStart)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
