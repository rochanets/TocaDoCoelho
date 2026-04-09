#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import webbrowser
import subprocess
import requests
import threading
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

def resolve_app_version():
    default_version = '1.0.0'
    env_version = (os.environ.get('TOCA_APP_VERSION') or '').strip()
    candidate_dirs = [Path(__file__).resolve().parent]

    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidate_dirs.append(Path(meipass))
        candidate_dirs.append(Path(sys.executable).resolve().parent)

    for base_dir in candidate_dirs:
        version_file = base_dir / 'version.txt'
        try:
            if version_file.exists():
                file_version = version_file.read_text(encoding='utf-8').strip()
                if file_version:
                    return file_version
        except Exception as error:
            print(f"[WARN] Falha ao ler versão em {version_file}: {error}")

    return env_version or default_version


APP_VERSION = resolve_app_version()


def open_app_in_browser():
    webbrowser.open('http://localhost:3000')


class WindowsTrayIcon:
    """
    Ícone de bandeja no Windows para permitir abrir/encerrar o app em background.
    """

    def __init__(self, on_open, on_exit, icon_path=None):
        self.on_open = on_open
        self.on_exit = on_exit
        self.icon_path = str(icon_path) if icon_path else None
        self.hwnd = None
        self.thread = None
        self._ready = threading.Event()
        self._class_name = "TocaDoCoelhoTrayIconWindow"

    def _run(self):
        import win32api
        import win32con
        import win32gui

        message_map = {
            win32con.WM_COMMAND: self._on_command,
            win32con.WM_DESTROY: self._on_destroy,
            win32con.WM_USER + 20: self._on_notify,
        }

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = self._class_name
        wc.lpfnWndProc = message_map
        win32gui.RegisterClass(wc)

        self.hwnd = win32gui.CreateWindow(
            self._class_name,
            self._class_name,
            0,
            0,
            0,
            win32con.CW_USEDEFAULT,
            win32con.CW_USEDEFAULT,
            0,
            0,
            wc.hInstance,
            None,
        )

        icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
        hicon = None
        if self.icon_path and os.path.exists(self.icon_path):
            hicon = win32gui.LoadImage(
                0,
                self.icon_path,
                win32con.IMAGE_ICON,
                0,
                0,
                icon_flags,
            )
        if not hicon:
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (self.hwnd, 0, flags, win32con.WM_USER + 20, hicon, "Toca do Coelho")
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

        self._ready.set()
        win32gui.PumpMessages()

    def start(self):
        self.thread = threading.Thread(target=self._run, name="tray-icon-thread", daemon=True)
        self.thread.start()
        self._ready.wait(timeout=5)

    def stop(self):
        if not self.hwnd:
            return
        import win32con
        import win32gui
        try:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        import win32gui
        nid = (self.hwnd, 0)
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
        win32gui.PostQuitMessage(0)
        return 0

    def _on_command(self, hwnd, msg, wparam, lparam):
        command_id = wparam & 0xFFFF
        if command_id == 1024:
            self.on_open()
        elif command_id == 1025:
            self.on_exit()
        return 0

    def _show_menu(self):
        import win32con
        import win32gui

        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1024, "Abrir Toca do Coelho")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1025, "Encerrar aplicativo")
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN | win32con.TPM_RIGHTBUTTON,
            pos[0],
            pos[1],
            0,
            self.hwnd,
            None,
        )
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def _on_notify(self, hwnd, msg, wparam, lparam):
        import win32con
        if lparam == win32con.WM_LBUTTONDBLCLK:
            self.on_open()
        elif lparam == win32con.WM_RBUTTONUP:
            self._show_menu()
        return 0

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
print(f"  TOCA DO COELHO - Registro de Atividades v{APP_VERSION}")
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
open_app_in_browser()
print("[OK] Navegador aberto!")
print()

print("=" * 60)
print("  Toca do Coelho está rodando em http://localhost:3000")
print("  Para encerrar no Windows, use o ícone na bandeja do sistema")
print("=" * 60)
print()

stop_event = threading.Event()
tray_icon = None

if sys.platform == 'win32':
    icon_path = EXE_DIR / 'coelho_icon_transparent.ico'
    if not icon_path.exists():
        icon_path = APP_DIR / 'coelho_icon_transparent.ico'
    try:
        tray_icon = WindowsTrayIcon(
            on_open=open_app_in_browser,
            on_exit=stop_event.set,
            icon_path=icon_path
        )
        tray_icon.start()
        print("[OK] Ícone de bandeja iniciado.")
    except Exception as e:
        print(f"[WARN] Falha ao iniciar ícone de bandeja: {e}")

# Manter processo vivo
try:
    while not stop_event.is_set():
        time.sleep(1)
        if server_process.poll() is not None:
            print("[ERRO] Servidor encerrou inesperadamente!")
            print(f"[INFO] Verifique o log em: {LOG_PATH}")
            stop_event.set()
            break
except KeyboardInterrupt:
    print()
    stop_event.set()
finally:
    print("[INFO] Encerrando servidor...")
    if tray_icon:
        tray_icon.stop()
    if server_process.poll() is None:
        server_process.terminate()
        server_process.wait(timeout=5)
    print("[OK] Servidor encerrado!")
