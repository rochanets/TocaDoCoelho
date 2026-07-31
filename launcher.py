#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import shutil
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


def fatal_error_dialog(message):
    """Mostra um erro fatal ao usuário antes de encerrar. O build usa
    --noconsole, então input() sempre falha com 'lost sys.stdin' (não há
    console nem stdin anexado) — usar um MessageBox nativo do Windows em vez
    disso, que não depende de terminal."""
    print(message)
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Toca do Coelho - Erro", 0x10)  # MB_ICONERROR
            return
        except Exception:
            pass
    try:
        time.sleep(5)
    except Exception:
        pass

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


def get_server_port():
    return int(os.environ.get('PORT', '3000'))


def open_app_in_browser():
    webbrowser.open(f'http://localhost:{get_server_port()}')


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

    def notify(self, title, message):
        """Notificação nativa do Windows (balão/toast) via Shell_NotifyIcon."""
        import win32con
        import win32gui
        if not self._ready.wait(timeout=10) or not self.hwnd:
            return
        try:
            nid = (
                self.hwnd, 0, win32gui.NIF_INFO, win32con.WM_USER + 20, 0,
                "Toca do Coelho", str(message)[:250], 10, str(title)[:60],
                win32gui.NIIF_INFO,
            )
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception as e:
            print(f"[WARN] Falha ao exibir notificação: {e}")

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

WAHA_PORT = int(os.environ.get('WAHA_PORT', '3001'))
WAHA_API_KEY_DEFAULT = os.environ.get('WAHA_API_KEY', 'toca-test-key-2024')
WAHA_LITE_SCRIPT = Path('waha-lite') / 'waha-lite.js'


def _find_node():
    """Localiza o node.exe bundled no EXE_DIR, depois no PATH."""
    bundled = EXE_DIR / 'node.exe'
    if bundled.exists():
        return str(bundled)
    found = shutil.which('node') or shutil.which('node.exe')
    return found


def _waha_node_modules_ok(script):
    """True se o node_modules do WAHA-lite existir e não estiver vazio."""
    nm = Path(script).parent / 'node_modules'
    try:
        return nm.is_dir() and next(nm.iterdir(), None) is not None
    except Exception:
        return False


def _ensure_waha_deps(script):
    """Garante o node_modules do WAHA-lite. Se ausente (ex.: build sem deps ou execução
    do código-fonte), tenta 'npm install' como best effort. Retorna True se ok ao final."""
    if _waha_node_modules_ok(script):
        return True
    npm = shutil.which('npm') or shutil.which('npm.cmd')
    if not npm:
        return False
    print("[INFO] Dependências do WAHA-lite ausentes — rodando 'npm install' (pode levar alguns minutos)...")
    try:
        kwargs = {'cwd': str(Path(script).parent)}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        subprocess.run([npm, 'install', '--no-audit', '--no-fund'], timeout=600, **kwargs)
    except Exception as exc:
        print(f"[WARN] npm install falhou: {exc}")
    return _waha_node_modules_ok(script)


