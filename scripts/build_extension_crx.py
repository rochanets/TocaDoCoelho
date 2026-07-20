#!/usr/bin/env python3
"""Empacota a extensão AutoToca como um .crx3 ASSINADO para auto-update local.

Este script é executado no BUILD/RELEASE (não em runtime). Ele:

1. Gera a chave privada de assinatura na primeira execução (fora do repositório) —
   ou reutiliza a existente, informada por ``--key`` / ``TOCA_EXT_KEY``.
2. Empacota a pasta ``public/autotoca-extension/autotoca-chrome-extension`` num
   arquivo ``.crx`` assinado (formato CRX3, usado pelo Chrome/Edge atuais),
   injetando ``update_url`` apontando para o servidor local do próprio app.
3. Grava a chave PÚBLICA (base64 DER) em ``autotoca-helper.pubkey`` — o app usa
   esse arquivo em runtime para derivar o ID da extensão sem precisar de nenhuma
   biblioteca de criptografia.

A chave PRIVADA nunca deve ir para o repositório. Se ela for perdida, o único efeito
é o ID da extensão mudar: o app reescreve a política de auto-instalação sozinho e o
navegador reinstala a extensão uma vez.

Requisitos: ``pip install cryptography`` (só na máquina de build).

Uso:
    python scripts/build_extension_crx.py
    python scripts/build_extension_crx.py --key /caminho/minha-chave.pem
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover - orientação de setup
    sys.stderr.write(
        'ERRO: biblioteca "cryptography" ausente. Rode: pip install cryptography\n'
    )
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = ROOT / 'public' / 'autotoca-extension' / 'autotoca-chrome-extension'
OUT_CRX = ROOT / 'public' / 'autotoca-extension' / 'autotoca-helper.crx'
OUT_PUBKEY = ROOT / 'public' / 'autotoca-extension' / 'autotoca-helper.pubkey'
DEFAULT_KEY = ROOT / 'secrets' / 'ext_signing_key.pem'

# Só entram no pacote os arquivos reais da extensão (nada de .crx/.pubkey/.zip).
EXT_FILES = ['manifest.json', 'background.js', 'content.js', 'reembolso.js']

# Porta padrão do servidor local do Toca (mesma de app.py: os.getenv('PORT', 3000)).
DEFAULT_UPDATE_URL = 'http://localhost:3000/ext/updates.xml'


def _pb_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _pb_field(field_number: int, data: bytes) -> bytes:
    """Codifica um campo protobuf length-delimited (wire type 2)."""
    tag = _pb_varint((field_number << 3) | 2)
    return tag + _pb_varint(len(data)) + data


def load_or_create_key(key_path: Path) -> rsa.RSAPrivateKey:
    if key_path.exists():
        return serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    print(f'[build-crx] chave privada gerada em: {key_path}')
    return key


def public_key_der(key: rsa.RSAPrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def extension_id(pub_der: bytes) -> str:
    digest = hashlib.sha256(pub_der).digest()[:16]
    return ''.join(chr(ord('a') + (b >> 4)) + chr(ord('a') + (b & 0x0F)) for b in digest)


def build_zip(update_url: str) -> bytes:
    """Monta o zip da extensão, injetando update_url no manifest (cópia, sem tocar o fonte)."""
    manifest = json.loads((EXT_DIR / 'manifest.json').read_text(encoding='utf-8'))
    manifest['update_url'] = update_url
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in EXT_FILES:
            if name == 'manifest.json':
                continue
            zf.write(EXT_DIR / name, arcname=name)
    return buffer.getvalue()


def build_crx(key: rsa.RSAPrivateKey, zip_bytes: bytes) -> bytes:
    pub_der = public_key_der(key)
    crx_id = hashlib.sha256(pub_der).digest()[:16]

    # signed_header_data = SignedData{ field 1: crx_id }
    signed_header_data = _pb_field(1, crx_id)

    # Payload assinado = "CRX3 SignedData\x00" + len(signed_header_data) + signed_header_data + zip
    to_sign = (
        b'CRX3 SignedData\x00'
        + struct.pack('<I', len(signed_header_data))
        + signed_header_data
        + zip_bytes
    )
    signature = key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())

    # AsymmetricKeyProof{ field 1: public_key, field 2: signature }
    proof = _pb_field(1, pub_der) + _pb_field(2, signature)
    # CrxFileHeader{ field 2: sha256_with_rsa(proof), field 10000: signed_header_data }
    header = _pb_field(2, proof) + _pb_field(10000, signed_header_data)

    return b'Cr24' + struct.pack('<II', 3, len(header)) + header + zip_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description='Gera a extensão AutoToca assinada (.crx).')
    parser.add_argument(
        '--key',
        default=os.environ.get('TOCA_EXT_KEY', str(DEFAULT_KEY)),
        help='Caminho da chave privada PEM (padrão: secrets/ext_signing_key.pem).',
    )
    parser.add_argument(
        '--update-url',
        default=os.environ.get('TOCA_EXT_UPDATE_URL', DEFAULT_UPDATE_URL),
        help='update_url gravado no manifest da extensão.',
    )
    args = parser.parse_args()

    key = load_or_create_key(Path(args.key))
    pub_der = public_key_der(key)
    ext_id = extension_id(pub_der)

    zip_bytes = build_zip(args.update_url)
    crx_bytes = build_crx(key, zip_bytes)

    OUT_CRX.write_bytes(crx_bytes)
    OUT_PUBKEY.write_text(base64.b64encode(pub_der).decode('ascii'), encoding='utf-8')

    manifest = json.loads((EXT_DIR / 'manifest.json').read_text(encoding='utf-8'))
    print(f'[build-crx] versão:        {manifest.get("version")}')
    print(f'[build-crx] ID da extensão: {ext_id}')
    print(f'[build-crx] .crx gravado em: {OUT_CRX.relative_to(ROOT)} ({len(crx_bytes)} bytes)')
    print(f'[build-crx] chave pública:   {OUT_PUBKEY.relative_to(ROOT)}')
    print(f'[build-crx] update_url:      {args.update_url}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
