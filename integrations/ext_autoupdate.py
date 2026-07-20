"""Auto-update local da extensão AutoToca (hospedagem no próprio app).

O Chrome/Edge só atualizam extensões sozinhos quando elas são instaladas por uma
política de empresa (``ExtensionInstallForcelist``) apontando para um ``update_url``.
Aqui o próprio Toca do Coelho faz esse papel, 100% local:

* O ``.crx`` assinado e a chave pública ficam empacotados no app
  (gerados por ``scripts/build_extension_crx.py`` no build/release).
* Em runtime derivamos o ID da extensão a partir da chave pública — sem depender de
  nenhuma biblioteca de criptografia.
* Registramos a política de auto-instalação no registro do Windows (Chrome + Edge)
  apontando para o servidor local (``http://localhost:<porta>/ext/updates.xml``).

A partir daí o navegador instala e atualiza a extensão sozinho, sem o usuário baixar,
descompactar ou recarregar nada. Tudo é best-effort: qualquer falha é apenas logada,
e o download manual do ``.zip``/``.xpi`` continua disponível como plano B.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger('toca-do-coelho')

_EXT_BASE = Path(__file__).resolve().parent.parent / 'public' / 'autotoca-extension'
_EXT_SOURCE_DIR = _EXT_BASE / 'autotoca-chrome-extension'
CRX_PATH = _EXT_BASE / 'autotoca-helper.crx'
PUBKEY_PATH = _EXT_BASE / 'autotoca-helper.pubkey'
_MANIFEST_PATH = _EXT_SOURCE_DIR / 'manifest.json'

# Arquivos que compõem a extensão (o que é copiado para a pasta estável).
_EXT_FILES = ['manifest.json', 'background.js', 'content.js', 'reembolso.js']

# Nome do arquivo do .crx exposto pela rota Flask (ver routes/config.py).
CRX_FILENAME = 'autotoca-helper.crx'


def is_available() -> bool:
    """True quando o pacote assinado foi empacotado com este build."""
    return CRX_PATH.exists() and PUBKEY_PATH.exists()


def extension_id() -> str | None:
    """ID determinístico da extensão, derivado da chave pública committada."""
    try:
        pub_der = base64.b64decode(PUBKEY_PATH.read_text(encoding='utf-8').strip())
        digest = hashlib.sha256(pub_der).digest()[:16]
        return ''.join(chr(97 + (b >> 4)) + chr(97 + (b & 0x0F)) for b in digest)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.debug(f'[ExtAutoUpdate] Falha ao derivar ID da extensão: {exc}')
        return None


def bundled_version() -> str:
    try:
        return (json.loads(_MANIFEST_PATH.read_text(encoding='utf-8')).get('version') or '').strip()
    except Exception:  # pragma: no cover - defensivo
        return ''


def _manifest_version(path: Path) -> str:
    try:
        return (json.loads(path.read_text(encoding='utf-8')).get('version') or '').strip()
    except Exception:
        return ''


def publish_unpacked(dest_dir: Path) -> Path | None:
    """Publica os arquivos da extensão numa pasta ESTÁVEL, sempre na versão atual.

    O usuário faz "Carregar sem compactação" uma única vez apontando para essa pasta.
    A cada atualização do app, sobrescrevemos os arquivos aqui e a própria extensão se
    recarrega sozinha (``chrome.runtime.reload()`` — ver background.js), sem download,
    descompactação ou re-adição manual. Só copia quando a versão empacotada difere da
    já publicada, para não mexer nos arquivos à toa.
    """
    try:
        dest_dir = Path(dest_dir)
        current = bundled_version()
        published = _manifest_version(dest_dir / 'manifest.json') if dest_dir.exists() else ''
        if current and current == published:
            return dest_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in _EXT_FILES:
            src = _EXT_SOURCE_DIR / name
            if src.exists():
                shutil.copy2(src, dest_dir / name)
        logger.info(f'[ExtAutoUpdate] Extensão publicada em {dest_dir} (versão {current or "?"}).')
        return dest_dir
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(f'[ExtAutoUpdate] Falha ao publicar a extensão em pasta estável: {exc}')
        return None


def updates_xml(crx_url: str) -> str:
    """Manifesto de update no protocolo Omaha lido pelo Chrome/Edge."""
    ext_id = extension_id() or ''
    version = bundled_version() or '0.0.0'
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid='{ext_id}'>\n"
        f"    <updatecheck codebase='{crx_url}' version='{version}' />\n"
        "  </app>\n"
        "</gupdate>\n"
    )


# ---------------------------------------------------------------------------
# Política de auto-instalação (Windows) — Chrome, Edge e Brave
# ---------------------------------------------------------------------------

# HKCU funciona sem a máquina estar num domínio: o navegador lê políticas do usuário.
_POLICY_KEYS = {
    'Chrome': r'Software\Policies\Google\Chrome\ExtensionInstallForcelist',
    'Edge': r'Software\Policies\Microsoft\Edge\ExtensionInstallForcelist',
    'Brave': r'Software\Policies\BraveSoftware\Brave-Browser\ExtensionInstallForcelist',
}
# Onde guardamos qual valor gravamos, para o desinstalador limpar depois.
_MARK_KEY = r'Software\TocaDoCoelho\ExtForcelist'


def _write_forcelist(ext_id: str, update_url: str) -> None:
    import winreg  # noqa: import local — só existe no Windows

    entry = f'{ext_id};{update_url}'
    for browser, subkey in _POLICY_KEYS.items():
        try:
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_ALL_ACCESS)
        except OSError as exc:
            logger.debug(f'[ExtAutoUpdate] {browser}: não foi possível abrir a política ({exc}).')
            continue
        try:
            # Lê os índices existentes; remove entradas antigas nossas (ID pode ter mudado).
            existing = {}
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                existing[name] = value
                index += 1

            already = any(str(v) == entry for v in existing.values())
            for name, value in list(existing.items()):
                if str(value).startswith(f'{ext_id};') and str(value) != entry:
                    winreg.DeleteValue(key, name)
                    existing.pop(name, None)

            if not already:
                used = {int(n) for n in existing if str(n).isdigit()}
                slot = 1
                while slot in used:
                    slot += 1
                winreg.SetValueEx(key, str(slot), 0, winreg.REG_SZ, entry)
                logger.info(f'[ExtAutoUpdate] {browser}: extensão registrada para auto-instalação ({entry}).')
                _mark_value(subkey, str(slot))
        finally:
            winreg.CloseKey(key)


def _mark_value(subkey: str, value_name: str) -> None:
    """Guarda qual índice gravamos em cada política, para o desinstalador remover depois.

    Nome da marca = a subchave da política; dado = o índice criado. Assim o
    desinstalador (NSIS) lê por subchave conhecida e apaga só o nosso índice.
    """
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _MARK_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, subkey, 0, winreg.REG_SZ, value_name)
    except OSError as exc:  # pragma: no cover - defensivo
        logger.debug(f'[ExtAutoUpdate] Falha ao registrar marca de limpeza ({subkey}): {exc}')


def register_autoinstall(port: int) -> None:
    """Registra a política de auto-instalação da extensão nos navegadores (Windows)."""
    if os.name != 'nt':
        logger.debug('[ExtAutoUpdate] Registro de política ignorado (não é Windows).')
        return
    if not is_available():
        logger.info('[ExtAutoUpdate] .crx assinado ausente — auto-update local indisponível neste build.')
        return
    ext_id = extension_id()
    if not ext_id:
        return
    update_url = f'http://localhost:{port}/ext/updates.xml'
    try:
        _write_forcelist(ext_id, update_url)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(f'[ExtAutoUpdate] Não foi possível registrar a auto-instalação: {exc}')


def bootstrap(port: int, local_dir: Path | None = None) -> None:
    """Chamado no startup do app (best-effort, nunca deve derrubar o servidor).

    - Publica a extensão na pasta estável (para o "carregar sem compactação" + auto-reload).
    - Registra a política de auto-instalação (Chrome/Edge/Brave) para máquinas não gerenciadas.
    """
    try:
        if local_dir is not None:
            publish_unpacked(local_dir)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(f'[ExtAutoUpdate] publish_unpacked falhou: {exc}')
    try:
        register_autoinstall(port)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(f'[ExtAutoUpdate] bootstrap falhou: {exc}')
