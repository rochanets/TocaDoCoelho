#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exportador de metadados do Outlook para o Toca do Coelho.

Requisito: pip install pywin32
Uso:
  python outlook_export.py                    # últimos 60 dias
  python outlook_export.py --days 30          # últimos 30 dias
  python outlook_export.py --output meus_emails.json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers para extração via COM
# ---------------------------------------------------------------------------

def _get_all_subfolders(folder):
    """Retorna a pasta e todos os seus subdiretórios, recursivamente."""
    result = [folder]
    try:
        for subfolder in folder.Folders:
            result.extend(_get_all_subfolders(subfolder))
    except Exception:
        pass
    return result


def _smtp_from_recipient(recipient):
    """
    Tenta extrair endereço SMTP de um recipient.
    Endereços internos do Exchange (tipo EX) começam com '/o=' e não são emails válidos.
    """
    try:
        addr = (recipient.Address or '').strip().lower()
        if addr and '@' in addr and not addr.startswith('/o='):
            return addr
        # Fallback via PropertyAccessor (PR_SMTP_ADDRESS)
        return recipient.PropertyAccessor.GetProperty(
            'http://schemas.microsoft.com/mapi/proptag/0x39FE001E'
        ).strip().lower()
    except Exception:
        return ''


def _smtp_from_sender(mail_item):
    """
    Tenta extrair endereço SMTP do remetente.
    """
    try:
        addr = (mail_item.SenderEmailAddress or '').strip().lower()
        if addr and '@' in addr and not addr.startswith('/o='):
            return addr
        # Fallback via PR_SENT_REPRESENTING_SMTP_ADDRESS
        return mail_item.PropertyAccessor.GetProperty(
            'http://schemas.microsoft.com/mapi/proptag/0x5D01001E'
        ).strip().lower()
    except Exception:
        return ''


def _extract_recipients(mail_item):
    result = []
    try:
        for r in mail_item.Recipients:
            try:
                email = _smtp_from_recipient(r)
                result.append({
                    'name': (r.Name or '').strip(),
                    'email': email
                })
            except Exception:
                pass
    except Exception:
        pass
    return result


def _pywintypes_to_datetime(dt):
    """Converte pywintypes.datetime para datetime nativo."""
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def _extract_email_data(item, direction, cutoff):
    """
    Extrai metadados de um MailItem.
    Retorna dict ou None se fora do período, inválido ou erro.
    """
    try:
        # Ignorar itens que não são emails (reuniões, tarefas, etc.)
        if item.Class != 43:  # 43 = olMail
            return None

        raw_dt = item.ReceivedTime if direction == 'received' else item.SentOn
        dt = _pywintypes_to_datetime(raw_dt)

        if dt < cutoff:
            return None

        subject = (item.Subject or '').strip()
        body_preview = ''
        try:
            body_preview = (item.Body or '')[:1500].strip()
        except Exception:
            pass

        sender = {
            'name': (item.SenderName or '').strip(),
            'email': _smtp_from_sender(item)
        }
        recipients = _extract_recipients(item)

        return {
            'subject': subject,
            'date': dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'direction': direction,
            'sender': sender,
            'recipients': recipients,
            'body_preview': body_preview
        }
    except AttributeError:
        return None  # item sem propriedades de email
    except Exception:
        return None


