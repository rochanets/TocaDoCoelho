#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import sqlite3
import webbrowser
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False

# Configuracao
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

# Diretorio de dados
if sys.platform == 'win32':
    DATA_DIR = Path('C:/toca-do-coelho-version2')
    OLD_DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
    OLD_DATA_DIR_V1 = Path('C:/toca-do-coelho')  # Migrar da versão anterior sem versionamento
else:
    DATA_DIR = Path.home() / '.toca-do-coelho-version2'
    OLD_DATA_DIR = None
    OLD_DATA_DIR_V1 = None

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'toca-do-coelho-version2.db'
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_UPLOAD_DIR = UPLOAD_DIR / 'accounts'
ACCOUNT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Migração automática do banco de dados antigo
if sys.platform == 'win32' and not DB_PATH.exists():
    import shutil
    migrated = False
    
    # Prioridade 1: Migrar de C:/toca-do-coelho (versão anterior sem versionamento)
    if OLD_DATA_DIR_V1 and OLD_DATA_DIR_V1.exists():
        old_db = OLD_DATA_DIR_V1 / 'toca-do-coelho.db'
        if old_db.exists():
            print(f'[Database] Migrando banco de dados de {old_db} para {DB_PATH}')
            shutil.copy2(str(old_db), str(DB_PATH))
            # Migrar também a pasta de uploads
            old_uploads = OLD_DATA_DIR_V1 / 'uploads'
            if old_uploads.exists():
                for item in old_uploads.iterdir():
                    dest = UPLOAD_DIR / item.name
                    if not dest.exists():
                        if item.is_file():
                            shutil.copy2(str(item), str(dest))
                        elif item.is_dir():
                            shutil.copytree(str(item), str(dest))
            print(f'[Database] Migração de C:/toca-do-coelho concluída com sucesso!')
            migrated = True
    
    # Prioridade 2: Migrar de AppData/Roaming (versão original)
    if not migrated and OLD_DATA_DIR and OLD_DATA_DIR.exists():
        old_db = OLD_DATA_DIR / 'toca-do-coelho.db'
        if old_db.exists():
            print(f'[Database] Migrando banco de dados de {old_db} para {DB_PATH}')
            shutil.copy2(str(old_db), str(DB_PATH))
            # Migrar também a pasta de uploads
            old_uploads = OLD_DATA_DIR / 'uploads'
            if old_uploads.exists():
                for item in old_uploads.iterdir():
                    dest = UPLOAD_DIR / item.name
                    if not dest.exists():
                        if item.is_file():
                            shutil.copy2(str(item), str(dest))
                        elif item.is_dir():
                            shutil.copytree(str(item), str(dest))
            print(f'[Database] Migração de AppData/Roaming concluída com sucesso!')

print(f'[Database] Caminho: {DB_PATH}')

