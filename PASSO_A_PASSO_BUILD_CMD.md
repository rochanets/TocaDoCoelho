# Passo a passo final (CMD) — gerar Executável + Instalador (version3)

> Execute tudo no **Prompt de Comando (cmd.exe)**, na raiz do projeto.

## 1) Entrar na pasta do projeto

```cmd
cd /d C:\caminho\para\TocaDoCoelho
```

## 2) Criar venv e instalar dependências de build

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
```

## 3) Gerar o executável (PyInstaller) **sem abrir janela de terminal**

```cmd
pyinstaller --noconfirm --onedir --windowed --name TocaDoCoelho --icon coelho_icon_transparent.ico --add-data "app.py;." --add-data "public;public" --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all win32com --hidden-import win32com.client --hidden-import pywintypes --hidden-import app launcher.py
```

## 4) Validar se o executável foi criado

```cmd
if exist dist\TocaDoCoelho\TocaDoCoelho.exe (
  echo [OK] Executavel gerado com sucesso
) else (
  echo [ERRO] Executavel nao foi gerado
)
```

## 5) Compilar instalador NSIS

> Com NSIS já instalado no Windows:

```cmd
BUILD_INSTALLER.bat
```

Esse script:
- verifica `dist\TocaDoCoelho\TocaDoCoelho.exe`;
- baixa `tools\tesseract-ocr-w64-setup.exe` (se ainda não existir);
- gera `TocaDoCoelho-1.0.0-Setup.exe`.

## 6) Validar se o instalador foi criado

```cmd
if exist TocaDoCoelho-1.0.0-Setup.exe (
  echo [OK] Instalador gerado com sucesso
) else (
  echo [ERRO] Instalador nao foi gerado
)
```

## 7) Entregáveis finais

- `dist\TocaDoCoelho\TocaDoCoelho.exe`
- `TocaDoCoelho-1.0.0-Setup.exe`

---

## Se você estiver usando **PowerShell** (e não CMD)

Os erros que você recebeu (`if exist ...` e `BUILD_INSTALLER.bat` não encontrado) acontecem porque esses comandos são sintaxe de `cmd.exe`.

No PowerShell, use:

```powershell
if (Test-Path "dist\TocaDoCoelho\TocaDoCoelho.exe") {
  Write-Host "[OK] Executavel gerado com sucesso"
} else {
  Write-Host "[ERRO] Executavel nao foi gerado"
}

.\BUILD_INSTALLER.bat

if (Test-Path "TocaDoCoelho-1.0.0-Setup.exe") {
  Write-Host "[OK] Instalador gerado com sucesso"
} else {
  Write-Host "[ERRO] Instalador nao foi gerado"
}
```
