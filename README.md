# Toca do Coelho - Sistema de Gestão de Clientes

Sistema de gestão de clientes com interface web local.

## 📦 Instalação (Windows - recomendado)

### Fluxo oficial de release (version3)

1. Gere o executável com PyInstaller (inclui runtime Python):
   ```bash
   pyinstaller --noconfirm --onedir --name TocaDoCoelho --icon coelho_icon_transparent.ico launcher.py
   ```
2. Compile o instalador NSIS:
   - Execute `BUILD_INSTALLER.bat`
3. Distribua `TocaDoCoelho-1.0.0-Setup.exe`

### Experiência do usuário final

- Duplo clique em `TocaDoCoelho-1.0.0-Setup.exe`
- Next → Next → Install
- Atalho criado na Área de Trabalho/Menu Iniciar
- Pronto para usar (sem instalar Python via terminal)

## 💾 Onde os dados ficam

- **Windows:** `%AppData%\toca-do-coelho\`
- **Mac/Linux:** `~/.toca-do-coelho/`

### Regras de atualização/desinstalação

- A atualização troca os binários em `C:\Program Files\TocaDoCoelho`.
- O banco SQLite e uploads permanecem em `%AppData%\toca-do-coelho`.
- A desinstalação **preserva os dados do usuário por padrão**.

## 🔄 Migração automática de dados legados

Na primeira execução (Windows), se o banco novo não existir, o app tenta migrar automaticamente:

1. `C:\toca-do-coelho-version2\toca-do-coelho-version2.db`
2. `C:\toca-do-coelho\toca-do-coelho.db`

Uploads também são migrados quando encontrados.

## 📋 Funcionalidades

✅ Dashboard de clientes  
✅ Gestão de clientes e atividades  
✅ Upload de foto  
✅ Exportação de dados  
✅ Regras automáticas de status  

## 🛠️ Dependências pesadas (Whisper / FFmpeg)

Para transcrição por voz, o app usa Whisper e precisa de FFmpeg.

Estratégias recomendadas de distribuição:

1. **Pacote completo:** incluir FFmpeg junto no build (mais simples para usuário).
2. **Opcional guiado:** detectar ausência e exibir instrução guiada de instalação.

Para release comercial, priorize a opção 1.

## 🧪 Troubleshooting rápido

### Porta 3000 em uso
- Feche instâncias antigas do app e tente novamente.

### Dados não salvam
- Verifique permissão de escrita em `%AppData%\toca-do-coelho`.

### Erro de transcrição
- Verifique se FFmpeg está disponível no ambiente/bundle.

## 📝 Versão

Branch de release alvo: **version3**.
