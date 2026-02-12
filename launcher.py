#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import webbrowser
import subprocess
import requests
from pathlib import Path

# Diretorio do app
APP_DIR = Path(__file__).parent
DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho' if sys.platform == 'win32' else Path.home() / '.toca-do-coelho'
DB_PATH = DATA_DIR / 'toca-do-coelho.db'

# Criar diretorio de dados se não existir
DATA_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  TOCA DO COELHO - Registro de Atividades v1.0.0")
print("=" * 60)
print()

# Verificar se Python está disponível
try:
    import flask
except ImportError:
    print("[✗] Flask não está instalado!")
    print("[INFO] Instalando dependências...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(APP_DIR / "requirements.txt")])
    print("[✓] Dependências instaladas!")
    print()

# Iniciar servidor Flask em background
print("[INFO] Iniciando servidor...")
server_process = subprocess.Popen(
    [sys.executable, str(APP_DIR / "app.py")],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
)

print("[✓] Servidor iniciado (PID: {})".format(server_process.pid))
print()

# Aguardar servidor estar pronto
print("[INFO] Aguardando servidor ficar pronto...")
max_attempts = 30
attempt = 0

while attempt < max_attempts:
    try:
        response = requests.get('http://localhost:3000/', timeout=1)
        if response.status_code == 200:
            print("[✓] Servidor pronto!")
            break
    except:
        pass
    
    time.sleep(0.5)
    attempt += 1

if attempt >= max_attempts:
    print("[✗] Servidor não respondeu a tempo!")
    server_process.terminate()
    sys.exit(1)

print()

# Abrir navegador
print("[INFO] Abrindo navegador...")
webbrowser.open('http://localhost:3000')
print("[✓] Navegador aberto!")
print()

print("=" * 60)
print("  Toca do Coelho está rodando em http://localhost:3000")
print("  Feche esta janela para encerrar o aplicativo")
print("=" * 60)
print()

# Manter processo vivo
try:
    while True:
        time.sleep(1)
        # Verificar se servidor ainda está rodando
        if server_process.poll() is not None:
            print("[✗] Servidor encerrou inesperadamente!")
            break
except KeyboardInterrupt:
    print()
    print("[INFO] Encerrando servidor...")
    server_process.terminate()
    server_process.wait(timeout=5)
    print("[✓] Servidor encerrado!")
