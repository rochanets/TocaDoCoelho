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

## 3) Garantir que o arquivo de credenciais existe

O arquivo `graph_credentials.py` contém as credenciais da integração Microsoft 365 e **não é versionado no git**.
Ele deve estar presente na raiz do projeto antes do build.

Se não existir, crie manualmente:

```cmd
copy NUL graph_credentials.py
```

...e adicione o conteúdo:
```
GRAPH_TENANT_ID = 'seu-tenant-id'
GRAPH_CLIENT_ID = 'seu-client-id'
GRAPH_CLIENT_SECRET = 'seu-client-secret'
```

> **Nota:** solicite o arquivo completo com as credenciais ao administrador do projeto.

## 4) Gerar o executável (PyInstaller) **sem abrir janela de terminal**

```cmd
pyinstaller --noconfirm --onedir --windowed --name TocaDoCoelho --icon coelho_icon_transparent.ico --add-data "app.py;." --add-data "routes;routes" --add-data "public;public" --add-data "integrations;integrations" --add-data "graph_credentials.py;." --collect-binaries imageio_ffmpeg --collect-all faster_whisper --collect-all ctranslate2 --collect-all win32com --hidden-import win32com.client --hidden-import pywintypes --hidden-import app --hidden-import graph_credentials launcher.py
```

> **Novo em relação à versão anterior:**
> - `--add-data "integrations;integrations"` — inclui o pacote de integrações (Microsoft Graph)
> - `--add-data "graph_credentials.py;."` — inclui as credenciais do Microsoft 365
> - `--hidden-import graph_credentials` — garante que o módulo é reconhecido pelo PyInstaller

## 5) Validar se o executável foi criado

```cmd
if exist dist\TocaDoCoelho\TocaDoCoelho.exe (
  echo [OK] Executavel gerado com sucesso
) else (
  echo [ERRO] Executavel nao foi gerado
)
```

## 6) Compilar instalador NSIS

> Com NSIS já instalado no Windows:

```cmd
BUILD_INSTALLER.bat
```

Esse script:
- verifica `dist\TocaDoCoelho\TocaDoCoelho.exe`;
- baixa `tools\tesseract-ocr-w64-setup.exe` (se ainda não existir);
- gera `TocaDoCoelho-1.0.0-Setup.exe`.

## 7) Validar se o instalador foi criado

```cmd
if exist TocaDoCoelho-1.0.0-Setup.exe (
  echo [OK] Instalador gerado com sucesso
) else (
  echo [ERRO] Instalador nao foi gerado
)
```

## 8) Entregáveis finais

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