# Inicializar banco de dados
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    # Tabela de clientes
    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        company TEXT NOT NULL,
        position TEXT NOT NULL,
        area_of_activity TEXT,
        email TEXT,
        phone TEXT,
        photo_url TEXT,
        is_target INTEGER DEFAULT 0,
        is_cold_contact INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS job_groupings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS job_grouping_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grouping_id INTEGER NOT NULL,
        position TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(grouping_id) REFERENCES job_groupings(id) ON DELETE CASCADE,
        UNIQUE(grouping_id, position)
    )''')

    # Tabela de configuracoes gerais
    c.execute('''CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Tabela de regras de status por cargo
    c.execute('''CREATE TABLE IF NOT EXISTS status_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position TEXT NOT NULL UNIQUE,
        green_days INTEGER NOT NULL,
        yellow_days INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Tabela de perfil do usuario
    c.execute('''CREATE TABLE IF NOT EXISTS user_profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        full_name TEXT NOT NULL,
        nickname TEXT NOT NULL,
        position TEXT NOT NULL,
        photo_url TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS account_sectors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        logo_url TEXT,
        is_target INTEGER DEFAULT 0,
        sector TEXT,
        average_revenue_cents INTEGER,
        professionals_count INTEGER,
        global_presence TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS account_main_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        UNIQUE(account_id, client_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS account_presences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        delivery_name TEXT NOT NULL,
        stf_owner TEXT,
        current_revenue_cents INTEGER,
        validity_month TEXT,
        focal_client_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY(focal_client_id) REFERENCES clients(id) ON DELETE SET NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS account_renewal_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        presence_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        due_date TEXT NOT NULL,
        due_time TEXT DEFAULT '09:00',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY(presence_id) REFERENCES account_presences(id) ON DELETE CASCADE,
        UNIQUE(presence_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS message_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        available_whatsapp INTEGER DEFAULT 1,
        available_email INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Tabela de compromissos (agenda)
    c.execute('''CREATE TABLE IF NOT EXISTS commitments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        activity_id INTEGER,
        title TEXT NOT NULL,
        notes TEXT,
        due_date TEXT NOT NULL,
        due_time TEXT,
        source_type TEXT DEFAULT 'activity',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE SET NULL
    )''')

    # Tabela de atividades
    c.execute('''CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        contact_type TEXT DEFAULT 'Outro',
        information TEXT,
        description TEXT,
        activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
    )''')
    
    # Tabela de cards de mapeamento de ambiente
    c.execute('''CREATE TABLE IF NOT EXISTS environment_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        display_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Tabela de respostas de mapeamento por cliente
    c.execute('''CREATE TABLE IF NOT EXISTS environment_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        response TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(card_id) REFERENCES environment_cards(id) ON DELETE CASCADE,
        FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE,
        UNIQUE(card_id, client_id)
    )''')
    
    # Tabela de sugestões diárias
    c.execute('''CREATE TABLE IF NOT EXISTS daily_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        suggestion_type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        target_id INTEGER,
        target_data TEXT,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )''')
    
    # Inserir cards pré-definidos se não existirem
    predefined_cards = [
        ('ERP', '', 1),
        ('Cloud', '', 2),
        ('Principal Concorrente', '', 3),
        ('Gestão de Ativos/HAAS', '', 4),
        ('Cyber/Observability', '', 5),
        ('DWS', '', 6)
    ]
    
    for title, description, order in predefined_cards:
        c.execute('SELECT id FROM environment_cards WHERE title = ?', (title,))
        if not c.fetchone():
            c.execute('INSERT INTO environment_cards (title, description, display_order) VALUES (?, ?, ?)', 
                      (title, description, order))
    
    # Adicionar coluna last_activity_date à tabela clients se não existir
    c.execute("PRAGMA table_info(clients)")
    columns = [col[1] for col in c.fetchall()]
    if 'last_activity_date' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN last_activity_date TIMESTAMP')
    if 'is_target' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN is_target INTEGER DEFAULT 0')
    if 'area_of_activity' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN area_of_activity TEXT')
    if 'is_cold_contact' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN is_cold_contact INTEGER DEFAULT 0')

    c.execute("PRAGMA table_info(commitments)")
    commitment_columns = [col[1] for col in c.fetchall()]
    if 'due_time' not in commitment_columns:
        c.execute('ALTER TABLE commitments ADD COLUMN due_time TEXT')
    if 'source_type' not in commitment_columns:
        c.execute('ALTER TABLE commitments ADD COLUMN source_type TEXT DEFAULT "activity"')

    # Configuracoes padrao da faixa de status
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('status_green_days', '7'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('status_yellow_days', '14'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('target_green_days', '5'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('target_yellow_days', '10'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('cold_green_days', '45'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('cold_yellow_days', '60'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('iata_video_path', '/videos/TocaVideo.mp4'))
    
    conn.commit()
    
    # Migração: adicionar colunas se não existirem
    try:
        c.execute("PRAGMA table_info(user_profile)")
        profile_cols = [col[1] for col in c.fetchall()]
        if 'email' not in profile_cols:
            c.execute('ALTER TABLE user_profile ADD COLUMN email TEXT')
        if 'phone' not in profile_cols:
            c.execute('ALTER TABLE user_profile ADD COLUMN phone TEXT')
        if 'boss_name' not in profile_cols:
            c.execute('ALTER TABLE user_profile ADD COLUMN boss_name TEXT')
        if 'boss_email' not in profile_cols:
            c.execute('ALTER TABLE user_profile ADD COLUMN boss_email TEXT')

        c.execute("PRAGMA table_info(activities)")
        columns = [col[1] for col in c.fetchall()]
        if 'contact_type' not in columns:
            c.execute('ALTER TABLE activities ADD COLUMN contact_type TEXT DEFAULT "Outro"')
        if 'information' not in columns:
            c.execute('ALTER TABLE activities ADD COLUMN information TEXT')
        conn.commit()
    except:
        pass
    
    conn.close()
    print('[Database] Banco de dados inicializado')

init_db()

# Funcoes auxiliares
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def dict_from_row(row):
    if row is None:
        return None
    return dict(row)


def parse_currency_to_cents(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r'[^\d,.-]', '', text)
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        return int(round(float(text) * 100))
    except Exception:
        digits = re.sub(r'\D', '', str(value))
        return int(digits) if digits else None


def normalize_phone(phone):
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone))
    if not digits:
        return None
    if len(digits) > 11:
        digits = digits[-11:]
    if len(digits) < 10:
        return digits
    if len(digits) == 10:
        digits = digits[:2] + '9' + digits[2:]
    return f"{digits[:2]} {digits[2:7]}.{digits[7:11]}"


def extract_time_from_text(text):
    if not text:
        return None
    lower = text.lower()
    patterns = [
        r'\b([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)\b',
        r'\b([01]?\d|2[0-3])\s*h\s*([0-5]\d)\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, lower)
        if m:
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.search(r'\b([01]?\d|2[0-3])\s*h\b', lower)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None


def extract_future_commitment_dates(text):
    if not text:
        return []

    now = datetime.now()
    matches = []
    month_map = {
        'janeiro': 1, 'jan': 1,
        'fevereiro': 2, 'fev': 2,
        'marco': 3, 'março': 3, 'mar': 3,
        'abril': 4, 'abr': 4,
        'maio': 5, 'mai': 5,
        'junho': 6, 'jun': 6,
        'julho': 7, 'jul': 7,
        'agosto': 8, 'ago': 8,
        'setembro': 9, 'set': 9,
        'outubro': 10, 'out': 10,
        'novembro': 11, 'nov': 11,
        'dezembro': 12, 'dez': 12,
    }

    def add_date(day, month, year=None):
        y = year or now.year
        if y < 100:
            y += 2000
        try:
            dt = datetime(y, month, day)
            if dt.date() < now.date() and year is None:
                dt = datetime(y + 1, month, day)
            if dt.date() >= now.date():
                matches.append(dt.date().isoformat())
        except ValueError:
            pass

    for m in re.finditer(r'\b(\d{1,2})[\/\.\-](\d{1,2})(?:[\/\.\-](\d{2,4}))?\b', text):
        add_date(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None)

    lowered = text.lower()
    for m in re.finditer(r'\b(\d{1,2})\s+de\s+([a-zç]+)(?:\s+de\s+(\d{2,4}))?\b', lowered):
        day = int(m.group(1))
        month = month_map.get((m.group(2) or '').strip())
        if month:
            add_date(day, month, int(m.group(3)) if m.group(3) else None)

    for m in re.finditer(r'\bem\s+(\d{1,3})\s+dias?\b', lowered):
        days = int(m.group(1))
        if days >= 0:
            matches.append((now.date() + timedelta(days=days)).isoformat())

    if 'depois de amanhã' in lowered or 'depois de amanha' in lowered:
        matches.append((now.date() + timedelta(days=2)).isoformat())
    elif 'amanh' in lowered:
        matches.append((now.date() + timedelta(days=1)).isoformat())

    seen = set()
    ordered = []
    for d in matches:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return ordered


def create_commitments_from_activity(cursor, client_id, activity_id, text):
    dates = extract_future_commitment_dates(text)
    if not dates:
        return []

    safe_title = (text or '').strip().replace('\n', ' ')
    if len(safe_title) > 120:
        safe_title = safe_title[:117] + '...'

    parsed_time = extract_time_from_text(text)
    created = []
    for due_date in dates:
        cursor.execute(
            '''INSERT INTO commitments (client_id, activity_id, title, notes, due_date, due_time, source_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (client_id, activity_id, safe_title or 'Retorno com cliente', text, due_date, parsed_time, 'activity')
        )
        created.append({
            'id': cursor.lastrowid,
            'client_id': client_id,
            'due_date': due_date,
            'due_time': parsed_time,
            'title': safe_title or 'Retorno com cliente',
            'notes': text
        })
    return created


def enrich_commitments_with_client_data(cursor, commitments, client_id):
    if not commitments:
        return commitments
    cursor.execute('SELECT name, company, position, email, photo_url FROM clients WHERE id = ?', (client_id,))
    client = dict_from_row(cursor.fetchone()) or {}
    for item in commitments:
        item['client_name'] = client.get('name')
        item['client_company'] = client.get('company')
        item['client_position'] = client.get('position')
        item['client_email'] = client.get('email')
        item['client_photo'] = client.get('photo_url')
    return commitments


def _col_index(cell_ref):
    letters = ''.join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = (idx * 26) + (ord(ch) - 64)
    return max(idx - 1, 0)


def parse_xlsx_without_openpyxl(file_storage):
    """Le arquivo XLSX usando apenas bibliotecas nativas (fallback)."""
    import io

    file_bytes = file_storage.read()
    file_storage.seek(0)

    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        # shared strings (quando as celulas usam indice de string)
        shared_strings = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in root.findall('x:si', ns):
                parts = [t.text or '' for t in si.findall('.//x:t', ns)]
                shared_strings.append(''.join(parts))

        sheet_name = 'xl/worksheets/sheet1.xml'
        if sheet_name not in zf.namelist():
            # fallback para o primeiro worksheet encontrado
            worksheet_files = [n for n in zf.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')]
            if not worksheet_files:
                raise ValueError('Planilha inválida: worksheet não encontrada')
            sheet_name = sorted(worksheet_files)[0]

        sheet_root = ET.fromstring(zf.read(sheet_name))
        rows = []

        for row in sheet_root.findall('.//x:sheetData/x:row', ns):
            row_data = []
            for cell in row.findall('x:c', ns):
                cell_ref = cell.get('r', '')
                col_idx = _col_index(cell_ref) if cell_ref else len(row_data)

                while len(row_data) < col_idx:
                    row_data.append('')

                cell_type = cell.get('t')
                value = ''

                if cell_type == 's':
                    v = cell.find('x:v', ns)
                    if v is not None and (v.text or '').isdigit():
                        s_idx = int(v.text)
                        if 0 <= s_idx < len(shared_strings):
                            value = shared_strings[s_idx]
                elif cell_type == 'inlineStr':
                    t = cell.find('.//x:t', ns)
                    value = t.text if t is not None and t.text is not None else ''
                else:
                    v = cell.find('x:v', ns)
                    value = v.text if v is not None and v.text is not None else ''

                row_data.append(str(value).strip())

            rows.append(row_data)

    return rows

# API - Clientes (rotas alternativas para compatibilidade)
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    return get_clients()

@app.route('/api/clients', methods=['GET'])
def get_clients():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM clients ORDER BY name')
        clients = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(clients)
    except Exception as e:
        print(f'[ERROR] GET /api/clients: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/cargos', methods=['GET'])
def get_positions():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT position FROM clients WHERE position IS NOT NULL AND TRIM(position) != "" ORDER BY position')
        positions = [row['position'] for row in c.fetchall()]
        conn.close()
        return jsonify(positions)
    except Exception as e:
        print(f'[ERROR] GET /api/cargos: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/empresas', methods=['GET'])
def get_companies():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT company FROM clients WHERE company IS NOT NULL AND TRIM(company) != "" ORDER BY company')
        companies = [row['company'] for row in c.fetchall()]
        conn.close()
        return jsonify(companies)
    except Exception as e:
        print(f'[ERROR] GET /api/empresas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status', methods=['GET'])
def get_status_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT key, value FROM app_settings WHERE key IN ("status_green_days", "status_yellow_days", "target_green_days", "target_yellow_days", "cold_green_days", "cold_yellow_days")')
        settings = {row['key']: row['value'] for row in c.fetchall()}
        c.execute('SELECT id, position, green_days, yellow_days FROM status_rules ORDER BY position')
        rules = [dict_from_row(row) for row in c.fetchall()]
        conn.close()

        return jsonify({
            'universal': {
                'green_days': int(settings.get('status_green_days', '7')),
                'yellow_days': int(settings.get('status_yellow_days', '14'))
            },
            'rules': rules,
            'target': {
                'green_days': int(settings.get('target_green_days', '5')),
                'yellow_days': int(settings.get('target_yellow_days', '10'))
            },
            'cold': {
                'green_days': int(settings.get('cold_green_days', '45')),
                'yellow_days': int(settings.get('cold_yellow_days', '60'))
            }
        })
    except Exception as e:
        print(f'[ERROR] GET /api/config/status: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/universal', methods=['PUT'])
def update_universal_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 7))
        yellow_days = int(data.get('yellow_days', 14))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'status_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'status_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração universal atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/config/status/universal: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/config/status/target', methods=['PUT'])
def update_target_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 5))
        yellow_days = int(data.get('yellow_days', 10))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'target_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'target_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração Target atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/config/status/target: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/config/status/cold', methods=['PUT'])
def update_cold_status_config():
    try:
        data = request.get_json() or {}
        green_days = int(data.get('green_days', 45))
        yellow_days = int(data.get('yellow_days', 60))

        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(green_days), 'cold_green_days'))
        c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(yellow_days), 'cold_yellow_days'))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Configuração de contato frio atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/config/status/cold: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings', methods=['GET'])
def list_position_groupings():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name FROM job_groupings ORDER BY name')
        groups = [dict_from_row(row) for row in c.fetchall()]
        for group in groups:
            c.execute('SELECT position FROM job_grouping_positions WHERE grouping_id = ? ORDER BY position', (group['id'],))
            group['positions'] = [row['position'] for row in c.fetchall()]
        conn.close()
        return jsonify(groups)
    except Exception as e:
        print(f'[ERROR] GET /api/config/position-groupings: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings', methods=['POST'])
