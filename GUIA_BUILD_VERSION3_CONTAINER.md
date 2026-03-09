# Guia final (container Linux) para gerar **executável Windows** + **instalador NSIS** (version3)

Este projeto está preparado para release Windows (PyInstaller + NSIS), mas os scripts oficiais (`BUILD_INSTALLER.bat`) assumem ambiente Windows.

No container Linux, o fluxo final recomendado é:

1. montar ambiente Python para validar dependências do projeto;
2. gerar o `.exe` com Python Windows via **Wine**;
3. compilar o instalador `.exe` com **makensis** no Linux.

---

## 0) Diagnóstico rápido do estado atual

- Comando de build oficial já está documentado no `README.md`.
- O instalador NSIS (`installer.nsi`) já aponta para `dist\TocaDoCoelho\*.*` e gera `TocaDoCoelho-1.0.0-Setup.exe`.
- O script `BUILD_INSTALLER.bat` também faz download automático do instalador do Tesseract para `tools\tesseract-ocr-w64-setup.exe`.

---

## 1) Preparar dependências no container

```bash
cd /workspace/TocaDoCoelho
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
sudo apt-get update
sudo apt-get install -y nsis wine64 wget unzip
```

> Observação: `pyinstaller` nativo Linux **não** gera `.exe` Windows.

---

## 2) Gerar executável Windows (`dist/TocaDoCoelho/TocaDoCoelho.exe`) via Wine

### 2.1 Instalar Python Windows dentro do prefixo Wine

```bash
cd /workspace/TocaDoCoelho
mkdir -p tools/wine
cd tools/wine
wget -O python-win.exe https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
wine python-win.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
```

### 2.2 Instalar dependências e empacotar

```bash
cd /workspace/TocaDoCoelho
wine py -3.11 -m pip install --upgrade pip
wine py -3.11 -m pip install -r requirements.txt pyinstaller
wine py -3.11 -m PyInstaller \
  --noconfirm \
  --onedir \
  --windowed \
  --name TocaDoCoelho \
  --icon coelho_icon_transparent.ico \
  --add-data "app.py;." \
  --add-data "public;public" \
  --collect-binaries imageio_ffmpeg \
  --collect-all faster_whisper \
  --collect-all ctranslate2 \
  --hidden-import app \
  launcher.py
```

### 2.3 Validar artefato

```bash
test -f dist/TocaDoCoelho/TocaDoCoelho.exe && echo "OK: exe gerado"
```

---

## 3) Incluir Tesseract no bundle do instalador (opcional, mas recomendado)

```bash
cd /workspace/TocaDoCoelho
mkdir -p tools
wget -O tools/tesseract-ocr-w64-setup.exe \
  https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe
```

---

## 4) Gerar instalador NSIS

```bash
cd /workspace/TocaDoCoelho
makensis -V4 installer.nsi
```

Validar saída:

```bash
test -f TocaDoCoelho-1.0.0-Setup.exe && echo "OK: instalador gerado"
```

---

## 5) Entregáveis finais esperados

- `dist/TocaDoCoelho/TocaDoCoelho.exe`
- `TocaDoCoelho-1.0.0-Setup.exe`

Se ambos existirem, o pipeline de build/release do `version3` está concluído no container.
