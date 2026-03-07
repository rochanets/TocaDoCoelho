#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import webbrowser
import subprocess
import requests
from pathlib import Path

# ---------------------------------------------------------------------------
# Detectar se está rodando dentro de um bundle PyInstaller ou em modo dev
# Dentro do bundle: sys.frozen = True e sys._MEIPASS aponta para _internal/
# Em modo dev:      __file__ aponta para o diretório do projeto
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    # Executável gerado pelo PyInstaller
    APP_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    # Rodando diretamente com python launcher.py
    APP_DIR = Path(__file__).parent
    EXE_DIR = APP_DIR

DATA_DIR = (
    Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
    if sys.platform == 'win32'
    else Path.home() / '.toca-do-coelho'
)
DB_PATH = DATA_DIR / 'toca-do-coelho.db'

# Modo servidor interno para evitar loop de subprocesso no bundle PyInstaller.
# No modo frozen, sys.executable aponta para o próprio TocaDoCoelho.exe.
# Aqui importamos o módulo app diretamente (sem runpy) para que o PyInstaller
# colete as dependências do app no build.
if '--serve' in sys.argv:
    import app as app_module
    port = int(os.environ.get('PORT', '3000'))
    app_module.app.run(host='localhost', port=port, debug=False, use_reloader=False)
    sys.exit(0)

# Criar diretório de dados se não existir
DATA_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  TOCA DO COELHO - Registro de Atividades v1.0.0")
print("=" * 60)
print()
print(f"[INFO] APP_DIR : {APP_DIR}")
print(f"[INFO] DATA_DIR: {DATA_DIR}")
print()

# Caminho do app.py (incluído como dado no bundle via --add-data)
APP_PY = APP_DIR / "app.py"

if not APP_PY.exists():
    print(f"[erro] app.py não encontrado em: {APP_PY}")
    print("[erro] Verifique se o build foi feito com --add-data \"app.py;.\"")
    input("Pressione ENTER para fechar...")
    sys.exit(1)

# Iniciar servidor Flask em background
print("[INFO] Iniciando servidor...")

# Arquivo de log do servidor
LOG_PATH = DATA_DIR / 'server.log'
print(f"[INFO] Log do servidor: {LOG_PATH}")

log_file = open(LOG_PATH, 'w', encoding='utf-8')

server_process = subprocess.Popen(
    [sys.executable, '--serve'],
    stdout=log_file,
    stderr=log_file,
    cwd=str(APP_DIR),
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
)

print(f"[OK] Servidor iniciado (PID: {server_process.pid})")
print()

# Aguardar servidor estar pronto
print("[INFO] Aguardando servidor ficar pronto...")
startup_timeout_seconds = int(os.environ.get('TOCA_STARTUP_TIMEOUT_SECONDS', '60'))
max_attempts = max(20, startup_timeout_seconds * 2)
attempt = 0

while attempt < max_attempts:
    # Verificar se o processo morreu antes de responder
    if server_process.poll() is not None:
        print(f"[ERRO] Servidor encerrou antes de responder! Código: {server_process.returncode}")
        print(f"[INFO] Verifique o log em: {LOG_PATH}")
        input("Pressione ENTER para fechar...")
        sys.exit(1)

    try:
        response = requests.get('http://localhost:3000/', timeout=1)
        if response.status_code == 200:
            print("[OK] Servidor pronto!")
            break
    except Exception:
        pass

    time.sleep(0.5)
    attempt += 1

if attempt >= max_attempts:
    print(f"[ERRO] Servidor não respondeu a tempo! (timeout: {startup_timeout_seconds}s)")
    print(f"[INFO] Verifique o log em: {LOG_PATH}")
    server_process.terminate()
    input("Pressione ENTER para fechar...")
    sys.exit(1)

print()

# Abrir navegador
print("[INFO] Abrindo navegador...")
webbrowser.open('http://localhost:3000')
print("[OK] Navegador aberto!")
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
        if server_process.poll() is not None:
            print("[ERRO] Servidor encerrou inesperadamente!")
            print(f"[INFO] Verifique o log em: {LOG_PATH}")
            input("Pressione ENTER para fechar...")
            break
except KeyboardInterrupt:
    print()
    print("[INFO] Encerrando servidor...")
    server_process.terminate()
    server_process.wait(timeout=5)
    print("[OK] Servidor encerrado!")