def create_position_grouping():
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        positions = sorted(set([(p or '').strip() for p in (data.get('positions') or []) if (p or '').strip()]))

        if not name or len(positions) < 2:
            return jsonify({'error': 'Informe um nome e ao menos 2 cargos'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO job_groupings (name, updated_at) VALUES (?, CURRENT_TIMESTAMP)', (name,))
        grouping_id = c.lastrowid
        for position in positions:
            c.execute('INSERT INTO job_grouping_positions (grouping_id, position) VALUES (?, ?)', (grouping_id, position))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Agrupamento criado'})
    except Exception as e:
        print(f'[ERROR] POST /api/config/position-groupings: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/position-groupings/<int:grouping_id>', methods=['DELETE'])
def delete_position_grouping(grouping_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM job_groupings WHERE id = ?', (grouping_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Agrupamento removido'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/config/position-groupings/{grouping_id}: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/status/rules', methods=['POST'])
def create_or_update_status_rule():
    try:
        data = request.get_json() or {}
        position = (data.get('position') or '').strip()
        green_days = int(data.get('green_days', 7))
        yellow_days = int(data.get('yellow_days', 14))

        if not position:
            return jsonify({'error': 'Cargo é obrigatório'}), 400
        if green_days < 0 or yellow_days <= green_days:
            return jsonify({'error': 'Faixas inválidas: amarelo deve ser maior que verde'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO status_rules (position, green_days, yellow_days, updated_at)
                     VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                     ON CONFLICT(position) DO UPDATE SET
                        green_days = excluded.green_days,
                        yellow_days = excluded.yellow_days,
                        updated_at = CURRENT_TIMESTAMP''',
                  (position, green_days, yellow_days))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Regra por cargo salva'})
    except Exception as e:
        print(f'[ERROR] POST /api/config/status/rules: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/status/rules/<int:rule_id>', methods=['DELETE'])
def delete_status_rule(rule_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM status_rules WHERE id = ?', (rule_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Regra removida'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/config/status/rules/{rule_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/profile', methods=['GET'])
def get_profile_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM user_profile WHERE id = 1')
        profile = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(profile or {})
    except Exception as e:
        print(f'[ERROR] GET /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/config/ui', methods=['GET'])
def get_ui_config():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT key, value FROM app_settings WHERE key IN ("iata_video_path")')
        settings = {row['key']: row['value'] for row in c.fetchall()}
        conn.close()
        return jsonify({'iata_video_path': settings.get('iata_video_path', '/videos/TocaVideo.mp4')})
    except Exception as e:
        print(f'[ERROR] GET /api/config/ui: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/profile', methods=['POST'])
def save_profile_config():
    try:
        full_name = request.form.get('full_name', '').strip()
        nickname = request.form.get('nickname', '').strip()
        position = request.form.get('position', '').strip()
        email = request.form.get('email', '').strip()
        phone = normalize_phone(request.form.get('phone', '').strip())
        boss_name = request.form.get('boss_name', '').strip() or None
        boss_email = request.form.get('boss_email', '').strip() or None

        if not full_name or not nickname or not position or not email or not phone:
            return jsonify({'error': 'Nome completo, apelido, cargo, email e telefone são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT photo_url FROM user_profile WHERE id = 1')
        row = c.fetchone()
        photo_url = row['photo_url'] if row else None

        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'

        if not photo_url:
            return jsonify({'error': 'Foto é obrigatória'}), 400

        c.execute('''INSERT INTO user_profile (id, full_name, nickname, position, email, phone, photo_url, boss_name, boss_email, updated_at)
                     VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                     ON CONFLICT(id) DO UPDATE SET
                        full_name = excluded.full_name,
                        nickname = excluded.nickname,
                        position = excluded.position,
                        email = excluded.email,
                        phone = excluded.phone,
                        photo_url = excluded.photo_url,
                        boss_name = excluded.boss_name,
                        boss_email = excluded.boss_email,
                        updated_at = CURRENT_TIMESTAMP''',
                  (full_name, nickname, position, email, phone, photo_url, boss_name, boss_email))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Perfil salvo'})
    except Exception as e:
        print(f'[ERROR] POST /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/profile', methods=['DELETE'])
def delete_profile_config():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM user_profile WHERE id = 1')
        conn.commit()
        conn.close()
        return jsonify({'message': 'Usuário excluído com sucesso'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/config/profile: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/clients/<int:client_id>', methods=['GET'])
def get_client(client_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        client = dict_from_row(c.fetchone())
        conn.close()
        
        if not client:
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        return jsonify(client)
    except Exception as e:
        print(f'[ERROR] GET /api/clients/{client_id}: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/clients/check-duplicate', methods=['POST'])
def check_duplicate_client():
    try:
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()
        phone = normalize_phone((data.get('phone') or '').strip())
        exclude_id = data.get('exclude_id')

        clauses = []
        params = []
        if name:
            clauses.append('LOWER(TRIM(name)) = LOWER(TRIM(?))')
            params.append(name)
        if email:
            clauses.append('LOWER(TRIM(email)) = LOWER(TRIM(?))')
            params.append(email)
        if phone:
            clauses.append('TRIM(phone) = TRIM(?)')
            params.append(phone)

        if not clauses:
            return jsonify({'matches': []})

        where = ' OR '.join(f'({c})' for c in clauses)
        sql = f'SELECT * FROM clients WHERE {where}'
        if exclude_id:
            sql += ' AND id != ?'
            params.append(int(exclude_id))

        conn = get_db()
        c = conn.cursor()
        c.execute(sql, params)
        matches = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify({'matches': matches})
    except Exception as e:
        print(f'[ERROR] POST /api/clients/check-duplicate: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/clientes', methods=['POST'])
def create_cliente():
    return create_client()

@app.route('/api/clients', methods=['POST'])
def create_client():
    try:
        print('[DEBUG] POST /api/clients')
        print(f'[DEBUG] Content-Type: {request.content_type}')
        print(f'[DEBUG] Form data: {request.form}')
        print(f'[DEBUG] Files: {request.files}')
        
        name = request.form.get('name', '').strip()
        company = request.form.get('company', '').strip()
        position = request.form.get('position', '').strip()
        email = request.form.get('email', '').strip()
        phone = normalize_phone(request.form.get('phone', '').strip())
        area_of_activity = request.form.get('area_of_activity', '').strip()
        is_cold_contact = 1 if request.form.get('is_cold_contact') in ('1', 'true', 'on') else 0
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'on') else 0
        force_create = request.form.get('force_create') in ('1', 'true', 'on')
        
        if not name or not company or not position:
            return jsonify({'error': 'Nome, empresa e cargo sao obrigatorios'}), 400
        
        if not force_create:
            duplicate_clauses = []
            duplicate_params = []
            if name:
                duplicate_clauses.append('LOWER(TRIM(name)) = LOWER(TRIM(?))')
                duplicate_params.append(name)
            if email:
                duplicate_clauses.append('LOWER(TRIM(email)) = LOWER(TRIM(?))')
                duplicate_params.append(email)
            if phone:
                duplicate_clauses.append('TRIM(phone) = TRIM(?)')
                duplicate_params.append(phone)
            if duplicate_clauses:
                conn = get_db()
                c = conn.cursor()
                c.execute(f"SELECT * FROM clients WHERE {' OR '.join([f'({cl})' for cl in duplicate_clauses])} ORDER BY id DESC LIMIT 1", duplicate_params)
                existing = dict_from_row(c.fetchone())
                conn.close()
                if existing:
                    return jsonify({'error': 'Possível duplicidade encontrada', 'duplicate': existing}), 409

        photo_url = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO clients (name, company, position, area_of_activity, email, phone, photo_url, is_target, is_cold_contact)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (name, company, position, area_of_activity or None, email or None, phone or None, photo_url, is_target, is_cold_contact))
        conn.commit()
        client_id = c.lastrowid
        conn.close()
        
        print(f'[DEBUG] Cliente criado com ID: {client_id}')
        return jsonify({'id': client_id, 'message': 'Cliente criado'}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/clients: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/clientes/<int:client_id>', methods=['PUT'])
def update_cliente(client_id):
    return update_client(client_id)

@app.route('/api/clients/<int:client_id>', methods=['PUT'])
def update_client(client_id):
    try:
        print(f'[DEBUG] PUT /api/clients/{client_id}')
        
        name = request.form.get('name', '').strip()
        company = request.form.get('company', '').strip()
        position = request.form.get('position', '').strip()
        email = request.form.get('email', '').strip()
        phone = normalize_phone(request.form.get('phone', '').strip())
        area_of_activity = request.form.get('area_of_activity', '').strip()
        is_cold_contact = 1 if request.form.get('is_cold_contact') in ('1', 'true', 'on') else 0
        remove_photo = request.form.get('remove_photo', '0') == '1'
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'on') else 0
        
        if not name or not company or not position:
            return jsonify({'error': 'Nome, empresa e cargo sao obrigatorios'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Obter cliente atual
        c.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        client = dict_from_row(c.fetchone())
        if not client:
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        
        photo_url = None if remove_photo else client['photo_url']
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'
        
        c.execute('''UPDATE clients SET name = ?, company = ?, position = ?, area_of_activity = ?, email = ?, phone = ?, photo_url = ?, is_target = ?, is_cold_contact = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (name, company, position, area_of_activity or None, email or None, phone or None, photo_url, is_target, is_cold_contact, client_id))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Cliente {client_id} atualizado')
        return jsonify({'message': 'Cliente atualizado'})
    except Exception as e:
        print(f'[ERROR] PUT /api/clients/{client_id}: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/clientes/<int:client_id>', methods=['DELETE'])
def delete_cliente(client_id):
    return delete_client(client_id)

@app.route('/api/clients/<int:client_id>', methods=['DELETE'])
def delete_client(client_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM clients WHERE id = ?', (client_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Cliente deletado'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/clients/{client_id}: {e}')
        return jsonify({'error': str(e)}), 500

# API - Atividades (rotas alternativas para compatibilidade)
@app.route('/api/atividades', methods=['GET'])
def get_atividades():
    return get_activities()

@app.route('/api/activities', methods=['GET'])
def get_activities():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT a.*, c.name, c.company, c.position FROM activities a
                     JOIN clients c ON a.client_id = c.id
                     ORDER BY a.activity_date DESC''')
        activities = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(activities)
    except Exception as e:
        print(f'[ERROR] GET /api/activities: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/atividades', methods=['POST'])
def create_atividade():
    try:
        print('[DEBUG] POST /api/atividades')
        # Aceitar tanto JSON quanto FormData
        if request.is_json:
            data = request.get_json()
            client_id = data.get('client_id')
            contact_type = data.get('contact_type', 'Outro')
            information = data.get('information', '').strip()
        else:
            client_id = request.form.get('client_id')
            contact_type = request.form.get('contact_type', 'Outro')
            information = request.form.get('information', '').strip()
        
        print(f'[DEBUG] client_id: {client_id}, contact_type: {contact_type}, information: {information}')
        
        if not client_id or not information:
            return jsonify({'error': 'Cliente e informacoes sao obrigatorios'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Verificar se cliente existe
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        
        # Salvar com campos separados
        c.execute('''INSERT INTO activities (client_id, contact_type, information)
                     VALUES (?, ?, ?)''',
                  (client_id, contact_type, information))
        conn.commit()
        activity_id = c.lastrowid

        # Detectar compromissos futuros no texto da atividade e registrar na agenda
        created_commitments = create_commitments_from_activity(c, client_id, activity_id, information)
        created_commitments = enrich_commitments_with_client_data(c, created_commitments, client_id)
        conn.commit()
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada', 'commitments_created': created_commitments}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/atividades: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/activities', methods=['POST'])
def create_activity():
    try:
        print('[DEBUG] POST /api/activities')
        data = request.get_json()
        print(f'[DEBUG] Data: {data}')
        
        client_id = data.get('client_id')
        description = data.get('description', '').strip()
        
        if not client_id or not description:
            return jsonify({'error': 'Cliente e descricao sao obrigatorios'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Verificar se cliente existe
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente nao encontrado'}), 404
        
        c.execute('''INSERT INTO activities (client_id, information)
                     VALUES (?, ?)''',
                  (client_id, description))
        conn.commit()
        activity_id = c.lastrowid

        # Detectar compromissos futuros no texto da atividade e registrar na agenda
        created_commitments = create_commitments_from_activity(c, client_id, activity_id, description)
        created_commitments = enrich_commitments_with_client_data(c, created_commitments, client_id)
        conn.commit()
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada', 'commitments_created': created_commitments}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/activities: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/atividades/<int:activity_id>', methods=['PUT'])
def update_atividade(activity_id):
    try:
        print(f'[DEBUG] PUT /api/atividades/{activity_id}')
        # Aceitar tanto JSON quanto FormData
        if request.is_json:
            data = request.get_json()
            contact_type = data.get('contact_type', 'Outro')
            information = data.get('information', '').strip()
        else:
            contact_type = request.form.get('contact_type', 'Outro')
            information = request.form.get('information', '').strip()
        
        if not information:
            return jsonify({'error': 'Informacoes sao obrigatorias'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''UPDATE activities SET contact_type = ?, information = ? WHERE id = ?''',
                  (contact_type, information, activity_id))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Atividade {activity_id} atualizada')
        return jsonify({'message': 'Atividade atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/atividades/{activity_id}: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/atividades/<int:activity_id>', methods=['DELETE'])
def delete_atividade(activity_id):
    return delete_activity(activity_id)

@app.route('/api/activities/<int:activity_id>', methods=['DELETE'])
def delete_activity(activity_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM activities WHERE id = ?', (activity_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Atividade deletada'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/activities/{activity_id}: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/agenda', methods=['GET'])
def get_agenda():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        conn = get_db()
        c = conn.cursor()

        query = '''SELECT CAST(cm.id AS TEXT) as id, cm.client_id, cm.activity_id, cm.title, cm.notes, cm.due_date, cm.due_time, cm.source_type,
                          cl.name as client_name, cl.company as client_company, cl.position as client_position, cl.email as client_email, cl.photo_url as client_photo
                   FROM commitments cm
                   JOIN clients cl ON cm.client_id = cl.id'''
        params = []

        if start_date and end_date:
            query += ' WHERE DATE(cm.due_date) >= ? AND DATE(cm.due_date) <= ?'
            params.extend([start_date, end_date])

        query += ''' UNION ALL SELECT "acc-" || CAST(ev.id AS TEXT) as id, NULL as client_id, NULL as activity_id, ev.title, ev.title as notes, ev.due_date, ev.due_time, "account_presence" as source_type,
                          ac.name as client_name, ac.name as client_company, "Conta" as client_position, NULL as client_email, ac.logo_url as client_photo
                   FROM account_renewal_events ev
                   JOIN accounts ac ON ev.account_id = ac.id'''
        if start_date and end_date:
            query += ' WHERE DATE(ev.due_date) >= ? AND DATE(ev.due_date) <= ?'
            params.extend([start_date, end_date])

        query += ' ORDER BY due_date ASC, id ASC'
        c.execute(query, params)
        items = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    except Exception as e:
        print(f'[ERROR] GET /api/agenda: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda', methods=['POST'])
def create_agenda_item():
    try:
        data = request.get_json() or {}
        client_id = data.get('client_id')
        due_date = (data.get('due_date') or '').strip()
        due_time = (data.get('due_time') or '').strip() or None
        title = (data.get('title') or '').strip()
        notes = (data.get('notes') or '').strip()

        if not client_id or not due_date:
            return jsonify({'error': 'Cliente e data são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Cliente não encontrado'}), 404

        c.execute('''INSERT INTO commitments (client_id, title, notes, due_date, due_time, source_type)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (client_id, title or 'Agenda manual', notes or title or 'Agenda manual', due_date, due_time, 'manual'))
        commitment_id = c.lastrowid
        conn.commit()

        c.execute('''SELECT cm.*, cl.name as client_name, cl.company as client_company, cl.position as client_position, cl.email as client_email, cl.photo_url as client_photo
                     FROM commitments cm JOIN clients cl ON cm.client_id = cl.id WHERE cm.id = ?''', (commitment_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify({'message': 'Compromisso criado', 'item': item}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/agenda: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/<int:commitment_id>/time', methods=['PUT'])
def update_agenda_time(commitment_id):
    try:
        data = request.get_json() or {}
        due_time = (data.get('due_time') or '').strip()
        if not due_time:
            return jsonify({'error': 'Horário obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE commitments SET due_time = ? WHERE id = ?', (due_time, commitment_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Horário atualizado'})
    except Exception as e:
        print(f'[ERROR] PUT /api/agenda/{commitment_id}/time: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/agenda/<int:commitment_id>', methods=['DELETE'])
def delete_agenda_item(commitment_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM commitments WHERE id = ?', (commitment_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Compromisso removido'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/agenda/{commitment_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/<int:commitment_id>/ics', methods=['GET'])
def download_agenda_ics(commitment_id):
    try:
        attendee = (request.args.get('attendee') or '').strip()
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT cm.*, cl.name as client_name, cl.company as client_company, cl.email as client_email FROM commitments cm JOIN clients cl ON cm.client_id = cl.id WHERE cm.id = ?', (commitment_id,))
        item = dict_from_row(c.fetchone())
        conn.close()

        if not item:
            return jsonify({'error': 'Compromisso não encontrado'}), 404

        due_date = item.get('due_date')
        due_time = item.get('due_time') or '09:00'
        dtstart = datetime.fromisoformat(f"{due_date}T{due_time}:00")
        dtend = dtstart + timedelta(hours=1)

        uid = f"toca-{commitment_id}@local"
        stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        start = dtstart.strftime('%Y%m%dT%H%M%S')
        end = dtend.strftime('%Y%m%dT%H%M%S')
        summary = (item.get('title') or 'Compromisso').replace('\n', ' ')
        description = (item.get('notes') or '').replace('\n', '\\n')

        attendee_lines = ''
        if attendee:
            attendee_lines = f"ATTENDEE;CN={attendee}:mailto:{attendee}\r\n"

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Toca do Coelho//Agenda//PT-BR\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{stamp}\r\n"
            f"DTSTART:{start}\r\n"
            f"DTEND:{end}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"DESCRIPTION:{description}\r\n"
            f"LOCATION:{item.get('client_company') or ''}\r\n"
            f"{attendee_lines}"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        from flask import Response
        response = Response(ics, mimetype='text/calendar')
        response.headers['Content-Disposition'] = f'attachment; filename=agenda-{commitment_id}.ics'
        return response
    except Exception as e:
        print(f'[ERROR] GET /api/agenda/{commitment_id}/ics: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/agenda/semana-atual-count', methods=['GET'])
def get_week_commitments_count():
    try:
        today = datetime.now().date()
        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)

        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) as total FROM commitments
                     WHERE DATE(due_date) >= ? AND DATE(due_date) <= ?''',
                  (start_week.isoformat(), end_week.isoformat()))
        total = c.fetchone()['total']
        conn.close()

        return jsonify({
            'total': total,
            'start_week': start_week.isoformat(),
            'end_week': end_week.isoformat()
        })
    except Exception as e:
        print(f'[ERROR] GET /api/agenda/semana-atual-count: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/clients/<int:client_id>/target', methods=['PUT'])
def update_client_target(client_id):
    try:
        data = request.get_json() or {}
        is_target = 1 if data.get('is_target') else 0

        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE clients SET is_target = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (is_target, client_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Target atualizado'})
    except Exception as e:
        print(f'[ERROR] PUT /api/clients/{client_id}/target: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/clients/target-bulk', methods=['POST'])
def update_target_bulk():
    try:
        data = request.get_json() or {}
        company = (data.get('company') or '').strip()
        position = (data.get('position') or '').strip()

        if not company and not position:
            return jsonify({'error': 'Informe empresa ou cargo'}), 400

        conn = get_db()
        c = conn.cursor()
        where = []
        params = []
        if company:
            where.append('company = ?')
            params.append(company)
        if position:
            where.append('position = ?')
            params.append(position)

        c.execute(f"UPDATE clients SET is_target = 1, updated_at = CURRENT_TIMESTAMP WHERE {' AND '.join(where)}", params)
        affected = c.rowcount
        conn.commit()
        conn.close()
        return jsonify({'message': 'Target em massa aplicado', 'affected': affected})
    except Exception as e:
        print(f'[ERROR] POST /api/clients/target-bulk: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/export/group-xlsx', methods=['GET'])
def export_group_xlsx():
    try:
        group_type = (request.args.get('group_type') or '').strip().lower()
        group_value = (request.args.get('group_value') or '').strip()

        if group_type not in ('company', 'position') or not group_value:
            return jsonify({'error': 'Parâmetros inválidos'}), 400

        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Exportação XLSX requer openpyxl instalado'}), 500

        conn = get_db()
        c = conn.cursor()

        if group_type == 'company':
            c.execute('''
                SELECT name, position, email, phone
                FROM clients
                WHERE LOWER(company) = LOWER(?)
                ORDER BY
                    CASE
                        WHEN LOWER(TRIM(position)) = 'ceo' THEN 1
                        WHEN LOWER(TRIM(position)) LIKE 'c%' AND LENGTH(TRIM(position)) <= 4 THEN 2
                        WHEN LOWER(position) LIKE '%diretor%' OR LOWER(position) LIKE '%superintendente%' THEN 3
                        WHEN LOWER(position) LIKE '%gerente%' THEN 4
                        WHEN LOWER(position) LIKE '%coordenador%' THEN 5
                        ELSE 6
                    END,
                    LOWER(name)
            ''', (group_value,))
        else:
            c.execute('''
                SELECT name, position, email, phone
                FROM clients
                WHERE LOWER(position) = LOWER(?)
                ORDER BY LOWER(name)
            ''', (group_value,))

        rows = c.fetchall()
        conn.close()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Grupo'
        ws.append(['Nome', 'Cargo', 'Email', 'Telefone'])

        for row in rows:
            ws.append([
                row['name'] or '',
                row['position'] or '',
                row['email'] or '',
                row['phone'] or ''
            ])

        from io import BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        from flask import send_file
        safe_group = secure_filename(group_value) or 'grupo'
        file_name = f'grupo-{group_type}-{safe_group}.xlsx'
        return send_file(
            output,
            as_attachment=True,
            download_name=file_name,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        print(f'[ERROR] GET /api/export/group-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


# Rotas de exportacao
@app.route('/api/export/clientes', methods=['GET'])
def export_clientes():
    try:
        import csv
        from io import StringIO
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name, company, position, email, phone, created_at FROM clients ORDER BY name')
        rows = c.fetchall()
        conn.close()
        
        # Criar CSV em memoria
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Nome', 'Empresa', 'Cargo', 'Email', 'Telefone', 'Data de Cadastro'])
        
        for row in rows:
            writer.writerow([
                row['id'],
                row['name'],
                row['company'],
                row['position'],
                row['email'] or '',
                row['phone'] or '',
                row['created_at']
            ])
        
        # Retornar como arquivo
        from flask import Response
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=clientes.csv'
        return response
    except Exception as e:
        print(f'[ERROR] GET /api/export/clientes: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/atividades', methods=['GET'])
def export_atividades():
    try:
        import csv
        from io import StringIO
        
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        conn = get_db()
        c = conn.cursor()
        
        if start_date and end_date:
            c.execute('''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at 
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        WHERE DATE(a.created_at) >= ? AND DATE(a.created_at) <= ?
                        ORDER BY a.created_at DESC''',
                     (start_date, end_date))
        else:
            c.execute('''SELECT a.id, c.name, c.company, c.position, a.description, a.created_at 
                        FROM activities a
                        JOIN clients c ON a.client_id = c.id
                        ORDER BY a.created_at DESC''')
        
        rows = c.fetchall()
        conn.close()
        
        # Criar CSV em memoria
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Cliente', 'Empresa', 'Cargo', 'Informacoes', 'Data'])
        
        for row in rows:
            writer.writerow([
                row['id'],
                row['name'],
                row['company'],
                row['position'],
                row['description'],
                row['created_at']
            ])
        
        # Retornar como arquivo
        from flask import Response
        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=atividades.csv'
        return response
    except Exception as e:
        print(f'[ERROR] GET /api/export/atividades: {e}')
        return jsonify({'error': str(e)}), 500

# Importar clientes via CSV/Excel (suporta CSV e XLSX) COM VALIDACOES
@app.route('/api/importar-clientes', methods=['POST'])
def import_clients():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Nenhum arquivo selecionado'}), 400
        
        import csv
        import io
        import tempfile
        
        filename = file.filename.lower()
        rows = []
        
        # VALIDACAO 1: Verificar tamanho do arquivo (maximo 5MB)
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
        if file_size > MAX_FILE_SIZE:
            return jsonify({'error': f'Arquivo muito grande. Maximo: 5MB. Tamanho: {file_size / 1024 / 1024:.2f}MB'}), 400
        
        # Detectar tipo de arquivo
        if filename.endswith('.xls') and not filename.endswith('.xlsx'):
            return jsonify({'error': 'Formato .xls não suportado. Salve como .xlsx ou .csv.'}), 400

        if filename.endswith('.xlsx'):
            try:
                if OPENPYXL_AVAILABLE:
                    from openpyxl import load_workbook

                    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                        file.save(tmp.name)
                        wb = load_workbook(tmp.name, data_only=True)
                        ws = wb.active

                        for idx, row in enumerate(ws.iter_rows(values_only=True)):
                            if idx == 0:
                                continue
                            row_data = []
                            for cell in row:
                                if cell is None:
                                    row_data.append('')
                                else:
                                    val = str(cell).strip()
                                    if any(ord(c) > 127 and ord(c) < 160 for c in val):
                                        val = val.encode('utf-8', errors='ignore').decode('utf-8')
                                    row_data.append(val)
                            rows.append(row_data)

                        os.unlink(tmp.name)
                else:
                    parsed_rows = parse_xlsx_without_openpyxl(file)
                    for idx, row in enumerate(parsed_rows):
                        if idx == 0:
                            continue
                        rows.append(row)
            except Exception as e:
                print(f'[ERROR] Excel parsing: {e}')
                return jsonify({'error': f'Erro ao ler Excel: {str(e)}'}), 400
        else:
            try:
                # Ler arquivo e detectar encoding
                file_content = file.stream.read()

                # Detectar encoding com chardet quando disponivel,
                # mas manter fallback para nao quebrar importacao.
                if CHARDET_AVAILABLE:
                    detected = chardet.detect(file_content)
                    encoding = detected.get('encoding', 'utf-8') or 'utf-8'
                    try:
                        text = file_content.decode(encoding)
                    except:
                        text = file_content.decode('utf-8', errors='ignore')
                else:
                    # fallback sem dependencia externa
                    try:
                        text = file_content.decode('utf-8')
                    except UnicodeDecodeError:
                        text = file_content.decode('latin-1', errors='ignore')
                
                stream = io.StringIO(text, newline=None)
                csv_data = csv.reader(stream)
                
                for idx, row in enumerate(csv_data):
                    if idx == 0:
                        continue
                    rows.append(row)
            except Exception as e:
                print(f'[ERROR] CSV parsing: {e}')
                return jsonify({'error': f'Erro ao ler CSV: {str(e)}'}), 400
        
        # VALIDACAO 2: Verificar quantidade de linhas (maximo 1000)
        MAX_ROWS = 1000
        if len(rows) > MAX_ROWS:
            return jsonify({'error': f'Arquivo contem muitas linhas. Maximo: {MAX_ROWS}. Enviado: {len(rows)}'}), 400
        
        if len(rows) == 0:
            return jsonify({'error': 'Arquivo vazio ou sem dados validos'}), 400
        
        # VALIDACAO 3: Validar estrutura dos dados
        invalid_rows = []
        valid_rows = []
        
        for idx, row in enumerate(rows):
            if len(row) < 3:
                invalid_rows.append(f'Linha {idx + 2}: Dados incompletos (minimo 3 campos)')
                continue
            
            name = row[0].strip() if len(row) > 0 else ''
            company = row[1].strip() if len(row) > 1 else ''
            position = row[2].strip() if len(row) > 2 else ''
            email = row[3].strip() if len(row) > 3 else None
            phone = row[4].strip() if len(row) > 4 else None
            
            # VALIDACAO 4: Campos obrigatorios nao podem estar vazios
            if not name or not company or not position:
                invalid_rows.append(f'Linha {idx + 2}: Nome, Empresa ou Cargo vazios')
                continue
            
            # VALIDACAO 5: Validar tamanho dos campos
            if len(name) > 100 or len(company) > 100 or len(position) > 100:
                invalid_rows.append(f'Linha {idx + 2}: Campos muito longos (maximo 100 caracteres)')
                continue
            
            # VALIDACAO 6: Validar email se fornecido
            if email and '@' not in email:
                invalid_rows.append(f'Linha {idx + 2}: Email invalido')
                continue
            
            valid_rows.append({
                'name': name,
                'company': company,
                'position': position,
                'email': email,
                'phone': phone
            })
        
        # Se houver erros de validacao, retornar sem importar nada
        if invalid_rows:
            error_msg = 'Erros encontrados no arquivo:\n' + '\n'.join(invalid_rows[:10])
            if len(invalid_rows) > 10:
                error_msg += f'\n... e mais {len(invalid_rows) - 10} erros'
            return jsonify({'error': error_msg}), 400
        
        # IMPORTACAO: Usar transacao para garantir consistencia
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        
        try:
            imported_count = 0
            duplicates_count = 0
            
            for row_data in valid_rows:
                # Verificar se cliente ja existe
                c.execute('SELECT id FROM clients WHERE name = ? AND company = ?', 
                         (row_data['name'], row_data['company']))
                if c.fetchone():
                    duplicates_count += 1
                    continue
                
                # Inserir novo cliente
                c.execute('''INSERT INTO clients (name, company, position, email, phone, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                         (row_data['name'], row_data['company'], row_data['position'], 
                          row_data['email'], row_data['phone']))
                imported_count += 1
            
            conn.commit()
            
            msg = f'Importados {imported_count} clientes'
            if duplicates_count > 0:
                msg += f'. {duplicates_count} duplicatas ignoradas'
            
            return jsonify({'imported': imported_count, 'duplicates': duplicates_count, 'message': msg}), 200
        
        except Exception as e:
            conn.rollback()
            print(f'[ERROR] Import transaction failed: {e}')
            return jsonify({'error': f'Erro ao importar dados: {str(e)}'}), 500
        finally:
            conn.close()
    
    except Exception as e:
        print(f'[ERROR] POST /api/importar-clientes: {e}')
        return jsonify({'error': str(e)}), 500

# Rotas de mapeamento de ambiente
@app.route('/api/environment/cards', methods=['GET'])
def get_environment_cards():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM environment_cards ORDER BY display_order, id')
        cards = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(cards)
    except Exception as e:
        print(f'[ERROR] GET /api/environment/cards: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/cards', methods=['POST'])
def create_environment_card():
    try:
        title = request.json.get('title', '').strip()
        description = request.json.get('description', '').strip()
        
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Obter a próxima posição de exibição
        c.execute('SELECT MAX(display_order) FROM environment_cards')
        max_order = c.fetchone()[0] or 0
        
        c.execute('INSERT INTO environment_cards (title, description, display_order) VALUES (?, ?, ?)',
                  (title, description, max_order + 1))
        conn.commit()
        card_id = c.lastrowid
        conn.close()
        
        return jsonify({'message': 'Card criado com sucesso', 'id': card_id}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/environment/cards: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/cards/<int:card_id>', methods=['PUT'])
def update_environment_card(card_id):
    try:
        title = request.json.get('title', '').strip()
        description = request.json.get('description', '').strip()
        
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400
        
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE environment_cards SET title = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                  (title, description, card_id))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Card atualizado com sucesso'})
    except Exception as e:
        print(f'[ERROR] PUT /api/environment/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/cards/<int:card_id>', methods=['DELETE'])
def delete_environment_card(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Deletar todas as respostas associadas ao card
        c.execute('DELETE FROM environment_responses WHERE card_id = ?', (card_id,))
        
        # Deletar o card
        c.execute('DELETE FROM environment_cards WHERE id = ?', (card_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Card deletado com sucesso'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/environment/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/responses', methods=['GET'])
def get_environment_responses():
    try:
        client_id = request.args.get('client_id')
        
        conn = get_db()
        c = conn.cursor()
        
        if client_id:
            # Buscar respostas de um cliente específico
            c.execute('''SELECT er.*, ec.title as card_title 
                        FROM environment_responses er
                        JOIN environment_cards ec ON er.card_id = ec.id
                        WHERE er.client_id = ?
                        ORDER BY ec.display_order, ec.id''', (client_id,))
        else:
            # Buscar todas as respostas
            c.execute('''SELECT er.*, ec.title as card_title, cl.name as client_name, cl.company as client_company
                        FROM environment_responses er
                        JOIN environment_cards ec ON er.card_id = ec.id
                        JOIN clients cl ON er.client_id = cl.id
                        ORDER BY ec.display_order, ec.id, cl.company, cl.name''')
        
        responses = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(responses)
    except Exception as e:
        print(f'[ERROR] GET /api/environment/responses: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/responses', methods=['POST'])
def save_environment_response():
    try:
        card_id = request.json.get('card_id')
        client_id = request.json.get('client_id')
        response_text = request.json.get('response', '').strip()
        
        if not card_id or not client_id:
            return jsonify({'error': 'Card e cliente são obrigatórios'}), 400
        
        # Limitar a 400 caracteres
        if len(response_text) > 400:
            return jsonify({'error': 'Resposta deve ter no máximo 400 caracteres'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # Inserir ou atualizar resposta
        c.execute('''INSERT INTO environment_responses (card_id, client_id, response, updated_at)
                     VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                     ON CONFLICT(card_id, client_id) DO UPDATE SET
                        response = excluded.response,
                        updated_at = CURRENT_TIMESTAMP''',
                  (card_id, client_id, response_text))
        
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Resposta salva com sucesso'})
    except Exception as e:
        print(f'[ERROR] POST /api/environment/responses: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/environment/card/<int:card_id>/all-responses', methods=['GET'])
def get_card_all_responses(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Buscar card
        c.execute('SELECT * FROM environment_cards WHERE id = ?', (card_id,))
        card = dict_from_row(c.fetchone())
        
        if not card:
            return jsonify({'error': 'Card não encontrado'}), 404
        
        # Buscar todos os clientes com suas respostas para este card
        # Agrupar por empresa (pegar apenas a primeira ocorrência de cada empresa)
        c.execute('''SELECT cl.id, cl.name, cl.company, 
                            COALESCE(er.response, '') as response
                     FROM clients cl
                     LEFT JOIN environment_responses er ON er.client_id = cl.id AND er.card_id = ?
                     ORDER BY cl.company, cl.name''', (card_id,))
        
        all_clients = [dict_from_row(row) for row in c.fetchall()]
        
        # Filtrar para pegar apenas uma empresa por vez (primeira ocorrência)
        seen_companies = set()
        clients_responses = []
        for client in all_clients:
            if client['company'] and client['company'] not in seen_companies:
                seen_companies.add(client['company'])
                clients_responses.append(client)
        conn.close()
        
        return jsonify({
            'card': card,
            'responses': clients_responses
        })
    except Exception as e:
        print(f'[ERROR] GET /api/environment/card/{card_id}/all-responses: {e}')
        return jsonify({'error': str(e)}), 500

# Rotas de backup e restore do banco de dados
@app.route('/api/backup/database', methods=['GET'])
def backup_database():
    try:
        from flask import send_file
        import tempfile
        import shutil
        
        # Criar cópia temporária do banco
        temp_dir = tempfile.mkdtemp()
        temp_db = Path(temp_dir) / 'toca-do-coelho-backup.db'
        shutil.copy2(str(DB_PATH), str(temp_db))
        
        return send_file(
            str(temp_db),
            as_attachment=True,
            download_name=f'toca-do-coelho-backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db',
            mimetype='application/x-sqlite3'
        )
    except Exception as e:
        print(f'[ERROR] GET /api/backup/database: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/restore/database', methods=['POST'])
def restore_database():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Arquivo inválido'}), 400
        
        # Criar backup do banco atual antes de restaurar
        backup_dir = DATA_DIR / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f'pre-restore-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db'
        
        import shutil
        shutil.copy2(str(DB_PATH), str(backup_path))
        print(f'[Database] Backup de segurança criado em {backup_path}')
        
        # Salvar arquivo temporário
        temp_path = DATA_DIR / 'temp_restore.db'
        file.save(str(temp_path))
        
        # Validar se é um banco SQLite válido
        try:
            test_conn = sqlite3.connect(str(temp_path))
            test_conn.execute('SELECT name FROM sqlite_master WHERE type="table"')
            test_conn.close()
        except Exception as e:
            temp_path.unlink()
            return jsonify({'error': 'Arquivo não é um banco de dados SQLite válido'}), 400
        
        # Substituir banco atual
        shutil.move(str(temp_path), str(DB_PATH))
        print(f'[Database] Banco de dados restaurado com sucesso')
        
        return jsonify({
            'message': 'Banco de dados restaurado com sucesso! Recarregue a página.',
            'backup_location': str(backup_path)
        }), 200
        
    except Exception as e:
        print(f'[ERROR] POST /api/restore/database: {e}')
        return jsonify({'error': str(e)}), 500

# Rotas de sugestões diárias
@app.route('/api/suggestions/today', methods=['GET'])
def get_today_suggestions():
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = get_db()
        c = conn.cursor()
        
        # Verificar se já existem sugestões para hoje
        c.execute('SELECT * FROM daily_suggestions WHERE date = ? ORDER BY completed ASC, id ASC', (today,))
        existing = [dict_from_row(row) for row in c.fetchall()]
        
        if existing:
            conn.close()
            return jsonify(existing)
        
        # Gerar novas sugestões
        suggestions = []
        
        # 1. Clientes com status vermelho (atrasados)
        c.execute('''
            SELECT c.id, c.name, c.company, c.last_activity_date
            FROM clients c
            WHERE c.last_activity_date IS NOT NULL
            ORDER BY c.last_activity_date ASC
        ''')
        overdue_clients = c.fetchall()
        
        for client in overdue_clients:
            client_id, name, company, last_date = client
            if last_date:
                days_diff = (datetime.now() - datetime.fromisoformat(last_date)).days
                if days_diff > 14:  # Status vermelho
                    suggestions.append({
                        'type': 'contact_overdue',
                        'title': f'Contatar {name} ({company})',
                        'description': f'Cliente sem contato há {days_diff} dias',
                        'target_id': client_id,
                        'target_data': json.dumps({'client_id': client_id, 'days': days_diff})
                    })
        
        # 2. Cargos faltantes em clientes
        c.execute('SELECT DISTINCT position FROM clients WHERE position IS NOT NULL AND position != ""')
        all_positions = [row[0] for row in c.fetchall()]
        
        c.execute('SELECT id, name, company FROM clients')
        all_clients = c.fetchall()
        
        for client_id, client_name, client_company in all_clients:
            c.execute('SELECT position FROM clients WHERE company = ?', (client_company,))
            existing_positions = [row[0] for row in c.fetchall()]
            
            missing_positions = [pos for pos in all_positions if pos not in existing_positions]
            
            if missing_positions:
                # Sugerir o primeiro cargo faltante
                position = missing_positions[0]
                suggestions.append({
                    'type': 'missing_position',
                    'title': f'Cadastrar {position} na {client_company}',
                    'description': f'Cargo {position} não cadastrado para esta empresa',
                    'target_id': client_id,
                    'target_data': json.dumps({'company': client_company, 'position': position})
                })
        
        # 3. Mapear itens de cards vazios
        c.execute('SELECT id, title FROM environment_cards')
        cards = c.fetchall()
        
        c.execute('SELECT id, name, company FROM clients')
        clients = c.fetchall()
        
        for card_id, card_title in cards:
            for client_id, client_name, client_company in clients:
                c.execute('SELECT response FROM environment_responses WHERE card_id = ? AND client_id = ?', 
                          (card_id, client_id))
                response = c.fetchone()
                
                if not response or not response[0]:
                    suggestions.append({
                        'type': 'map_environment',
                        'title': f'Mapear {card_title} da {client_company}',
                        'description': f'Informação ainda não mapeada',
                        'target_id': card_id,
                        'target_data': json.dumps({'card_id': card_id, 'client_id': client_id, 'company': client_company})
                    })
        
        # 4. Cadastros incompletos (sem foto ou campos vazios)
        c.execute('''
            SELECT id, name, company, email, phone, photo_url
            FROM clients
        ''')
        clients = c.fetchall()
        
        for client_id, name, company, email, phone, photo in clients:
            missing_fields = []
            if not email: missing_fields.append('e-mail')
            if not phone: missing_fields.append('telefone')
            if not photo: missing_fields.append('foto')
            
            if missing_fields:
                suggestions.append({
                    'type': 'incomplete_profile',
                    'title': f'Completar cadastro de {name} ({company})',
                    'description': f'Faltam: {', '.join(missing_fields)}',
                    'target_id': client_id,
                    'target_data': json.dumps({'client_id': client_id, 'missing': missing_fields})
                })
        
        # Remover sugestões duplicadas (mesmo tipo + mesmo alvo)
        unique_suggestions = []
        seen_keys = set()
        for sug in suggestions:
            dedupe_key = (sug['type'], sug['target_data'])
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            unique_suggestions.append(sug)

        # Selecionar até 5 sugestões com diversidade
        import random
        
        # Agrupar por tipo
        by_type = {
            'contact_overdue': [],
            'missing_position': [],
            'map_environment': [],
            'incomplete_profile': []
        }
        
        for sug in unique_suggestions:
            by_type[sug['type']].append(sug)
        
        # Embaralhar cada grupo
        for key in by_type:
            random.shuffle(by_type[key])
        
        # Selecionar com diversidade: máximo 2 de cada tipo
        selected = []
        priority_order = ['contact_overdue', 'missing_position', 'map_environment', 'incomplete_profile']
        
        # Embaralhar a ordem de prioridade para variar
        random.shuffle(priority_order)
        
        # Primeira rodada: pegar 1 de cada tipo (se disponível)
        for sug_type in priority_order:
            if by_type[sug_type] and len(selected) < 5:
                selected.append(by_type[sug_type].pop(0))
        
        # Segunda rodada: pegar mais 1 de cada tipo (máximo 2 por tipo)
        # Embaralhar novamente para variar a ordem
        random.shuffle(priority_order)
        for sug_type in priority_order:
            if by_type[sug_type] and len(selected) < 5:
                selected.append(by_type[sug_type].pop(0))
        
        # Embaralhar a lista final para evitar padrões
        random.shuffle(selected)
        
        # Inserir no banco
        for sug in selected:
            c.execute('''
                INSERT INTO daily_suggestions (date, suggestion_type, title, description, target_id, target_data)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (today, sug['type'], sug['title'], sug['description'], sug['target_id'], sug['target_data']))
        
        conn.commit()
        
        # Buscar as sugestões inseridas
        c.execute('SELECT * FROM daily_suggestions WHERE date = ? ORDER BY id ASC', (today,))
        result = [dict_from_row(row) for row in c.fetchall()]
        
        conn.close()
        return jsonify(result)
        
    except Exception as e:
        print(f'[ERROR] GET /api/suggestions/today: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/complete', methods=['POST'])
def complete_suggestion(suggestion_id):
    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT * FROM daily_suggestions WHERE id = ?', (suggestion_id,))
        suggestion = c.fetchone()
        if not suggestion:
            conn.close()
            return jsonify({'error': 'Sugestão não encontrada'}), 404

        suggestion_dict = dict_from_row(suggestion)
        target_data = json.loads(suggestion_dict['target_data']) if suggestion_dict.get('target_data') else {}

        is_completed = False

        if suggestion_dict['suggestion_type'] == 'contact_overdue':
            client_id = target_data.get('client_id')
            if client_id:
                c.execute('SELECT id FROM activities WHERE client_id = ? AND date(created_at) = date("now", "localtime")', (client_id,))
                is_completed = c.fetchone() is not None

        elif suggestion_dict['suggestion_type'] == 'missing_position':
            company = target_data.get('company')
            position = target_data.get('position')
            if company and position:
                c.execute('''
                    SELECT id FROM clients
                    WHERE company = ? AND position = ?
                ''', (company, position))
                is_completed = c.fetchone() is not None

        elif suggestion_dict['suggestion_type'] == 'map_environment':
            card_id = target_data.get('card_id')
            client_id = target_data.get('client_id')
            if card_id and client_id:
                c.execute('''
                    SELECT response FROM environment_responses
                    WHERE card_id = ? AND client_id = ?
                ''', (card_id, client_id))
                response = c.fetchone()
                is_completed = bool(response and response[0] and response[0].strip())

        elif suggestion_dict['suggestion_type'] == 'incomplete_profile':
            client_id = target_data.get('client_id')
            if client_id:
                c.execute('SELECT email, phone, photo_url FROM clients WHERE id = ?', (client_id,))
                client = c.fetchone()
                if client:
                    email, phone, photo_url = client
                    is_completed = bool(email and phone and photo_url)

        if not is_completed:
            conn.close()
            return jsonify({'error': 'A sugestão ainda não foi concluída'}), 400

        c.execute('''
            UPDATE daily_suggestions 
            SET completed = 1, completed_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (suggestion_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Sugestão marcada como concluída'})
        
    except Exception as e:
        print(f'[ERROR] POST /api/suggestions/{suggestion_id}/complete: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/templates', methods=['GET'])
def list_message_templates():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM message_templates ORDER BY title COLLATE NOCASE')
        items = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    except Exception as e:
        print(f'[ERROR] GET /api/config/templates: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates', methods=['POST'])
def create_message_template():
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        available_whatsapp = 1 if data.get('available_whatsapp', True) else 0
        available_email = 1 if data.get('available_email', True) else 0
        if not title or not description:
            return jsonify({'error': 'Título e descritivo são obrigatórios'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('''INSERT INTO message_templates (title, description, available_whatsapp, available_email, updated_at)
                     VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''', (title, description, available_whatsapp, available_email))
        template_id = c.lastrowid
        conn.commit()
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item), 201
    except Exception as e:
        print(f'[ERROR] POST /api/config/templates: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates/<int:template_id>', methods=['PUT'])
def update_message_template(template_id):
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        available_whatsapp = 1 if data.get('available_whatsapp', True) else 0
        available_email = 1 if data.get('available_email', True) else 0
        if not title or not description:
            return jsonify({'error': 'Título e descritivo são obrigatórios'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('''UPDATE message_templates
                     SET title = ?, description = ?, available_whatsapp = ?, available_email = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''', (title, description, available_whatsapp, available_email, template_id))
        conn.commit()
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item or {'message': 'Atualizado'})
    except Exception as e:
        print(f'[ERROR] PUT /api/config/templates/{template_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/templates/<int:template_id>', methods=['DELETE'])
def delete_message_template(template_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM message_templates WHERE id = ?', (template_id,))
        conn.commit(); conn.close()
        return jsonify({'message': 'Modelo removido'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/config/templates/{template_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/support-data', methods=['GET'])
def get_accounts_support_data():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT DISTINCT company FROM clients WHERE company IS NOT NULL AND TRIM(company) != "" ORDER BY company')
        companies = [row['company'] for row in c.fetchall()]
        c.execute('SELECT name FROM account_sectors ORDER BY name')
        sectors = [row['name'] for row in c.fetchall()]
        conn.close()
        return jsonify({'companies': companies, 'sectors': sectors})
    except Exception as e:
        print(f'[ERROR] GET /api/accounts/support-data: {e}')
        return jsonify({'error': str(e)}), 500


def _create_or_update_presence_event(c, account_name, account_id, presence):
    validity = (presence.get('validity_month') or '').strip()
    if not validity:
        return
    due_date = f"{validity}-01"
    title = f"Renovação {account_name}: {presence.get('delivery_name') or ''}".strip()
    c.execute('''INSERT INTO account_renewal_events (account_id, presence_id, title, due_date, due_time)
                 VALUES (?, ?, ?, ?, '09:00')
                 ON CONFLICT(presence_id) DO UPDATE SET
                    title = excluded.title,
                    due_date = excluded.due_date,
                    due_time = '09:00' ''',
              (account_id, presence['id'], title, due_date))


@app.route('/api/accounts', methods=['GET'])
def list_accounts():
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts ORDER BY name COLLATE NOCASE')
        accounts = [dict_from_row(r) for r in c.fetchall()]
        for acc in accounts:
            c.execute('''SELECT p.* FROM account_presences p WHERE p.account_id = ? ORDER BY p.delivery_name COLLATE NOCASE''', (acc['id'],))
            acc['presences'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(accounts)
    except Exception as e:
        print(f'[ERROR] GET /api/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
def get_account(account_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        account = dict_from_row(c.fetchone())
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''SELECT c.id, c.name, c.position, c.photo_url, c.email
                     FROM clients c
                     WHERE LOWER(TRIM(c.company)) = LOWER(TRIM(?))
                     ORDER BY c.name''', (account['name'],))
        account['contacts'] = [dict_from_row(r) for r in c.fetchall()]
        c.execute('''SELECT client_id FROM account_main_contacts WHERE account_id = ? ORDER BY id''', (account_id,))
        account['main_contact_ids'] = [row['client_id'] for row in c.fetchall()]
        c.execute('SELECT * FROM account_presences WHERE account_id = ? ORDER BY delivery_name COLLATE NOCASE', (account_id,))
        account['presences'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close(); return jsonify(account)
    except Exception as e:
        print(f'[ERROR] GET /api/accounts/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts', methods=['POST'])
def create_account():
    try:
        name = request.form.get('name', '').strip()
        sector = request.form.get('sector', '').strip() or None
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'True') else 0
        average_revenue_cents = parse_currency_to_cents(request.form.get('average_revenue'))
        professionals_count = request.form.get('professionals_count', '').strip()
        professionals_count = int(professionals_count) if professionals_count.isdigit() else None
        global_presence = request.form.get('global_presence', '').strip() or None
        main_contact_ids = request.form.get('main_contact_ids', '').strip()
        if not name:
            return jsonify({'error': 'Nome da conta é obrigatório'}), 400
        conn = get_db(); c = conn.cursor()
        logo_url = None
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                filename = secure_filename(f"acc_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(str(ACCOUNT_UPLOAD_DIR / filename))
                logo_url = f'/uploads/accounts/{filename}'
        c.execute('''INSERT INTO accounts (name, logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (name, logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence))
        account_id = c.lastrowid
        if sector:
            c.execute('INSERT OR IGNORE INTO account_sectors (name) VALUES (?)', (sector,))
        ids = [int(x) for x in main_contact_ids.split(',') if x.strip().isdigit()]
        for cid in ids:
            c.execute('INSERT OR IGNORE INTO account_main_contacts (account_id, client_id) VALUES (?, ?)', (account_id, cid))
        conn.commit(); conn.close()
        return jsonify({'id': account_id, 'message': 'Conta criada'}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
def update_account(account_id):
    try:
        name = request.form.get('name', '').strip()
        sector = request.form.get('sector', '').strip() or None
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'True') else 0
        average_revenue_cents = parse_currency_to_cents(request.form.get('average_revenue'))
        professionals_count = request.form.get('professionals_count', '').strip()
        professionals_count = int(professionals_count) if professionals_count.isdigit() else None
        global_presence = request.form.get('global_presence', '').strip() or None
        main_contact_ids = request.form.get('main_contact_ids', '').strip()
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        row = dict_from_row(c.fetchone())
        if not row:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        logo_url = row.get('logo_url')
        if 'logo' in request.files:
            f = request.files['logo']
            if f and f.filename:
                filename = secure_filename(f"acc_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(str(ACCOUNT_UPLOAD_DIR / filename))
                logo_url = f'/uploads/accounts/{filename}'
        c.execute('''UPDATE accounts SET name=?, logo_url=?, is_target=?, sector=?, average_revenue_cents=?, professionals_count=?, global_presence=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                  (name or row['name'], logo_url, is_target, sector, average_revenue_cents, professionals_count, global_presence, account_id))
        if sector:
            c.execute('INSERT OR IGNORE INTO account_sectors (name) VALUES (?)', (sector,))
        c.execute('DELETE FROM account_main_contacts WHERE account_id = ?', (account_id,))
        ids = [int(x) for x in main_contact_ids.split(',') if x.strip().isdigit()]
        for cid in ids:
            c.execute('INSERT OR IGNORE INTO account_main_contacts (account_id, client_id) VALUES (?, ?)', (account_id, cid))
        conn.commit(); conn.close()
        return jsonify({'message': 'Conta atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/accounts/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences', methods=['POST'])
def create_account_presence(account_id):
    try:
        data = request.get_json() or {}
        delivery_name = (data.get('delivery_name') or '').strip()
        if not delivery_name:
            return jsonify({'error': 'Nome da Entrega é obrigatório'}), 400
        stf_owner = (data.get('stf_owner') or '').strip() or None
        current_revenue_cents = parse_currency_to_cents(data.get('current_revenue'))
        validity_month = (data.get('validity_month') or '').strip() or None
        focal_client_id = data.get('focal_client_id')
        focal_client_id = int(focal_client_id) if str(focal_client_id).isdigit() else None
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT name FROM accounts WHERE id = ?', (account_id,))
        account = c.fetchone()
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''INSERT INTO account_presences (account_id, delivery_name, stf_owner, current_revenue_cents, validity_month, focal_client_id, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (account_id, delivery_name, stf_owner, current_revenue_cents, validity_month, focal_client_id))
        presence_id = c.lastrowid
        c.execute('SELECT * FROM account_presences WHERE id = ?', (presence_id,))
        presence = dict_from_row(c.fetchone())
        _create_or_update_presence_event(c, account['name'], account_id, presence)
        conn.commit(); conn.close()
        return jsonify(presence), 201
    except Exception as e:
        print(f'[ERROR] POST /api/accounts/{account_id}/presences: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences/<int:presence_id>', methods=['PUT'])
def update_account_presence(account_id, presence_id):
    try:
        data = request.get_json() or {}
        delivery_name = (data.get('delivery_name') or '').strip()
        if not delivery_name:
            return jsonify({'error': 'Nome da Entrega é obrigatório'}), 400
        stf_owner = (data.get('stf_owner') or '').strip() or None
        current_revenue_cents = parse_currency_to_cents(data.get('current_revenue'))
        validity_month = (data.get('validity_month') or '').strip() or None
        focal_client_id = data.get('focal_client_id')
        focal_client_id = int(focal_client_id) if str(focal_client_id).isdigit() else None
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT name FROM accounts WHERE id = ?', (account_id,))
        account = c.fetchone()
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''UPDATE account_presences
                     SET delivery_name=?, stf_owner=?, current_revenue_cents=?, validity_month=?, focal_client_id=?, updated_at=CURRENT_TIMESTAMP
                     WHERE id=? AND account_id=?''',
                  (delivery_name, stf_owner, current_revenue_cents, validity_month, focal_client_id, presence_id, account_id))
        c.execute('SELECT * FROM account_presences WHERE id = ? AND account_id = ?', (presence_id, account_id))
        presence = dict_from_row(c.fetchone())
        if presence:
            _create_or_update_presence_event(c, account['name'], account_id, presence)
        conn.commit(); conn.close()
        return jsonify(presence or {'message': 'Atualizada'})
    except Exception as e:
        print(f'[ERROR] PUT /api/accounts/{account_id}/presences/{presence_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/presences/<int:presence_id>', methods=['DELETE'])
def delete_account_presence(account_id, presence_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM account_renewal_events WHERE presence_id = ?', (presence_id,))
        c.execute('DELETE FROM account_presences WHERE id = ? AND account_id = ?', (presence_id, account_id))
        conn.commit(); conn.close()
        return jsonify({'message': 'Presença removida'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/accounts/{account_id}/presences/{presence_id}: {e}')
        return jsonify({'error': str(e)}), 500

# Servir arquivos estaticos

@app.route('/uploads/accounts/<filename>')
def serve_account_upload(filename):
    return send_from_directory(str(ACCOUNT_UPLOAD_DIR), filename)

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    print('=' * 50)
    print('  TOCA DO COELHO - Gestao de Clientes')
    print('=' * 50)
    print(f'[Database] Banco de dados inicializado')
    print(f'[Server] Iniciando em http://localhost:{port}')
    print(f'[Server] Pressione CTRL+C para parar')
    print()
    
    # Abrir navegador
    import threading
    def open_browser():
        import time
        time.sleep(2)
        webbrowser.open(f'http://localhost:{port}')
    
    thread = threading.Thread(target=open_browser, daemon=True)
    thread.start()
    
    app.run(host='localhost', port=port, debug=False)
