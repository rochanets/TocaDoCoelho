# Guia de Compilação do Instalador Windows (version3)

## 📋 Pré-requisitos

1. **Python** (somente para gerar build)
2. **PyInstaller**
   ```bash
   pip install pyinstaller
   ```
3. **NSIS** 3.09+
   - https://nsis.sourceforge.io/Download

## 🚀 Passo a passo

### 1) Gerar executável (runtime embutido + FFmpeg + faster-whisper)

```bash
pyinstaller --noconfirm --onedir --name TocaDoCoelho --icon coelho_icon_transparent.ico --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all whisper launcher.py
```

Saída esperada:
- `dist\TocaDoCoelho\TocaDoCoelho.exe`

### 2) Compilar instalador

Execute:
- `BUILD_INSTALLER.bat`

Saída:
- `TocaDoCoelho-1.0.0-Setup.exe`

## 📦 O que o instalador faz

✅ Instala em `C:\Program Files\TocaDoCoelho`  
✅ Cria atalhos (Desktop/Menu Iniciar)  
✅ Não depende de Python instalado no PC do usuário  
✅ Inclui suporte ao FFmpeg no bundle de build  
✅ Registra em Adicionar/Remover Programas  
✅ Preserva dados em `%AppData%\toca-do-coelho` ao desinstalar  

## 💾 Dados do usuário

- Banco e uploads: `%AppData%\toca-do-coelho`
- Esse diretório **não é removido por padrão** no uninstall.

## 🧾 Logs e backup para suporte

- Logs: `%AppData%\toca-do-coelho\logs\app.log`
- Backups automáticos: `%AppData%\toca-do-coelho\backups\` (a cada 3 dias)


## 🔑 Configuração de APIs no app

- O usuário final pode informar as próprias chaves em **Configurações > Integrações de API**.
- O app persiste as configurações no SQLite local e usa essas chaves nas features de busca/LLM.

## ❓ Problemas comuns

### Erro: build não encontrado
- Gere primeiro o executável via PyInstaller.

### Erro: NSIS não encontrado
- Instale NSIS e rode o script novamente.

### App abre mas transcrição falha
- Verifique se o build foi feito com `--collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all whisper`.
- Confirme que as dependências foram instaladas com `pip install -r requirements.txt` antes do build.