def _kill_stale_waha_port(port):
    """Encerra processos órfãos ESCUTANDO na porta do WAHA-lite antes de subir um novo.

    Sem isso, um node.exe/Chrome que sobrou de uma sessão anterior que travou segura
    a porta 3001 e o novo WAHA-lite morre com EADDRINUSE. Só mata quem está em
    LISTENING no endereço local — nunca conexões de saída."""
    try:
        if sys.platform == 'win32':
            out = subprocess.check_output(
                ['netstat', '-ano', '-p', 'TCP'],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode(errors='ignore')
            seen = set()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                proto, local, state, pid = parts[0], parts[1], parts[3], parts[-1]
                if (proto.upper().startswith('TCP') and state.upper() == 'LISTENING'
                        and local.endswith(f':{port}') and pid.isdigit() and pid != '0'
                        and pid not in seen):
                    seen.add(pid)
                    subprocess.call(
                        ['taskkill', '/F', '/T', '/PID', pid],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stderr=subprocess.DEVNULL,
                    )
                    print(f"[INFO] WAHA-lite órfão (PID {pid}) na porta {port} encerrado.")
        else:
            out = subprocess.check_output(
                ['lsof', '-ti', f'TCP:{port}', '-sTCP:LISTEN'],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode(errors='ignore').strip()
            import signal as _sig
            for pid in out.splitlines():
                if pid.isdigit():
                    try:
                        os.kill(int(pid), _sig.SIGTERM)
                        print(f"[INFO] WAHA-lite órfão (PID {pid}) na porta {port} encerrado.")
                    except Exception:
                        pass
    except Exception:
        pass  # netstat/lsof ausente ou porta livre — segue o fluxo


def _start_waha_lite():
    """
    Inicia o WAHA-lite (mini-servidor WhatsApp em Node.js) como processo
    separado, sem Docker. Usa Chrome ou Edge já instalado no sistema.
    Define as variáveis de ambiente para que o app.py auto-configure o
    WhatsApp Update na inicialização.
    """
    os.environ.setdefault('WAHA_API_URL',      f'http://localhost:{WAHA_PORT}')
    os.environ.setdefault('WAHA_API_KEY',       WAHA_API_KEY_DEFAULT)
    os.environ.setdefault('WAHA_SESSION_NAME',  'default')

    node = _find_node()
    if not node:
        print("[INFO] Node.js não encontrado — WhatsApp Update não disponível.")
        return False

    script = next(
        (p for p in (EXE_DIR / WAHA_LITE_SCRIPT, APP_DIR / WAHA_LITE_SCRIPT) if p.exists()),
        None
    )
    if not script:
        print("[INFO] waha-lite.js não encontrado — WhatsApp Update não disponível.")
        return False

    waha_data = DATA_DIR / 'waha-sessions'
    waha_data.mkdir(parents=True, exist_ok=True)

    # O servidor Flask também pode reiniciar o WAHA-lite quando detectar que ele
    # caiu. Exponha no ambiente do launcher o mesmo diretório persistente usado no
    # primeiro start; sem isso o restart caía em `.waha-sessions` ao lado do script
    # e pedia um novo QR code mesmo com a sessão válida salva em AppData\Roaming.
    os.environ['WAHA_PORT']         = str(WAHA_PORT)
    os.environ['WAHA_DATA_DIR']     = str(waha_data)

    env = os.environ.copy()
    env['WAHA_PORT']         = str(WAHA_PORT)
    env['WAHA_API_KEY']      = WAHA_API_KEY_DEFAULT
    env['WAHA_SESSION_NAME'] = 'default'
    env['WAHA_DATA_DIR']     = str(waha_data)

    # Expõe paths para que app.py possa reiniciar o WAHA-lite automaticamente
    os.environ['WAHA_NODE_EXE'] = node
    os.environ['WAHA_SCRIPT']   = str(script)

    # Sem node_modules, o Node crasha no primeiro require e nada escuta na porta do WhatsApp.
    if not _ensure_waha_deps(script):
        os.environ['WAHA_DEPS_MISSING'] = '1'
        print("[ERRO] Dependencias do WAHA-lite ausentes (node_modules) e nao foi possivel instala-las.")
        print("[ERRO] WhatsApp Update indisponivel — reinstale o Toca do Coelho ou rode 'npm install' em waha-lite.")
        return False
    os.environ.pop('WAHA_DEPS_MISSING', None)

    # Log do WAHA-lite: antes a saída ia para DEVNULL, então qualquer crash do Node
    # (navegador ausente, node_modules quebrado, etc.) ficava invisível. Gravar num
    # arquivo no DATA_DIR torna esses problemas diagnosticáveis. WAHA_LOG é exposto para
    # que o app.py reaproveite o mesmo arquivo ao reiniciar o WAHA-lite.
    waha_log_path = DATA_DIR / 'waha-lite.log'
    try:
        waha_log = open(waha_log_path, 'a', encoding='utf-8', buffering=1)
        os.environ['WAHA_LOG'] = str(waha_log_path)
    except Exception:
        waha_log = subprocess.DEVNULL

    # Limpa órfãos na porta antes de subir, evitando EADDRINUSE no arranque.
    _kill_stale_waha_port(WAHA_PORT)
    time.sleep(1.0)  # dá tempo de o SO liberar a porta

    try:
        kwargs = {
            'env': env,
            'cwd': str(script.parent),
            'stdout': waha_log,
            'stderr': waha_log,
        }
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        subprocess.Popen([node, str(script)], **kwargs)
        os.environ['WAHA_STARTED_AT'] = str(time.time())
        print(f"[OK] WAHA-lite iniciado (Node.js) — porta {WAHA_PORT}")
        print(f"[INFO] Log do WAHA-lite: {waha_log_path}")
        return True
    except Exception as exc:
        print(f"[WARN] Falha ao iniciar WAHA-lite: {exc}")
        return False


# Modo servidor interno para evitar loop de subprocesso no bundle PyInstaller.
# No modo frozen, sys.executable aponta para o próprio TocaDoCoelho.exe.
# Aqui importamos o módulo app diretamente (sem runpy) para que o PyInstaller
# colete as dependências do app no build.
if '--serve' in sys.argv:
    import app as app_module
    port = get_server_port()
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
    fatal_error_dialog(f"app.py não encontrado em:\n{APP_PY}\n\nVerifique se o build foi feito com --add-data \"app.py;.\"")
    sys.exit(1)

# Iniciar WAHA-lite (gateway do WhatsApp Update via Node.js, sem Docker)
print("[INFO] Verificando WAHA-lite (WhatsApp Update)...")
_start_waha_lite()
print()

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
        fatal_error_dialog(f"O servidor encerrou antes de responder (código {server_process.returncode}).\n\nVerifique o log em:\n{LOG_PATH}")
        sys.exit(1)

    try:
        response = requests.get(f'http://localhost:{get_server_port()}/', timeout=1)
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
    fatal_error_dialog(f"O servidor não respondeu a tempo (timeout: {startup_timeout_seconds}s).\n\nVerifique o log em:\n{LOG_PATH}")
    sys.exit(1)

print()

# Abrir navegador
print("[INFO] Abrindo navegador...")
open_app_in_browser()
print("[OK] Navegador aberto!")
print()

print("=" * 60)
print(f"  Toca do Coelho está rodando em http://localhost:{get_server_port()}")
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

        # Notificação nativa de follow-ups do dia (Bloco 7), mesmo com o app
        # minimizado na bandeja. Uma vez por dia + rechecagem periódica.
        def _commitment_notifier(tray):
            import datetime as _dt
            notified_dates = set()
            while True:
                time.sleep(25)
                today = _dt.date.today().isoformat()
                if today not in notified_dates:
                    try:
                        resp = requests.get(
                            f'http://localhost:{get_server_port()}/api/commitments/alerts',
                            timeout=10
                        )
                        data = resp.json() if resp.status_code == 200 else {}
                        todays = data.get('today') or []
                        overdue = data.get('overdue') or []
                        if todays or overdue:
                            parts = []
                            if todays:
                                names = ', '.join(t.get('name', '') for t in todays[:3])
                                parts.append(f"{len(todays)} follow-up(s) hoje: {names}")
                            if overdue:
                                parts.append(f"{len(overdue)} vencido(s)")
                            tray.notify('Follow-ups — Toca do Coelho', ' | '.join(parts))
                        notified_dates.add(today)
                    except Exception:
                        pass  # servidor ainda subindo — tenta no próximo ciclo
                time.sleep(4 * 3600)

        threading.Thread(target=_commitment_notifier, args=(tray_icon,), daemon=True).start()
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
    # O WAHA-lite é um processo filho separado — encerra junto com o sistema operacional
    # ou ao fechar o Toca do Coelho. A sessão do WhatsApp persiste em DATA_DIR/waha-sessions.
    print("[OK] Servidor encerrado!")