def _process_folder(folder, direction, cutoff, emails):
    """Processa emails de uma pasta com filtro de data no Outlook."""
    count = 0
    try:
        items = folder.Items
        date_str = cutoff.strftime('%m/%d/%Y %H:%M %p')
        filter_field = 'ReceivedTime' if direction == 'received' else 'SentOn'
        try:
            items = items.Restrict(f"[{filter_field}] >= '{date_str}'")
        except Exception:
            pass  # Se falhar, itera tudo e filtra manualmente

        for item in items:
            try:
                data = _extract_email_data(item, direction, cutoff)
                if data:
                    emails.append(data)
                    count += 1
            except Exception:
                pass
    except Exception as e:
        print(f'    [AVISO] Erro ao processar pasta "{getattr(folder, "Name", "?")}": {e}')
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Exporta metadados de emails do Outlook para importação no Toca do Coelho'
    )
    parser.add_argument(
        '--days', type=int, default=60,
        help='Período em dias para exportar (padrão: 60)'
    )
    parser.add_argument(
        '--output', type=str, default='',
        help='Arquivo de saída JSON (padrão: outlook_export_YYYYMMDD_HHMMSS.json)'
    )
    parser.add_argument(
        '--upload', action='store_true',
        help='Envia o JSON diretamente ao Toca do Coelho em http://localhost:3000 após exportar'
    )
    parser.add_argument(
        '--toca-url', type=str, default='http://localhost:3000',
        help='URL do Toca do Coelho (padrão: http://localhost:3000)'
    )
    args = parser.parse_args()

    try:
        import win32com.client  # noqa: F401
    except ImportError:
        print('[ERRO] Módulo pywin32 não encontrado.')
        print('       Instale com: pip install pywin32')
        sys.exit(1)

    cutoff = datetime.now() - timedelta(days=args.days)
    output_file = args.output or f'outlook_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

    print('=' * 56)
    print('  Exportador de Emails — Toca do Coelho')
    print('=' * 56)
    print(f'  Período  : últimos {args.days} dias (desde {cutoff.strftime("%d/%m/%Y")})')
    print(f'  Saída    : {output_file}')
    print()

    # Conectar ao Outlook
    print('[INFO] Conectando ao Outlook...')
    try:
        import win32com.client
        outlook = win32com.client.Dispatch('Outlook.Application')
        namespace = outlook.GetNamespace('MAPI')
    except Exception as e:
        print(f'[ERRO] Não foi possível conectar ao Outlook: {e}')
        print('       Certifique-se de que o Outlook está aberto e instalado.')
        sys.exit(1)

    emails = []

    # --- Caixa de Entrada + todas as subpastas ---
    print('[INFO] Lendo Caixa de Entrada (com subpastas)...')
    try:
        inbox = namespace.GetDefaultFolder(6)  # olFolderInbox = 6
        all_folders = _get_all_subfolders(inbox)
        for folder in all_folders:
            try:
                n = _process_folder(folder, 'received', cutoff, emails)
                if n:
                    print(f'    {folder.Name}: {n} email(s)')
            except Exception:
                pass
    except Exception as e:
        print(f'[AVISO] Erro ao acessar Caixa de Entrada: {e}')

    # --- Itens Enviados ---
    print('[INFO] Lendo Itens Enviados...')
    try:
        sent_folder = namespace.GetDefaultFolder(5)  # olFolderSentMail = 5
        n = _process_folder(sent_folder, 'sent', cutoff, emails)
        if n:
            print(f'    Itens Enviados: {n} email(s)')
    except Exception as e:
        print(f'[AVISO] Erro ao acessar Itens Enviados: {e}')

    # --- Gravar JSON ---
    payload = {
        'exported_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'period_days': args.days,
        'total_emails': len(emails),
        'emails': emails
    }

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'[ERRO] Não foi possível gravar o arquivo: {e}')
        sys.exit(1)

    print()
    print('=' * 56)
    print(f'  [OK] {len(emails)} email(s) exportados → {output_file}')

    # --- Upload automático para o Toca do Coelho ---
    if args.upload:
        print()
        print(f'[INFO] Enviando para o Toca do Coelho ({args.toca_url})...')
        try:
            import urllib.request
            import urllib.error

            boundary = '----TocaOutlookBoundary'
            json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            filename = output_file.split('/')[-1].split('\\')[-1]

            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: application/json\r\n\r\n'
            ).encode('utf-8') + json_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')

            req = urllib.request.Request(
                f'{args.toca_url}/api/outlook/import',
                data=body,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            print(f'  [OK] {result.get("message", "Importação concluída.")}')
            if result.get('skipped_no_match'):
                print(f'  [INFO] {result["skipped_no_match"]} email(s) sem contato correspondente no sistema.')
        except urllib.error.URLError:
            print('  [AVISO] Toca do Coelho não está rodando ou não acessível.')
            print(f'  Importe manualmente o arquivo "{output_file}" em:')
            print('  Configurações > Importar Emails do Outlook')
        except Exception as e:
            print(f'  [AVISO] Falha no upload automático: {e}')
            print(f'  Importe manualmente o arquivo "{output_file}" em:')
            print('  Configurações > Importar Emails do Outlook')
    else:
        print()
        print('  Próximo passo:')
        print('  Importe o arquivo em Configurações > Importar Emails do Outlook')
        print('  dentro do Toca do Coelho.')

    print('=' * 56)


if __name__ == '__main__':
    main()
