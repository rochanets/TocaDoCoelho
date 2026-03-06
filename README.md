# Toca do Coelho - Sistema de Gestão de Clientes

Sistema de gestão de clientes com interface web local.

## 📦 Instalação (Windows - recomendado)

### Fluxo oficial de release (version3)

1. Gere o executável com PyInstaller (inclui runtime Python + binários do FFmpeg via `imageio_ffmpeg`):
   ```bash
   pyinstaller --noconfirm --onedir --name TocaDoCoelho --icon coelho_icon_transparent.ico --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 launcher.py
   ```
2. Compile o instalador NSIS:
   - Execute `BUILD_INSTALLER.bat`
3. Distribua `TocaDoCoelho-1.0.0-Setup.exe`

### Experiência do usuário final

- Duplo clique em `TocaDoCoelho-1.0.0-Setup.exe`
- Next → Next → Install
- Atalho criado na Área de Trabalho/Menu Iniciar
- Pronto para usar (sem instalar Python ou FFmpeg via terminal)

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

## 🧾 Logs e suporte pós-release

- Log de aplicação: `%AppData%\toca-do-coelho\logs\app.log`
- O app grava eventos importantes (inicialização, migrações, backup e erros inesperados).
- Para suporte, peça ao usuário o arquivo `app.log`.

## 🔑 Chaves de API por usuário (Tavily / OpenRouter)

- Agora o usuário pode configurar as próprias chaves em **Configurações > Integrações de API**.
- Campos disponíveis:
  - Tavily API Key (busca)
  - OpenRouter API Key (LLM)
  - Modelo, Referer e Nome do app (OpenRouter)
- As configurações são persistidas em `app_settings` no SQLite local do usuário.
- Compatibilidade: se o usuário não preencher na UI, o sistema ainda tenta ler variáveis de ambiente (`TAVILY_API_KEY`, `OPENROUTER_API_KEY`, etc.).

## 💽 Backup automático

- O SQLite é copiado automaticamente para `%AppData%\toca-do-coelho\backups\`
- Frequência: **a cada 3 dias** (quando o app é aberto e detectar período vencido).
- Nome do arquivo: `toca-do-coelho-backup-AAAAMMDD-HHMMSS.db`

## 🛠️ Dependências pesadas (faster-whisper / FFmpeg)

Para transcrição por voz, o app usa faster-whisper e precisa de suporte de decodificação de áudio.

Na release atual, a recomendação é **incluir FFmpeg no bundle** (via `--collect-binaries imageio_ffmpeg`) para não exigir instalação manual.

## 🧪 Troubleshooting rápido

### Porta 3000 em uso
- Feche instâncias antigas do app e tente novamente.

### Dados não salvam
- Verifique permissão de escrita em `%AppData%\toca-do-coelho`.

### Erro de transcrição
- Verifique se o build foi gerado com `--collect-binaries imageio_ffmpeg`.

## 📝 Versão

Branch de release alvo: **version3**.
