#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Linha de comando do Toca Companion."""

import argparse
import os
import platform
import socket
import sys
import time
from pathlib import Path

from integrations.companion_client import (
    CompanionApiClient,
    CompanionConfigStore,
    CompanionError,
    CompanionRunner,
)


def resolve_version():
    configured = (os.environ.get('TOCA_COMPANION_VERSION') or '').strip()
    if configured:
        return configured
    for base in (Path(__file__).resolve().parent, Path(sys.executable).resolve().parent):
        version_path = base / 'version.txt'
        try:
            value = version_path.read_text(encoding='utf-8').strip()
            if value:
                return value
        except OSError:
            pass
    return '1.0.0'


def build_parser():
    parser = argparse.ArgumentParser(
        description='Toca Companion — executor local seguro das automações do Toca.'
    )
    subcommands = parser.add_subparsers(dest='command', required=True)

    pair = subcommands.add_parser('pair', help='Vincular este computador ao usuário.')
    pair.add_argument('--server', required=True, help='URL HTTPS do Toca web.')
    pair.add_argument('--code', required=True, help='Código de vínculo exibido no Toca.')
    pair.add_argument(
        '--name',
        default=f'{socket.gethostname()} - Toca Companion',
        help='Nome deste dispositivo.',
    )

    run = subcommands.add_parser('run', help='Consumir e executar tarefas.')
    run.add_argument('--once', action='store_true', help='Consultar a fila apenas uma vez.')
    run.add_argument('--poll-seconds', type=int, default=5)

    subcommands.add_parser('status', help='Mostrar o vínculo local sem revelar o token.')
    subcommands.add_parser('manifest', help='Consultar atualizações disponíveis.')
    return parser


def _client_from_store(store, version):
    identity = store.load()
    return identity, CompanionApiClient(
        identity.server_url,
        identity.device_token,
        app_version=version,
    )


def main(argv=None):
    args = build_parser().parse_args(argv)
    version = resolve_version()
    store = CompanionConfigStore()
    try:
        if args.command == 'pair':
            client = CompanionApiClient(args.server, app_version=version)
            paired = client.claim_pairing(
                args.code,
                args.name,
                platform=f'{platform.system()} {platform.release()}',
            )
            store.save(
                server_url=args.server,
                device_id=paired.get('device_id'),
                device_name=args.name,
                device_token=paired.get('device_token'),
            )
            print(f'Companion vinculado com sucesso: {args.name}')
            return 0

        identity, client = _client_from_store(store, version)
        if args.command == 'status':
            print(f'Servidor: {identity.server_url}')
            print(f'Dispositivo: {identity.device_name} ({identity.device_id})')
            print(f'Versão: {version}')
            return 0
        if args.command == 'manifest':
            manifest = client.manifest()
            if manifest.get('update_required'):
                print(f'Atualização obrigatória: {manifest.get("minimum_version")}')
            elif manifest.get('update_available'):
                print(f'Atualização disponível: {manifest.get("latest_version")}')
            else:
                print('Companion atualizado.')
            return 0

        runner = CompanionRunner(client)
        if args.once:
            handled = runner.run_once()
            print('Tarefa processada.' if handled else 'Nenhuma tarefa pendente.')
            return 0
        poll_seconds = max(2, min(int(args.poll_seconds), 60))
        print(
            f'Toca Companion {version} conectado a {identity.server_url}. '
            'Pressione Ctrl+C para encerrar.'
        )
        while True:
            handled = runner.run_once()
            if not handled:
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print('\nCompanion encerrado.')
        return 0
    except CompanionError as exc:
        print(f'Erro [{exc.code}]: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
