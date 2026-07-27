# Toca do Coelho - Sistema de Gestão de Clientes

Sistema de gestão de clientes com interface web local.

## 📦 Instalação (Windows - recomendado)

### Fluxo oficial de release (version3)

1. Gere o executável com PyInstaller (inclui runtime Python + binários do FFmpeg via `imageio_ffmpeg`):
   ```bash
   pyinstaller --noconfirm --onedir --windowed --name TocaDoCoelho --icon coelho_icon_transparent.ico --add-data "app.py;." --add-data "public;public" --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all playwright --hidden-import app launcher.py
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

- A instalação é **per-user** (sem UAC): os binários ficam em `%LocalAppData%\TocaDoCoelho`.
- Instalações antigas em `C:\Program Files\TocaDoCoelho` são migradas automaticamente na atualização (a pasta antiga é removida quando há permissão; atalhos, registro e autostart passam a apontar para o novo local).
- O banco SQLite e uploads permanecem em `%AppData%\toca-do-coelho` — nunca são tocados pelo instalador.
- A desinstalação **preserva os dados do usuário por padrão**.

## ⬆️ Verificar atualizações pelo GitHub Releases

- Em **Configurações > Ajuda e Atualizações**, os campos já vêm pré-configurados para `rochanets/TocaDoCoelho`.
- Se você publicar em outro repositório/fork, ajuste:
  - `GitHub Owner` (usuário ou organização)
  - `GitHub Repositório`
- Clique em **Salvar Fonte** e depois em **Verificar atualizações**.
- O app consulta `https://api.github.com/repos/<owner>/<repo>/releases/latest` e compara a tag mais recente com a versão instalada.
- Se houver versão nova, o app mostra link para abrir a release no GitHub.

## 🔄 Migração automática de dados legados

Na primeira execução (Windows), se o banco novo não existir, o app tenta migrar automaticamente:

1. `C:\toca-do-coelho-version2\toca-do-coelho-version2.db`
2. `C:\toca-do-coelho\toca-do-coelho.db`

Uploads também são migrados quando encontrados.

## 🤖 Banco fictício para testes de IA

- O banco mocado em `BD_teste/toca-do-coelho-ficticio-reduzido.db` pode ser usado como fallback **somente para testes**.
- Ele só é aplicado quando:
  - não existe banco configurado do usuário em `%AppData%\toca-do-coelho\toca-do-coelho.db` (ou `~/.toca-do-coelho/toca-do-coelho.db`);
  - a variável de ambiente `TOCA_ENABLE_TEST_DB_FALLBACK=1` está ativa.
- Prioridade sempre do banco real do usuário: se já existir banco configurado/migrado, o fallback não roda.
- Em build instalada (`PyInstaller`/`sys.frozen`), o fallback de teste é ignorado por segurança.

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

## 🎙️ Transcrição web gratuita (Azure Speech F0)

No modo web autenticado, os ditados de voz usam a API de áudio curto do Azure
Speech F0. Configure no servidor:

- `AZURE_SPEECH_KEY`: chave do recurso Speech F0;
- `AZURE_SPEECH_REGION`: região do recurso, por exemplo `brazilsouth`;
- `TOCA_TRANSCRIPTION_MONTHLY_MINUTES`: teto opcional de até 300 minutos.

O navegador converte a gravação para WAV PCM mono de 16 kHz. Cada ditado é
interrompido em 55 segundos e o Toca registra no banco apenas o consumo mensal,
sem persistir o áudio ou o texto transcrito. O teto nunca ultrapassa as cinco
horas mensais do F0. Com `TOCA_AUTH_ENABLED` desligado, o desktop continua
usando `faster-whisper` localmente.

## 🐇 Toca Companion

No modo web, automações que dependem de navegador visível e sessão local são
entregues ao Toca Companion por uma fila persistente e auditável. A Fase 7.4
inclui vínculo de dispositivo, autenticação por token, leases, idempotência,
cancelamento, download privado de anexos e manifesto de atualização. O executor
Playwright do Chamado Jurídico será conectado na Fase 7.5.

O protocolo está documentado em
[`docs/toca-companion-contract-v1.md`](docs/toca-companion-contract-v1.md).

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
- Verifique se o build foi gerado com os parâmetros `--add-data "app.py;." --add-data "public;public" --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all playwright --hidden-import app`.

## 📝 Versão

Branch de release alvo: **version3**.
