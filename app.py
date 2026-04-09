#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import sqlite3
import webbrowser
import logging
import re
import zipfile
import tempfile
import threading
import concurrent.futures
import traceback
import shutil
import urllib.request
import urllib.error
import urllib.parse
import html
import time
import ssl
import base64
import mimetypes
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlparse, quote_plus
from pathlib import Path
from xml.etree import ElementTree as ET
from flask import Flask, jsonify, request, send_from_directory, send_file, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    SELENIUM_AVAILABLE = True
except Exception:
    SELENIUM_AVAILABLE = False
from werkzeug.exceptions import HTTPException
from autotoca import AccountAddressService
from integrations.outlook_graph import (
    OutlookOAuthError,
    OutlookSyncError,
    build_authorize_url as outlook_graph_build_authorize_url,
    ensure_schema as outlook_graph_ensure_schema,
    exchange_code_and_store as outlook_graph_exchange_code_and_store,
    fetch_messages as outlook_graph_fetch_messages,
    get_valid_access_token as outlook_graph_get_valid_access_token,
    parse_state as outlook_graph_parse_state,
)
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

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False

try:
    import docx as python_docx
    PYTHON_DOCX_AVAILABLE = True
except ImportError:
    python_docx = None
    PYTHON_DOCX_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    PYTESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    convert_from_path = None
    PDF2IMAGE_AVAILABLE = False

try:
    from PIL import Image as PILImage
    from PIL import ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PILImage = None
    ImageOps = None
    PIL_AVAILABLE = False

REPORTLAB_IMPORT_ERROR = None
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Paragraph
    REPORTLAB_AVAILABLE = True
except Exception as e:
    colors = None
    TA_LEFT = TA_CENTER = None
    A4 = None
    ParagraphStyle = None
    getSampleStyleSheet = None
    mm = None
    ImageReader = None
    stringWidth = None
    Paragraph = None
    REPORTLAB_AVAILABLE = False
    REPORTLAB_IMPORT_ERROR = e

WHISPER_IMPORT_ERROR = None
WHISPER_IMPORT_ATTEMPTED = False
WhisperModel = None
WHISPER_AVAILABLE = True

TRANSCRIPTION_BACKEND = 'faster-whisper'

try:
    import imageio_ffmpeg
    IMAGEIO_FFMPEG_AVAILABLE = True
except ImportError:
    imageio_ffmpeg = None
    IMAGEIO_FFMPEG_AVAILABLE = False

# Configuracao
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

# Diretorio de dados
if sys.platform == 'win32':
    DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
    LEGACY_DATA_DIR_V2 = Path('C:/toca-do-coelho-version2')
    LEGACY_DATA_DIR_V1 = Path('C:/toca-do-coelho')
else:
    DATA_DIR = Path.home() / '.toca-do-coelho'
    LEGACY_DATA_DIR_V2 = None
    LEGACY_DATA_DIR_V1 = None

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'toca-do-coelho.db'
TEST_DB_TEMPLATE_PATH = Path(__file__).resolve().parent / 'BD_teste' / 'toca-do-coelho-ficticio-reduzido.db'
BACKUP_DIR = DATA_DIR / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = DATA_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'app.log'
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_UPLOAD_DIR = UPLOAD_DIR / 'accounts'
ACCOUNT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
WIKI_UPLOAD_DIR = UPLOAD_DIR / 'wikitoca'
WIKI_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AUTOTOCA_UPLOAD_DIR = UPLOAD_DIR / 'autotoca'
AUTOTOCA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AUTOTOCA_SUPPORT_FILES_DIR = Path(app.static_folder) / 'assets' / 'autotoca' / 'chamado-juridico'
AUTOTOCA_SUPPORT_FILES_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL = None
WHISPER_MODEL_LOCK = threading.Lock()
TRANSCRIPTION_DEBUG = os.environ.get('TRANSCRIPTION_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'}


def setup_logging():
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    file_handler_exists = any(
        isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', '') == str(LOG_FILE)
        for handler in root_logger.handlers
    )
    if not file_handler_exists:
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


setup_logging()
logger = logging.getLogger('toca-do-coelho')

APP_VERSION = os.environ.get('TOCA_APP_VERSION', '1.0.0').strip() or '1.0.0'
DEFAULT_GITHUB_OWNER = os.environ.get('TOCA_UPDATE_GITHUB_OWNER', 'rochanets').strip()
DEFAULT_GITHUB_REPO = os.environ.get('TOCA_UPDATE_GITHUB_REPO', 'TocaDoCoelho').strip()

logger.info('[Transcription] Backend faster-whisper será carregado sob demanda (lazy).')

AUTOMAPPING_CANCELLED_REQUESTS = set()
AUTOMAPPING_CANCELLED_LOCK = threading.Lock()


def _mark_automapping_cancelled(request_id):
    if not request_id:
        return
    with AUTOMAPPING_CANCELLED_LOCK:
        AUTOMAPPING_CANCELLED_REQUESTS.add(request_id)


def _is_automapping_cancelled(request_id, consume=False):
    if not request_id:
        return False
    with AUTOMAPPING_CANCELLED_LOCK:
        if request_id not in AUTOMAPPING_CANCELLED_REQUESTS:
            return False
        if consume:
            AUTOMAPPING_CANCELLED_REQUESTS.discard(request_id)
        return True


def configure_ffmpeg_for_whisper():
    bundled_candidates = []

    if getattr(sys, 'frozen', False):
        bundled_candidates.append(Path(sys.executable).parent / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'))
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            bundled_candidates.append(Path(meipass) / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'))

    bundled_candidates.append(Path(__file__).resolve().parent / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'))

    for candidate in bundled_candidates:
        if candidate.exists():
            os.environ['FFMPEG_BINARY'] = str(candidate)
            return str(candidate)

    ffmpeg_binary = os.environ.get('FFMPEG_BINARY')
    if ffmpeg_binary and Path(ffmpeg_binary).exists():
        return ffmpeg_binary

    ffmpeg_on_path = shutil.which('ffmpeg')
    if ffmpeg_on_path:
        os.environ['FFMPEG_BINARY'] = ffmpeg_on_path
        return ffmpeg_on_path

    if IMAGEIO_FFMPEG_AVAILABLE:
        try:
            ffmpeg_imageio = imageio_ffmpeg.get_ffmpeg_exe()
            ffmpeg_dir = str(Path(ffmpeg_imageio).parent)
            os.environ['PATH'] = f"{ffmpeg_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            os.environ['FFMPEG_BINARY'] = ffmpeg_imageio
            return ffmpeg_imageio
        except Exception as e:
            if TRANSCRIPTION_DEBUG:
                logger.debug(f"[Transcription] Falha ao obter ffmpeg via imageio_ffmpeg: {e}")

    return None


def get_ffmpeg_install_instructions():
    if sys.platform == 'win32':
        return [
            'Windows (winget): winget install -e --id Gyan.FFmpeg',
            'Ou Windows (choco): choco install ffmpeg -y',
            'Depois reinicie o app.'
        ]
    if sys.platform == 'darwin':
        return ['macOS: brew install ffmpeg', 'Depois reinicie o app.']
    return ['Linux (Debian/Ubuntu): sudo apt update && sudo apt install -y ffmpeg', 'Depois reinicie o app.']


def get_whisper_model():
    global WHISPER_MODEL, WhisperModel, WHISPER_AVAILABLE, WHISPER_IMPORT_ERROR, WHISPER_IMPORT_ATTEMPTED

    if not WHISPER_AVAILABLE:
        return None

    with WHISPER_MODEL_LOCK:
        if WHISPER_MODEL is not None:
            return WHISPER_MODEL

        if WhisperModel is None and not WHISPER_IMPORT_ATTEMPTED:
            WHISPER_IMPORT_ATTEMPTED = True
            try:
                from faster_whisper import WhisperModel as _WhisperModel
                WhisperModel = _WhisperModel
            except Exception as e:
                WHISPER_AVAILABLE = False
                WHISPER_IMPORT_ERROR = str(e)
                logger.warning(f'[Transcription] Backend faster-whisper indisponível: {WHISPER_IMPORT_ERROR}')
                return None

        if WhisperModel is None:
            return None

        try:
            WHISPER_MODEL = WhisperModel('base', device='cpu', compute_type='int8')
        except Exception as e:
            WHISPER_AVAILABLE = False
            WHISPER_IMPORT_ERROR = str(e)
            logger.warning(f'[Transcription] Falha ao inicializar faster-whisper: {WHISPER_IMPORT_ERROR}')
            return None

    return WHISPER_MODEL


TEST_DB_REQUIRED_SCHEMA = {
    'clients': {'id', 'name', 'company', 'position'},
    'accounts': {'id', 'name'},
    'activities': {'id', 'client_id'},
    'commitments': {'id', 'client_id', 'title', 'due_date'},
    'app_settings': {'key', 'value'},
    'itoca_chat_history': {'id', 'session_id', 'role', 'content'},
}


def _is_test_db_schema_valid(db_path):
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        for table_name, required_columns in TEST_DB_REQUIRED_SCHEMA.items():
            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,)
            )
            if c.fetchone() is None:
                logger.warning(
                    f'[Database] Banco de teste inválido: tabela obrigatória ausente ({table_name}).'
                )
                conn.close()
                return False

            c.execute(f"PRAGMA table_info({table_name})")
            table_columns = {row[1] for row in c.fetchall()}
            missing_columns = required_columns - table_columns
            if missing_columns:
                logger.warning(
                    '[Database] Banco de teste inválido: colunas obrigatórias ausentes em %s: %s',
                    table_name,
                    ', '.join(sorted(missing_columns))
                )
                conn.close()
                return False

        conn.close()
        return True
    except Exception as e:
        logger.warning(f'[Database] Falha ao validar banco de teste: {e}')
        return False


def maybe_seed_test_db_fallback():
    if DB_PATH.exists():
        return

    should_use_test_db = os.environ.get('TOCA_ENABLE_TEST_DB_FALLBACK', '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    if not should_use_test_db:
        return

    if getattr(sys, 'frozen', False):
        logger.info('[Database] Fallback de banco de teste ignorado em build instalada.')
        return

    if not TEST_DB_TEMPLATE_PATH.exists():
        logger.warning(f'[Database] Banco de teste não encontrado em {TEST_DB_TEMPLATE_PATH}.')
        return

    if not _is_test_db_schema_valid(TEST_DB_TEMPLATE_PATH):
        logger.warning('[Database] Banco de teste inválido. O app seguirá com banco vazio padrão.')
        return

    shutil.copy2(str(TEST_DB_TEMPLATE_PATH), str(DB_PATH))
    logger.info(f'[Database] Banco de teste copiado para uso local: {DB_PATH}')

# Migração automática do banco de dados antigo
if sys.platform == 'win32' and not DB_PATH.exists():
    import shutil
    migrated = False

    legacy_sources = [
        ('C:/toca-do-coelho-version2', LEGACY_DATA_DIR_V2, 'toca-do-coelho-version2.db'),
        ('C:/toca-do-coelho', LEGACY_DATA_DIR_V1, 'toca-do-coelho.db'),
    ]

    for source_label, legacy_dir, legacy_db_name in legacy_sources:
        if migrated or not legacy_dir or not legacy_dir.exists():
            continue

        old_db = legacy_dir / legacy_db_name
        if old_db.exists():
            logger.info(f'[Database] Migrando banco de dados de {old_db} para {DB_PATH}')
            shutil.copy2(str(old_db), str(DB_PATH))

            old_uploads = legacy_dir / 'uploads'
            if old_uploads.exists():
                for item in old_uploads.iterdir():
                    dest = UPLOAD_DIR / item.name
                    if dest.exists():
                        continue
                    if item.is_file():
                        shutil.copy2(str(item), str(dest))
                    elif item.is_dir():
                        shutil.copytree(str(item), str(dest))

            logger.info(f'[Database] Migração de {source_label} concluída com sucesso!')
            migrated = True

maybe_seed_test_db_fallback()

logger.info(f'[Database] Caminho: {DB_PATH}')

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
        linkedin TEXT,
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

    # WikiToca (base de conhecimento + documentos)
    c.execute('''CREATE TABLE IF NOT EXISTS wiki_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT,
        content TEXT NOT NULL,
        tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS wiki_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        file_name TEXT NOT NULL,
        original_name TEXT NOT NULL,
        file_url TEXT NOT NULL,
        file_ext TEXT,
        file_size INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        delivery_cell TEXT,
        service_id TEXT,
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

    c.execute('''CREATE TABLE IF NOT EXISTS account_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        activity_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
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

    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT,
        raw_input TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_offer_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offer_id INTEGER NOT NULL,
        pain TEXT,
        solution TEXT,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(offer_id) REFERENCES portfolio_offers(id) ON DELETE CASCADE
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

    c.execute('''CREATE TABLE IF NOT EXISTS kanban_columns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        display_order INTEGER DEFAULT 0,
        is_system INTEGER DEFAULT 0,
        is_locked INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS kanban_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        tag TEXT,
        account_id INTEGER,
        contact_id INTEGER,
        activity TEXT,
        urgency TEXT DEFAULT 'Média',
        column_id INTEGER NOT NULL,
        display_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(column_id) REFERENCES kanban_columns(id) ON DELETE CASCADE,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL,
        FOREIGN KEY(contact_id) REFERENCES clients(id) ON DELETE SET NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS kanban_card_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(card_id) REFERENCES kanban_cards(id) ON DELETE CASCADE
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

    # Histórico de execuções de AutoMapping
    c.execute('''CREATE TABLE IF NOT EXISTS automapping_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        country TEXT NOT NULL,
        industry TEXT NOT NULL,
        query_key TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')


    c.execute('CREATE INDEX IF NOT EXISTS idx_automapping_query_key ON automapping_runs(query_key)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_automapping_created_at ON automapping_runs(created_at)')

    # Tokens de integrações OAuth por usuário (Outlook Graph e futuros conectores)
    outlook_graph_ensure_schema(conn)

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

    c.execute("PRAGMA table_info(kanban_columns)")
    kanban_column_cols = [col[1] for col in c.fetchall()]
    if 'is_system' not in kanban_column_cols:
        c.execute('ALTER TABLE kanban_columns ADD COLUMN is_system INTEGER DEFAULT 0')
    if 'is_locked' not in kanban_column_cols:
        c.execute('ALTER TABLE kanban_columns ADD COLUMN is_locked INTEGER DEFAULT 0')

    c.execute('SELECT COUNT(*) FROM kanban_columns')
    has_columns = c.fetchone()[0] > 0
    if not has_columns:
        default_columns = [
            ('Backlog', 1, 1, 0),
            ('Em Andamento', 2, 1, 0),
            ('Hold', 3, 1, 0),
            ('Done', 4, 1, 1),
            ('Descartado', 5, 1, 1)
        ]
        c.executemany(
            'INSERT INTO kanban_columns (title, display_order, is_system, is_locked) VALUES (?, ?, ?, ?)',
            default_columns
        )

    c.execute("UPDATE kanban_columns SET title = 'Done', updated_at = CURRENT_TIMESTAMP WHERE lower(title) = 'finalizado'")

    c.execute("PRAGMA table_info(kanban_cards)")
    kanban_card_cols = [col[1] for col in c.fetchall()]
    if 'urgency' not in kanban_card_cols:
        c.execute('ALTER TABLE kanban_cards ADD COLUMN urgency TEXT DEFAULT "Média"')
    
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
    if 'linkedin' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN linkedin TEXT')

    c.execute("PRAGMA table_info(commitments)")
    commitment_columns = [col[1] for col in c.fetchall()]
    if 'due_time' not in commitment_columns:
        c.execute('ALTER TABLE commitments ADD COLUMN due_time TEXT')
    if 'source_type' not in commitment_columns:
        c.execute('ALTER TABLE commitments ADD COLUMN source_type TEXT DEFAULT "activity"')

    c.execute("PRAGMA table_info(account_presences)")
    account_presence_columns = [col[1] for col in c.fetchall()]
    if 'delivery_cell' not in account_presence_columns:
        c.execute('ALTER TABLE account_presences ADD COLUMN delivery_cell TEXT')
    if 'service_id' not in account_presence_columns:
        c.execute('ALTER TABLE account_presences ADD COLUMN service_id TEXT')

    # Configuracoes padrao da faixa de status
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('status_green_days', '7'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('status_yellow_days', '14'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('target_green_days', '5'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('target_yellow_days', '10'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('cold_green_days', '45'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('cold_yellow_days', '60'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('iata_video_path', '/videos/TocaVideo.mp4'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('tavily_api_key', ''))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('openrouter_api_key', ''))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('openrouter_model', 'stepfun/step-3.5-flash:free'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('openrouter_site_url', 'http://localhost'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('openrouter_app_name', 'TocaDoCoelho'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('update_github_owner', DEFAULT_GITHUB_OWNER))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('update_github_repo', DEFAULT_GITHUB_REPO))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_base_snapshot', ''))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_base_updated_at', ''))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_sai_api_key', ''))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_sai_template_id', '69ac3c87024adc2d2bdc19f5'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_sai_base_url', 'https://sai-library.saiapplications.com'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_action_detector_template_id', '69b1c662485ca1e93db65015'))
    c.execute('INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)', ('itoca_sai_simple_template_id', '69bc155d7462bf7c702e9295'))
    # Histórico de conversas do iToca (30 dias)
    c.execute('''
        CREATE TABLE IF NOT EXISTS itoca_chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            confidence_percent INTEGER,
            needs_refinement INTEGER DEFAULT 0,
            refinement_hint TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

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

        # Garantir schema mínimo do WikiToca para bases antigas/parciais
        c.execute("PRAGMA table_info(wiki_entries)")
        wiki_entry_columns = [col[1] for col in c.fetchall()]
        if 'category' not in wiki_entry_columns:
            c.execute('ALTER TABLE wiki_entries ADD COLUMN category TEXT')
        if 'tags' not in wiki_entry_columns:
            c.execute('ALTER TABLE wiki_entries ADD COLUMN tags TEXT')
        if 'created_at' not in wiki_entry_columns:
            c.execute('ALTER TABLE wiki_entries ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        if 'updated_at' not in wiki_entry_columns:
            c.execute('ALTER TABLE wiki_entries ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')

        c.execute("PRAGMA table_info(wiki_documents)")
        wiki_doc_columns = [col[1] for col in c.fetchall()]
        if 'file_ext' not in wiki_doc_columns:
            c.execute('ALTER TABLE wiki_documents ADD COLUMN file_ext TEXT')
        if 'file_size' not in wiki_doc_columns:
            c.execute('ALTER TABLE wiki_documents ADD COLUMN file_size INTEGER')
        if 'created_at' not in wiki_doc_columns:
            c.execute('ALTER TABLE wiki_documents ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        if 'updated_at' not in wiki_doc_columns:
            c.execute('ALTER TABLE wiki_documents ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        conn.commit()
    except:
        pass
    
    conn.close()
    logger.info('[Database] Banco de dados inicializado')


def run_automatic_db_backup(interval_days=3):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute('SELECT value FROM app_settings WHERE key = ?', ('db_last_backup_at',))
        row = c.fetchone()

        now = datetime.utcnow()
        should_backup = True

        if row and row[0]:
            try:
                last_backup = datetime.fromisoformat(row[0])
                should_backup = (now - last_backup) >= timedelta(days=interval_days)
            except Exception:
                should_backup = True

        if should_backup and DB_PATH.exists():
            backup_name = f"toca-do-coelho-backup-{now.strftime('%Y%m%d-%H%M%S')}.db"
            backup_path = BACKUP_DIR / backup_name
            shutil.copy2(str(DB_PATH), str(backup_path))
            c.execute(
                'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                ('db_last_backup_at', now.isoformat())
            )
            conn.commit()
            logger.info(f'[Backup] Backup automático criado em: {backup_path}')
        else:
            logger.info('[Backup] Backup automático não necessário neste momento.')

        conn.close()
    except Exception as e:
        logger.exception(f'[Backup] Falha ao executar backup automático: {e}')

init_db()
run_automatic_db_backup(interval_days=3)

# Funcoes auxiliares
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def dict_from_row(row):
    if row is None:
        return None
    return dict(row)


def _load_app_settings_map(keys):
    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?'] * len(keys))
    c.execute(f'SELECT key, value FROM app_settings WHERE key IN ({placeholders})', tuple(keys))
    mapping = {row['key']: row['value'] for row in c.fetchall()}
    conn.close()
    return mapping




def _normalize_version(version):
    normalized = re.sub(r'^[vV]', '', str(version or '').strip())
    return normalized


def _version_key(version):
    normalized = _normalize_version(version)
    if not normalized:
        return tuple()
    parts = re.split(r'[.+\-]', normalized)
    parsed = []
    for part in parts:
        if part.isdigit():
            parsed.append((0, int(part)))
        else:
            parsed.append((1, part.lower()))
    return tuple(parsed)

def _resolve_setting(secret_key, env_key):
    try:
        db_value = (_load_app_settings_map([secret_key]).get(secret_key) or '').strip()
    except Exception:
        db_value = ''
    if db_value:
        return db_value
    return (os.environ.get(env_key, '') or '').strip()


def _sai_simple_prompt(question: str) -> str | None:
    """Envia uma pergunta ao template SAI de prompt simples e retorna o texto da resposta.

    Este é o helper padrão para chamar o LLM via SAI no TocaDoCoelho.
    Use esta função sempre que precisar de uma resposta de LLM para uma pergunta livre.
    A chave e a URL base são lidas automaticamente das configurações do app (itoca_sai_api_key,
    itoca_sai_base_url). O template usado é o 'simple prompt' (itoca_sai_simple_template_id),
    que aceita apenas o campo 'question' como entrada.

    Retorna o texto bruto da resposta do LLM, ou None se o SAI não estiver configurado
    ou se ocorrer algum erro de comunicação.

    Exemplo de uso:
        raw = _sai_simple_prompt("Qual o faturamento anual da Petrobras? Responda em JSON.")
        # raw pode ser '{"faturamento": 500000000000}' ou None
    """
    api_key = _resolve_setting('itoca_sai_api_key', 'ITOCA_SAI_API_KEY')
    if not api_key:
        return None
    base_url = (_load_app_settings_map(['itoca_sai_base_url']).get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'
    template_id = (_load_app_settings_map(['itoca_sai_simple_template_id']).get('itoca_sai_simple_template_id') or '').strip() or '69bc155d7462bf7c702e9295'
    try:
        req = urllib.request.Request(
            f'{base_url}/api/templates/{template_id}/execute',
            data=json.dumps({'inputs': {'question': question}}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'X-Api-Key': api_key},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f'[SAI][simple_prompt] falha: {e}')
        return None


def api_error(status, code, message, details=None, hint=None):
    payload = {
        'error': message,
        'error_code': code
    }
    if details:
        payload['details'] = str(details)
    if hint:
        payload['hint'] = hint
    return jsonify(payload), status


def _extract_bing_image_urls(raw_html, log_prefix='[AutoPic]'):
    """Extrai as URLs originais das imagens do HTML do Bing Images.
    O Bing codifica os dados de imagem com HTML entities nos atributos data-*,
    por isso o padrão usa &quot; ao invés de aspas diretas.
    """
    # Padrão principal: Bing usa HTML entities nos atributos data-*
    matches = re.findall(r'&quot;murl&quot;:&quot;(https?://[^&]+)&quot;', raw_html)
    logger.debug(f'{log_prefix} _extract_bing_image_urls: padrão HTML entities encontrou {len(matches)} resultado(s).')

    if not matches:
        # Fallback: tentar sem HTML entities (caso o Bing mude o formato)
        matches = re.findall(r'"murl":"(https?://[^"]+)"', raw_html)
        logger.debug(f'{log_prefix} _extract_bing_image_urls: padrão aspas diretas (fallback) encontrou {len(matches)} resultado(s).')

    if not matches:
        logger.warning(f'{log_prefix} _extract_bing_image_urls: NENHUM resultado encontrado com nenhum padrão. '
                       f'Tamanho do HTML: {len(raw_html)} chars. '
                       f'Contém "murl": {"murl" in raw_html}. '
                       f'Primeiros 300 chars: {repr(raw_html[:300])}')

    urls = []
    for item in matches:
        url = html.unescape(item).replace('\\/', '/')
        if url.startswith('http://') or url.startswith('https://'):
            urls.append(url)
    return urls


def _find_image_candidates_on_web(query, limit=3):
    """Busca as primeiras imagens do Bing Images para o query fornecido.
    Retorna lista de URLs das imagens originais (as primeiras que aparecem na tela).
    """
    log_prefix = '[AutoPic]'
    if not query:
        logger.warning(f'{log_prefix} _find_image_candidates_on_web: query vazio, abortando.')
        return []

    limit = max(1, int(limit or 3))
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    )
    search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}&form=HDRSC2&first=1"
    logger.info(f'{log_prefix} Buscando imagens para query="{query}" limit={limit} url={search_url}')

    # Contexto SSL sem verificação para evitar erros de certificado em ambientes restritos
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    # Solicitar apenas gzip (não brotli) para evitar dependência do módulo brotli
    req = urllib.request.Request(
        search_url,
        headers={
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',  # sem 'br' para evitar brotli
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    )

    import gzip
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as response:
            raw_data = response.read()
            http_status = response.status
            encoding = (response.headers.get('Content-Encoding') or '').lower().strip()
            content_type = (response.headers.get('Content-Type') or '').lower()
            logger.info(f'{log_prefix} Resposta do Bing: HTTP {http_status}, '
                        f'Content-Encoding={encoding!r}, Content-Type={content_type!r}, '
                        f'tamanho bruto={len(raw_data)} bytes')

            if encoding == 'gzip':
                try:
                    content = gzip.decompress(raw_data).decode('utf-8', errors='ignore')
                    logger.debug(f'{log_prefix} Descomprimido gzip: {len(content)} chars')
                except Exception as gz_err:
                    logger.error(f'{log_prefix} Falha ao descomprimir gzip: {gz_err}. Tentando decodificar direto.')
                    content = raw_data.decode('utf-8', errors='ignore')
            elif encoding == 'br':
                # brotli pode não estar instalado — tentar e logar claramente
                try:
                    import brotli
                    content = brotli.decompress(raw_data).decode('utf-8', errors='ignore')
                    logger.debug(f'{log_prefix} Descomprimido brotli: {len(content)} chars')
                except ImportError:
                    logger.error(f'{log_prefix} ERRO CRÍTICO: O servidor retornou encoding brotli (br) mas o '
                                 f'módulo "brotli" não está instalado. '
                                 f'Execute: pip install brotli  (ou adicione ao requirements.txt). '
                                 f'O AutoPic não conseguirá encontrar imagens até isso ser resolvido.')
                    return []
                except Exception as br_err:
                    logger.error(f'{log_prefix} Falha ao descomprimir brotli: {br_err}. Tentando decodificar direto.')
                    content = raw_data.decode('utf-8', errors='ignore')
            elif encoding in ('deflate', ''):
                content = raw_data.decode('utf-8', errors='ignore')
                logger.debug(f'{log_prefix} Conteúdo sem compressão: {len(content)} chars')
            else:
                logger.warning(f'{log_prefix} Encoding desconhecido "{encoding}", tentando decodificar direto.')
                content = raw_data.decode('utf-8', errors='ignore')

    except urllib.error.HTTPError as http_err:
        logger.error(f'{log_prefix} HTTPError ao acessar Bing: {http_err.code} {http_err.reason}')
        raise
    except urllib.error.URLError as url_err:
        logger.error(f'{log_prefix} URLError ao acessar Bing: {url_err.reason}')
        raise
    except Exception as e:
        logger.error(f'{log_prefix} Erro inesperado ao acessar Bing: {type(e).__name__}: {e}')
        raise

    urls = _extract_bing_image_urls(content, log_prefix=log_prefix)
    logger.info(f'{log_prefix} Total de URLs extraídas antes de deduplicar: {len(urls)}')

    # Remover duplicatas mantendo a ordem (as primeiras são as que aparecem na tela)
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    result = unique_urls[:limit]
    logger.info(f'{log_prefix} Retornando {len(result)} candidato(s) para query="{query}": {result}')
    return result


def _download_remote_image_to_uploads(image_url, prefix='autofind'):
    log_prefix = '[AutoPic]'
    logger.info(f'{log_prefix} Download de imagem: url={image_url[:120]!r} prefix={prefix!r}')

    parsed = urllib.parse.urlparse(image_url)
    if parsed.scheme not in {'http', 'https'}:
        logger.error(f'{log_prefix} URL inválida (scheme={parsed.scheme!r}): {image_url[:120]}')
        raise ValueError('URL de imagem inválida.')

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(image_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Referer': 'https://www.bing.com/',
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as response:
            http_status = response.status
            content_type = (response.headers.get('Content-Type') or '').lower()
            data = response.read(6 * 1024 * 1024 + 1)
            logger.info(f'{log_prefix} Download concluído: HTTP {http_status}, '
                        f'Content-Type={content_type!r}, tamanho={len(data)} bytes')
    except urllib.error.HTTPError as http_err:
        logger.error(f'{log_prefix} HTTPError ao baixar imagem {image_url[:120]!r}: '
                     f'{http_err.code} {http_err.reason}')
        raise
    except urllib.error.URLError as url_err:
        logger.error(f'{log_prefix} URLError ao baixar imagem {image_url[:120]!r}: {url_err.reason}')
        raise
    except Exception as e:
        logger.error(f'{log_prefix} Erro inesperado ao baixar imagem {image_url[:120]!r}: '
                     f'{type(e).__name__}: {e}')
        raise

    if len(data) > 6 * 1024 * 1024:
        logger.warning(f'{log_prefix} Imagem muito grande: {len(data)} bytes (máx 6MB)')
        raise ValueError('Imagem muito grande (máximo 6MB).')
    if not content_type.startswith('image/'):
        logger.error(f'{log_prefix} Content-Type inválido: {content_type!r} para url={image_url[:120]!r}')
        raise ValueError('A URL selecionada não retornou uma imagem válida.')

    ext = '.jpg'
    if 'png' in content_type:
        ext = '.png'
    elif 'webp' in content_type:
        ext = '.webp'
    elif 'gif' in content_type:
        ext = '.gif'

    filename = secure_filename(f"{prefix}-{int(time.time()*1000)}{ext}")
    path = UPLOAD_DIR / filename
    with open(path, 'wb') as f:
        f.write(data)
    logger.info(f'{log_prefix} Imagem salva em: {path}')
    return f'/uploads/{filename}'


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


def format_currency_br(cents):
    if cents is None:
        return 'Não informado'
    try:
        value = (int(cents) or 0) / 100.0
    except Exception:
        return 'Não informado'
    formatted = f"{value:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _relation_report_hex_to_color(value, fallback='#047857'):
    if not REPORTLAB_AVAILABLE:
        return None
    text = (value or fallback or '').strip()
    if not text:
        text = fallback
    if not text.startswith('#'):
        text = f'#{text}'
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', text):
        text = fallback
    return colors.HexColor(text)


def _relation_report_pick_system_colors():
    settings = _load_app_settings_map([
        'theme_primary_color', 'theme_secondary_color', 'theme_accent_color',
        'brand_primary_color', 'brand_secondary_color', 'brand_accent_color'
    ])
    primary = settings.get('theme_primary_color') or settings.get('brand_primary_color') or '#047857'
    secondary = settings.get('theme_secondary_color') or settings.get('brand_secondary_color') or '#065f46'
    accent = settings.get('theme_accent_color') or settings.get('brand_accent_color') or '#34d399'
    return {
        'primary': _relation_report_hex_to_color(primary, '#047857'),
        'secondary': _relation_report_hex_to_color(secondary, '#065f46'),
        'accent': _relation_report_hex_to_color(accent, '#34d399'),
        'primary_hex': primary if str(primary).startswith('#') else f'#{primary}',
        'secondary_hex': secondary if str(secondary).startswith('#') else f'#{secondary}',
        'accent_hex': accent if str(accent).startswith('#') else f'#{accent}'
    }


def _relation_report_resolve_local_image(candidate_url):
    if not candidate_url:
        return None
    try:
        parsed = urlparse(candidate_url)
        path = parsed.path or candidate_url
    except Exception:
        path = candidate_url
    path = str(path).strip()
    if not path:
        return None
    if path.startswith('/uploads/accounts/'):
        local = ACCOUNT_UPLOAD_DIR / Path(path).name
        return local if local.exists() else None
    if path.startswith('/uploads/'):
        local = UPLOAD_DIR / path.replace('/uploads/', '', 1)
        return local if local.exists() else None
    local_path = Path(path)
    if local_path.exists():
        return local_path
    project_public = Path(__file__).resolve().parent / 'public'
    for rel in ['logo-coelho.png', 'favicon.png', 'coelho-sugestoes.png']:
        probe = project_public / rel
        if probe.exists() and Path(path).name == rel:
            return probe
    return None


def _relation_report_system_logo_path():
    project_public = Path(__file__).resolve().parent / 'public'
    for rel in ['logo-coelho.png', 'favicon.png']:
        probe = project_public / rel
        if probe.exists():
            return probe
    return None


def _relation_report_safe_image(image_path, max_width=220, max_height=120):
    if not image_path or not PIL_AVAILABLE:
        return None
    try:
        img = PILImage.open(str(image_path)).convert('RGBA')
        img.thumbnail((max_width, max_height))
        background = PILImage.new('RGBA', img.size, (255, 255, 255, 255))
        background.alpha_composite(img)
        return ImageReader(background.convert('RGB'))
    except Exception:
        return None


def _relation_report_parse_dt(value):
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%Y-%m', '%Y-%m-%d %H:%M'):
        try:
            sample = raw[:19] if ('%H' in fmt or 'T' in fmt) else raw[:10]
            return datetime.strptime(sample, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _relation_report_format_dt(value):
    dt = _relation_report_parse_dt(value)
    if not dt:
        return 'Não informado'
    raw = str(value).strip()
    if len(raw) <= 10:
        return dt.strftime('%d/%m/%Y')
    return dt.strftime('%d/%m/%Y %H:%M')


def _relation_report_period_clause(date_column, start_date=None, end_date=None):
    clauses = []
    params = []
    if start_date:
        clauses.append(f"date({date_column}) >= date(?)")
        params.append(start_date)
    if end_date:
        clauses.append(f"date({date_column}) <= date(?)")
        params.append(end_date)
    return (' AND ' + ' AND '.join(clauses)) if clauses else '', params


def _relation_report_topic_from_text(text):
    content = f" {str(text or '').lower()} "
    topic_rules = [
        ('IA', [' ia ', 'inteligência artificial', 'inteligencia artificial', ' ai ', 'openai', 'copilot', 'gemini', 'claude', 'llm', 'machine learning']),
        ('Cyber', ['cyber', 'segurança', 'seguranca', 'security', 'soc', 'siem', 'firewall', 'iam', 'identity', 'phishing', 'ransomware']),
        ('Aplicações', ['aplica', 'aplicações', 'aplicacoes', 'software', 'sistema', ' app ', 'erp', 'crm', 'sap', 'oracle', 'totvs', 'desenvolvimento']),
        ('Marketing', ['marketing', 'campanha', 'mídia', 'midia', 'lead', 'brand', 'marca', 'comunicação', 'comunicacao']),
        ('Cloud', ['cloud', 'nuvem', 'aws', 'azure', 'gcp', 'google cloud', 'oracle cloud', 'multicloud', 'finops', 'kubernetes']),
    ]
    for topic, keywords in topic_rules:
        for keyword in keywords:
            if keyword in content:
                return topic
    return 'Outros'


def _relation_report_collect_data(account_id, start_date=None, end_date=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    account = dict_from_row(c.fetchone())
    if not account:
        conn.close()
        return None

    c.execute("""SELECT c.*, CASE WHEN amc.client_id IS NOT NULL THEN 1 ELSE 0 END AS is_main_contact
                 FROM clients c
                 LEFT JOIN account_main_contacts amc ON amc.client_id = c.id AND amc.account_id = ?
                 WHERE LOWER(TRIM(c.company)) = LOWER(TRIM(?))
                 ORDER BY is_main_contact DESC, c.name COLLATE NOCASE""", (account_id, account['name']))
    contacts = [dict_from_row(r) for r in c.fetchall()]
    contact_ids = [row['id'] for row in contacts]

    c.execute("""SELECT ap.*, fc.name AS focal_client_name
                 FROM account_presences ap
                 LEFT JOIN clients fc ON fc.id = ap.focal_client_id
                 WHERE ap.account_id = ?
                 ORDER BY ap.delivery_name COLLATE NOCASE""", (account_id,))
    presences = [dict_from_row(r) for r in c.fetchall()]

    period_sql_activities, activity_params = _relation_report_period_clause('a.activity_date', start_date, end_date)
    activities = []
    if contact_ids:
        placeholders = ','.join(['?'] * len(contact_ids))
        c.execute(f"""SELECT a.*, cl.name AS client_name, cl.position AS client_position, cl.company AS client_company
                      FROM activities a
                      JOIN clients cl ON cl.id = a.client_id
                      WHERE a.client_id IN ({placeholders}) {period_sql_activities}
                      ORDER BY datetime(a.activity_date) DESC, a.id DESC""", tuple(contact_ids) + tuple(activity_params))
        activities = [dict_from_row(r) for r in c.fetchall()]

    period_sql_account_acts, account_activity_params = _relation_report_period_clause('activity_date', start_date, end_date)
    c.execute(f"""SELECT id, account_id, description, activity_date, created_at
                  FROM account_activities
                  WHERE account_id = ? {period_sql_account_acts}
                  ORDER BY datetime(activity_date) DESC, created_at DESC""", (account_id, *account_activity_params))
    account_activities = [dict_from_row(r) for r in c.fetchall()]

    environment_responses = []
    if contact_ids:
        placeholders = ','.join(['?'] * len(contact_ids))
        c.execute(f"""SELECT er.*, ec.title AS card_title, ec.description AS card_description,
                             cl.name AS client_name, cl.position AS client_position
                      FROM environment_responses er
                      JOIN environment_cards ec ON ec.id = er.card_id
                      JOIN clients cl ON cl.id = er.client_id
                      WHERE er.client_id IN ({placeholders})
                      ORDER BY ec.display_order ASC, ec.title COLLATE NOCASE, cl.name COLLATE NOCASE""", tuple(contact_ids))
        environment_responses = [dict_from_row(r) for r in c.fetchall()]

    period_sql_kanban, kanban_params = _relation_report_period_clause('kc.updated_at', start_date, end_date)
    contact_condition = ''
    params = [account_id]
    if contact_ids:
        contact_condition = ' OR kc.contact_id IN ({})'.format(','.join(['?'] * len(contact_ids)))
        params.extend(contact_ids)
    c.execute(f"""SELECT kc.*, kcol.title AS column_title, cl.name AS contact_name, ac.name AS account_name
                  FROM kanban_cards kc
                  LEFT JOIN kanban_columns kcol ON kcol.id = kc.column_id
                  LEFT JOIN clients cl ON cl.id = kc.contact_id
                  LEFT JOIN accounts ac ON ac.id = kc.account_id
                  WHERE (kc.account_id = ? {contact_condition}) {period_sql_kanban}
                  ORDER BY datetime(kc.updated_at) DESC, kc.id DESC""", tuple(params) + tuple(kanban_params))
    kanban_cards = [dict_from_row(r) for r in c.fetchall()]

    for card in kanban_cards:
        c.execute("SELECT content, created_at FROM kanban_card_activities WHERE card_id = ? ORDER BY created_at DESC", (card['id'],))
        card['activities'] = [dict_from_row(r) for r in c.fetchall()]

    latest_interaction = None
    latest_candidates = []
    for item in activities:
        latest_candidates.append({
            'date': item.get('activity_date') or item.get('created_at'),
            'person': item.get('client_name'),
            'source': 'Atividade',
            'description': item.get('description') or item.get('information')
        })
    for item in account_activities:
        latest_candidates.append({
            'date': item.get('activity_date') or item.get('created_at'),
            'person': account.get('name'),
            'source': 'Atividade da conta',
            'description': item.get('description')
        })
    latest_candidates = [x for x in latest_candidates if x.get('date')]
    latest_candidates.sort(key=lambda x: _relation_report_parse_dt(x.get('date')) or datetime.min, reverse=True)
    if latest_candidates:
        latest_interaction = latest_candidates[0]

    relationship_cards = []
    for contact in contacts:
        contact_activities = [a for a in activities if a.get('client_id') == contact.get('id')]
        contact_responses = [r for r in environment_responses if r.get('client_id') == contact.get('id')]
        contact_kanban = [k for k in kanban_cards if k.get('contact_id') == contact.get('id')]
        last_contact = None
        if contact_activities:
            act = sorted(contact_activities, key=lambda x: _relation_report_parse_dt(x.get('activity_date')) or datetime.min, reverse=True)[0]
            last_contact = {
                'date': act.get('activity_date') or act.get('created_at'),
                'summary': act.get('description') or act.get('information') or 'Interação registrada'
            }
        relationship_cards.append({
            'contact': contact,
            'activities_count': len(contact_activities),
            'mapping_count': len(contact_responses),
            'kanban_count': len(contact_kanban),
            'last_contact': last_contact,
            'topics': sorted(set(_relation_report_topic_from_text(' '.join(filter(None, [a.get('description') or '', a.get('information') or '']))) for a in contact_activities if (a.get('description') or a.get('information'))))
        })

    topic_buckets = {key: [] for key in ['IA', 'Cyber', 'Aplicações', 'Marketing', 'Cloud', 'Outros']}
    topic_sources = []
    for item in activities:
        topic_sources.append({
            'text': ' '.join(filter(None, [item.get('description'), item.get('information')])),
            'date': item.get('activity_date') or item.get('created_at'),
            'person': item.get('client_name'),
            'source': 'atividade'
        })
    for item in account_activities:
        topic_sources.append({
            'text': item.get('description') or '',
            'date': item.get('activity_date') or item.get('created_at'),
            'person': account.get('name'),
            'source': 'atividade_conta'
        })
    for item in kanban_cards:
        topic_sources.append({
            'text': ' '.join(filter(None, [item.get('title'), item.get('description'), item.get('activity')])),
            'date': item.get('updated_at') or item.get('created_at'),
            'person': item.get('contact_name') or account.get('name'),
            'source': 'kanban'
        })
    for item in environment_responses:
        topic_sources.append({
            'text': ' '.join(filter(None, [item.get('card_title'), item.get('card_description'), item.get('response')])),
            'date': item.get('updated_at'),
            'person': item.get('client_name'),
            'source': 'mapeamento'
        })
    for source in topic_sources:
        topic = _relation_report_topic_from_text(source.get('text'))
        topic_buckets[topic].append(source)

    summary_counts = {
        'contacts': len(contacts),
        'main_contacts': len([c for c in contacts if c.get('is_main_contact')]),
        'activities': len(activities),
        'account_activities': len(account_activities),
        'mapping_items': len(environment_responses),
        'kanban_cards': len(kanban_cards),
        'presences': len(presences)
    }

    conn.close()
    return {
        'account': account,
        'contacts': contacts,
        'presences': presences,
        'activities': activities,
        'account_activities': account_activities,
        'environment_responses': environment_responses,
        'kanban_cards': kanban_cards,
        'latest_interaction': latest_interaction,
        'relationship_cards': relationship_cards,
        'topics': topic_buckets,
        'summary_counts': summary_counts,
        'start_date': start_date,
        'end_date': end_date,
        'full_period': not start_date and not end_date
    }


def _relation_report_build_llm_context(report_data):
    account = report_data['account']
    lines = []
    lines.append(f"Conta: {account.get('name')}")
    lines.append(f"Setor: {account.get('sector') or 'Não informado'}")
    lines.append(f"Receita média: {format_currency_br(account.get('average_revenue_cents'))}")
    lines.append(f"Profissionais: {account.get('professionals_count') or 'Não informado'}")
    lines.append(f"Presença global: {account.get('global_presence') or 'Não informado'}")
    lines.append('')
    lines.append('Resumo quantitativo:')
    for key, value in report_data['summary_counts'].items():
        lines.append(f"- {key}: {value}")
    lines.append('')
    lines.append('Contatos da conta:')
    for contact in report_data['contacts'][:50]:
        lines.append(f"- {contact.get('name')} | cargo: {contact.get('position') or 'Não informado'} | área: {contact.get('area_of_activity') or 'Não informado'} | email: {contact.get('email') or 'Não informado'} | principal: {'sim' if contact.get('is_main_contact') else 'não'}")
    lines.append('')
    lines.append('Powermapping / cards resumidos por contato:')
    for card in report_data['relationship_cards'][:50]:
        c = card['contact']
        lines.append(f"- {c.get('name')}: atividades={card.get('activities_count',0)}, mapeamentos={card.get('mapping_count',0)}, kanban={card.get('kanban_count',0)}, último contato={_relation_report_format_dt((card.get('last_contact') or {}).get('date'))}")
    lines.append('')
    lines.append('Presenças / entregas:')
    for presence in report_data['presences'][:50]:
        lines.append(f"- {presence.get('delivery_name')}: owner={presence.get('stf_owner') or 'Não informado'}, receita atual={format_currency_br(presence.get('current_revenue_cents'))}, validade={presence.get('validity_month') or 'Não informado'}, focal={presence.get('focal_client_name') or 'Não informado'}")
    lines.append('')
    lines.append('Últimas interações:')
    for item in report_data['activities'][:25]:
        lines.append(f"- {item.get('client_name')} em {_relation_report_format_dt(item.get('activity_date') or item.get('created_at'))}: {item.get('description') or item.get('information') or 'Sem detalhe'}")
    for item in report_data['account_activities'][:15]:
        lines.append(f"- Conta em {_relation_report_format_dt(item.get('activity_date') or item.get('created_at'))}: {item.get('description') or 'Sem detalhe'}")
    lines.append('')
    lines.append('Kanban:')
    for item in report_data['kanban_cards'][:25]:
        lines.append(f"- [{item.get('column_title') or 'Sem coluna'}] {item.get('title')} | contato={item.get('contact_name') or 'Não informado'} | urgência={item.get('urgency') or 'Não informada'} | descrição={item.get('description') or 'Sem descrição'}")
    lines.append('')
    lines.append('Mapeamento de ambiente:')
    for item in report_data['environment_responses'][:30]:
        lines.append(f"- {item.get('client_name')} | card={item.get('card_title')} | resposta={item.get('response') or 'Sem resposta'}")
    lines.append('')
    lines.append('Tópicos estratégicos:')
    for topic, items in report_data['topics'].items():
        lines.append(f"- {topic}: {len(items)} evidência(s)")
        for sample in items[:5]:
            lines.append(f"  * {_relation_report_format_dt(sample.get('date'))} | {sample.get('person') or 'Não informado'} | {str(sample.get('text') or '')[:240]}")
    return '\n'.join(lines)


def _relation_report_build_account_snapshot(report_data):
    account = report_data.get('account') or {}
    counts = report_data.get('summary_counts') or {}
    latest = report_data.get('latest_interaction') or {}
    presences = report_data.get('presences') or []
    total_stefanini_cents = sum(int(p.get('current_revenue_cents') or 0) for p in presences if p.get('current_revenue_cents') is not None)
    parts = []
    segment = account.get('sector') or account.get('segment') or 'Não informado'
    parts.append(f"Conta do segmento {segment}.")
    parts.append(
        f"{counts.get('contacts', 0)} contatos relacionados. "
        f"{counts.get('activities', 0) + counts.get('account_activities', 0)} atividades registradas no período. "
        f"{counts.get('kanban_cards', 0)} cards no Kanban. "
        f"{counts.get('mapping_items', 0)} itens de mapeamento de ambiente. "
        f"{counts.get('presences', 0)} presenças/entregas ativas ou históricas."
    )
    parts.append(
        f"Última interação identificada em {_relation_report_format_dt(latest.get('date'))} "
        f"com {latest.get('person') or 'contato não identificado'}, via {latest.get('source') or 'registro interno'}."
    )
    extra = []
    if account.get('average_revenue'):
        extra.append(f"Faturamento de mercado da conta: {account.get('average_revenue')}")
    elif account.get('average_revenue_cents') is not None:
        extra.append(f"Faturamento de mercado da conta: {format_currency_br(account.get('average_revenue_cents'))}")
    if total_stefanini_cents > 0:
        extra.append(f"Serviços Stefanini atualmente mapeados: {format_currency_br(total_stefanini_cents)}")
    if account.get('number_of_professionals'):
        extra.append(f"Profissionais: {account.get('number_of_professionals')}")
    elif account.get('professionals_count'):
        extra.append(f"Profissionais: {account.get('professionals_count')}")
    if account.get('presence'):
        extra.append(f"Presença geográfica: {account.get('presence')}")
    elif account.get('global_presence'):
        extra.append(f"Presença geográfica: {account.get('global_presence')}")
    if extra:
        parts.append('. '.join(extra) + '.')
    parts.append('Ao interpretar a conta, trate faturamento de mercado da conta e receita de Serviços Stefanini como informações distintas.')
    return '\n'.join([p for p in parts if p])


def _relation_report_build_relationship_snapshot(report_data):
    cards = report_data.get('relationship_cards') or []
    activities = report_data.get('activities') or []
    account_activities = report_data.get('account_activities') or []
    kanban_cards = report_data.get('kanban_cards') or []
    lines = []
    concrete_signals = 0
    scheduling_signals = 0
    for item in activities[:40] + account_activities[:20]:
        text = ' '.join([
            str(item.get('activity_type') or ''),
            str(item.get('description') or ''),
            str(item.get('notes') or ''),
            str(item.get('subject') or '')
        ]).lower()
        if any(token in text for token in ['agenda', 'agendar', 'tentativa', 'follow-up', 'follow up', 'cobrança']) and not any(token in text for token in ['reunião realizada', 'workshop', 'apresentação', 'assessment', 'kickoff', 'discussão', 'definição', 'próximo passo definido', 'proposta apresentada']):
            scheduling_signals += 1
        if any(token in text for token in ['reunião realizada', 'workshop', 'apresentação', 'assessment', 'kickoff', 'discussão', 'alinhamento', 'proposta', 'entrega', 'roadmap', 'diagnóstico']):
            concrete_signals += 1
    for card in cards[:8]:
        contact = card.get('contact') or {}
        lines.append(
            f"{contact.get('name') or 'Contato sem nome'}, {contact.get('position') or 'cargo não informado'}, "
            f"atua em {contact.get('area_of_activity') or 'área não informada'}; "
            f"{card.get('activities_count', 0)} atividades, {card.get('mapping_count', 0)} mapeamentos, "
            f"{card.get('kanban_count', 0)} itens no Kanban; último contato em {_relation_report_format_dt((card.get('last_contact') or {}).get('date'))}."
        )
    if not lines:
        lines.append('Não há contatos suficientes mapeados para descrever o Power Mapping da conta.')
    lines.append(
        f"Sinais de profundidade relacional: {concrete_signals} registro(s) de interação concreta e {scheduling_signals} registro(s) predominantemente voltados a pedido de agenda ou tentativa de contato. "
        f"Não trate volume de interação como sinônimo automático de relacionamento profundo."
    )
    if kanban_cards:
        kanban_lines = []
        for card in kanban_cards[:6]:
            title = str(card.get('title') or 'Card sem título').strip()
            col = str(card.get('column_name') or 'coluna não informada').strip()
            desc = str(card.get('description') or '').strip().replace('\n', ' ')
            if len(desc) > 140:
                desc = desc[:137] + '...'
            snippet = f"{title} [{col}]"
            if desc:
                snippet += f": {desc}"
            kanban_lines.append(snippet)
        lines.append('Leitura de Kanban: ' + ' | '.join(kanban_lines))
    lines.append('Considere a densidade de interação, sinais de influência, cobertura dos stakeholders e conteúdo real das interações ao redigir a análise.')
    return '\n'.join(lines)


def _relation_report_build_topic_evidence(report_data):
    sections = []
    for topic in ['IA', 'Cyber', 'Aplicações', 'Marketing', 'Cloud', 'Outros']:
        items = (report_data.get('topics') or {}).get(topic) or []
        if not items:
            sections.append(f"{topic}:\nSem evidências relevantes identificadas no período.")
            continue
        lines = []
        for item in items[:5]:
            when = _relation_report_format_dt(item.get('date'))
            who = item.get('person') or 'não informado'
            source = item.get('source') or 'registro interno'
            snippet = str(item.get('text') or '').strip().replace('\n', ' ')
            if len(snippet) > 220:
                snippet = snippet[:217] + '...'
            lines.append(f"- {when} | {who} | {source}: {snippet}")
        sections.append(f"{topic}:\n" + '\n'.join(lines))
    return '\n\n'.join(sections)


def _relation_report_fetch_market_context(account_name: str) -> str | None:
    question = (
        f"Você é um analista de negócios. Pesquise na web notícias e informações recentes "
        f"sobre a empresa '{account_name}'. "
        "Escreva um parágrafo executivo de 3 a 5 linhas descrevendo o momento atual "
        "desta empresa no mercado: tendências, movimentos estratégicos, expansões, "
        "desafios ou destaque setorial. "
        "Use somente informações verificáveis e recentes. "
        "Se não encontrar informações confiáveis, responda exatamente: SEM_DADOS"
    )
    raw = _sai_simple_prompt(question)
    if not raw:
        return None
    text = raw.strip()
    if 'SEM_DADOS' in text or len(text) < 30:
        return None
    return text


def _relation_report_generate_highlights(report_data: dict) -> list[str]:
    account_name = ((report_data.get('account') or {}).get('name') or 'Conta').strip()
    activities = report_data.get('activities') or []
    account_activities = report_data.get('account_activities') or []

    lines = []
    for activity in (account_activities + activities)[:40]:
        desc = (activity.get('description') or activity.get('notes') or activity.get('information') or '').strip()
        date = (
            activity.get('date')
            or activity.get('activity_date')
            or activity.get('created_at')
            or ''
        )
        atype = (activity.get('type') or activity.get('category') or activity.get('origin') or '').strip()
        if desc:
            lines.append(f"[{str(date)[:10]}][{atype}] {desc}")

    if not lines:
        return []

    activities_text = '\n'.join(lines)
    question = (
        f"Analise as atividades abaixo registradas na conta '{account_name}'. "
        "Gere de 4 a 6 bullets executivos destacando os pontos mais relevantes: "
        "temas estratégicos discutidos, avanços concretos de relacionamento, "
        "pendências ou oportunidades identificadas, e padrão de engajamento. "
        "Seja direto, use verbos no passado ou presente, sem inventar fatos. "
        "Retorne SOMENTE os bullets, um por linha, começando cada linha com '- '. "
        "Atividades:\n" + activities_text
    )
    raw = _sai_simple_prompt(question)
    if not raw:
        return []

    bullets = [
        line.lstrip('- •*').strip()
        for line in raw.strip().splitlines()
        if line.strip().startswith(('-', '•', '*')) and len(line.strip()) > 10
    ]
    return bullets[:6]


def _relation_report_call_sai_narrative_template(
    account_name,
    report_period,
    account_snapshot,
    relationship_snapshot,
    topic_evidence,
    output_style,
):
    settings_map = _load_app_settings_map([
        'relation_report_sai_api_key',
        'relation_report_sai_template_id',
        'relation_report_sai_base_url'
    ])
    api_key = (settings_map.get('relation_report_sai_api_key') or '').strip() or (os.environ.get('RELATION_REPORT_SAI_API_KEY', '') or '').strip() or 'RuWKlxg1Sk+/3PpzUKof+w'
    template_id = (settings_map.get('relation_report_sai_template_id') or '').strip() or '69b83e37025459101ee6735d'
    base_url = (settings_map.get('relation_report_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

    if not api_key:
        return None

    url = f'{base_url}/api/templates/{template_id}/execute'
    headers = {
        'Content-Type': 'application/json',
        'X-Api-Key': api_key
    }
    payload = {
        'inputs': {
            'account_name': account_name,
            'report_period': report_period,
            'account_snapshot': account_snapshot,
            'relationship_snapshot': relationship_snapshot,
            'topic_evidence': topic_evidence,
            'output_style': output_style,
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode('utf-8')

    logger.debug(f'[RelationReport][SAI] raw response (primeiros 500 chars): {raw[:500]}')
    parsed_outer = None
    try:
        parsed_outer = json.loads(raw)
    except Exception:
        parsed_outer = None

    candidate_texts = []
    if isinstance(parsed_outer, dict):
        for key in ['answer', 'output', 'result', 'text', 'response', 'data']:
            value = parsed_outer.get(key)
            if isinstance(value, str):
                candidate_texts.append(value)
            elif isinstance(value, dict):
                candidate_texts.append(json.dumps(value, ensure_ascii=False))
        candidate_texts.append(raw)
    else:
        candidate_texts.append(raw)

    parsed = None
    for candidate in candidate_texts:
        try:
            obj = json.loads((candidate or '').strip())
            if isinstance(obj, dict):
                parsed = obj
                break
        except Exception:
            obj = _extract_json_object_from_text(candidate or '')
            if isinstance(obj, dict):
                parsed = obj
                break

    if not isinstance(parsed, dict):
        return None

    return {
        'executive_summary': (parsed.get('executive_summary') or '').strip(),
        'relationship_maturity': (parsed.get('relationship_maturity') or 'Em evolução').strip(),
        'next_steps': [str(x).strip() for x in (parsed.get('next_steps') or []) if str(x).strip()][:5],
        'topic_breakdown': parsed.get('topic_breakdown') or {},
        'highlights': [str(x).strip() for x in (parsed.get('highlights') or []) if str(x).strip()][:6],
        'llm_used': True
    }


def _relation_report_generate_narrative(report_data):
    account = report_data.get('account') or {}
    period = report_data.get('period') or {}
    account_name = (account.get('name') or 'Conta sem nome').strip()
    report_period = 'Todo o período' if period.get('full_period') else f"{period.get('start_date') or 'Início não informado'} a {period.get('end_date') or 'Fim não informado'}"
    account_snapshot = _relation_report_build_account_snapshot(report_data)
    relationship_snapshot = _relation_report_build_relationship_snapshot(report_data)
    topic_evidence = _relation_report_build_topic_evidence(report_data)
    output_style = 'Tom executivo, objetivo, claro, elegante e sem inventar fatos. Use sempre a expressão Power Mapping. Não trate faturamento de mercado da conta como receita da Stefanini. Só classifique o relacionamento como profundo quando houver evidências concretas de avanço, reuniões realizadas, discussões de conteúdo, entregas, proposta, assessment, workshop, roadmap ou desdobramentos objetivos. Se o histórico indicar apenas tentativa de agenda, cobrança ou follow-up sem avanço real, deixe isso explícito. Considere também o conteúdo dos cards de Kanban para explicar como eles se relacionam com a conta.'

    narrative_data = None
    market_context = None
    llm_highlights = []

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_narrative = executor.submit(
                _relation_report_call_sai_narrative_template,
                account_name,
                report_period,
                account_snapshot,
                relationship_snapshot,
                topic_evidence,
                output_style,
            )
            f_market = executor.submit(_relation_report_fetch_market_context, account_name)
            f_highlights = executor.submit(_relation_report_generate_highlights, report_data)

            try:
                narrative_data = f_narrative.result()
            except Exception as e:
                logger.warning(f'[RelationReport] Falha ao gerar narrativa com SAI: {e}')
            try:
                market_context = f_market.result()
            except Exception as e:
                logger.warning(f'[RelationReport] Falha ao gerar contexto de mercado: {e}')
            try:
                llm_highlights = f_highlights.result() or []
            except Exception as e:
                logger.warning(f'[RelationReport] Falha ao gerar destaques via LLM: {e}')
    except Exception as e:
        logger.warning(f'[RelationReport] Falha no executor paralelo da narrativa: {e}')

    if isinstance(narrative_data, dict):
        if len(llm_highlights) >= 2:
            narrative_data['highlights'] = llm_highlights
        narrative_data['market_context'] = market_context
        return narrative_data

    latest = report_data.get('latest_interaction') or {}
    counts = report_data.get('summary_counts') or {}
    executive_summary = (
        f"A conta {report_data['account'].get('name')} possui {counts.get('contacts', 0)} contato(s) relacionado(s), "
        f"{counts.get('presences', 0)} presença(s)/entrega(s) mapeada(s), {counts.get('activities', 0)} atividade(s) de relacionamento "
        f"e {counts.get('kanban_cards', 0)} card(s) ativos ou históricos no Kanban dentro do recorte consultado. "
        f"O conjunto de registros indica um relacionamento {'mais estruturado' if counts.get('activities', 0) >= 5 or counts.get('mapping_items', 0) >= 5 else 'em consolidação'}, "
        f"com evidências distribuídas entre interações registradas, mapeamentos de ambiente e acompanhamento operacional.\n\n"
        f"A interação mais recente identificada ocorreu em {_relation_report_format_dt(latest.get('date'))}, "
        f"associada a {latest.get('person') or report_data['account'].get('name')}, via {latest.get('source') or 'registro interno'}. "
        f"Isso sugere {'continuidade recente do relacionamento' if latest.get('date') else 'baixa clareza temporal sobre a última interação'}, "
        f"e reforça a importância de manter cadência de contato, atualização do Kanban e aprofundamento do powermapping por contato-chave."
    )
    topic_breakdown = {}
    for topic, items in report_data['topics'].items():
        if items:
            sample = items[0]
            topic_breakdown[topic] = f"Há {len(items)} evidência(s) relacionadas a {topic.lower()} no período, com destaque para registros de {sample.get('source')} e menções envolvendo {sample.get('person') or 'contatos da conta'}."
        else:
            topic_breakdown[topic] = f"Não foram encontradas evidências relevantes sobre {topic.lower()} no período analisado."
    fallback_narrative = {
        'executive_summary': executive_summary,
        'relationship_maturity': 'Em evolução' if counts.get('activities', 0) < 8 else 'Estruturado',
        'next_steps': [
            'Validar os contatos principais e atualizar os responsáveis por influência e decisão.',
            'Revisar os cards do Kanban com foco em prioridades e próximos passos claros.',
            'Usar o resumo temático para orientar novas conversas consultivas com a conta.'
        ],
        'topic_breakdown': topic_breakdown,
        'highlights': [
            f"{counts.get('contacts', 0)} contato(s) associado(s) à conta.",
            f"{counts.get('mapping_items', 0)} item(ns) de mapeamento de ambiente registrados.",
            f"Última interação em {_relation_report_format_dt(latest.get('date'))}."
        ],
        'llm_used': False,
        'market_context': market_context,
    }
    if len(llm_highlights) >= 2:
        fallback_narrative['highlights'] = llm_highlights
    return fallback_narrative


def _relation_report_draw_paragraph(c, text, x, y, width, style):
    para = Paragraph(text or '', style)
    _, h = para.wrap(width, 10000)
    para.drawOn(c, x, y - h)
    return y - h


def _relation_report_draw_header(c, report_data, colors_map, page_width, page_height):
    c.setFillColor(colors_map['primary'])
    c.roundRect(18 * mm, page_height - 42 * mm, page_width - 36 * mm, 24 * mm, 6 * mm, fill=1, stroke=0)
    account = report_data['account']
    system_logo = _relation_report_safe_image(_relation_report_system_logo_path(), 180, 90)
    account_logo = _relation_report_safe_image(_relation_report_resolve_local_image(account.get('logo_url')), 180, 90)
    if system_logo:
        c.drawImage(system_logo, 22 * mm, page_height - 38 * mm, width=18 * mm, height=18 * mm, mask='auto', preserveAspectRatio=True)
    if account_logo:
        c.drawImage(account_logo, page_width - 40 * mm, page_height - 38 * mm, width=18 * mm, height=18 * mm, mask='auto', preserveAspectRatio=True)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 18)
    c.drawString(44 * mm, page_height - 27 * mm, 'Relation Report')
    c.setFont('Helvetica', 10)
    c.drawString(44 * mm, page_height - 33 * mm, 'Toca do Coelho')
    c.setFont('Helvetica-Bold', 14)
    title = account.get('name') or 'Cliente'
    max_width = 90 * mm
    while stringWidth(title, 'Helvetica-Bold', 14) > max_width and len(title) > 20:
        title = title[:-4] + '...'
    c.drawRightString(page_width - 44 * mm, page_height - 27 * mm, title)
    c.setFont('Helvetica', 9)
    subtitle = 'Período completo' if report_data.get('full_period') else f"{report_data.get('start_date') or '...'} a {report_data.get('end_date') or '...'}"
    c.drawRightString(page_width - 44 * mm, page_height - 33 * mm, subtitle)


def _relation_report_build_browser_html(report_data, profile=None, embed_images=False):
    profile = profile or {}

    def _local_image_from_url(url):
        if not url:
            return None
        raw_url = str(url).strip()
        if not raw_url:
            return None
        try:
            parsed = urlparse(raw_url)
            path = (parsed.path or raw_url).strip()
        except Exception:
            parsed = None
            path = raw_url
        if raw_url.startswith('file://') and parsed and parsed.path:
            file_path = Path(parsed.path)
            return file_path if file_path.exists() else None
        if not path:
            return None
        normalized = path.replace('\\', '/').strip()
        if normalized.startswith('/uploads/'):
            local = UPLOAD_DIR / normalized.replace('/uploads/', '', 1)
            return local if local.exists() else None
        if normalized.startswith('uploads/'):
            local = UPLOAD_DIR / normalized.replace('uploads/', '', 1)
            return local if local.exists() else None
        if normalized.startswith('/public/'):
            local = Path(BASE_DIR) / normalized.lstrip('/')
            return local if local.exists() else None
        if normalized.startswith('/'):
            local = Path(BASE_DIR) / 'public' / normalized.lstrip('/')
            return local if local.exists() else None
        local = Path(normalized)
        if local.exists():
            return local
        local_public = Path(BASE_DIR) / 'public' / normalized
        if local_public.exists():
            return local_public
        resolved = _relation_report_resolve_local_image(raw_url) or _relation_report_resolve_local_image(path)
        return resolved if resolved and Path(resolved).exists() else None

    def _inline_image_url(url):
        url = (url or '').strip()
        if not url or url.startswith('data:') or not embed_images:
            return url
        try:
            local_path = _local_image_from_url(url)
            if local_path:
                with open(local_path, 'rb') as fh:
                    raw = fh.read()
                mime, _ = mimetypes.guess_type(str(local_path))
                mime = mime or 'application/octet-stream'
                return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            if url.startswith('/static/'):
                static_path = os.path.join(BASE_DIR, url.lstrip('/'))
                if os.path.exists(static_path):
                    with open(static_path, 'rb') as fh:
                        raw = fh.read()
                    mime, _ = mimetypes.guess_type(static_path)
                    mime = mime or 'application/octet-stream'
                    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            if url.startswith('http://') or url.startswith('https://'):
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                mime = resp.headers.get('Content-Type', '').split(';')[0].strip() or mimetypes.guess_type(url)[0] or 'application/octet-stream'
                return f"data:{mime};base64,{base64.b64encode(resp.content).decode('ascii')}"
        except Exception:
            return url
        return url

    narrative = report_data.get('narrative') or _relation_report_generate_narrative(report_data)
    report_data['narrative'] = narrative
    account = report_data.get('account') or {}
    latest = report_data.get('latest_interaction') or {}
    counts = report_data.get('summary_counts') or {}
    profile = profile or {}

    def esc(value):
        return html.escape(str(value or ''))

    def fmt_money(value):
        try:
            if value in (None, ''):
                return 'Não informado'
            cents = int(value)
            return f"R$ {cents/100:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        except Exception:
            return 'Não informado'

    def topic_card(topic, bg):
        txt = ((narrative.get('topic_breakdown') or {}).get(topic) or f'Sem evidências relevantes para {topic.lower()}.').strip()
        return f"<div class='rr-topic-card' style='background:{bg};'><div class='rr-topic-title'>{esc(topic)}</div><div class='rr-topic-text'>{esc(txt)}</div></div>"

    profile_name = profile.get('nickname') or profile.get('full_name') or 'Usuário'
    profile_photo = profile.get('photo_url') or ''
    profile_role = profile.get('role') or profile.get('job_title') or profile.get('position') or 'Responsável pelo relacionamento'
    account_logo = account.get('logo_url') or ''
    account_name = account.get('name') or 'Conta'
    period_label = 'Todo o período' if report_data.get('full_period') else f"{report_data.get('start_date') or '...'} a {report_data.get('end_date') or '...'}"
    latest_text = 'Sem interações registradas'
    if latest:
        latest_text = f"{_relation_report_format_dt(latest.get('date'))} · {latest.get('with') or 'Contato não identificado'}"

    def company_rank(position):
        p = str(position or '').strip().lower()
        if p == 'ceo':
            return 1
        if p == 'cio':
            return 2
        if p.startswith('c') and len(p) <= 5:
            return 3
        if 'diretor' in p or 'superintendente' in p:
            return 4
        if 'gerente' in p:
            return 5
        if 'coordenador' in p:
            return 6
        return 7

    sorted_contacts = sorted(
        report_data.get('contacts') or [],
        key=lambda c: (company_rank(c.get('position')), str(c.get('name') or '').lower())
    )

    contacts_html = []
    for contact in sorted_contacts:
        photo = _inline_image_url(contact.get('photo_url') or '')
        initials = (str(contact.get('name') or '?').strip()[:1] or '?').upper()
        badges = []
        if contact.get('is_main_contact'):
            badges.append("<span class='rr-badge rr-badge-primary'>Contato-chave</span>")
        if contact.get('is_target'):
            badges.append("<span class='rr-badge rr-badge-soft'>Target</span>")
        if contact.get('is_cold_contact'):
            badges.append("<span class='rr-badge rr-badge-cold'>Cold</span>")
        meta = []
        if contact.get('position'):
            meta.append(esc(contact.get('position')))
        if contact.get('email'):
            meta.append(esc(contact.get('email')))
        if contact.get('phone'):
            meta.append(esc(contact.get('phone')))
        linkedin_raw = str(contact.get('linkedin') or '').strip()
        linkedin_html = ''
        if linkedin_raw:
            linkedin_safe = esc(linkedin_raw)
            linkedin_html = f"<div class='rr-contact-linkedin'><a href='{linkedin_safe}' target='_blank' rel='noopener noreferrer'>LinkedIn</a></div>"
        activities = [a for a in (report_data.get('activities') or []) if a.get('client_id') == contact.get('id')]
        last_contact = activities[0] if activities else None
        last_contact_line = f"Última interação: {esc(_relation_report_format_dt(last_contact.get('activity_date')))}" if last_contact else 'Última interação: não registrada'
        photo_html = f"<img src='{esc(photo)}' class='rr-contact-photo'/>" if photo else f"<div class='rr-contact-photo rr-contact-photo-fallback'>{esc(initials)}</div>"
        contacts_html.append(f"""
        <div class='rr-contact-card'>
            <div class='rr-contact-head'>
                {photo_html}
                <div>
                    <div class='rr-contact-name'>{esc(contact.get('name'))}</div>
                    <div class='rr-contact-meta'>{' · '.join(meta) if meta else 'Sem detalhes complementares'}</div>
                    {linkedin_html}
                </div>
            </div>
            <div class='rr-badge-row'>{''.join(badges)}</div>
            <div class='rr-contact-kpi'>{esc(last_contact_line)}</div>
        </div>
        """)

    highlights_html = ''.join([f"<li>{esc(item)}</li>" for item in (narrative.get('highlights') or [])]) or '<li>Sem destaques adicionais.</li>'
    market_context_text = (narrative.get('market_context') or '').strip()
    market_context_html = ''
    if market_context_text:
        market_context_html = f"""
        <div class='rr-market-context'>
          <h3 style='font-size:13px; color:#6b7280; text-transform:uppercase; letter-spacing:.05em; margin:18px 0 6px;'>
            Contexto de Mercado
          </h3>
          <p style='font-size:14px; line-height:1.7; color:#374151;'>
            {esc(market_context_text)}
          </p>
        </div>
        """
    next_steps_html = ''.join([f"<li>{esc(item)}</li>" for item in (narrative.get('next_steps') or [])]) or '<li>Sem próximos passos sugeridos.</li>'
    account_logo = _inline_image_url(account_logo)
    account_logo_html = f"<img src='{esc(account_logo)}' alt='Logo da conta'>" if account_logo else "📊"
    context_badges_html = ''.join([
        f"<span class='rr-context-pill'><strong>Período</strong> {esc(period_label)}</span>",
        f"<span class='rr-context-pill'><strong>Última interação</strong> {esc(latest_text)}</span>",
        f"<span class='rr-context-pill'><strong>Maturidade</strong> {esc(narrative.get('relationship_maturity') or 'Não classificada')}</span>",
        f"<span class='rr-context-pill'><strong>Presença</strong> {esc(account.get('global_presence') or 'Não informada')}</span>"
    ])
    profile_photo = _inline_image_url(profile_photo)
    profile_photo_html = f"<img src='{esc(profile_photo)}' class='rr-user-photo' alt='Foto do usuário'>" if profile_photo else f"<div class='rr-user-photo rr-user-fallback'>{esc(str(profile_name)[:1].upper())}</div>"

    return f"""<!DOCTYPE html>
<html lang='pt-BR'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>Relation Report - {esc(account_name)}</title>
<style>
:root {{ --green:#059669; --green-dark:#065f46; --mint:#d1fae5; --bg:#f6fffb; --text:#1f2937; --muted:#6b7280; --card:#ffffff; --line:#d1fae5; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter,Segoe UI,Arial,sans-serif; background:linear-gradient(180deg,#ecfdf5 0%, #ffffff 38%, #f8fafc 100%); color:var(--text); }}
.rr-shell {{ max-width:1360px; margin:0 auto; padding:32px 28px 60px; }}
.rr-hero {{ background:linear-gradient(135deg,#064e3b 0%, #047857 50%, #10b981 100%); color:#fff; border-radius:28px; padding:28px; box-shadow:0 24px 80px rgba(5,150,105,.22); position:relative; overflow:hidden; }}
.rr-hero:after {{ content:''; position:absolute; inset:auto -80px -80px auto; width:240px; height:240px; background:rgba(255,255,255,.08); border-radius:50%; }}
.rr-top {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:20px; align-items:flex-start; }}
.rr-brand {{ display:flex; gap:16px; align-items:center; min-width:0; }}
.rr-brand-mark {{ min-width:72px; width:auto; height:72px; border-radius:22px; background:rgba(255,255,255,.12); display:flex; align-items:center; justify-content:center; font-size:28px; border:1px solid rgba(255,255,255,.18); backdrop-filter:blur(8px); overflow:hidden; padding:8px 12px; max-width:240px; }}
.rr-brand-mark img {{ max-width:216px; max-height:56px; width:auto; height:auto; object-fit:contain; }}
.rr-title {{ font-size:34px; font-weight:800; line-height:1.05; margin:0 0 8px; }}
.rr-subtitle {{ margin:0; color:rgba(255,255,255,.88); font-size:15px; max-width:760px; line-height:1.6; }}
.rr-user {{ display:flex; gap:14px; align-items:center; justify-self:end; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.18); padding:12px 14px; border-radius:20px; backdrop-filter:blur(8px); min-width:260px; }}
.rr-user-photo {{ width:88px; height:88px; border-radius:50%; object-fit:cover; border:2px solid rgba(255,255,255,.35); background:rgba(255,255,255,.16); }}
.rr-user-fallback {{ display:flex; align-items:center; justify-content:center; color:#fff; font-weight:800; }}
.rr-user-name {{ font-size:16px; font-weight:700; margin:0; }}
.rr-user-role {{ margin:4px 0 0; font-size:12px; color:rgba(255,255,255,.82); }}
.rr-hero-grid {{ display:grid; grid-template-columns:1fr; gap:18px; margin-top:22px; }}
.rr-panel {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.16); border-radius:24px; padding:18px; backdrop-filter:blur(8px); }}
.rr-panel-summary {{ grid-column:1 / -1; }}

.rr-panel h3 {{ margin:0 0 10px; font-size:14px; text-transform:uppercase; letter-spacing:.08em; color:rgba(255,255,255,.98); }}
.rr-kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-top:24px; }}
.rr-kpi {{ background:var(--card); border:1px solid var(--line); border-radius:22px; padding:18px; box-shadow:0 10px 30px rgba(16,185,129,.08); }}
.rr-kpi-label {{ font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; margin-bottom:8px; }}
.rr-kpi-value {{ font-size:28px; font-weight:800; color:var(--green-dark); }}
.rr-grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:22px; margin-top:24px; }}
.rr-section {{ background:rgba(255,255,255,.86); border:1px solid rgba(209,250,229,.9); border-radius:24px; padding:24px; box-shadow:0 18px 55px rgba(15,118,110,.08); }}
.rr-section h2 {{ margin:0 0 14px; font-size:22px; color:var(--green-dark); }}
.rr-lead {{ color:rgba(255,255,255,.96); font-size:15px; line-height:1.75; white-space:pre-line; }}
.rr-context-pills {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; }}
.rr-context-pill {{ display:inline-flex; align-items:center; gap:8px; padding:9px 12px; border-radius:999px; background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.18); color:#f8fafc; font-size:12px; line-height:1.35; }}
.rr-context-pill strong {{ color:#ffffff; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
.rr-info-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
.rr-info-item {{ background:#fff; border:1px solid #ecfdf5; border-radius:14px; padding:10px 12px; }}
.rr-info-item-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
.rr-info-item-value {{ font-size:13px; font-weight:700; color:#111827; }}
.rr-contact-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:start; }}
.rr-contact-card {{ background:#fff; border:1px solid #e5e7eb; border-radius:20px; padding:16px; box-shadow:0 8px 24px rgba(15,23,42,.05); }}
.rr-contact-head {{ display:flex; gap:12px; align-items:center; margin-bottom:12px; }}
.rr-contact-photo {{ width:58px; height:58px; border-radius:18px; object-fit:cover; background:#ecfdf5; }}
.rr-contact-photo-fallback {{ display:flex; align-items:center; justify-content:center; font-weight:800; color:var(--green-dark); font-size:22px; }}
.rr-contact-name {{ font-size:17px; font-weight:800; color:#111827; }}
.rr-contact-meta {{ font-size:13px; color:#6b7280; margin-top:3px; line-height:1.4; }}
.rr-contact-linkedin {{ margin-top:6px; }}
.rr-contact-linkedin a {{ color:#0a66c2; text-decoration:none; font-size:12px; font-weight:600; }}
.rr-contact-linkedin a:hover {{ text-decoration:underline; }}
.rr-badge-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:10px; }}
.rr-badge {{ font-size:11px; font-weight:700; border-radius:999px; padding:6px 10px; display:inline-flex; align-items:center; }}
.rr-badge-primary {{ background:#dcfce7; color:#166534; }}
.rr-badge-soft {{ background:#ecfeff; color:#155e75; }}
.rr-badge-cold {{ background:#eff6ff; color:#1d4ed8; }}
.rr-contact-kpi {{ font-size:13px; color:#4b5563; line-height:1.5; }}
.rr-topic-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
.rr-topic-card {{ border-radius:18px; padding:16px; border:1px solid rgba(255,255,255,.35); min-height:132px; }}
.rr-topic-title {{ font-size:16px; font-weight:800; margin-bottom:10px; color:#0f172a; }}
.rr-topic-text {{ font-size:14px; line-height:1.65; color:#334155; }}
.rr-list {{ padding-left:20px; margin:0; color:#374151; line-height:1.8; }}
.rr-toolbar {{ position:sticky; top:0; z-index:20; backdrop-filter:blur(12px); background:rgba(255,255,255,.74); border-bottom:1px solid rgba(209,250,229,.9); padding:12px 28px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
.rr-toolbar-title {{ font-weight:700; color:var(--green-dark); }}
.rr-toolbar-actions {{ display:flex; gap:10px; flex-wrap:wrap; }}
.rr-btn {{ border:none; border-radius:14px; padding:10px 16px; font-weight:700; cursor:pointer; }}
.rr-btn-primary {{ background:#10b981; color:#fff; }}
.rr-btn-secondary {{ background:#e5e7eb; color:#111827; }}
/* ── FireShot Modal ── */
#rr-fireshot-modal {{
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.45);
  z-index: 9999;
  align-items: center;
  justify-content: center;
}}
#rr-fireshot-modal.active {{
  display: flex;
}}
.rr-fs-box {{
  background: #fff;
  border-radius: 18px;
  padding: 32px 28px 24px;
  max-width: 480px;
  width: 92%;
  box-shadow: 0 24px 64px rgba(4,120,87,0.18);
  border-top: 4px solid #10b981;
}}
.rr-fs-header {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 18px;
}}
.rr-fs-title {{
  font-size: 18px;
  font-weight: 700;
  color: #047857;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.rr-fs-close {{
  background: none;
  border: none;
  font-size: 22px;
  color: #6b7280;
  cursor: pointer;
  line-height: 1;
  padding: 0;
}}
.rr-fs-close:hover {{ color: #1f2937; }}
.rr-fs-steps {{
  list-style: none;
  padding: 0;
  margin: 0 0 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.rr-fs-steps li {{
  display: flex;
  gap: 12px;
  align-items: flex-start;
  font-size: 13.5px;
  color: #1f2937;
  line-height: 1.5;
}}
.rr-fs-step-num {{
  background: #10b981;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
  border-radius: 50%;
  min-width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}}
.rr-fs-note {{
  background: #ecfdf5;
  border: 1px solid #d1fae5;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12.5px;
  color: #047857;
  margin-bottom: 20px;
}}
.rr-fs-actions {{
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}}
.rr-fs-btn-install {{
  background: #10b981;
  color: #fff;
  border: none;
  border-radius: 12px;
  padding: 10px 18px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}}
.rr-fs-btn-install:hover {{ background: #047857; }}
.rr-fs-btn-ok {{
  background: #e5e7eb;
  color: #1f2937;
  border: none;
  border-radius: 12px;
  padding: 10px 18px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}}
.rr-fs-btn-ok:hover {{ background: #d1d5db; }}
@media (max-width: 1024px) {{ .rr-hero-grid,.rr-grid,.rr-kpis,.rr-contact-grid,.rr-topic-grid,.rr-info-list {{ grid-template-columns:1fr; }} }}
@page {{ size: landscape; margin: 12mm 10mm; }}
@media print {{ .rr-toolbar {{ display:none !important; }} html, body {{ background:#fff !important; width:100%; height:auto; margin:0 !important; padding:0 !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }} .rr-shell {{ max-width:none !important; width:100% !important; padding:0 !important; margin:0 !important; }} .rr-hero {{ min-height:auto !important; padding:16px !important; margin-top:0 !important; border-radius:18px !important; overflow:visible !important; }} .rr-hero:after {{ display:none !important; }} .rr-top {{ display:grid !important; grid-template-columns:minmax(0,1fr) 220px !important; gap:14px !important; align-items:start !important; }} .rr-brand {{ gap:12px !important; align-items:flex-start !important; min-width:0 !important; }} .rr-user {{ justify-self:end !important; align-self:start !important; width:220px !important; }} .rr-brand-copy p {{ max-width:none !important; }} .rr-section,.rr-kpi,.rr-panel,.rr-contact-card,.rr-topic-card,.rr-info-item {{ box-shadow:none !important; break-inside:avoid; page-break-inside:avoid; }} .rr-hero {{ break-inside:avoid !important; page-break-inside:avoid !important; }} .rr-grid,.rr-kpis,.rr-contact-grid,.rr-topic-grid,.rr-info-list {{ display:grid !important; }} .rr-kpis {{ grid-template-columns:repeat(4,minmax(0,1fr)) !important; gap:10px !important; margin-top:12px !important; }} .rr-grid {{ grid-template-columns:1.1fr .9fr !important; gap:14px !important; margin-top:16px !important; }} .rr-hero-grid {{ display:block !important; margin-top:10px !important; }} .rr-panel-summary {{ display:block !important; width:100% !important; background:rgba(255,255,255,.14) !important; border:1px solid rgba(255,255,255,.18) !important; padding:14px !important; border-radius:18px !important; margin-top:8px !important; break-inside:avoid !important; page-break-inside:avoid !important; }} .rr-contact-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:12px !important; }} .rr-topic-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:12px !important; }} .rr-info-list {{ grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:10px !important; }} .rr-kpi,.rr-section,.rr-contact-card,.rr-topic-card,.rr-info-item,.rr-panel {{ margin-bottom:10px !important; }} .rr-section {{ padding:16px !important; border-radius:18px !important; }} .rr-contact-card {{ min-height:0 !important; padding:14px !important; }} .rr-topic-card {{ min-height:0 !important; padding:14px !important; }} .rr-kpi {{ padding:14px !important; }} .rr-user-photo {{ width:68px !important; height:68px !important; }} .rr-brand-mark {{ max-width:170px !important; height:52px !important; border-radius:16px !important; }} .rr-brand-mark img {{ max-width:150px !important; max-height:38px !important; }} .rr-title {{ font-size:26px !important; line-height:1.08 !important; margin-bottom:6px !important; }} .rr-subtitle {{ font-size:12px !important; line-height:1.4 !important; margin-top:4px !important; max-width:none !important; }} .rr-panel-summary h3 {{ margin:0 0 10px !important; font-size:16px !important; color:#ffffff !important; }} .rr-lead {{ font-size:12px !important; line-height:1.5 !important; color:#ffffff !important; display:block !important; visibility:visible !important; opacity:1 !important; }} .rr-context-pills {{ gap:8px !important; margin-bottom:10px !important; }} .rr-context-pill {{ padding:6px 9px !important; font-size:10px !important; }} .rr-contact-meta, .rr-muted, .rr-user-role, .rr-info-item-value {{ font-size:10px !important; }} .rr-page-break-before {{ break-before:page; page-break-before:always; }} }}
</style>
</head>
<body>
<div class='rr-toolbar'>
  <div class='rr-toolbar-title'>Relation Report · {esc(account_name)}</div>
  <div class='rr-toolbar-actions'>
    <button class='rr-btn rr-btn-secondary' onclick='window.close()'>✕ Fechar</button>
    <button class='rr-btn rr-btn-primary' onclick='rrShowFireshotModal()'>
      <span style='font-size:15px;'>📷</span> Exportar JPG
    </button>
  </div>
</div>
<div class='rr-shell'>
  <section class='rr-hero'>
    <div class='rr-top'>
      <div class='rr-brand'>
        <div class='rr-brand-mark'>{account_logo_html}</div>
        <div>
          <p style='margin:0 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.14em; color:rgba(255,255,255,.72);'>Toca do Coelho · Executive Relation Report</p>
          <h1 class='rr-title'>{esc(account_name)}</h1>
          <p class='rr-subtitle'>Visão executiva do relacionamento da conta, combinando Power Mapping, histórico de interação, presença operacional, leitura temática e próximos passos recomendados.</p>
        </div>
      </div>
      <div class='rr-user'>{profile_photo_html}
        <div>
          <p class='rr-user-name'>{esc(profile_name)}</p>
          <p class='rr-user-role'>{esc(profile_role)}</p>
          <p class='rr-user-role'>Relatório gerado em {esc(datetime.now().strftime('%d/%m/%Y %H:%M'))}</p>
        </div>
      </div>
    </div>
    <div class='rr-hero-grid'>
      <div class='rr-panel rr-panel-summary'>
        <h3>Resumo executivo</h3>
        <div class='rr-context-pills'>{context_badges_html}</div>
        <div class='rr-lead'>{esc((narrative.get('executive_summary') or 'Sem resumo gerado.').replace('powermapping', 'Power Mapping').replace('Powermapping', 'Power Mapping'))}</div>
        {market_context_html}
      </div>
    </div>
  </section>
  <section class='rr-kpis'>
    <div class='rr-kpi'><div class='rr-kpi-label'>Contatos</div><div class='rr-kpi-value'>{counts.get('contacts', 0)}</div></div>
    <div class='rr-kpi'><div class='rr-kpi-label'>Atividades</div><div class='rr-kpi-value'>{counts.get('activities', 0) + counts.get('account_activities', 0)}</div></div>
    <div class='rr-kpi'><div class='rr-kpi-label'>Kanban</div><div class='rr-kpi-value'>{counts.get('kanban_cards', 0)}</div></div>
    <div class='rr-kpi'><div class='rr-kpi-label'>Mapeamentos</div><div class='rr-kpi-value'>{counts.get('mapping_items', 0)}</div></div>
  </section>
  <section class='rr-grid'>
    <div class='rr-section'>
      <h2>Power Mapping e contatos-chave</h2>
      <div class='rr-contact-grid'>{''.join(contacts_html) or '<div class="rr-contact-card">Nenhum contato encontrado para a conta.</div>'}</div>
    </div>
    <div class='rr-section'>
      <h2>Contexto da conta</h2>
      <div class='rr-info-list'>
        <div class='rr-info-item'><div class='rr-info-item-label'>Setor</div><div class='rr-info-item-value'>{esc(account.get('sector') or 'Não informado')}</div></div>
        <div class='rr-info-item'><div class='rr-info-item-label'>Receita média</div><div class='rr-info-item-value'>{esc(fmt_money(account.get('average_revenue_cents')))}</div></div>
        <div class='rr-info-item'><div class='rr-info-item-label'>Profissionais</div><div class='rr-info-item-value'>{esc(account.get('professionals_count') or 'Não informado')}</div></div>
        <div class='rr-info-item'><div class='rr-info-item-label'>Conta-alvo</div><div class='rr-info-item-value'>{'Sim' if account.get('is_target') else 'Não'}</div></div>
      </div>
      <div style='margin-top:18px;'>
        <h2 style='font-size:18px;'>Destaques</h2>
        <ul class='rr-list'>{highlights_html}</ul>
      </div>
    </div>
  </section>
  <section class='rr-grid'>
    <div class='rr-section'>
      <h2>Leitura temática</h2>
      <div class='rr-topic-grid'>
        {topic_card('IA', '#ecfeff')}
        {topic_card('Cyber', '#f8fafc')}
        {topic_card('Aplicações', '#f0fdf4')}
        {topic_card('Marketing', '#fff7ed')}
        {topic_card('Cloud', '#eff6ff')}
        {topic_card('Outros', '#f9fafb')}
      </div>
    </div>
    <div class='rr-section'>
      <h2>Próximos passos sugeridos</h2>
      <ul class='rr-list'>{next_steps_html}</ul>
    </div>
  </section>
</div>
<div id='rr-fireshot-modal' onclick="if(event.target===this)rrCloseFireshotModal()">
  <div class='rr-fs-box'>
    <div class='rr-fs-header'>
      <div class='rr-fs-title'>
        <span>📷</span> Exportar como JPG
      </div>
      <button class='rr-fs-close' onclick='rrCloseFireshotModal()'>&#215;</button>
    </div>
    <ol class='rr-fs-steps'>
      <li>
        <span class='rr-fs-step-num'>1</span>
        <span>Instale a extensão <strong>FireShot</strong> no Google Chrome (gratuita).</span>
      </li>
      <li>
        <span class='rr-fs-step-num'>2</span>
        <span>Feche este popup e, com o relatório aberto, clique com o botão <strong>direito</strong> em qualquer área da página.</span>
      </li>
      <li>
        <span class='rr-fs-step-num'>3</span>
        <span>No menu de contexto, selecione <strong>"Capturar página inteira"</strong> → <strong>"Salvar como imagem"</strong>.</span>
      </li>
      <li>
        <span class='rr-fs-step-num'>4</span>
        <span>Escolha o formato <strong>JPG</strong> e salve o arquivo.</span>
      </li>
    </ol>
    <div class='rr-fs-note'>
      💡 Se preferir, use o ícone do FireShot na barra de extensões do Chrome e selecione <em>"Capturar página inteira"</em>.
    </div>
    <div class='rr-fs-actions'>
      <a class='rr-fs-btn-install'
         href='https://chrome.google.com/webstore/detail/fireshot/mcbpblocgmgfnpjjppndjkmgjaogfceg'
         target='_blank' rel='noopener'>
        ⬇ Instalar FireShot
      </a>
      <button class='rr-fs-btn-ok' onclick='rrCloseFireshotModal()'>Entendido</button>
    </div>
  </div>
</div>
<script>
function rrShowFireshotModal() {{
  document.getElementById('rr-fireshot-modal').classList.add('active');
}}
function rrCloseFireshotModal() {{
  document.getElementById('rr-fireshot-modal').classList.remove('active');
}}
// Fechar com ESC
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') rrCloseFireshotModal();
}});
</script>
</body>
</html>"""


def _relation_report_render_pdf(report_data):
    global REPORTLAB_AVAILABLE, REPORTLAB_IMPORT_ERROR, colors, TA_LEFT, TA_CENTER, A4, ParagraphStyle, getSampleStyleSheet, mm, ImageReader, stringWidth, Paragraph
    if not REPORTLAB_AVAILABLE:
        try:
            from reportlab.lib import colors as _colors
            from reportlab.lib.enums import TA_LEFT as _TA_LEFT, TA_CENTER as _TA_CENTER
            from reportlab.lib.pagesizes import A4 as _A4
            from reportlab.lib.styles import ParagraphStyle as _ParagraphStyle, getSampleStyleSheet as _getSampleStyleSheet
            from reportlab.lib.units import mm as _mm
            from reportlab.lib.utils import ImageReader as _ImageReader
            from reportlab.pdfbase.pdfmetrics import stringWidth as _stringWidth
            from reportlab.platypus import Paragraph as _Paragraph
            colors = _colors
            TA_LEFT = _TA_LEFT
            TA_CENTER = _TA_CENTER
            A4 = _A4
            ParagraphStyle = _ParagraphStyle
            getSampleStyleSheet = _getSampleStyleSheet
            mm = _mm
            ImageReader = _ImageReader
            stringWidth = _stringWidth
            Paragraph = _Paragraph
            REPORTLAB_AVAILABLE = True
            REPORTLAB_IMPORT_ERROR = None
        except Exception as e:
            REPORTLAB_IMPORT_ERROR = e
            raise RuntimeError(f'ReportLab não está disponível para gerar o PDF. Detalhe: {e}')

    from reportlab.pdfgen import canvas
    colors_map = _relation_report_pick_system_colors()
    buffer = BytesIO()
    page_width, page_height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle('RelationBody', parent=styles['BodyText'], fontName='Helvetica', fontSize=9.5, leading=13, textColor=colors.HexColor('#1f2937'))
    small_style = ParagraphStyle('RelationSmall', parent=body_style, fontSize=8.5, leading=11.5)

    def new_page():
        c.showPage()
        _relation_report_draw_header(c, report_data, colors_map, page_width, page_height)
        return page_height - 52 * mm

    def ensure_space(y, needed):
        return new_page() if y - needed < 18 * mm else y

    _relation_report_draw_header(c, report_data, colors_map, page_width, page_height)
    y = page_height - 52 * mm

    account = report_data['account']
    latest = report_data.get('latest_interaction') or {}
    counts = report_data.get('summary_counts') or {}
    narrative = report_data.get('narrative') or _relation_report_generate_narrative(report_data)

    cards = [
        ('Contatos', str(counts.get('contacts', 0))),
        ('Atividades', str(counts.get('activities', 0) + counts.get('account_activities', 0))),
        ('Kanban', str(counts.get('kanban_cards', 0))),
        ('Mapeamentos', str(counts.get('mapping_items', 0))),
    ]
    x_positions = [18 * mm, 67 * mm, 116 * mm, 165 * mm]
    for idx, (label, value) in enumerate(cards):
        c.setFillColor(colors.white)
        c.setStrokeColor(colors_map['accent'])
        c.roundRect(x_positions[idx], y - 16 * mm, 42 * mm, 14 * mm, 4 * mm, fill=1, stroke=1)
        c.setFillColor(colors_map['secondary'])
        c.setFont('Helvetica-Bold', 14)
        c.drawCentredString(x_positions[idx] + 21 * mm, y - 8 * mm, value)
        c.setFont('Helvetica', 8.5)
        c.drawCentredString(x_positions[idx] + 21 * mm, y - 12 * mm, label)
    y -= 22 * mm

    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Visão geral da conta')
    y -= 5 * mm
    c.setStrokeColor(colors.HexColor('#d1d5db'))
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 6 * mm

    general_lines = [
        f"Setor: {account.get('sector') or 'Não informado'}",
        f"Receita média: {format_currency_br(account.get('average_revenue_cents'))}",
        f"Profissionais: {account.get('professionals_count') or 'Não informado'}",
        f"Presença global: {account.get('global_presence') or 'Não informado'}",
        f"Última interação: {_relation_report_format_dt(latest.get('date'))}",
        f"Com quem: {latest.get('person') or 'Não identificado'}"
    ]
    for idx, line in enumerate(general_lines):
        col = 18 * mm if idx < 3 else 110 * mm
        row_y = y - (idx % 3) * 6 * mm
        c.setFillColor(colors.HexColor('#111827'))
        c.setFont('Helvetica', 9.2)
        c.drawString(col, row_y, line)
    y -= 22 * mm

    y = ensure_space(y, 40 * mm)
    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Resumo executivo do relacionamento')
    y -= 4 * mm
    c.setStrokeColor(colors_map['accent'])
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 5 * mm
    y = _relation_report_draw_paragraph(c, narrative.get('executive_summary') or 'Sem resumo disponível.', 18 * mm, y, page_width - 36 * mm, body_style)
    y -= 6 * mm

    if narrative.get('highlights'):
        y = ensure_space(y, 24 * mm)
        c.setFillColor(colors.HexColor('#ecfdf5'))
        c.roundRect(18 * mm, y - 18 * mm, page_width - 36 * mm, 16 * mm, 4 * mm, fill=1, stroke=0)
        c.setFillColor(colors_map['secondary'])
        c.setFont('Helvetica-Bold', 9.5)
        c.drawString(22 * mm, y - 6 * mm, 'Destaques')
        c.setFillColor(colors.HexColor('#065f46'))
        c.setFont('Helvetica', 8.5)
        for i, item in enumerate(narrative['highlights'][:3]):
            c.drawString(22 * mm, y - (10 + i * 4) * mm, f'• {item[:120]}')
        y -= 22 * mm

    y = ensure_space(y, 52 * mm)
    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Powermapping da conta')
    y -= 4 * mm
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 6 * mm
    for rel in report_data['relationship_cards'][:18]:
        y = ensure_space(y, 22 * mm)
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor('#d1d5db'))
        c.roundRect(18 * mm, y - 17 * mm, page_width - 36 * mm, 15 * mm, 4 * mm, fill=1, stroke=1)
        contact = rel['contact']
        c.setFillColor(colors.HexColor('#111827'))
        c.setFont('Helvetica-Bold', 10)
        c.drawString(22 * mm, y - 6 * mm, f"{contact.get('name') or 'Contato'} — {contact.get('position') or 'Cargo não informado'}")
        c.setFont('Helvetica', 8.3)
        c.setFillColor(colors.HexColor('#4b5563'))
        linkedin_value = str(contact.get('linkedin') or '').strip() or 'Não informado'
        c.drawString(22 * mm, y - 10 * mm, f"Área: {contact.get('area_of_activity') or 'Não informada'} | Email: {contact.get('email') or 'Não informado'}")
        c.drawString(22 * mm, y - 12.5 * mm, f"LinkedIn: {linkedin_value[:95]}")
        c.drawString(22 * mm, y - 15 * mm, f"Cards: atividades {rel.get('activities_count',0)} | mapeamento {rel.get('mapping_count',0)} | kanban {rel.get('kanban_count',0)} | último contato {_relation_report_format_dt((rel.get('last_contact') or {}).get('date'))}")
        y -= 20 * mm

    y = ensure_space(y, 45 * mm)
    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Entregas, presenças e Kanban')
    y -= 4 * mm
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 5 * mm
    for presence in report_data['presences'][:8]:
        y = ensure_space(y, 9 * mm)
        txt = f"• {presence.get('delivery_name')} | owner {presence.get('stf_owner') or 'N/I'} | receita {format_currency_br(presence.get('current_revenue_cents'))} | validade {presence.get('validity_month') or 'N/I'} | focal {presence.get('focal_client_name') or 'N/I'}"
        y = _relation_report_draw_paragraph(c, txt, 18 * mm, y, page_width - 36 * mm, small_style) - 2 * mm
    if not report_data['presences']:
        y = _relation_report_draw_paragraph(c, 'Nenhuma presença/entrega mapeada para esta conta.', 18 * mm, y, page_width - 36 * mm, small_style) - 2 * mm
    y -= 2 * mm
    y = _relation_report_draw_paragraph(c, f"Kanban mapeado: {len(report_data['kanban_cards'])} card(s).", 18 * mm, y, page_width - 36 * mm, body_style) - 3 * mm
    for card in report_data['kanban_cards'][:10]:
        y = ensure_space(y, 8 * mm)
        txt = f"• [{card.get('column_title') or 'Sem coluna'}] {card.get('title')} — contato: {card.get('contact_name') or 'N/I'} — urgência: {card.get('urgency') or 'N/I'}"
        y = _relation_report_draw_paragraph(c, txt, 22 * mm, y, page_width - 40 * mm, small_style) - 1 * mm

    y = ensure_space(y, 55 * mm)
    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Quebra resumida por tópico')
    y -= 4 * mm
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 6 * mm
    for topic in ['IA', 'Cyber', 'Aplicações', 'Marketing', 'Cloud', 'Outros']:
        y = ensure_space(y, 15 * mm)
        c.setFillColor(colors.HexColor('#ecfeff') if topic in ('IA', 'Cloud') else colors.HexColor('#f9fafb'))
        c.roundRect(18 * mm, y - 12 * mm, page_width - 36 * mm, 10 * mm, 3 * mm, fill=1, stroke=0)
        c.setFillColor(colors_map['secondary'])
        c.setFont('Helvetica-Bold', 9.5)
        c.drawString(21 * mm, y - 6 * mm, topic)
        c.setFillColor(colors.HexColor('#374151'))
        topic_text = (narrative.get('topic_breakdown') or {}).get(topic) or f"Sem evidências relevantes para {topic.lower()}."
        y = _relation_report_draw_paragraph(c, topic_text, 42 * mm, y - 2 * mm, page_width - 60 * mm, small_style) - 4 * mm

    y = ensure_space(y, 30 * mm)
    c.setFillColor(colors_map['secondary'])
    c.setFont('Helvetica-Bold', 12)
    c.drawString(18 * mm, y, 'Próximos passos sugeridos')
    y -= 4 * mm
    c.line(18 * mm, y, page_width - 18 * mm, y)
    y -= 6 * mm
    for item in narrative.get('next_steps') or []:
        y = ensure_space(y, 8 * mm)
        y = _relation_report_draw_paragraph(c, f"• {item}", 18 * mm, y, page_width - 36 * mm, body_style) - 2 * mm

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#6b7280'))
    c.drawRightString(page_width - 18 * mm, 12 * mm, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    c.save()
    buffer.seek(0)
    return buffer


@app.route('/api/report/relation', methods=['GET'])
def export_relation_report():
    try:
        account_id_raw = (request.args.get('account_id') or '').strip()
        if not account_id_raw.isdigit():
            return jsonify({'error': 'account_id é obrigatório'}), 400
        account_id = int(account_id_raw)
        full_period = (request.args.get('full_period', 'false') or 'false').lower() == 'true'
        start_date = (request.args.get('start_date') or '').strip() or None
        end_date = (request.args.get('end_date') or '').strip() or None
        if not full_period and (not start_date or not end_date):
            return jsonify({'error': 'Informe start_date e end_date ou marque full_period=true'}), 400
        if full_period:
            start_date = None
            end_date = None
        report_data = _relation_report_collect_data(account_id, start_date=start_date, end_date=end_date)
        if not report_data:
            return jsonify({'error': 'Conta não encontrada'}), 404
        pdf_buffer = _relation_report_render_pdf(report_data)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '-', (report_data['account'].get('name') or 'cliente').strip()).strip('-').lower() or 'cliente'
        file_name = f'relation-report-{safe_name}-{datetime.now().strftime("%Y%m%d-%H%M%S")}.pdf'
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=file_name
        )
    except Exception as e:
        logger.exception(f'[RelationReport] Falha ao gerar relatório: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/report/relation/view', methods=['GET'])
def view_relation_report_browser():
    try:
        account_id_raw = (request.args.get('account_id') or '').strip()
        if not account_id_raw.isdigit():
            return 'account_id é obrigatório', 400
        account_id = int(account_id_raw)
        full_period = (request.args.get('full_period', 'false') or 'false').lower() == 'true'
        start_date = (request.args.get('start_date') or '').strip() or None
        end_date = (request.args.get('end_date') or '').strip() or None
        if full_period:
            start_date = None
            end_date = None
        report_data = _relation_report_collect_data(account_id, start_date=start_date, end_date=end_date)
        if not report_data:
            return 'Conta não encontrada', 404
        report_data['narrative'] = _relation_report_generate_narrative(report_data)
        profile_response = get_profile_config()
        profile = profile_response.get_json(silent=True) if hasattr(profile_response, 'get_json') else {}
        html_doc = _relation_report_build_browser_html(report_data, profile=profile or {}, embed_images=True)
        return Response(html_doc, mimetype='text/html; charset=utf-8')
    except Exception as e:
        logger.exception(f'[RelationReport] Falha ao montar visualização HTML: {e}')
        return f'<h1>Erro ao gerar relatório</h1><pre>{html.escape(str(e))}</pre>', 500


@app.route('/report/relation/export-html', methods=['GET'])
def export_relation_report_html():
    try:
        account_id_raw = (request.args.get('account_id') or '').strip()
        if not account_id_raw.isdigit():
            return 'account_id é obrigatório', 400
        account_id = int(account_id_raw)
        full_period = (request.args.get('full_period', 'false') or 'false').lower() == 'true'
        start_date = (request.args.get('start_date') or '').strip() or None
        end_date = (request.args.get('end_date') or '').strip() or None
        if full_period:
            start_date = None
            end_date = None
        report_data = _relation_report_collect_data(account_id, start_date=start_date, end_date=end_date)
        if not report_data:
            return 'Conta não encontrada', 404
        report_data['narrative'] = _relation_report_generate_narrative(report_data)
        profile_response = get_profile_config()
        profile = profile_response.get_json(silent=True) if hasattr(profile_response, 'get_json') else {}
        html_doc = _relation_report_build_browser_html(report_data, profile=profile or {}, embed_images=True)
        account_name = (report_data.get('account') or {}).get('name') or f'account-{account_id}'
        safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '-', account_name.strip()).strip('-').lower() or f'account-{account_id}'
        response = Response(html_doc, mimetype='text/html; charset=utf-8')
        response.headers['Content-Disposition'] = f'attachment; filename=relation-report-{safe_name}.html'
        return response
    except Exception as e:
        logger.exception(f'[RelationReport] Falha ao exportar HTML: {e}')
        return f'<h1>Erro ao exportar relatório</h1><pre>{html.escape(str(e))}</pre>', 500


@app.route('/api/report/relation/preview', methods=['GET'])
def preview_relation_report_data():
    try:
        account_id_raw = (request.args.get('account_id') or '').strip()
        if not account_id_raw.isdigit():
            return jsonify({'error': 'account_id é obrigatório'}), 400
        account_id = int(account_id_raw)
        full_period = (request.args.get('full_period', 'false') or 'false').lower() == 'true'
        start_date = (request.args.get('start_date') or '').strip() or None
        end_date = (request.args.get('end_date') or '').strip() or None
        if full_period:
            start_date = None
            end_date = None
        report_data = _relation_report_collect_data(account_id, start_date=start_date, end_date=end_date)
        if not report_data:
            return jsonify({'error': 'Conta não encontrada'}), 404
        narrative = _relation_report_generate_narrative(report_data)
        return jsonify({
            'account': report_data['account'],
            'summary_counts': report_data['summary_counts'],
            'latest_interaction': report_data['latest_interaction'],
            'relationship_cards': report_data['relationship_cards'][:12],
            'topics': {k: len(v) for k, v in report_data['topics'].items()},
            'highlights': narrative.get('highlights') or [],
            'narrative': narrative,
            'period': {
                'full_period': report_data['full_period'],
                'start_date': report_data['start_date'],
                'end_date': report_data['end_date']
            }
        })
    except Exception as e:
        logger.exception(f'[RelationReport] Falha ao gerar preview: {e}')
        return jsonify({'error': str(e)}), 500


ITOCA_EXCLUDED_TABLES = {
    'sqlite_sequence',
    'app_settings',
    'itoca_chat_history',
    'automapping_runs',
    'status_rules',
    'job_groupings',
    'job_grouping_positions',
}


# Mapa de sinônimos para expansão semântica nas buscas do RAG
_ITOCA_SYNONYMS = {
    'cnpj': ['cnpj', 'cadastro nacional', 'pessoa juridica', 'registro empresa', 'inscricao federal'],
    'cpf': ['cpf', 'cadastro pessoa fisica', 'registro pessoa'],
    'email': ['email', 'e-mail', 'correio eletronico', 'contato'],
    'telefone': ['telefone', 'celular', 'fone', 'contato', 'whatsapp'],
    'agenda': ['agenda', 'compromisso', 'reuniao', 'evento', 'encontro', 'meeting'],
    'reuniao': ['reuniao', 'meeting', 'encontro', 'compromisso', 'agenda'],
    'evento': ['evento', 'compromisso', 'reuniao', 'agenda', 'encontro'],
    'proxima': ['proxima', 'proximo', 'futuro', 'upcoming', 'semana'],
    'semana': ['semana', 'week', 'proximos dias', 'agenda'],
    'contato': ['contato', 'cliente', 'pessoa', 'lead'],
    'empresa': ['empresa', 'companhia', 'organizacao', 'account', 'conta'],
    'wiki': ['wiki', 'documento', 'conhecimento', 'wikitoca'],
    'documento': ['documento', 'arquivo', 'pdf', 'doc', 'wiki'],
    'atividade': ['atividade', 'activity', 'interacao', 'historico'],
    'contas': ['contas', 'conta', 'empresa', 'account', 'accounts', 'clientes', 'relacionamento'],
    'conta': ['conta', 'contas', 'empresa', 'account', 'accounts'],
    'clientes': ['clientes', 'cliente', 'contatos', 'contato', 'leads', 'prospects', 'contas'],
    'cliente': ['cliente', 'clientes', 'contato', 'lead', 'prospect'],
    'relacionamento': ['relacionamento', 'relacao', 'historico', 'atividade', 'interacao', 'contas', 'clientes'],
    'pipeline': ['pipeline', 'kanban', 'funil', 'oportunidade', 'negociacao'],
    'resumo': ['resumo', 'status', 'situacao', 'overview', 'panorama', 'visao geral'],
    'status': ['status', 'situacao', 'resumo', 'estado', 'andamento'],
}

def _itoca_tokenize(question):
    base_tokens = [
        token for token in re.findall(r'[a-zA-ZÀ-ÿ0-9_-]{3,}', (question or '').lower())
        if token not in {'para', 'com', 'sem', 'sobre', 'como', 'qual', 'quais', 'onde', 'quando', 'que', 'uma', 'uns', 'das', 'dos', 'nos', 'nas', 'por', 'foi', 'sao', 'tem', 'ter'}
    ]
    # Expande com sinônimos semânticos
    expanded = list(base_tokens)
    for token in base_tokens:
        if token in _ITOCA_SYNONYMS:
            for syn in _ITOCA_SYNONYMS[token]:
                if syn not in expanded:
                    expanded.append(syn)
    return expanded[:20]  # limita para não explodir a query SQL


def _itoca_text_columns(cursor, table_name):
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    columns = []
    for row in cursor.fetchall():
        column_name = row['name']
        column_type = (row['type'] or '').upper()
        if any(t in column_type for t in ['CHAR', 'TEXT', 'CLOB']) or column_type == '':
            columns.append(column_name)
    return columns


def _itoca_build_snippet(row_dict):
    # Campos de baixa relevância semântica que não devem aparecer no snippet genérico
    _SKIP_KEYS = {'id', 'created_at', 'updated_at', 'logo_url', 'photo_url', 'file_url',
                  'file_name', 'file_size', 'display_order', 'is_system', 'is_locked',
                  'completed', 'completed_at',
                  'account_id', 'client_id', 'card_id', 'column_id', 'presence_id',
                  'activity_id', 'grouping_id', 'focal_client_id', 'contact_id', 'target_id'}
    # Campos de data que devem ser formatados
    _DATE_KEYS = {'activity_date', 'due_date', 'validity_month'}
    parts = []
    # Traduz flags booleanas para rótulos semânticos legíveis pelo LLM
    if row_dict.get('is_target'):
        parts.append('classificacao: conta-alvo (target)')
    if row_dict.get('is_cold_contact'):
        parts.append('classificacao: cold contact')
    for key, value in row_dict.items():
        if key in _SKIP_KEYS:
            continue
        if key in ('is_target', 'is_cold_contact'):
            continue  # já tratados acima
            continue
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        # Formata datas para o padrão brasileiro
        if key in _DATE_KEYS:
            try:
                dt = datetime.strptime(text[:10], '%Y-%m-%d')
                text = dt.strftime('%d/%m/%Y')
            except Exception:
                pass
        # Trunca campos muito longos
        if len(text) > 500:
            text = text[:500] + '...'
        parts.append(f'{key}: {text}')
        if len(parts) >= 8:
            break
    return ' | '.join(parts)


def _itoca_search_context(question, limit=18):
    tokens = _itoca_tokenize(question)
    if not tokens:
        return []
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row['name'] for row in cursor.fetchall() if row['name'] not in ITOCA_EXCLUDED_TABLES]
    results = []
    seen = set()
    like_values = [f'%{token}%' for token in tokens[:6]]
    _generic_limit_reached = False
    for table in tables:
        if _generic_limit_reached:
            break
        text_columns = _itoca_text_columns(cursor, table)
        if not text_columns:
            continue
        search_clauses = []
        params = []
        for col in text_columns[:8]:
            for like_value in like_values:
                search_clauses.append(f'LOWER(COALESCE("{col}", "")) LIKE ?')
                params.append(like_value)
        if not search_clauses:
            continue
        sql = f'SELECT * FROM "{table}" WHERE ' + ' OR '.join(search_clauses) + ' LIMIT 6'
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        except Exception:
            continue
        for row in rows:
            row_dict = dict_from_row(row)
            # Enriquece o row_dict resolvendo FKs para nomes legíveis antes de gerar o snippet
            row_dict = _itoca_enrich_snippet_with_joins(cursor, table, row_dict)
            snippet = _itoca_build_snippet(row_dict)
            if not snippet:
                continue
            fingerprint = f"{table}:{snippet[:160]}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            results.append({
                'table': table,
                'id': row_dict.get('id'),
                'snippet': snippet,
                'search_text': snippet.lower()
            })
            if len(results) >= limit:
                _generic_limit_reached = True
                break  # Quebra o for row; a flag quebra o for table na próxima iteração.
                       # As buscas especializadas de wiki, agenda, accounts continuam abaixo.

    # Busca especializada de accounts/clients quando a pergunta menciona contas, clientes, relacionamento ou resumo
    account_client_keywords = {'contas', 'conta', 'clientes', 'cliente', 'relacionamento', 'relacao', 'resumo', 'status', 'pipeline', 'accounts', 'account'}
    is_account_query = any(t in account_client_keywords for t in tokens[:10])
    if is_account_query and len(results) < limit:
        try:
            # Busca accounts com última atividade, is_target e contagem de serviços
            cursor.execute('''
                SELECT ac.id, ac.name, ac.sector, ac.description, ac.is_target,
                       MAX(act.activity_date) as last_activity,
                       COUNT(DISTINCT act.id) as total_activities,
                       COUNT(DISTINCT ap.id) as total_services
                FROM accounts ac
                LEFT JOIN activities act ON act.account_id = ac.id
                LEFT JOIN account_presences ap ON ap.account_id = ac.id
                GROUP BY ac.id
                ORDER BY ac.is_target DESC, last_activity DESC NULLS LAST
                LIMIT 30
            ''')
            for row in cursor.fetchall():
                rd = dict_from_row(row)
                parts = []
                if rd.get('is_target'):
                    parts.append('classificacao: conta-alvo (target)')
                if rd.get('name'):
                    parts.append(f'empresa: {rd["name"]}')
                if rd.get('sector'):
                    parts.append(f'setor: {rd["sector"]}')
                if rd.get('description'):
                    parts.append(f'descricao: {rd["description"][:200]}')
                if rd.get('last_activity'):
                    try:
                        dt = datetime.strptime(rd['last_activity'][:10], '%Y-%m-%d')
                        parts.append(f'ultimo_contato: {dt.strftime("%d/%m/%Y")}')
                    except Exception:
                        parts.append(f'ultimo_contato: {rd["last_activity"]}')
                if rd.get('total_activities'):
                    parts.append(f'total_interacoes: {rd["total_activities"]}')
                if rd.get('total_services'):
                    parts.append(f'servicos_stefanini_cadastrados: {rd["total_services"]}')
                snippet = ' | '.join(parts)
                if not snippet:
                    continue
                fp = f'accounts:{snippet[:160]}'
                if fp in seen:
                    continue
                seen.add(fp)
                results.append({'table': 'accounts', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
        except Exception as e:
            logger.warning(f'[iToca] Erro ao buscar accounts para query de contas: {e}')

        try:
            # Busca clients com última atividade, is_target e is_cold_contact
            cursor.execute('''
                SELECT cl.id, cl.name, cl.company, cl.position, cl.email,
                       cl.last_activity_date, cl.is_target, cl.is_cold_contact,
                       COUNT(act.id) as total_activities
                FROM clients cl
                LEFT JOIN activities act ON act.client_id = cl.id
                GROUP BY cl.id
                ORDER BY cl.is_target DESC, cl.last_activity_date DESC NULLS LAST
                LIMIT 25
            ''')
            for row in cursor.fetchall():
                rd = dict_from_row(row)
                parts = []
                if rd.get('is_target'):
                    parts.append('classificacao: contato-alvo (target)')
                if rd.get('is_cold_contact'):
                    parts.append('classificacao: cold contact')
                if rd.get('name'):
                    parts.append(f'contato: {rd["name"]}')
                if rd.get('company'):
                    parts.append(f'empresa: {rd["company"]}')
                if rd.get('position'):
                    parts.append(f'cargo: {rd["position"]}')
                if rd.get('email'):
                    parts.append(f'email: {rd["email"]}')
                if rd.get('last_activity_date'):
                    try:
                        dt = datetime.strptime(rd['last_activity_date'][:10], '%Y-%m-%d')
                        parts.append(f'ultimo_contato: {dt.strftime("%d/%m/%Y")}')
                    except Exception:
                        parts.append(f'ultimo_contato: {rd["last_activity_date"]}')
                if rd.get('total_activities'):
                    parts.append(f'total_interacoes: {rd["total_activities"]}')
                snippet = ' | '.join(parts)
                if not snippet:
                    continue
                fp = f'clients:{snippet[:160]}'
                if fp in seen:
                    continue
                seen.add(fp)
                results.append({'table': 'clients', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
        except Exception as e:
            logger.warning(f'[iToca] Erro ao buscar clients para query de contas: {e}')

    # Busca dedicada na agenda (commitments + account_renewal_events)
    try:
        agenda_tokens = tokens[:8]
        # Sempre inclui eventos futuros quando a pergunta menciona agenda/evento/semana/próximo
        agenda_keywords = {'agenda', 'compromisso', 'reuniao', 'evento', 'encontro', 'meeting', 'semana', 'proxima', 'proximo', 'futuro', 'upcoming', 'proximos'}
        is_agenda_query = any(t in agenda_keywords for t in agenda_tokens)
        if is_agenda_query:
            # Retorna todos os eventos futuros (próximos 90 dias)
            future_limit = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT cm.id, cm.title, cm.notes, cm.due_date, cm.due_time,
                       cl.name as client_name, cl.company as client_company
                FROM commitments cm
                LEFT JOIN clients cl ON cm.client_id = cl.id
                WHERE DATE(cm.due_date) >= ?
                ORDER BY cm.due_date ASC
                LIMIT 20
            ''', (today_str,))
            for row in cursor.fetchall():
                rd = dict_from_row(row)
                parts = []
                if rd.get('title'):
                    parts.append(f'titulo: {rd["title"]}')
                if rd.get('due_date'):
                    try:
                        dt = datetime.strptime(rd['due_date'][:10], '%Y-%m-%d')
                        parts.append(f'data: {dt.strftime("%d/%m/%Y")}')
                    except Exception:
                        parts.append(f'data: {rd["due_date"]}')
                if rd.get('due_time'):
                    parts.append(f'hora: {rd["due_time"]}')
                if rd.get('client_name'):
                    parts.append(f'contato: {rd["client_name"]}')
                if rd.get('client_company'):
                    parts.append(f'empresa: {rd["client_company"]}')
                if rd.get('notes') and rd['notes'] != rd.get('title'):
                    parts.append(f'notas: {rd["notes"][:200]}')
                snippet = ' | '.join(parts)
                if not snippet:
                    continue
                fp = f'commitments:{snippet[:160]}'
                if fp in seen:
                    continue
                seen.add(fp)
                results.append({'table': 'commitments', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
        else:
            # Busca por tokens no título/notas dos compromissos
            if agenda_tokens:
                like_clauses_a = ' OR '.join(['LOWER(cm.title) LIKE ? OR LOWER(cm.notes) LIKE ?' for _ in agenda_tokens[:4]])
                params_a = []
                for t in agenda_tokens[:4]:
                    params_a += [f'%{t}%', f'%{t}%']
                cursor.execute(f'''
                    SELECT cm.id, cm.title, cm.notes, cm.due_date, cm.due_time,
                           cl.name as client_name, cl.company as client_company
                    FROM commitments cm
                    LEFT JOIN clients cl ON cm.client_id = cl.id
                    WHERE {like_clauses_a}
                    ORDER BY cm.due_date ASC LIMIT 6
                ''', params_a)
                for row in cursor.fetchall():
                    rd = dict_from_row(row)
                    parts = []
                    if rd.get('title'):
                        parts.append(f'titulo: {rd["title"]}')
                    if rd.get('due_date'):
                        try:
                            dt = datetime.strptime(rd['due_date'][:10], '%Y-%m-%d')
                            parts.append(f'data: {dt.strftime("%d/%m/%Y")}')
                        except Exception:
                            parts.append(f'data: {rd["due_date"]}')
                    if rd.get('due_time'):
                        parts.append(f'hora: {rd["due_time"]}')
                    if rd.get('client_name'):
                        parts.append(f'contato: {rd["client_name"]}')
                    snippet = ' | '.join(parts)
                    if not snippet:
                        continue
                    fp = f'commitments:{snippet[:160]}'
                    if fp in seen:
                        continue
                    seen.add(fp)
                    results.append({'table': 'commitments', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao buscar agenda: {e}')

    # Busca adicional em wiki_entries (conteúdo completo)
    try:
        like_clauses = ' OR '.join(['LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(tags) LIKE ?' for _ in tokens[:6]])
        params_wiki = []
        for t in tokens[:6]:
            params_wiki += [f'%{t}%', f'%{t}%', f'%{t}%']
        cursor.execute(f'SELECT id, title, category, content, tags FROM wiki_entries WHERE {like_clauses} LIMIT 6', params_wiki)
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('category'):
                parts.append(f'categoria: {rd["category"]}')
            if rd.get('content'):
                parts.append(f'conteudo: {rd["content"][:1500]}')
            snippet = ' | '.join(parts)
            if not snippet:
                continue
            fp = f'wiki_entries:{snippet[:160]}'
            if fp in seen:
                continue
            seen.add(fp)
            results.append({'table': 'wiki_entries', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao buscar wiki_entries: {e}')

    # Busca adicional em wiki_documents (metadados + busca no texto extraído do arquivo)
    try:
        # Busca por título/nome do arquivo
        like_clauses_d = ' OR '.join(['LOWER(title) LIKE ? OR LOWER(original_name) LIKE ?' for _ in tokens[:6]])
        params_docs = []
        for t in tokens[:6]:
            params_docs += [f'%{t}%', f'%{t}%']
        cursor.execute(f'SELECT id, title, original_name, file_name, file_ext FROM wiki_documents WHERE {like_clauses_d} LIMIT 4', params_docs)
        doc_rows_by_title = {row['id']: dict_from_row(row) for row in cursor.fetchall()}

        # Busca também em TODOS os documentos pelo conteúdo extraído (para termos como CNPJ que não estão no título)
        cursor.execute('SELECT id, title, original_name, file_name, file_ext FROM wiki_documents LIMIT 20')
        all_doc_rows = {row['id']: dict_from_row(row) for row in cursor.fetchall()}
        # Mescla: prioriza os encontrados por título, depois verifica os demais pelo conteúdo
        candidate_docs = {**all_doc_rows, **doc_rows_by_title}  # doc_rows_by_title sobrescreve

        for doc_id, rd in candidate_docs.items():
            file_path = WIKI_UPLOAD_DIR / (rd.get('file_name') or '')
            doc_text = ''
            if file_path.exists():
                doc_text = _itoca_extract_text_from_file(str(file_path))
            # Verifica se algum token aparece no conteúdo extraído
            doc_text_lower = doc_text.lower()
            found_in_content = any(t in doc_text_lower for t in tokens[:10])
            found_by_title = doc_id in doc_rows_by_title
            if not found_in_content and not found_by_title:
                continue
            doc_title = rd.get('title') or rd.get('original_name', '')
            doc_ext = rd.get('file_ext', '')
            if doc_text.strip():
                snippet = f'[WikiToca Doc] titulo: {doc_title} | tipo: {doc_ext} | conteudo: {doc_text[:3000]}'
            else:
                snippet = (f'[WikiToca Doc] titulo: {doc_title} | tipo: {doc_ext} | '
                           f'CONFIRMADO: o documento "{rd.get("original_name", "")}" EXISTE no WikiToca. '
                           f'Conteúdo interno não disponível para leitura automática (biblioteca de extração não instalada). '
                           f'Ao responder, informe que o documento existe mas não é possível detalhar o conteúdo.')
            fp = f'wiki_documents:{snippet[:160]}'
            if fp in seen:
                continue
            seen.add(fp)
            results.append({'table': 'wiki_documents', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao buscar wiki_documents: {e}')

    conn.close()
    return results


def _itoca_enrich_snippet_with_joins(cursor, table, row_dict):
    """Enriquece um row_dict de busca ao vivo resolvendo FKs para nomes legíveis.
    Isso garante que qualquer tabela retornada pela busca genérica (SELECT *)
    nunca exponha IDs brutos ao LLM quando o nome correspondente está disponível.
    Aplica-se a qualquer tabela que contenha client_id, account_id, contact_id,
    column_id, card_id, grouping_id, etc.
    """
    enriched = dict(row_dict)  # cópia para não mutar o original

    # Resolve client_id / contact_id / focal_client_id -> nome do contato e empresa
    for fk_field in ('client_id', 'contact_id', 'focal_client_id'):
        fk_val = enriched.get(fk_field)
        if fk_val and not enriched.get('client_name') and not enriched.get('contact_name'):
            try:
                cursor.execute('SELECT name, company, position FROM clients WHERE id = ? LIMIT 1', (fk_val,))
                r = cursor.fetchone()
                if r:
                    rd_cl = dict_from_row(r)
                    if rd_cl.get('name'):
                        enriched['nome_contato'] = rd_cl['name']
                    if rd_cl.get('company'):
                        enriched['empresa'] = rd_cl['company']
                    if rd_cl.get('position'):
                        enriched['cargo'] = rd_cl['position']
            except Exception:
                pass
        # Remove o campo de FK bruto para não aparecer no snippet
        enriched.pop(fk_field, None)

    # Resolve account_id -> nome da conta
    acct_id = enriched.get('account_id')
    if acct_id and not enriched.get('account_name') and not enriched.get('nome_conta'):
        try:
            cursor.execute('SELECT name, sector FROM accounts WHERE id = ? LIMIT 1', (acct_id,))
            r = cursor.fetchone()
            if r:
                rd_ac = dict_from_row(r)
                if rd_ac.get('name'):
                    enriched['nome_conta'] = rd_ac['name']
                if rd_ac.get('sector'):
                    enriched['setor'] = rd_ac['sector']
        except Exception:
            pass
    enriched.pop('account_id', None)

    # Resolve column_id -> título da coluna do Kanban
    col_id = enriched.get('column_id')
    if col_id and not enriched.get('column_title') and not enriched.get('coluna'):
        try:
            cursor.execute('SELECT title FROM kanban_columns WHERE id = ? LIMIT 1', (col_id,))
            r = cursor.fetchone()
            if r:
                rd_col = dict_from_row(r)
                if rd_col.get('title'):
                    enriched['coluna_kanban'] = rd_col['title']
        except Exception:
            pass
    enriched.pop('column_id', None)

    # Resolve card_id -> título do card
    card_id = enriched.get('card_id')
    if card_id and not enriched.get('card_title'):
        try:
            cursor.execute('SELECT title FROM environment_cards WHERE id = ? LIMIT 1', (card_id,))
            r = cursor.fetchone()
            if r:
                rd_card = dict_from_row(r)
                if rd_card.get('title'):
                    enriched['mapeamento'] = rd_card['title']
        except Exception:
            pass
    enriched.pop('card_id', None)

    # Resolve grouping_id -> nome do agrupamento
    grp_id = enriched.get('grouping_id')
    if grp_id and not enriched.get('agrupamento'):
        try:
            cursor.execute('SELECT name FROM job_groupings WHERE id = ? LIMIT 1', (grp_id,))
            r = cursor.fetchone()
            if r:
                rd_grp = dict_from_row(r)
                if rd_grp.get('name'):
                    enriched['agrupamento'] = rd_grp['name']
        except Exception:
            pass
    enriched.pop('grouping_id', None)

    # Remove outros campos de FK que não foram resolvidos
    for leftover in ('activity_id', 'presence_id', 'target_id'):
        enriched.pop(leftover, None)

    return enriched


def _itoca_find_tesseract_cmd():
    """Localiza o binário do tesseract no sistema.
    Ordem de busca:
      1. Diretório do próprio executável (bundled com o Toca do Coelho via NSIS)
      2. PATH do sistema
      3. Caminhos padrão do Windows
    """
    import subprocess

    # 1. Bundled junto ao executável do Toca do Coelho
    #    Quando empacotado com PyInstaller, sys.executable aponta para TocaDoCoelho.exe
    #    O installer.nsi instala o Tesseract em $INSTDIR\tesseract\
    bundled_candidates = []
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    bundled_candidates.append(exe_dir / 'tesseract' / 'tesseract.exe')
    # PyInstaller _MEIPASS
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled_candidates.append(Path(meipass) / 'tesseract' / 'tesseract.exe')
    # Diretório pai (caso o app.py esteja em subpasta)
    bundled_candidates.append(Path(__file__).resolve().parent / 'tesseract' / 'tesseract.exe')
    for candidate in bundled_candidates:
        if candidate.exists():
            # Configura TESSDATA_PREFIX para o tessdata bundled
            tessdata_dir = candidate.parent / 'tessdata'
            if tessdata_dir.exists():
                os.environ['TESSDATA_PREFIX'] = str(tessdata_dir)
            return str(candidate)

    # 2. PATH do sistema
    try:
        result = subprocess.run(['tesseract', '--version'], capture_output=True, timeout=5)
        if result.returncode == 0:
            return 'tesseract'
    except Exception:
        pass

    # 3. Caminhos padrão do Windows
    if sys.platform == 'win32':
        windows_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Users\{}\AppData\Local\Tesseract-OCR\tesseract.exe'.format(os.environ.get('USERNAME', '')),
            r'C:\TocaDoCoelho\tesseract\tesseract.exe',
        ]
        for p in windows_paths:
            if Path(p).exists():
                return p

    return None


def _itoca_extract_text_from_file(file_path_str):
    """Extrai texto de PDF, DOCX ou XLSX para indexação no RAG.
    Estratégia para PDFs:
      1. pdfplumber (texto digital)
      2. pdftotext via subprocess (poppler, Windows/Linux)
      3. OCR com pdf2image + pytesseract (PDFs escaneados/imagens)
    """
    path = Path(file_path_str)
    if not path.exists():
        logger.warning(f'[iToca] Arquivo não encontrado: {file_path_str}')
        return ''
    ext = path.suffix.lower()
    text_parts = []
    try:
        if ext == '.pdf':
            extracted = False

            # --- Tentativa 1: pdfplumber (PDFs com texto digital) ---
            if PDFPLUMBER_AVAILABLE:
                try:
                    with pdfplumber.open(str(path)) as pdf:
                        for page in pdf.pages[:30]:
                            page_text = page.extract_text() or ''
                            if page_text.strip():
                                text_parts.append(page_text.strip())
                    extracted = bool(text_parts)
                except Exception as e1:
                    logger.warning(f'[iToca] pdfplumber falhou em {path.name}: {e1}')

            # --- Tentativa 2: pdftotext (poppler-utils) ---
            if not extracted:
                try:
                    import subprocess
                    # Tenta localizar pdftotext no Windows e Linux
                    pdftotext_cmd = 'pdftotext'
                    if sys.platform == 'win32':
                        win_poppler_paths = [
                            r'C:\poppler\bin\pdftotext.exe',
                            r'C:\Program Files\poppler\bin\pdftotext.exe',
                            r'C:\Program Files (x86)\poppler\bin\pdftotext.exe',
                        ]
                        for wp in win_poppler_paths:
                            if Path(wp).exists():
                                pdftotext_cmd = wp
                                break
                    result = subprocess.run(
                        [pdftotext_cmd, '-enc', 'UTF-8', str(path), '-'],
                        capture_output=True, timeout=20
                    )
                    if result.returncode == 0 and result.stdout:
                        decoded = result.stdout.decode('utf-8', errors='replace')
                        if decoded.strip():
                            text_parts.append(decoded)
                            extracted = True
                except Exception as e2:
                    logger.debug(f'[iToca] pdftotext não disponível para {path.name}: {e2}')

            # --- Tentativa 3: OCR com pdf2image + pytesseract (PDFs escaneados) ---
            if not extracted and PDF2IMAGE_AVAILABLE and PYTESSERACT_AVAILABLE:
                tess_cmd = _itoca_find_tesseract_cmd()
                if tess_cmd:
                    try:
                        pytesseract.pytesseract.tesseract_cmd = tess_cmd
                        images = convert_from_path(str(path), dpi=200, first_page=1, last_page=15)
                        ocr_parts = []
                        for img in images:
                            ocr_text = pytesseract.image_to_string(img, lang='por+eng')
                            if ocr_text.strip():
                                ocr_parts.append(ocr_text.strip())
                        if ocr_parts:
                            text_parts.extend(ocr_parts)
                            extracted = True
                            logger.info(f'[iToca] OCR extraiu texto de {path.name} ({len(images)} páginas)')
                    except Exception as e3:
                        logger.warning(f'[iToca] OCR falhou em {path.name}: {e3}')
                else:
                    logger.info(f'[iToca] Tesseract não encontrado. Instale em https://github.com/UB-Mannheim/tesseract/wiki para OCR de PDFs escaneados.')

            if not extracted:
                logger.warning(f'[iToca] Não foi possível extrair texto de {path.name} '
                               f'(pdfplumber={PDFPLUMBER_AVAILABLE}, ocr={PDF2IMAGE_AVAILABLE and PYTESSERACT_AVAILABLE})')

        elif ext in ('.docx', '.doc'):
            if PYTHON_DOCX_AVAILABLE:
                try:
                    doc = python_docx.Document(str(path))
                    for para in doc.paragraphs:
                        if para.text.strip():
                            text_parts.append(para.text.strip())
                    for table in doc.tables:
                        for row in table.rows:
                            row_text = ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                            if row_text:
                                text_parts.append(row_text)
                except Exception as e4:
                    logger.warning(f'[iToca] python-docx falhou em {path.name}: {e4}')

        elif ext in ('.xlsx', '.xls'):
            if OPENPYXL_AVAILABLE:
                try:
                    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
                    for sheet in wb.worksheets:
                        for row in sheet.iter_rows(values_only=True):
                            row_text = ' | '.join(str(c) for c in row if c is not None and str(c).strip())
                            if row_text:
                                text_parts.append(row_text)
                except Exception as e5:
                    logger.warning(f'[iToca] openpyxl falhou em {path.name}: {e5}')

        elif ext == '.txt':
            try:
                text_parts.append(path.read_text(encoding='utf-8', errors='replace'))
            except Exception:
                pass

    except Exception as e:
        logger.warning(f'[iToca] Erro geral ao extrair texto de {file_path_str}: {e}')

    result_text = '\n'.join(text_parts)
    if result_text:
        logger.info(f'[iToca] Extraiu {len(result_text)} chars de {path.name}')
    return result_text


def _itoca_build_agenda_items(conn):
    """Gera itens da agenda (commitments + account_renewal_events) para o snapshot RAG com contexto rico."""
    cursor = conn.cursor()
    items = []
    today = datetime.now().strftime('%Y-%m-%d')
    # Compromissos da agenda (próximos 90 dias e últimos 30 dias)
    try:
        cursor.execute('''
            SELECT cm.id, cm.title, cm.notes, cm.due_date, cm.due_time, cm.source_type,
                   cl.name as client_name, cl.company as client_company
            FROM commitments cm
            LEFT JOIN clients cl ON cm.client_id = cl.id
            ORDER BY cm.due_date ASC
        ''')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('due_date'):
                try:
                    dt = datetime.strptime(rd['due_date'][:10], '%Y-%m-%d')
                    parts.append(f'data: {dt.strftime("%d/%m/%Y")}')
                except Exception:
                    parts.append(f'data: {rd["due_date"]}')
            if rd.get('due_time'):
                parts.append(f'hora: {rd["due_time"]}')
            if rd.get('client_name'):
                parts.append(f'contato: {rd["client_name"]}')
            if rd.get('client_company'):
                parts.append(f'empresa: {rd["client_company"]}')
            if rd.get('notes') and rd['notes'] != rd.get('title'):
                parts.append(f'notas: {rd["notes"][:300]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({
                    'table': 'commitments',
                    'id': rd.get('id'),
                    'snippet': snippet,
                    'search_text': snippet.lower()
                })
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar commitments: {e}')

    # Eventos de renovação de contas
    try:
        cursor.execute('''
            SELECT ev.id, ev.title, ev.due_date, ev.due_time,
                   ac.name as account_name
            FROM account_renewal_events ev
            LEFT JOIN accounts ac ON ev.account_id = ac.id
            ORDER BY ev.due_date ASC
        ''')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('due_date'):
                try:
                    dt = datetime.strptime(rd['due_date'][:10], '%Y-%m-%d')
                    parts.append(f'data: {dt.strftime("%d/%m/%Y")}')
                except Exception:
                    parts.append(f'data: {rd["due_date"]}')
            if rd.get('due_time'):
                parts.append(f'hora: {rd["due_time"]}')
            if rd.get('account_name'):
                parts.append(f'conta: {rd["account_name"]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({
                    'table': 'account_renewal_events',
                    'id': rd.get('id'),
                    'snippet': snippet,
                    'search_text': snippet.lower()
                })
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar account_renewal_events: {e}')

    return items


def _itoca_build_wiki_items(conn, max_chars_per_doc=8000):
    """Gera itens do WikiToca (entradas de conhecimento + documentos) para o snapshot RAG."""
    cursor = conn.cursor()
    items = []

    # 1. Entradas de conhecimento (wiki_entries)
    try:
        cursor.execute('SELECT id, title, category, content, tags FROM wiki_entries ORDER BY updated_at DESC')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('category'):
                parts.append(f'categoria: {rd["category"]}')
            if rd.get('tags'):
                parts.append(f'tags: {rd["tags"]}')
            if rd.get('content'):
                parts.append(f'conteudo: {rd["content"][:2000]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({
                    'table': 'wiki_entries',
                    'id': rd.get('id'),
                    'snippet': snippet,
                    'search_text': snippet.lower()
                })
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar wiki_entries: {e}')

    # 2. Documentos (wiki_documents) — extrai texto do arquivo
    try:
        cursor.execute('SELECT id, title, original_name, file_name, file_ext FROM wiki_documents ORDER BY updated_at DESC')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            file_path = WIKI_UPLOAD_DIR / (rd.get('file_name') or '')
            doc_text = ''
            if file_path.exists():
                doc_text = _itoca_extract_text_from_file(str(file_path))

            doc_title = rd.get('title') or rd.get('original_name', '')
            doc_ext = rd.get('file_ext', '')

            if not doc_text.strip():
                # Sem conteúdo extraível: indexa metadados com nota clara ao LLM
                snippet = (f'[WikiToca Doc] titulo: {doc_title} | tipo: {doc_ext} | '
                           f'CONFIRMADO: o documento "{rd.get("original_name", "")}" EXISTE no WikiToca. '
                           f'Conteúdo interno não disponível para leitura automática. '
                           f'Ao responder sobre este tema, informe que o documento existe mas não é possível detalhar o conteúdo.')
                # search_text inclui o título completo + nome original para melhor matching por tokens
                _search_base = (doc_title + ' ' + rd.get('original_name', '') + ' ' + doc_ext).lower()
                items.append({
                    'table': 'wiki_documents',
                    'id': rd.get('id'),
                    'snippet': snippet,
                    'search_text': _search_base
                })
            else:
                # Divide em chunks de max_chars_per_doc para não sobrecarregar o contexto
                max_total = max_chars_per_doc * 5
                chunks = [doc_text[i:i+max_chars_per_doc] for i in range(0, min(len(doc_text), max_total), max_chars_per_doc)]
                for idx, chunk in enumerate(chunks):
                    chunk_label = f'parte {idx+1}' if len(chunks) > 1 else 'conteúdo'
                    snippet = f'[WikiToca Doc] titulo: {doc_title} | {chunk_label} | {chunk.strip()[:3000]}'
                    items.append({
                        'table': 'wiki_documents',
                        'id': rd.get('id'),
                        'snippet': snippet,
                        'search_text': snippet.lower()
                    })
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar wiki_documents: {e}')

    return items


def _itoca_build_activities_items(conn):
    """Gera itens de atividades com JOIN em clients e commitments para contexto rico.
    Limita a 5 atividades mais recentes por empresa para evitar sobrecarga de tokens.
    Inclui o título do compromisso vinculado quando existir (via notes ou title match).
    """
    cursor = conn.cursor()
    items = []
    try:
        # Busca as 500 mais recentes; depois limita por empresa no Python
        cursor.execute('''
            SELECT ac.id, ac.contact_type, ac.information, ac.description, ac.activity_date,
                   cl.name as client_name, cl.company as client_company, cl.position as client_position,
                   cl.id as client_id
            FROM activities ac
            LEFT JOIN clients cl ON ac.client_id = cl.id
            ORDER BY ac.activity_date DESC
            LIMIT 500
        ''')
        rows = cursor.fetchall()

        # Conta por empresa para limitar a 5 mais recentes
        company_count = {}
        for row in rows:
            rd = dict_from_row(row)
            company = (rd.get('client_company') or '').strip().lower()
            if not company:
                company = '__sem_empresa__'
            if company_count.get(company, 0) >= 5:
                continue
            company_count[company] = company_count.get(company, 0) + 1

            parts = []
            if rd.get('client_name'):
                parts.append(f'contato: {rd["client_name"]}')
            if rd.get('client_company'):
                parts.append(f'empresa: {rd["client_company"]}')
            if rd.get('client_position'):
                parts.append(f'cargo: {rd["client_position"]}')
            if rd.get('contact_type'):
                parts.append(f'tipo: {rd["contact_type"]}')
            if rd.get('activity_date'):
                try:
                    dt = datetime.strptime(str(rd['activity_date'])[:10], '%Y-%m-%d')
                    parts.append(f'data: {dt.strftime("%d/%m/%Y")}')
                except Exception:
                    parts.append(f'data: {rd["activity_date"]}')
            if rd.get('information'):
                parts.append(f'informacao: {str(rd["information"])[:300]}')
            if rd.get('description') and rd['description'] != rd.get('information'):
                parts.append(f'descricao: {str(rd["description"])[:300]}')

            # Tenta encontrar compromisso vinculado pela data + contato
            # (commitments com mesmo client_id e due_date próxima da activity_date)
            if rd.get('client_id') and rd.get('activity_date'):
                try:
                    act_date = str(rd['activity_date'])[:10]
                    cursor.execute('''
                        SELECT title FROM commitments
                        WHERE client_id = ?
                          AND ABS(julianday(due_date) - julianday(?)) <= 7
                        ORDER BY ABS(julianday(due_date) - julianday(?)) ASC
                        LIMIT 1
                    ''', (rd['client_id'], act_date, act_date))
                    cm_row = cursor.fetchone()
                    if cm_row:
                        cm_title = (cm_row[0] if not isinstance(cm_row, sqlite3.Row) else cm_row['title'] if 'title' in cm_row.keys() else cm_row[0]) or ''
                        if cm_title:
                            parts.append(f'compromisso_vinculado: {cm_title[:120]}')
                except Exception:
                    pass

            snippet = ' | '.join(parts)
            if snippet:
                items.append({'table': 'activities', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar activities: {e}')
    return items


def _itoca_build_presences_items(conn):
    """Gera itens de presenças em contas com JOIN em accounts e clients."""
    cursor = conn.cursor()
    items = []
    try:
        cursor.execute('''
            SELECT ap.id, ap.delivery_name, ap.stf_owner, ap.current_revenue_cents,
                   ap.validity_month,
                   ac.name as account_name, ac.sector as account_sector,
                   cl.name as focal_contact_name
            FROM account_presences ap
            LEFT JOIN accounts ac ON ap.account_id = ac.id
            LEFT JOIN clients cl ON ap.focal_client_id = cl.id
            ORDER BY ap.updated_at DESC
        ''')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('account_name'):
                parts.append(f'conta: {rd["account_name"]}')
            if rd.get('account_sector'):
                parts.append(f'setor: {rd["account_sector"]}')
            if rd.get('delivery_name'):
                parts.append(f'entrega: {rd["delivery_name"]}')
            if rd.get('stf_owner'):
                parts.append(f'responsavel_stf: {rd["stf_owner"]}')
            if rd.get('focal_contact_name'):
                parts.append(f'contato_focal: {rd["focal_contact_name"]}')
            if rd.get('current_revenue_cents'):
                try:
                    receita = int(rd['current_revenue_cents']) / 100
                    parts.append(f'receita_atual: R$ {receita:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'))
                except Exception:
                    pass
            if rd.get('validity_month'):
                parts.append(f'validade: {rd["validity_month"]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({'table': 'account_presences', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar account_presences: {e}')
    return items


def _itoca_build_kanban_items(conn):
    """Gera itens do Kanban com JOIN em accounts, clients e kanban_columns."""
    cursor = conn.cursor()
    items = []
    try:
        cursor.execute('''
            SELECT kc.id, kc.title, kc.description, kc.tag, kc.urgency, kc.activity,
                   kc.updated_at,
                   col.title as column_title,
                   ac.name as account_name,
                   cl.name as contact_name
            FROM kanban_cards kc
            LEFT JOIN kanban_columns col ON kc.column_id = col.id
            LEFT JOIN accounts ac ON kc.account_id = ac.id
            LEFT JOIN clients cl ON kc.contact_id = cl.id
            ORDER BY kc.updated_at DESC
        ''')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('column_title'):
                parts.append(f'coluna: {rd["column_title"]}')
            if rd.get('account_name'):
                parts.append(f'conta: {rd["account_name"]}')
            if rd.get('contact_name'):
                parts.append(f'contato: {rd["contact_name"]}')
            if rd.get('urgency'):
                parts.append(f'urgencia: {rd["urgency"]}')
            if rd.get('tag'):
                parts.append(f'tag: {rd["tag"]}')
            if rd.get('description'):
                parts.append(f'descricao: {str(rd["description"])[:300]}')
            if rd.get('activity'):
                parts.append(f'atividade: {str(rd["activity"])[:200]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({'table': 'kanban_cards', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar kanban_cards: {e}')
    return items


def _itoca_build_environment_items(conn):
    """Gera itens de mapeamento de ambiente com JOIN em environment_cards, clients e accounts."""
    cursor = conn.cursor()
    items = []
    try:
        cursor.execute('''
            SELECT er.id, er.response,
                   ec.title as card_title,
                   cl.name as client_name, cl.company as client_company
            FROM environment_responses er
            LEFT JOIN environment_cards ec ON er.card_id = ec.id
            LEFT JOIN clients cl ON er.client_id = cl.id
            WHERE er.response IS NOT NULL AND TRIM(er.response) != ""
            ORDER BY er.updated_at DESC
        ''')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('client_company'):
                parts.append(f'empresa: {rd["client_company"]}')
            if rd.get('client_name'):
                parts.append(f'contato: {rd["client_name"]}')
            if rd.get('card_title'):
                parts.append(f'mapeamento: {rd["card_title"]}')
            if rd.get('response'):
                parts.append(f'resposta: {str(rd["response"])[:400]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({'table': 'environment_responses', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar environment_responses: {e}')
    return items


def _itoca_build_user_profile_item(conn):
    """Gera item fixo com o perfil do usuário para sempre estar no contexto."""
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT full_name, nickname, position, email, phone, boss_name, boss_email FROM user_profile WHERE id = 1')
        row = cursor.fetchone()
        if not row:
            return None
        rd = dict_from_row(row)
        parts = []
        if rd.get('full_name'):
            parts.append(f'nome: {rd["full_name"]}')
        if rd.get('nickname'):
            parts.append(f'apelido: {rd["nickname"]}')
        if rd.get('position'):
            parts.append(f'cargo: {rd["position"]}')
        if rd.get('email'):
            parts.append(f'email: {rd["email"]}')
        if rd.get('phone'):
            parts.append(f'telefone: {rd["phone"]}')
        if rd.get('boss_name'):
            parts.append(f'gestor: {rd["boss_name"]}')
        if rd.get('boss_email'):
            parts.append(f'email_gestor: {rd["boss_email"]}')
        snippet = ' | '.join(parts)
        if snippet:
            return {'table': 'user_profile', 'id': 1, 'snippet': snippet, 'search_text': snippet.lower()}
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar user_profile: {e}')
    return None


def _itoca_build_message_templates_items(conn):
    """Gera itens dos templates de mensagem para consulta pelo iToca."""
    cursor = conn.cursor()
    items = []
    try:
        cursor.execute('SELECT id, title, description FROM message_templates ORDER BY title')
        for row in cursor.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'):
                parts.append(f'titulo: {rd["title"]}')
            if rd.get('description'):
                parts.append(f'conteudo: {str(rd["description"])[:600]}')
            snippet = ' | '.join(parts)
            if snippet:
                items.append({'table': 'message_templates', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar message_templates: {e}')
    return items


def _itoca_build_base_snapshot(max_tables=120, max_rows_per_table=250, max_items=6000, progress_cb=None):
    """Constrói o snapshot RAG. progress_cb(percent, message) é chamado durante o processo."""
    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    # Tabelas que têm funções especializadas e não devem ser varridas genericamente
    _SPECIALIZED_TABLES = {
        'activities', 'commitments', 'account_renewal_events', 'account_presences',
        'kanban_cards', 'environment_responses', 'wiki_entries', 'wiki_documents',
        'user_profile', 'message_templates'
    }

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [
        row['name'] for row in cursor.fetchall()
        if row['name'] not in ITOCA_EXCLUDED_TABLES and row['name'] not in _SPECIALIZED_TABLES
    ][:max_tables]

    _progress(5, f'Lendo {len(tables)} tabelas genéricas do banco de dados...')
    items = []
    total_tables = max(len(tables), 1)
    for t_idx, table in enumerate(tables):
        text_columns = _itoca_text_columns(cursor, table)
        if not text_columns:
            continue
        try:
            cursor.execute(f'SELECT * FROM "{table}" LIMIT {int(max_rows_per_table)}')
            rows = cursor.fetchall()
        except Exception:
            continue

        for row in rows:
            row_dict = dict_from_row(row)
            snippet = _itoca_build_snippet(row_dict)
            if not snippet:
                continue
            items.append({
                'table': table,
                'id': row_dict.get('id'),
                'snippet': snippet,
                'search_text': snippet.lower()
            })
            if len(items) >= max_items:
                conn.close()
                _progress(100, f'Concluído: {len(items)} registros indexados.')
                return items

        pct_tables = 5 + int((t_idx + 1) / total_tables * 20)  # 5% a 25%
        _progress(pct_tables, f'Tabela {table} indexada ({t_idx+1}/{total_tables})...')

    # Perfil do usuário (item fixo)
    _progress(26, 'Indexando perfil do usuário...')
    profile_item = _itoca_build_user_profile_item(conn)
    if profile_item:
        items.append(profile_item)

    # Atividades com JOIN enriquecido
    _progress(30, 'Indexando atividades com contatos...')
    activity_items = _itoca_build_activities_items(conn)
    items.extend(activity_items)
    _progress(38, f'{len(activity_items)} atividades indexadas.')

    # Agenda
    _progress(40, 'Indexando agenda e compromissos...')
    agenda_items = _itoca_build_agenda_items(conn)
    items.extend(agenda_items)
    _progress(48, f'{len(agenda_items)} eventos de agenda indexados.')

    # Presenças em contas com JOIN
    _progress(50, 'Indexando presenças em contas...')
    presences_items = _itoca_build_presences_items(conn)
    items.extend(presences_items)
    _progress(55, f'{len(presences_items)} presenças indexadas.')

    # Kanban com JOIN
    _progress(57, 'Indexando cards do Kanban...')
    kanban_items = _itoca_build_kanban_items(conn)
    items.extend(kanban_items)
    _progress(62, f'{len(kanban_items)} cards do Kanban indexados.')

    # Mapeamento de ambiente com JOIN
    _progress(64, 'Indexando mapeamento de ambiente...')
    env_items = _itoca_build_environment_items(conn)
    items.extend(env_items)
    _progress(68, f'{len(env_items)} respostas de mapeamento indexadas.')

    # Templates de mensagem
    _progress(69, 'Indexando templates de mensagem...')
    template_items = _itoca_build_message_templates_items(conn)
    items.extend(template_items)
    _progress(70, f'{len(template_items)} templates indexados.')

    # WikiToca — mais demorado por causa da extração de PDF
    _progress(72, 'Indexando WikiToca (entradas de conhecimento)...')
    conn2 = get_db()
    cursor2 = conn2.cursor()
    wiki_entry_items = []
    try:
        cursor2.execute('SELECT id, title, category, content, tags FROM wiki_entries ORDER BY updated_at DESC')
        for row in cursor2.fetchall():
            rd = dict_from_row(row)
            parts = []
            if rd.get('title'): parts.append(f'titulo: {rd["title"]}')
            if rd.get('category'): parts.append(f'categoria: {rd["category"]}')
            if rd.get('tags'): parts.append(f'tags: {rd["tags"]}')
            if rd.get('content'): parts.append(f'conteudo: {rd["content"][:2000]}')
            snippet = ' | '.join(parts)
            if snippet:
                wiki_entry_items.append({'table': 'wiki_entries', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar wiki_entries: {e}')
    items.extend(wiki_entry_items)
    _progress(78, f'{len(wiki_entry_items)} entradas WikiToca indexadas. Processando documentos...')

    # Documentos WikiToca com extração de texto (pode ser lento por OCR)
    wiki_doc_items = []
    try:
        cursor2.execute('SELECT id, title, original_name, file_name, file_ext FROM wiki_documents ORDER BY updated_at DESC')
        all_docs = cursor2.fetchall()
        total_docs = max(len(all_docs), 1)
        for d_idx, row in enumerate(all_docs):
            rd = dict_from_row(row)
            doc_title = rd.get('title') or rd.get('original_name', '')
            doc_ext = rd.get('file_ext', '')
            file_path = WIKI_UPLOAD_DIR / (rd.get('file_name') or '')
            doc_text = ''
            pct_docs = 78 + int((d_idx + 1) / total_docs * 18)  # 78% a 96%
            _progress(pct_docs, f'Processando documento {d_idx+1}/{total_docs}: {doc_title[:40]}...')
            if file_path.exists():
                doc_text = _itoca_extract_text_from_file(str(file_path))
            if not doc_text.strip():
                snippet = (f'[WikiToca Doc] titulo: {doc_title} | tipo: {doc_ext} | '
                           f'CONFIRMADO: o documento "{rd.get("original_name", "")}" EXISTE no WikiToca. '
                           f'Conteúdo interno não disponível para leitura automática. '
                           f'Ao responder sobre este tema, informe que o documento existe mas não é possível detalhar o conteúdo.')
                _search_base = (doc_title + ' ' + rd.get('original_name', '') + ' ' + doc_ext).lower()
                wiki_doc_items.append({'table': 'wiki_documents', 'id': rd.get('id'), 'snippet': snippet, 'search_text': _search_base})
            else:
                max_total = 8000 * 5
                chunks = [doc_text[i:i+8000] for i in range(0, min(len(doc_text), max_total), 8000)]
                for idx, chunk in enumerate(chunks):
                    chunk_label = f'parte {idx+1}' if len(chunks) > 1 else 'conteúdo'
                    snippet = f'[WikiToca Doc] titulo: {doc_title} | {chunk_label} | {chunk.strip()[:3000]}'
                    wiki_doc_items.append({'table': 'wiki_documents', 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
    except Exception as e:
        logger.warning(f'[iToca] Erro ao indexar wiki_documents: {e}')
    conn2.close()
    items.extend(wiki_doc_items)

    conn.close()
    _progress(100, f'Concluído! {len(items)} registros indexados no total.')
    return items


def _itoca_update_cached_base(progress_cb=None, incremental=False):
    """Atualiza o snapshot RAG.
    Se incremental=True, re-indexa apenas registros modificados após o último update.
    Se incremental=False (padrão), faz a indexação completa.
    """
    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    if incremental:
        # Busca o timestamp do último update
        settings_map = _load_app_settings_map(['itoca_base_updated_at', 'itoca_base_snapshot'])
        last_updated = (settings_map.get('itoca_base_updated_at') or '').strip()
        raw_snapshot = (settings_map.get('itoca_base_snapshot') or '').strip()

        if not last_updated or not raw_snapshot:
            # Nunca foi indexado: faz completo
            _progress(0, 'Primeira indexação: executando indexação completa...')
            return _itoca_update_cached_base(progress_cb=progress_cb, incremental=False)

        try:
            existing_items = json.loads(raw_snapshot)
        except Exception:
            existing_items = []

        _progress(5, f'Indexação incremental desde {last_updated}...')
        conn = get_db()
        cursor = conn.cursor()
        new_items = []
        seen_keys = set()

        # Tabelas com coluna updated_at ou created_at para filtro incremental
        _INCREMENTAL_TABLES = [
            'clients', 'accounts', 'account_presences', 'account_main_contacts',
            'kanban_cards', 'kanban_card_activities', 'daily_suggestions',
            'environment_cards', 'account_sectors'
        ]
        _INCREMENTAL_SPECIALIZED = [
            ('activities', '_itoca_build_activities_items'),
            ('commitments', '_itoca_build_agenda_items'),
            ('account_renewal_events', '_itoca_build_agenda_items'),
            ('account_presences', '_itoca_build_presences_items'),
            ('kanban_cards', '_itoca_build_kanban_items'),
            ('environment_responses', '_itoca_build_environment_items'),
            ('wiki_entries', None),
            ('wiki_documents', None),
            ('message_templates', '_itoca_build_message_templates_items'),
        ]

        # Verifica se houve alterações em tabelas genéricas
        generic_changed = False
        for table in _INCREMENTAL_TABLES:
            try:
                cursor.execute(
                    f'SELECT COUNT(*) as cnt FROM "{table}" WHERE updated_at > ? OR created_at > ?',
                    (last_updated, last_updated)
                )
                row = cursor.fetchone()
                if row and (dict_from_row(row).get('cnt') or 0) > 0:
                    generic_changed = True
                    break
            except Exception:
                pass

        # Verifica se houve alterações nas tabelas especializadas
        specialized_changed_tables = set()
        for table, _ in _INCREMENTAL_SPECIALIZED:
            try:
                col = 'updated_at'
                cursor.execute(f"PRAGMA table_info('{table}')")
                cols = [r['name'] for r in cursor.fetchall()]
                if 'updated_at' not in cols:
                    col = 'created_at'
                if col not in cols:
                    specialized_changed_tables.add(table)
                    continue
                cursor.execute(
                    f'SELECT COUNT(*) as cnt FROM "{table}" WHERE {col} > ?',
                    (last_updated,)
                )
                row = cursor.fetchone()
                if row and (dict_from_row(row).get('cnt') or 0) > 0:
                    specialized_changed_tables.add(table)
            except Exception:
                specialized_changed_tables.add(table)

        # Se nada mudou, retorna o snapshot existente sem reprocessar
        if not generic_changed and not specialized_changed_tables:
            _progress(100, f'Nenhuma alteração detectada. Base já está atualizada ({len(existing_items)} registros).')
            conn.close()
            updated_at = datetime.now().isoformat(timespec='seconds')
            c = get_db()
            cc = c.cursor()
            cc.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (updated_at, 'itoca_base_updated_at'))
            c.commit()
            c.close()
            return {'items': existing_items, 'updated_at': updated_at, 'incremental': True, 'changed': False}

        # Remove do snapshot existente os registros das tabelas que mudaram
        tables_to_refresh = set()
        if generic_changed:
            tables_to_refresh.update(_INCREMENTAL_TABLES)
        tables_to_refresh.update(specialized_changed_tables)

        # Sempre re-indexa user_profile (item fixo, muito leve)
        tables_to_refresh.add('user_profile')

        _progress(10, f'Atualizando {len(tables_to_refresh)} tabelas modificadas...')

        # Mantém registros de tabelas não alteradas
        kept_items = [item for item in existing_items if item.get('table') not in tables_to_refresh]
        seen_keys = {f"{item.get('table')}:{item.get('id')}" for item in kept_items}

        # Re-indexa tabelas genéricas alteradas
        if generic_changed:
            for table in _INCREMENTAL_TABLES:
                if table not in tables_to_refresh:
                    continue
                text_columns = _itoca_text_columns(cursor, table)
                if not text_columns:
                    continue
                try:
                    cursor.execute(f'SELECT * FROM "{table}" LIMIT 250')
                    for row in cursor.fetchall():
                        rd = dict_from_row(row)
                        snippet = _itoca_build_snippet(rd)
                        if snippet:
                            kept_items.append({'table': table, 'id': rd.get('id'), 'snippet': snippet, 'search_text': snippet.lower()})
                except Exception:
                    pass

        # Re-indexa tabelas especializadas alteradas
        if 'user_profile' in tables_to_refresh:
            p = _itoca_build_user_profile_item(conn)
            if p:
                kept_items.append(p)
        if 'activities' in tables_to_refresh:
            kept_items.extend(_itoca_build_activities_items(conn))
        if 'commitments' in tables_to_refresh or 'account_renewal_events' in tables_to_refresh:
            kept_items.extend(_itoca_build_agenda_items(conn))
        if 'account_presences' in tables_to_refresh:
            kept_items.extend(_itoca_build_presences_items(conn))
        if 'kanban_cards' in tables_to_refresh:
            kept_items.extend(_itoca_build_kanban_items(conn))
        if 'environment_responses' in tables_to_refresh:
            kept_items.extend(_itoca_build_environment_items(conn))
        if 'message_templates' in tables_to_refresh:
            kept_items.extend(_itoca_build_message_templates_items(conn))

        # Re-indexa wiki se necessário
        if 'wiki_entries' in tables_to_refresh or 'wiki_documents' in tables_to_refresh:
            _progress(60, 'Atualizando WikiToca...')
            kept_items.extend(_itoca_build_wiki_items(conn))

        conn.close()
        snapshot_items = kept_items
        _progress(95, f'Incremental concluído: {len(snapshot_items)} registros na base.')

    else:
        # Indexação completa
        snapshot_items = _itoca_build_base_snapshot(progress_cb=progress_cb)

    updated_at = datetime.now().isoformat(timespec='seconds')
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (json.dumps(snapshot_items, ensure_ascii=False), 'itoca_base_snapshot'))
    c.execute('UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (updated_at, 'itoca_base_updated_at'))
    conn.commit()
    conn.close()
    _progress(100, f'Base atualizada: {len(snapshot_items)} registros indexados.')
    return {'items': snapshot_items, 'updated_at': updated_at, 'incremental': incremental}


def _itoca_get_cached_base():
    settings_map = _load_app_settings_map(['itoca_base_snapshot', 'itoca_base_updated_at'])
    raw_snapshot = (settings_map.get('itoca_base_snapshot') or '').strip()
    updated_at = (settings_map.get('itoca_base_updated_at') or '').strip()
    if not raw_snapshot:
        return [], updated_at
    try:
        snapshot = json.loads(raw_snapshot)
    except Exception:
        snapshot = []
    return snapshot if isinstance(snapshot, list) else [], updated_at


def _itoca_search_in_cached_snapshot(question, snapshot_items, limit=18):
    tokens = _itoca_tokenize(question)
    if not tokens or not snapshot_items:
        return []

    scored = []
    for item in snapshot_items:
        haystack = str(item.get('search_text') or item.get('snippet') or '').lower()
        if not haystack:
            continue
        score = sum(1 for token in tokens if token in haystack)
        if score <= 0:
            continue
        scored.append((score, item))

    scored.sort(key=lambda x: (-x[0], str(x[1].get('table') or ''), str(x[1].get('id') or '')))
    return [item for _, item in scored[:max(1, int(limit or 18))]]


# Rótulos legíveis por tabela para o contexto do LLM
_ITOCA_TABLE_LABELS = {
    'clients': 'Contato/Cliente',
    'accounts': 'Conta/Empresa',
    'activities': 'Atividade/Interação com Contato',
    'commitments': 'Compromisso/Evento de Agenda',
    'account_renewal_events': 'Evento de Renovação de Contrato',
    'account_presences': 'Presença/Entrega em Conta',
    'account_main_contacts': 'Contato Principal de Conta',
    'wiki_entries': 'Conhecimento do WikiToca',
    'wiki_documents': 'Documento do WikiToca',
    'environment_cards': 'Card de Mapeamento de Ambiente',
    'environment_responses': 'Resposta de Mapeamento de Ambiente',
    'kanban_columns': 'Coluna do Kanban',
    'kanban_cards': 'Card do Kanban',
    'daily_suggestions': 'Sugestão Diária',
    'user_profile': 'Perfil do Usuário',
    'message_templates': 'Template de Mensagem',
    'account_sectors': 'Setor de Conta',
    'job_groupings': 'Agrupamento de Cargos',
}


def infer_kanban_tag(description):
    text = (description or '').strip().lower()
    if not text:
        return ''

    tag_rules = [
        ('Comercial', ['proposta', 'orcamento', 'negoci', 'cliente', 'venda', 'pipeline', 'lead']),
        ('Técnico', ['api', 'erro', 'sistema', 'infra', 'deploy', 'integracao', 'bug', 'arquitetura']),
        ('Financeiro', ['fatur', 'pagamento', 'custo', 'contrato', 'budget', 'receita']),
        ('Relacionamento', ['reuniao', 'follow-up', 'contato', 'alinhamento', 'feedback', 'stakeholder']),
        ('Produto', ['produto', 'feature', 'roadmap', 'release', 'sprint']),
        ('Prioridade Alta', ['urgente', 'critico', 'hoje', 'bloqueio'])
    ]

    found_tags = []
    for tag, keywords in tag_rules:
        if any(keyword in text for keyword in keywords):
            found_tags.append(tag)

    if found_tags:
        return ' | '.join(found_tags)

    tokens = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text)
    stopwords = {
        'para', 'com', 'sobre', 'entre', 'pelos', 'pelas', 'isso', 'essa', 'esse', 'dele', 'dela',
        'card', 'tarefa', 'atividade', 'fazer', 'sera', 'será', 'esta', 'está', 'mais', 'muito', 'pouco',
        'uma', 'uns', 'das', 'dos', 'que', 'por', 'sem'
    }
    keywords = []
    for token in tokens:
        tk = token.strip().lower()
        if tk in stopwords:
            continue
        label = tk.capitalize()
        if label not in keywords:
            keywords.append(label)
        if len(keywords) >= 4:
            break
    if keywords:
        return ' | '.join(keywords)

    raw_tokens = [t.strip().capitalize() for t in re.findall(r"[a-zA-ZÀ-ÿ]{2,}", text) if t.strip()]
    raw_tokens = [t for t in raw_tokens if t.lower() not in stopwords][:3]
    return ' | '.join(raw_tokens) if raw_tokens else ''

def _itoca_compose_context_text(context_rows, history_rows=None):
    """Formata as linhas de contexto em texto estruturado e semântico para envio ao LLM.
    Inclui: data/hora atual, instruções de formatação, histórico de sessão e registros agrupados por categoria.
    """
    from datetime import datetime as _dt
    import locale as _locale

    # Data e hora atual em português
    now = _dt.now()
    dias_semana = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
             'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
    dia_semana = dias_semana[now.weekday()]
    data_str = f'{dia_semana}, {now.day} de {meses[now.month - 1]} de {now.year}'
    hora_str = now.strftime('%H:%M')

    lines = []
    lines.append('=== CONTEXTO INTERNO DO SISTEMA TOCA DO COELHO ===')
    lines.append(f'DATA E HORA ATUAL: {data_str}, {hora_str}')
    lines.append('')
    lines.append('INSTRUÇÕES DE FORMATAÇÃO E PROFUNDIDADE DA RESPOSTA:')
    lines.append('- Use linguagem natural, profissional e direta. Evite termos técnicos do banco de dados.')
    lines.append('- Não repita os rótulos internos (ex: "titulo:", "conta:", "nome_contato:", "classificacao:") na resposta final; traduza para linguagem natural.')
    lines.append('- O rótulo "classificacao: conta-alvo (target)" significa que a conta/contato é prioritário (marcado como Target no sistema).')
    lines.append('- O rótulo "classificacao: cold contact" significa que o contato está em prospecção fria.')
    lines.append('- O rótulo "servicos_stefanini_cadastrados" indica quantos serviços/entregas Stefanini estão mapeados naquela conta.')
    lines.append('- O rótulo "PAINEL_GERAL" contém estatísticas globais do sistema — use para contextualizar totais e proporções.')
    lines.append('- Para listas com 3 ou mais itens, use tópicos com "•" (bullet) ou números.')
    lines.append('- TABELAS: use tabela Markdown APENAS para comparações diretas de atributos similares (ex: lista de contatos com cargo e e-mail). Para análise de relacionamento, use seções por conta com bullets — NÃO use tabela plana que mistura contas com contatos em linhas.')
    lines.append('- Datas devem ser apresentadas no formato DD/MM/AAAA. Horários no formato HH:MM.')
    lines.append('- Valores monetários devem usar o formato R$ X.XXX,XX.')
    lines.append('- Ao citar um compromisso, sempre informe: título, data, horário e contato/empresa envolvidos.')
    lines.append('- Se a pergunta envolver "próximos eventos" ou "esta semana", use a DATA ATUAL acima como referência.')
    lines.append('- ANÁLISE DE RELACIONAMENTO: quando perguntado sobre relacionamento com contas target ou múltiplas contas, organize a resposta COM UMA SEÇÃO POR CONTA, mostrando para cada uma:')
    lines.append('  * Nome da conta e se é target ou não')
    lines.append('  * Último contato realizado (data e tipo)')
    lines.append('  * Total de interações registradas')
    lines.append('  * Se possui serviços/entregas Stefanini cadastrados (quantos)')
    lines.append('  * Contatos/pessoas mapeadas (se disponível)')
    lines.append('  * Avaliação resumida: "evoluindo bem" se há atividades recentes, "só tentativas" se há poucas atividades, "sem histórico" se não há interações')
    lines.append('- NOMES: sempre use o nome da pessoa e da empresa, nunca IDs numéricos.')
    lines.append('- COMPLETUDE: se houver dados de múltiplas contas target, apresente TODAS, não apenas as primeiras.')
    lines.append('')

    # Histórico da sessão (se fornecido)
    if history_rows:
        lines.append('=== HISTÓRICO DA CONVERSA ATUAL ===')
        for h in history_rows[-6:]:  # últimas 3 trocas (user + assistant)
            role_label = 'Usuário' if h.get('role') == 'user' else 'iToca'
            lines.append(f'[{role_label}]: {str(h.get("content", ""))[:400]}')
        lines.append('')

    if not context_rows:
        lines.append('(Nenhum dado encontrado na base interna para esta pergunta.)')
        return '\n'.join(lines)

    lines.append('=== REGISTROS ENCONTRADOS NA BASE INTERNA ===')
    lines.append('(Use SOMENTE estas informações. CNPJ = Cadastro Nacional de Pessoa Jurídica. CPF = Cadastro de Pessoa Física.)')
    lines.append('')

    # Agrupa registros por categoria para facilitar a leitura do LLM
    from collections import defaultdict as _dd
    grouped = _dd(list)
    for item in context_rows[:25]:
        table = item.get('table', 'outros')
        grouped[table].append(item)

    # Ordem de apresentação das categorias (mais relevantes primeiro)
    _CATEGORY_ORDER = [
        'user_profile', 'commitments', 'account_renewal_events',
        'activities', 'clients', 'accounts', 'account_presences',
        'account_main_contacts', 'kanban_cards', 'environment_responses',
        'wiki_entries', 'wiki_documents', 'message_templates', 'daily_suggestions'
    ]
    ordered_tables = _CATEGORY_ORDER + [t for t in grouped if t not in _CATEGORY_ORDER]

    reg_num = 1
    for table in ordered_tables:
        if table not in grouped:
            continue
        label = _ITOCA_TABLE_LABELS.get(table, table)
        lines.append(f'--- [{label}] ---')
        for item in grouped[table]:
            row_id = f" #{item['id']}" if item.get('id') is not None else ''
            lines.append(f'  Registro {reg_num}{row_id}: {item["snippet"]}')
            reg_num += 1
        lines.append('')

    return '\n'.join(lines)


def _itoca_call_sai_llm(question, context_rows, history_rows=None):
    """Chama a API SAI LLM com a pergunta e o contexto. Retorna dict com answer, confidence_percent, needs_refinement, refinement_hint."""
    settings_map = _load_app_settings_map(['itoca_sai_api_key', 'itoca_sai_template_id', 'itoca_sai_base_url'])
    api_key = (settings_map.get('itoca_sai_api_key') or '').strip() or (os.environ.get('ITOCA_SAI_API_KEY', '') or '').strip()
    template_id = (settings_map.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
    base_url = (settings_map.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

    context_text = _itoca_compose_context_text(context_rows, history_rows=history_rows)

    if not api_key:
        # Fallback sem LLM: retorna resposta estruturada básica
        if not context_rows:
            return {
                'answer': 'Não encontrei dados suficientes na base interna para responder com segurança. Tente perguntar com mais detalhes (nome, empresa, cargo, data ou módulo).',
                'confidence_percent': 0,
                'needs_refinement': True,
                'refinement_hint': 'Forneça mais detalhes como nome, empresa, cargo ou data.',
                'llm_used': False
            }
        answer_lines = [f'Encontrei {len(context_rows)} registro(s) relevante(s):']
        for item in context_rows[:8]:
            row_id = f"#{item['id']}" if item.get('id') is not None else ''
            answer_lines.append(f"• [{item['table']}{row_id}] {item['snippet']}")
        answer_lines.append('')
        answer_lines.append('Configure a chave da API SAI em Configurações > Integrações para respostas em linguagem natural.')
        return {
            'answer': '\n'.join(answer_lines),
            'confidence_percent': 50,
            'needs_refinement': False,
            'refinement_hint': '',
            'llm_used': False
        }

    url = f'{base_url}/api/templates/{template_id}/execute'
    headers = {
        'Content-Type': 'application/json',
        'X-Api-Key': api_key
    }
    payload = {
        'inputs': {
            'question': question,
            'context_sources': context_text if context_text else 'Nenhum dado encontrado na base interna para esta pergunta.'
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else str(e)
        logger.error(f'[iToca][SAI] HTTPError {getattr(e, "code", None)}: {detail[:400]}')
        raise RuntimeError(f'Erro na API SAI (HTTP {getattr(e, "code", None)}): {detail[:200]}')
    except Exception as e:
        logger.error(f'[iToca][SAI] Erro de conexão: {e}')
        raise RuntimeError(f'Falha ao conectar com a API SAI: {str(e)}')

    # ─── Parsing robusto da resposta da API SAI ───────────────────────────────────────────────
    # A API SAI pode retornar o JSON do LLM de várias formas:
    #   1. JSON direto: {"answer": "...", "confidence_percent": 80, ...}
    #   2. Wrapper com "output": {"output": "{\"answer\":\"...\"}"}
    #   3. Wrapper com "result": {"result": "{\"answer\":\"...\"}"}
    #   4. Wrapper com "text": {"text": "{\"answer\":\"...\"}"}
    #   5. O campo answer já contém um JSON serializado como string
    # ───────────────────────────────────────────────────────────────────────
    logger.debug(f'[iToca][SAI] raw response (primeiros 500 chars): {raw[:500]}')

    def _try_parse_llm_json(text):
        """Tenta extrair o dict com 'answer' de uma string que pode conter JSON em vários níveis."""
        if not text:
            return None
        # Tentativa 1: parse direto
        try:
            obj = json.loads(text.strip())
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        # Tentativa 2: extrai o primeiro objeto JSON da string
        obj = _extract_json_object_from_text(text)
        if obj and isinstance(obj, dict):
            return obj
        return None

    # Passo 1: parse do envelope externo retornado pela API
    outer = _try_parse_llm_json(raw)

    # Passo 2: se o envelope externo não tem 'answer', procura em campos comuns de wrapper
    inner = None
    if outer and isinstance(outer, dict):
        if 'answer' in outer:
            # Caso ideal: o JSON do LLM já está no nível raiz
            inner = outer
        else:
            # Tenta extrair de campos de wrapper conhecidos
            for wrapper_key in ('output', 'result', 'text', 'content', 'response', 'data', 'message'):
                candidate = outer.get(wrapper_key)
                if candidate:
                    if isinstance(candidate, dict) and 'answer' in candidate:
                        inner = candidate
                        break
                    if isinstance(candidate, str):
                        parsed_inner = _try_parse_llm_json(candidate)
                        if parsed_inner and isinstance(parsed_inner, dict) and 'answer' in parsed_inner:
                            inner = parsed_inner
                            break
            # Se ainda não achou, tenta buscar qualquer JSON com 'answer' na string bruta
            if not inner:
                inner = _try_parse_llm_json(raw)
    else:
        # Não conseguiu parsear o envelope; tenta direto na string bruta
        inner = _try_parse_llm_json(raw)

    # Passo 3: verifica se o campo 'answer' em si é um JSON serializado (double-encoding)
    if inner and isinstance(inner, dict):
        raw_answer = inner.get('answer') or ''
        if isinstance(raw_answer, str) and raw_answer.strip().startswith('{'):
            double_parsed = _try_parse_llm_json(raw_answer)
            if double_parsed and isinstance(double_parsed, dict) and 'answer' in double_parsed:
                logger.debug('[iToca][SAI] Detectado double-encoding no campo answer — desencapsulando.')
                inner = double_parsed

    if not inner or not isinstance(inner, dict):
        # Fallback final: tenta extrair o campo 'answer' mesmo de um JSON truncado
        fallback_text = None
        if '"answer"' in raw:
            # Primeiro tenta parse completo
            extracted = _try_parse_llm_json(raw)
            if extracted and isinstance(extracted, dict) and 'answer' in extracted:
                fallback_text = (extracted.get('answer') or '').strip()
            else:
                # JSON truncado: extrai o texto do 'answer' até onde chegou
                partial = _extract_answer_from_partial_json(raw)
                if partial:
                    logger.warning('[iToca][SAI] JSON truncado detectado — usando extração parcial do campo answer.')
                    fallback_text = partial
        if not fallback_text:
            fallback_text = raw.strip()
        # Converte \n literais em quebras de linha
        fallback_text = fallback_text.replace('\\n', '\n')
        return {
            'answer': fallback_text or 'Não foi possível interpretar a resposta do assistente.',
            'confidence_percent': 50,
            'needs_refinement': False,
            'refinement_hint': '',
            'llm_used': True
        }

    # Passo 4: limpa o campo answer de \n literais (sequencia de barra-n) que o LLM pode gerar
    answer_text = (inner.get('answer') or '').strip()
    # Converte \n literais (como string de 2 chars) em quebras de linha reais
    answer_text = answer_text.replace('\\n', '\n')
    # Remove aspas externas se o LLM retornou a string entre aspas
    if answer_text.startswith('"') and answer_text.endswith('"') and len(answer_text) > 2:
        try:
            answer_text = json.loads(answer_text)
        except Exception:
            pass

    if not answer_text:
        answer_text = 'Sem resposta disponível.'

    return {
        'answer': answer_text,
        'confidence_percent': max(0, min(100, int(inner.get('confidence_percent') or 0))),
        'needs_refinement': bool(inner.get('needs_refinement')),
        'refinement_hint': (inner.get('refinement_hint') or '').strip(),
        'llm_used': True
    }


# ─────────────────────────────────────────────────────────────────────────────
# iToca — Detector de Intenção de Ação (segundo LLM SAI)
# ─────────────────────────────────────────────────────────────────────────────

# Tipos de ação reconhecidos e seus rótulos legíveis
_ITOCA_ACTION_LABELS = {
    'kanban_card':          'Criar card no Kanban',
    'activity':             'Registrar atividade com contato',
    'new_contact':          'Adicionar novo contato',
    'environment_mapping':  'Registrar mapeamento de ambiente',
    'wiki_entry':           'Salvar conhecimento no WikiToca',
    'commitment':           'Agendar compromisso',
}


def _itoca_detect_action_intent(question: str, answer: str) -> dict:
    """Chama o segundo LLM SAI (template 69b1c662485ca1e93db65015) para detectar
    se a mensagem do usuário expressa intenção de criar um registro no sistema.

    Retorna um dict com:
        action_type  (str | None)  — tipo da ação detectada ou None
        confidence   (float)       — 0.0 a 1.0
        label        (str)         — rótulo legível da ação
        fields       (dict)        — campos extraídos pelo LLM
        raw          (str)         — resposta bruta da API (para debug)
    """
    try:
        settings_map = _load_app_settings_map([
            'itoca_sai_api_key',
            'itoca_sai_base_url',
            'itoca_action_detector_template_id'
        ])
        api_key = (settings_map.get('itoca_sai_api_key') or '').strip() \
                  or (os.environ.get('ITOCA_SAI_API_KEY', '') or '').strip()
        base_url = (settings_map.get('itoca_sai_base_url') or '').strip() \
                   or 'https://sai-library.saiapplications.com'
        template_id = (settings_map.get('itoca_action_detector_template_id') or '').strip() \
                      or '69b1c662485ca1e93db65015'

        if not api_key:
            logger.debug('[iToca][ActionDetector] API key não configurada — detector desativado.')
            return {'action_type': None, 'confidence': 0.0, 'label': '', 'fields': {}, 'raw': ''}

        url = f'{base_url}/api/templates/{template_id}/execute'
        headers = {
            'Content-Type': 'application/json',
            'X-Api-Key': api_key
        }
        payload = {
            'inputs': {
                'question': question[:1000],   # limita para não inflar o payload
                'answer': answer[:1000]
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')

        parsed = _extract_json_object_from_text(raw)
        if not parsed or not isinstance(parsed, dict):
            logger.warning(f'[iToca][ActionDetector] Resposta não-JSON: {raw[:200]}')
            return {'action_type': None, 'confidence': 0.0, 'label': '', 'fields': {}, 'raw': raw}

        action_type = (parsed.get('action_type') or '').strip().lower()
        if action_type in ('none', '', 'null'):
            action_type = None

        # Valida que o tipo retornado é um dos reconhecidos
        if action_type and action_type not in _ITOCA_ACTION_LABELS:
            logger.warning(f'[iToca][ActionDetector] Tipo desconhecido: {action_type!r}')
            action_type = None

        confidence = float(parsed.get('confidence') or 0.0)
        fields = parsed.get('fields') or {}
        if not isinstance(fields, dict):
            fields = {}

        label = _ITOCA_ACTION_LABELS.get(action_type, '') if action_type else ''

        logger.info(f'[iToca][ActionDetector] action={action_type!r} confidence={confidence:.2f} fields={list(fields.keys())}')
        return {
            'action_type': action_type,
            'confidence': confidence,
            'label': label,
            'fields': fields,
            'raw': raw
        }

    except Exception as e:
        logger.warning(f'[iToca][ActionDetector] Erro ao detectar intenção: {e}')
        return {'action_type': None, 'confidence': 0.0, 'label': '', 'fields': {}, 'raw': ''}


def ensure_account_for_company(cursor, company_name):
    name = (company_name or '').strip()
    if not name:
        return None
    cursor.execute('SELECT id FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))', (name,))
    row = cursor.fetchone()
    if row:
        return row['id'] if isinstance(row, sqlite3.Row) else row[0]
    cursor.execute('INSERT INTO accounts (name, updated_at) VALUES (?, CURRENT_TIMESTAMP)', (name,))
    return cursor.lastrowid


def sync_accounts_from_clients():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT company FROM clients WHERE company IS NOT NULL AND TRIM(company) != ""')
        companies = [row['company'] for row in c.fetchall()]
        for company in companies:
            ensure_account_for_company(c, company)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[WARN] sync_accounts_from_clients: {e}')



sync_accounts_from_clients()


def _normalize_automapping_key(company, country, industry):
    def clean(v):
        return re.sub(r'\s+', ' ', (v or '').strip().lower())
    return f"{clean(company)}|{clean(country)}|{clean(industry)}"


def _extract_tavily_evidence(results, max_items=5):
    evidences = []
    seen_urls = set()
    for item in (results or []):
        url = (item.get('url') or '').strip()
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        snippet = (item.get('content') or item.get('snippet') or '').strip()
        title = (item.get('title') or '').strip()
        score = item.get('score')
        if title and snippet:
            snippet = f"{title}: {snippet}"
        evidences.append({
            'url': url,
            'snippet': snippet[:500],
            'title': title,
            'score': score
        })
        if len(evidences) >= max_items:
            break
    return evidences


def _detect_keywords_in_evidence(evidence, keywords):
    haystack = ' '.join([(e.get('snippet') or '').lower() for e in evidence])
    return [kw for kw in keywords if kw in haystack]


def _build_automapping_search_plan(company, country, industry):
    company_hint = f'"{company}"'
    base_context = f'{industry} {country}'
    return {
        'cloud': {
            'type': 'value',
            'keywords': ['aws', 'azure', 'microsoft azure', 'google cloud', 'gcp', 'oracle cloud', 'nuvem'],
            'query': f'{company_hint} {base_context} infraestrutura cloud provedor de nuvem aws azure gcp'
        },
        'erp': {
            'type': 'value',
            'keywords': ['sap', 'oracle erp', 'totvs', 'protheus', 'microsoft dynamics', 's/4hana'],
            'query': f'{company_hint} {base_context} sistema erp sap totvs oracle dynamics'
        },
        'crm': {
            'type': 'value',
            'keywords': ['salesforce', 'hubspot', 'dynamics 365', 'zoho crm', 'crm'],
            'query': f'{company_hint} {base_context} crm salesforce hubspot dynamics 365'
        },
        'observability': {
            'type': 'tools',
            'keywords': ['datadog', 'splunk', 'new relic', 'dynatrace', 'grafana', 'observability', 'observabilidade'],
            'query': f'{company_hint} {base_context} observabilidade datadog splunk dynatrace grafana'
        },
        'security': {
            'type': 'tools',
            'keywords': ['crowdstrike', 'palo alto', 'sentinelone', 'fortinet', 'okta', 'siem', 'edr', 'xdr'],
            'query': f'{company_hint} {base_context} cibersegurança siem edr xdr crowdstrike fortinet palo alto'
        },
        'data_analytics': {
            'type': 'tools',
            'keywords': ['snowflake', 'databricks', 'power bi', 'tableau', 'bigquery', 'data lake', 'analytics'],
            'query': f'{company_hint} {base_context} analytics bi power bi tableau databricks snowflake'
        },
        'ai': {
            'type': 'tools',
            'keywords': ['openai', 'copilot', 'gemini', 'claude', 'machine learning', 'ia generativa', 'inteligência artificial'],
            'query': f'{company_hint} {base_context} inteligência artificial ia generativa openai copilot gemini'
        }
    }


def _calculate_section_confidence(evidence, matched_keywords):
    evidence_count = len(evidence or [])
    keyword_hits = len(matched_keywords or [])
    if evidence_count == 0:
        return 'unknown'
    if keyword_hits >= 2:
        return 'high'
    if keyword_hits == 1:
        return 'medium'
    if evidence_count >= 3:
        return 'low'
    return 'unknown'


def _calculate_evidence_quality(evidence):
    if not evidence:
        return 0
    quality = 0
    for ev in evidence:
        url = (ev.get('url') or '').lower()
        snippet = (ev.get('snippet') or '')
        if url.startswith('https://'):
            quality += 2
        if any(domain in url for domain in ['.gov', '.edu', 'microsoft.com', 'oracle.com', 'sap.com', 'aws.amazon.com', 'salesforce.com']):
            quality += 2
        if len(snippet) >= 120:
            quality += 1
    return quality


def _build_section_result(section_key, section_cfg, evidence, error_message=None):
    matched_keywords = _detect_keywords_in_evidence(evidence, section_cfg['keywords'])
    confidence = _calculate_section_confidence(evidence, matched_keywords)
    status = 'identified' if matched_keywords else ('investigate' if evidence else 'unknown')

    if error_message:
        status = 'error'
        confidence = 'unknown'

    evidence_quality = _calculate_evidence_quality(evidence)

    base = {
        'status': status,
        'confidence': confidence,
        'evidence': evidence,
        'matched_keywords': matched_keywords,
        'query_used': section_cfg['query'],
        'evidence_quality': evidence_quality,
        'error': error_message
    }

    if section_cfg['type'] == 'value':
        value = ', '.join(matched_keywords) if matched_keywords else 'Não identificado'
        base['value'] = value
        if section_key in {'cloud', 'erp', 'crm'}:
            base['partners'] = []
    else:
        base['tools'] = matched_keywords

    return base


def _build_automapping_sections(company, country, industry, search_results_by_section, section_errors=None):
    plan = _build_automapping_search_plan(company, country, industry)
    sections = {}
    section_errors = section_errors or {}
    for section_key, section_cfg in plan.items():
        raw_results = search_results_by_section.get(section_key, [])
        evidence = _extract_tavily_evidence(raw_results, max_items=4)
        sections[section_key] = _build_section_result(section_key, section_cfg, evidence, section_errors.get(section_key))
    return sections


def _build_automapping_payload(company, country, industry, search_results_by_section, section_errors=None, execution_meta=None):
    sections = _build_automapping_sections(company, country, industry, search_results_by_section, section_errors)
    identified_sections = [k for k, v in sections.items() if v.get('status') == 'identified']
    error_sections = [k for k, v in sections.items() if v.get('status') == 'error']
    return {
        'schema_version': '2.0',
        'company': company,
        'country': country,
        'industry': industry,
        'sections': sections,
        'execution_summary': {
            'identified_sections_count': len(identified_sections),
            'error_sections_count': len(error_sections),
            'identified_sections': identified_sections,
            'error_sections': error_sections,
            'mode': 'partial' if error_sections else 'complete'
        },
        'strategic_reading': {
            'competitive_space': [],
            'lock_in_risk': [],
            'entry_points': []
        },
        'execution_meta': execution_meta or {},
        'generated_at': datetime.utcnow().isoformat() + 'Z'
    }


def _run_tavily_request(api_key, query, max_results=6):
    payload = {
        'api_key': api_key,
        'query': query,
        'search_depth': 'advanced',
        'max_results': max_results,
        'include_answer': False,
        'include_raw_content': False
    }

    req = urllib.request.Request(
        'https://api.tavily.com/search',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data.get('results') or []


def _run_tavily_search(company, country, industry):
    api_key = _resolve_setting('tavily_api_key', 'TAVILY_API_KEY')
    if not api_key:
        raise RuntimeError('A chave da Tavily não está configurada. Configure em Configurações > Integrações ou defina TAVILY_API_KEY no ambiente.')

    plan = _build_automapping_search_plan(company, country, industry)
    all_results = {}
    section_errors = {}
    attempts_by_section = {}

    for section_key, section_cfg in plan.items():
        max_attempts = 2
        attempts = 0
        last_error = None
        while attempts < max_attempts:
            attempts += 1
            try:
                all_results[section_key] = _run_tavily_request(api_key, section_cfg['query'])
                last_error = None
                break
            except Exception as e:
                last_error = str(e)
                if attempts < max_attempts:
                    time.sleep(0.4 * attempts)
        attempts_by_section[section_key] = attempts
        if last_error is not None:
            section_errors[section_key] = f'Falha ao consultar provider: {last_error[:180]}'
            all_results[section_key] = []

    execution_meta = {
        'provider': 'tavily',
        'attempts_by_section': attempts_by_section,
        'searched_sections_count': len(plan)
    }
    return all_results, section_errors, execution_meta




def _default_llm_summary(sections):
    summary = {}
    for section_key in (sections or {}).keys():
        summary[section_key] = {
            'final_answer': 'Inconclusivo com as evidências atuais.',
            'confidence_percent': 20,
            'certainty': 'uncertain',
            'reasoning': 'Não houve evidência específica suficiente para consolidar uma resposta final.'
        }
    return summary


def _extract_answer_from_partial_json(text):
    """Extrai o valor do campo 'answer' de um JSON potencialmente truncado.
    Útil quando a API retorna um JSON incompleto (cortado no meio).
    Estratégia: encontra '"answer"' na string, pula o ':', lê o valor da string
    até encontrar um '"' de fechamento não escapado.
    """
    if not text:
        return None
    # Procura a chave 'answer' no texto
    key_pos = text.find('"answer"')
    if key_pos == -1:
        return None
    # Avança até o ':'
    colon_pos = text.find(':', key_pos + 8)
    if colon_pos == -1:
        return None
    # Avança até a abertura da string de valor
    value_start = text.find('"', colon_pos + 1)
    if value_start == -1:
        return None
    # Lê a string até o fechamento (respeitando escapes)
    chars = []
    i = value_start + 1
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            # Caractere escapado
            next_ch = text[i + 1]
            if next_ch == 'n':
                chars.append('\n')
            elif next_ch == 't':
                chars.append('\t')
            elif next_ch == 'r':
                chars.append('\r')
            elif next_ch == '"':
                chars.append('"')
            elif next_ch == '\\':
                chars.append('\\')
            else:
                chars.append(next_ch)
            i += 2
            continue
        if ch == '"':
            # Fim da string — retorna o que foi lido até aqui
            return ''.join(chars).strip()
        chars.append(ch)
        i += 1
    # JSON truncado: retorna o que foi lido até o fim do texto
    result = ''.join(chars).strip()
    return result if result else None


def _extract_json_object_from_text(text):
    """Extrai o primeiro objeto JSON válido de uma string usando balanceamento de chaves.
    Mais robusto que rfind('}') para JSONs aninhados ou com múltiplos objetos.
    Também tenta detectar e limpar prefixos de texto antes do JSON.
    """
    if not text:
        return None
    # Tenta parse direto primeiro (caso mais comum e mais rápido)
    stripped = text.strip()
    if stripped.startswith('{'):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # Busca o primeiro '{' e tenta balancear as chaves
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                chunk = text[start:i+1]
                try:
                    return json.loads(chunk)
                except Exception:
                    # Se falhou, tenta o próximo '{'
                    next_start = text.find('{', start + 1)
                    if next_start == -1:
                        return None
                    start = next_start
                    depth = 0
                    in_string = False
                    escape_next = False
    return None


def _validate_openrouter_api_key(api_key):
    key = (api_key or '').strip()
    if not key:
        return False, 'OPENROUTER_API_KEY vazia.'
    # Formato mais comum das chaves OpenRouter: sk-or-v1-...
    if key.startswith('sk-or-'):
        return True, ''
    return False, 'OPENROUTER_API_KEY com formato inválido (esperado prefixo sk-or-).'


def _run_openrouter_synthesis(result_payload):
    settings_map = _load_app_settings_map([
        'openrouter_model',
        'openrouter_site_url',
        'openrouter_app_name'
    ])

    api_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
    if not api_key:
        raise RuntimeError('A chave da OpenRouter não está configurada. Configure em Configurações > Integrações ou defina OPENROUTER_API_KEY no ambiente.')

    key_ok, key_msg = _validate_openrouter_api_key(api_key)
    if not key_ok:
        raise RuntimeError(f'Chave OpenRouter inválida: {key_msg}')

    model = (settings_map.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
    site_url = (settings_map.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
    app_name = (settings_map.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
    sections = result_payload.get('sections') or {}

    compact_sections = {}
    for section_key, section_data in sections.items():
        evidence = section_data.get('evidence') or []
        compact_sections[section_key] = {
            'status': section_data.get('status'),
            'confidence': section_data.get('confidence'),
            'matched_keywords': section_data.get('matched_keywords') or [],
            'query_used': section_data.get('query_used'),
            'evidence': [
                {'url': ev.get('url'), 'snippet': (ev.get('snippet') or '')[:280]}
                for ev in evidence[:2]
            ]
        }

    user_payload = {
        'company': result_payload.get('company'),
        'country': result_payload.get('country'),
        'industry': result_payload.get('industry'),
        'sections': compact_sections
    }

    system_prompt = (
        'Você é um analista técnico corporativo extremamente conservador com alucinações. '
        'Responda APENAS em JSON válido. Para cada seção, gere UMA resposta final amigável em português. '
        'Se não houver evidência forte e específica da empresa, responda com incerteza ao invés de inventar. '
        'confidence_percent deve ser inteiro de 0 a 100. '
        'Formato obrigatório: '
        '{"sections":{"cloud":{"final_answer":"...","confidence_percent":0,"certainty":"confirmed|uncertain","reasoning":"..."}, ...}}'
    )

    request_payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)}
        ],
        'temperature': 0.1
    }

    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(request_payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': site_url,
            'X-Title': app_name
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else str(e)
        diagnostics = {
            'status': getattr(e, 'code', None),
            'model': model,
            'has_api_key': bool(api_key),
            'api_key_prefix': api_key[:7] if api_key else '',
            'sent_headers': ['Content-Type', 'Authorization', 'HTTP-Referer', 'X-Title']
        }
        print(f'[ERROR][OpenRouter] HTTPError diagnostics={diagnostics} body={detail[:500]}')
        hint = ' Verifique se OPENROUTER_API_KEY é a chave da OpenRouter (prefixo sk-or-) e se foi exportada no mesmo terminal do app.' if diagnostics.get('status') == 401 else ''
        raise RuntimeError(f'OpenRouter HTTP {diagnostics["status"]} - body: {detail[:400]} | diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}{hint}')
    except Exception as e:
        diagnostics = {
            'model': model,
            'has_api_key': bool(api_key),
            'api_key_prefix': api_key[:7] if api_key else ''
        }
        print(f'[ERROR][OpenRouter] Exception diagnostics={diagnostics} error={e}')
        raise RuntimeError(f'Falha inesperada OpenRouter: {str(e)} | diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}')

    choices = data.get('choices') or []
    message_content = ''
    if choices:
        content = ((choices[0] or {}).get('message') or {}).get('content')
        if isinstance(content, list):
            message_content = ''.join([part.get('text', '') for part in content if isinstance(part, dict)])
        else:
            message_content = str(content or '')

    parsed = _extract_json_object_from_text(message_content)
    llm_sections = ((parsed or {}).get('sections') or {}) if isinstance(parsed, dict) else {}

    final_sections = _default_llm_summary(sections)
    for section_key in final_sections.keys():
        candidate = llm_sections.get(section_key)
        if not isinstance(candidate, dict):
            continue
        answer = (candidate.get('final_answer') or '').strip() or final_sections[section_key]['final_answer']
        reasoning = (candidate.get('reasoning') or '').strip() or final_sections[section_key]['reasoning']
        certainty = candidate.get('certainty') if candidate.get('certainty') in {'confirmed', 'uncertain'} else 'uncertain'
        try:
            confidence = int(candidate.get('confidence_percent'))
        except Exception:
            confidence = final_sections[section_key]['confidence_percent']
        confidence = max(0, min(100, confidence))

        final_sections[section_key] = {
            'final_answer': answer,
            'confidence_percent': confidence,
            'certainty': certainty,
            'reasoning': reasoning
        }

    meta = {
        'provider': 'openrouter',
        'model': model,
        'raw_response_received': bool(message_content)
    }
    return final_sections, meta

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


@app.route('/api/transcribe-audio', methods=['POST', 'OPTIONS'])
@app.route('/api/transcribe-audio/', methods=['POST', 'OPTIONS'])
def transcribe_audio():
    if request.method == 'OPTIONS':
        return ('', 204)

    if TRANSCRIPTION_DEBUG:
        print('[Transcription][DEBUG] Requisição recebida em /api/transcribe-audio')
        print(f"[Transcription][DEBUG] Content-Type: {request.content_type}")
        print(f"[Transcription][DEBUG] Content-Length: {request.content_length}")

    if not WHISPER_AVAILABLE:
        details = f' ({WHISPER_IMPORT_ERROR})' if WHISPER_IMPORT_ERROR else ''
        print(f'[Transcription][ERROR] Biblioteca faster-whisper indisponível neste ambiente{details}.')
        return jsonify({'error': 'Biblioteca faster-whisper não está disponível neste ambiente.'}), 503

    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({'error': 'Arquivo de áudio não enviado.'}), 400

    ffmpeg_path = configure_ffmpeg_for_whisper()
    if TRANSCRIPTION_DEBUG and not ffmpeg_path:
        print('[Transcription][DEBUG] FFmpeg externo não encontrado; continuando com decoder da stack local.')

    suffix = Path(audio_file.filename or 'audio.webm').suffix or '.webm'
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio_file.save(tmp)
            temp_path = tmp.name

        if TRANSCRIPTION_DEBUG:
            print(f"[Transcription][DEBUG] Arquivo salvo temporariamente: {temp_path}")
            print(f"[Transcription][DEBUG] Nome original: {audio_file.filename}")
            print(f"[Transcription][DEBUG] FFmpeg em uso: {ffmpeg_path or 'decoder interno'}")

        model = get_whisper_model()
        if model is None:
            details = f' ({WHISPER_IMPORT_ERROR})' if WHISPER_IMPORT_ERROR else ''
            return jsonify({'error': f'Backend de transcrição indisponível{details}.'}), 503
        segments, _ = model.transcribe(temp_path, language='pt')
        text = ''.join(segment.text for segment in segments).strip()

        if TRANSCRIPTION_DEBUG:
            print(f"[Transcription][DEBUG] Texto transcrito (primeiros 200 chars): {text[:200]}")

        return jsonify({'text': text})
    except Exception as e:
        print(f'[Transcription][ERROR] POST /api/transcribe-audio: {e}')
        if TRANSCRIPTION_DEBUG:
            traceback.print_exc()
        return jsonify({'error': f'Falha ao transcrever áudio com faster-whisper: {e}'}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
            if TRANSCRIPTION_DEBUG:
                print(f"[Transcription][DEBUG] Arquivo temporário removido: {temp_path}")

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


@app.route('/api/autotoca/mala-direta/positions', methods=['GET'])
def get_autotoca_mailing_positions():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT position FROM clients WHERE position IS NOT NULL AND TRIM(position) != "" ORDER BY position COLLATE NOCASE')
        positions = [row['position'] for row in c.fetchall()]
        conn.close()
        return jsonify(positions)
    except Exception as e:
        print(f'[ERROR] GET /api/autotoca/mala-direta/positions: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/mala-direta/areas', methods=['GET'])
def get_autotoca_mailing_areas():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT DISTINCT area_of_activity FROM clients WHERE area_of_activity IS NOT NULL AND TRIM(area_of_activity) != "" ORDER BY area_of_activity COLLATE NOCASE')
        areas = [row['area_of_activity'] for row in c.fetchall()]
        conn.close()
        return jsonify(areas)
    except Exception as e:
        print(f'[ERROR] GET /api/autotoca/mala-direta/areas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/empresas', methods=['GET'])
def get_companies():
    try:
        sync_accounts_from_clients()
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT name, COALESCE(is_target, 0) as is_target FROM accounts
                     WHERE name IS NOT NULL AND TRIM(name) != ''
                     ORDER BY COALESCE(is_target, 0) DESC, name COLLATE NOCASE''')
        companies = [row['name'] for row in c.fetchall()]
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


@app.route('/api/config/integrations', methods=['GET'])
def get_integrations_config():
    try:
        settings_map = _load_app_settings_map([
            'tavily_api_key',
            'openrouter_api_key',
            'openrouter_model',
            'openrouter_site_url',
            'openrouter_app_name',
            'itoca_sai_api_key',
            'itoca_sai_template_id',
            'itoca_sai_base_url'
        ])

        tavily_key = (settings_map.get('tavily_api_key') or '').strip() or (os.environ.get('TAVILY_API_KEY', '') or '').strip()
        openrouter_key = (settings_map.get('openrouter_api_key') or '').strip() or (os.environ.get('OPENROUTER_API_KEY', '') or '').strip()
        model = (settings_map.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
        site_url = (settings_map.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
        app_name = (settings_map.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
        itoca_sai_key = (settings_map.get('itoca_sai_api_key') or '').strip() or (os.environ.get('ITOCA_SAI_API_KEY', '') or '').strip()
        itoca_sai_template_id = (settings_map.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
        itoca_sai_base_url = (settings_map.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

        return jsonify({
            'tavily_configured': bool(tavily_key),
            'tavily_key_preview': tavily_key[:6] + '...' if tavily_key else '',
            'openrouter_configured': bool(openrouter_key),
            'openrouter_key_preview': openrouter_key[:9] + '...' if openrouter_key else '',
            'openrouter_model': model,
            'openrouter_site_url': site_url,
            'openrouter_app_name': app_name,
            'itoca_sai_configured': bool(itoca_sai_key),
            'itoca_sai_key_preview': itoca_sai_key[:6] + '...' if itoca_sai_key else '',
            'itoca_sai_template_id': itoca_sai_template_id,
            'itoca_sai_base_url': itoca_sai_base_url
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/integrations: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/integrations', methods=['PUT'])
def save_integrations_config():
    try:
        data = request.get_json() or {}
        tavily_api_key = (data.get('tavily_api_key') or '').strip()
        openrouter_api_key = (data.get('openrouter_api_key') or '').strip()
        openrouter_model = (data.get('openrouter_model') or '').strip() or 'stepfun/step-3.5-flash:free'
        openrouter_site_url = (data.get('openrouter_site_url') or '').strip() or 'http://localhost'
        openrouter_app_name = (data.get('openrouter_app_name') or '').strip() or 'TocaDoCoelho'
        itoca_sai_api_key = (data.get('itoca_sai_api_key') or '').strip()
        itoca_sai_template_id = (data.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
        itoca_sai_base_url = (data.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

        if openrouter_api_key:
            key_ok, key_msg = _validate_openrouter_api_key(openrouter_api_key)
            if not key_ok:
                return jsonify({'error': f'OpenRouter inválida: {key_msg}'}), 400

        conn = get_db()
        c = conn.cursor()
        updates = [
            ('tavily_api_key', tavily_api_key),
            ('openrouter_api_key', openrouter_api_key),
            ('openrouter_model', openrouter_model),
            ('openrouter_site_url', openrouter_site_url),
            ('openrouter_app_name', openrouter_app_name),
            ('itoca_sai_api_key', itoca_sai_api_key),
            ('itoca_sai_template_id', itoca_sai_template_id),
            ('itoca_sai_base_url', itoca_sai_base_url)
        ]
        for key, value in updates:
            c.execute(
                'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                (key, value)
            )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Integrações salvas com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/integrations: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/config/update-source', methods=['GET'])
def get_update_source_config():
    try:
        settings_map = _load_app_settings_map(['update_github_owner', 'update_github_repo'])
        owner = (settings_map.get('update_github_owner') or DEFAULT_GITHUB_OWNER or '').strip()
        repo = (settings_map.get('update_github_repo') or DEFAULT_GITHUB_REPO or '').strip()
        return jsonify({
            'current_version': APP_VERSION,
            'github_owner': owner,
            'github_repo': repo,
            'configured': bool(owner and repo)
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/update-source: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/update-source', methods=['PUT'])
def save_update_source_config():
    try:
        data = request.get_json() or {}
        owner = (data.get('github_owner') or '').strip()
        repo = (data.get('github_repo') or '').strip()

        conn = get_db()
        c = conn.cursor()
        updates = [
            ('update_github_owner', owner),
            ('update_github_repo', repo)
        ]
        for key, value in updates:
            c.execute(
                'INSERT INTO app_settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                (key, value)
            )
        conn.commit()
        conn.close()

        return jsonify({'message': 'Fonte de atualização salva com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/config/update-source: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/check-updates', methods=['GET'])
def check_updates():
    try:
        settings_map = _load_app_settings_map(['update_github_owner', 'update_github_repo'])
        owner = (settings_map.get('update_github_owner') or DEFAULT_GITHUB_OWNER or '').strip()
        repo = (settings_map.get('update_github_repo') or DEFAULT_GITHUB_REPO or '').strip()

        if not owner or not repo:
            return jsonify({
                'update_available': False,
                'configured': False,
                'current_version': APP_VERSION,
                'message': 'Configure GitHub Owner e Repositório em Configurações para verificar updates.'
            }), 400

        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
        req = urllib.request.Request(api_url, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'TocaDoCoelho-Updater'
        })
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8'))

        latest_tag = (payload.get('tag_name') or '').strip()
        latest_version = _normalize_version(latest_tag)
        current_version = _normalize_version(APP_VERSION)

        if not latest_version:
            return jsonify({'error': 'Tag da release mais recente está vazia no GitHub.'}), 502

        update_available = _version_key(latest_version) > _version_key(current_version)
        return jsonify({
            'configured': True,
            'github_owner': owner,
            'github_repo': repo,
            'current_version': current_version,
            'latest_version': latest_version,
            'latest_tag': latest_tag,
            'update_available': update_available,
            'release_name': payload.get('name') or latest_tag,
            'release_notes': payload.get('body') or '',
            'html_url': payload.get('html_url') or '',
            'published_at': payload.get('published_at')
        })
    except urllib.error.HTTPError as e:
        logger.exception(f'[ERROR] GET /api/config/check-updates (HTTP): {e}')
        if e.code == 404:
            return jsonify({'error': 'Nenhuma release encontrada nesse repositório ou repositório inválido.'}), 404
        if e.code == 403:
            return jsonify({'error': 'GitHub API limit atingido temporariamente. Tente novamente mais tarde.'}), 429
        return jsonify({'error': f'Falha ao consultar GitHub Releases (HTTP {e.code}).'}), 502
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/check-updates: {e}')
        return jsonify({'error': f'Erro ao verificar updates: {e}'}), 500

@app.route('/api/config/startup', methods=['GET'])
def get_startup_config():
    if sys.platform != 'win32':
        return jsonify({'enabled': False, 'supported': False})
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, 'TocaDoCoelho')
            enabled = True
        except FileNotFoundError:
            enabled = False
        finally:
            winreg.CloseKey(key)
        return jsonify({'enabled': enabled, 'supported': True})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/config/startup: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/startup', methods=['POST'])
def set_startup_config():
    if sys.platform != 'win32':
        return jsonify({'error': 'Não suportado nesta plataforma.'}), 400
    try:
        data = request.get_json() or {}
        enable = bool(data.get('enabled', False))
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        if enable:
            exe_path = str(Path(sys.executable).resolve())
            winreg.SetValueEx(key, 'TocaDoCoelho', 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, 'TocaDoCoelho')
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return jsonify({'enabled': enable, 'message': 'Configuração salva com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/config/startup: {e}')
        return jsonify({'error': str(e)}), 500


def _outlook_fetch_via_powershell(days=60):
    """
    Lê emails do Outlook via PowerShell (compatível com Office C2R/365).
    PowerShell corre em 64-bit e tem acesso nativo ao COM do Click-to-Run.
    Retorna lista de dicts no formato de _outlook_extract_email().
    """
    import subprocess, tempfile, json, os

    ps_script = """\
param([int]$Days = 60)
$ErrorActionPreference = 'Continue'
$cutoff = (Get-Date).AddDays(-$Days)

function Get-SmtpAddress($r) {
    $a = $null; try { $a = $r.Address } catch {}
    if ($a -and $a -match '@' -and $a -notmatch '^/o=') { return $a.ToLower() }
    try { return ($r.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E')).ToLower() } catch {}
    return ''
}

function Get-SenderSmtp($m) {
    $a = $null; try { $a = $m.SenderEmailAddress } catch {}
    if ($a -and $a -match '@' -and $a -notmatch '^/o=') { return $a.ToLower() }
    try { return ($m.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x5D01001E')).ToLower() } catch {}
    return ''
}

function Get-AllFolders($folder) {
    $list = [System.Collections.Generic.List[object]]::new()
    $list.Add($folder)
    try { foreach ($s in $folder.Folders) { (Get-AllFolders $s) | ForEach-Object { $list.Add($_) } } } catch {}
    return ,$list
}

function Make-Item($item, $dt, $dir) {
    $rcpts = [System.Collections.Generic.List[hashtable]]::new()
    try { foreach ($r in $item.Recipients) { try { $rcpts.Add(@{ name=($r.Name+''); email=(Get-SmtpAddress $r) }) } catch {} } } catch {}
    $bp = ''
    try { $bp = ($item.Body -replace '[\\r\\n\\t]+',' ').Trim(); if ($bp.Length -gt 1500) { $bp = $bp.Substring(0,1500) } } catch {}
    return [PSCustomObject]@{
        subject      = ($item.Subject+'')
        date         = $dt.ToString('yyyy-MM-ddTHH:mm:ss')
        direction    = $dir
        sender       = @{ name=($item.SenderName+''); email=(Get-SenderSmtp $item) }
        recipients   = @($rcpts)
        body_preview = $bp
    }
}

$ol = $null
try {
    $ol = [System.Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
} catch {
    try { $ol = New-Object -ComObject Outlook.Application } catch {
        [Console]::Error.WriteLine("Nao foi possivel conectar ao Outlook: $_")
        exit 1
    }
}
$ns = $ol.GetNamespace('MAPI')
$results = [System.Collections.Generic.List[object]]::new()

try {
    $inbox = $ns.GetDefaultFolder(6)
    foreach ($folder in (Get-AllFolders $inbox)) {
        try {
            foreach ($item in $folder.Items) {
                try {
                    if ($item.Class -ne 43) { continue }
                    $dt = $null; try { $dt = $item.ReceivedTime } catch { continue }
                    if ($dt -lt $cutoff) { continue }
                    $results.Add((Make-Item $item $dt 'received'))
                } catch {}
            }
        } catch {}
    }
} catch { [Console]::Error.WriteLine("Erro inbox: $_") }

try {
    $sent = $ns.GetDefaultFolder(5)
    foreach ($item in $sent.Items) {
        try {
            if ($item.Class -ne 43) { continue }
            $dt = $null; try { $dt = $item.SentOn } catch { continue }
            if ($dt -lt $cutoff) { continue }
            $results.Add((Make-Item $item $dt 'sent'))
        } catch {}
    }
} catch { [Console]::Error.WriteLine("Erro sent: $_") }

if ($results.Count -eq 0) { '[]'; exit 0 }
$results | ConvertTo-Json -Depth 5 -Compress
"""

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ps1', delete=False, encoding='utf-8', errors='replace'
        ) as tmp:
            tmp.write(ps_script)
            tmp_path = tmp.name

        try:
            proc = subprocess.run(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-NoProfile',
                 '-File', tmp_path, '-Days', str(int(days))],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=300
            )
        except subprocess.TimeoutExpired as timeout_err:
            raise RuntimeError(
                'A leitura via Outlook COM excedeu 300s sem retorno. '
                'Não foi possível confirmar processamento parcial; tente reduzir o período '
                '(ex.: days=7), usar OUTLOOK_CONNECTOR_MODE=graph, ou configurar OAuth Graph.'
            ) from timeout_err
        stderr = (proc.stderr or '').strip()
        stdout = (proc.stdout or '').strip()
        if proc.returncode != 0 and not stdout:
            raise RuntimeError(stderr or f'PowerShell retornou código {proc.returncode}')
        if not stdout or stdout == '[]':
            return []
        data = json.loads(stdout)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            rcpts = item.get('recipients') or []
            if isinstance(rcpts, dict):
                rcpts = [rcpts]
            item['recipients'] = rcpts
            if not isinstance(item.get('sender'), dict):
                item['sender'] = {'name': '', 'email': ''}
        return data
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _outlook_extract_smtp_from_recipient(recipient):
    """Extrai endereço SMTP de um recipient do Outlook (trata Exchange/EX)."""
    try:
        addr = (recipient.Address or '').strip().lower()
        if addr and '@' in addr and not addr.startswith('/o='):
            return addr
        return recipient.PropertyAccessor.GetProperty(
            'http://schemas.microsoft.com/mapi/proptag/0x39FE001E'
        ).strip().lower()
    except Exception:
        return ''


def _outlook_extract_smtp_from_sender(mail_item):
    """Extrai endereço SMTP do remetente (trata Exchange/EX)."""
    try:
        addr = (mail_item.SenderEmailAddress or '').strip().lower()
        if addr and '@' in addr and not addr.startswith('/o='):
            return addr
        return mail_item.PropertyAccessor.GetProperty(
            'http://schemas.microsoft.com/mapi/proptag/0x5D01001E'
        ).strip().lower()
    except Exception:
        return ''


def _outlook_get_all_subfolders(folder):
    result = [folder]
    try:
        for sub in folder.Folders:
            result.extend(_outlook_get_all_subfolders(sub))
    except Exception:
        pass
    return result


def _outlook_extract_email(item, direction, cutoff_dt):
    """Extrai metadados de um MailItem. Retorna dict ou None."""
    try:
        if item.Class != 43:  # 43 = olMail
            return None
        raw_dt = item.ReceivedTime if direction == 'received' else item.SentOn
        dt = datetime(raw_dt.year, raw_dt.month, raw_dt.day,
                      raw_dt.hour, raw_dt.minute, raw_dt.second)
        if dt < cutoff_dt:
            return None
        recipients = []
        try:
            for r in item.Recipients:
                try:
                    email = _outlook_extract_smtp_from_recipient(r)
                    recipients.append({'name': (r.Name or '').strip(), 'email': email})
                except Exception:
                    pass
        except Exception:
            pass
        body_preview = ''
        try:
            body_preview = (item.Body or '')[:1500].strip()
        except Exception:
            pass
        return {
            'subject': (item.Subject or '').strip(),
            'date': dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'direction': direction,
            'sender': {
                'name': (item.SenderName or '').strip(),
                'email': _outlook_extract_smtp_from_sender(item)
            },
            'recipients': recipients,
            'body_preview': body_preview
        }
    except Exception:
        return None


def _outlook_process_folder(folder, direction, cutoff_dt, emails):
    count = 0
    try:
        items = folder.Items
        date_str = cutoff_dt.strftime('%m/%d/%Y %H:%M %p')
        field = 'ReceivedTime' if direction == 'received' else 'SentOn'
        try:
            items = items.Restrict(f"[{field}] >= '{date_str}'")
        except Exception:
            pass
        for item in items:
            try:
                data = _outlook_extract_email(item, direction, cutoff_dt)
                if data:
                    emails.append(data)
                    count += 1
            except Exception:
                pass
    except Exception:
        pass
    return count


def _outlook_import_emails(emails_data, conn):
    """
    Importa lista de emails já extraídos para o banco.
    Retorna (imported, skipped_duplicates, skipped_no_match).
    """
    c = conn.cursor()
    c.execute('SELECT id, email FROM clients WHERE email IS NOT NULL AND TRIM(email) != ""')
    email_to_client = {}
    for row in c.fetchall():
        normalized = (row['email'] or '').strip().lower()
        if normalized:
            email_to_client[normalized] = row['id']

    imported = 0
    skipped_duplicates = 0
    skipped_no_match = 0

    for email_data in emails_data:
        subject = (email_data.get('subject') or '').strip()
        email_date = (email_data.get('date') or '').strip()
        direction = email_data.get('direction', 'received')
        sender = email_data.get('sender') or {}
        recipients = email_data.get('recipients') or []
        body_preview = (email_data.get('body_preview') or '').strip()

        if not email_date:
            continue

        if direction == 'received':
            candidates = [sender] if sender.get('email') else []
            counterpart_label = 'De'
        else:
            candidates = [r for r in recipients if r.get('email')]
            counterpart_label = 'Para'

        matched_any = False
        for candidate in candidates:
            candidate_email = (candidate.get('email') or '').strip().lower()
            if not candidate_email or candidate_email not in email_to_client:
                continue

            matched_any = True
            client_id = email_to_client[candidate_email]

            date_minute = email_date[:16]
            subject_key = subject[:100]
            c.execute(
                '''SELECT id FROM activities
                   WHERE client_id = ?
                     AND contact_type = 'Email'
                     AND strftime('%Y-%m-%dT%H:%M', activity_date) = ?
                     AND information LIKE ?
                   LIMIT 1''',
                (client_id, date_minute, f'{subject_key}%')
            )
            if c.fetchone():
                skipped_duplicates += 1
                continue

            # Gerar resumo via LLM somente para emails novos
            summary = None
            if body_preview:
                raw_summary = _sai_simple_prompt(
                    f'Resuma em 1 a 2 frases o conteúdo do email abaixo em português, '
                    f'de forma objetiva, sem mencionar remetente ou destinatário:\n'
                    f'Assunto: {subject}\n'
                    f'Texto: {body_preview[:1000]}\n\n'
                    'Retorne SOMENTE o resumo, sem introdução, aspas ou formatação extra.'
                )
                if raw_summary:
                    summary = raw_summary.strip()

            candidate_name = (candidate.get('name') or candidate_email).strip()
            info_parts = [subject, f'{counterpart_label}: {candidate_name} <{candidate_email}>']
            if summary:
                info_parts.append(f'Resumo: {summary}')
            elif body_preview:
                info_parts.append(body_preview[:300])
            information = '\n'.join(info_parts)

            c.execute(
                '''INSERT INTO activities (client_id, contact_type, information, activity_date)
                   VALUES (?, 'Email', ?, ?)''',
                (client_id, information, email_date)
            )
            c.execute(
                '''UPDATE clients SET last_activity_date = ?
                   WHERE id = ? AND (last_activity_date IS NULL OR last_activity_date < ?)''',
                (email_date, client_id, email_date)
            )
            imported += 1

        if not matched_any:
            skipped_no_match += 1

    conn.commit()
    return imported, skipped_duplicates, skipped_no_match


@app.route('/api/outlook/sync', methods=['POST'])
def sync_outlook_emails():
    """Lê o Outlook via PowerShell e importa os emails como atividades."""
    if sys.platform != 'win32':
        return jsonify({'error': 'Sincronização com Outlook disponível somente no Windows.'}), 400
    try:
        data = request.get_json() or {}
        days = max(1, min(int(data.get('days', 60)), 365))
        emails = _outlook_fetch_via_powershell(days)
        if not emails:
            return jsonify({
                'imported': 0, 'skipped_duplicates': 0, 'skipped_no_match': 0,
                'total_read': 0,
                'message': f'Nenhum email encontrado nos últimos {days} dias.'
            })
        conn = get_db()
        imported, skipped_duplicates, skipped_no_match = _outlook_import_emails(emails, conn)
        conn.close()
        msg = f'{imported} atividade(s) importada(s)'
        if skipped_duplicates:
            msg += f', {skipped_duplicates} duplicata(s) ignorada(s)'
        msg += f'. ({len(emails)} emails lidos do Outlook)'
        return jsonify({
            'imported': imported,
            'skipped_duplicates': skipped_duplicates,
            'skipped_no_match': skipped_no_match,
            'total_read': len(emails),
            'message': msg
        })
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/sync: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/sync-stream', methods=['GET'])
def sync_outlook_stream():
    """SSE: roteia para COM legado ou Graph de acordo com OUTLOOK_CONNECTOR_MODE."""
    mode = (os.environ.get('OUTLOOK_CONNECTOR_MODE') or 'auto').strip().lower()
    if mode not in {'com', 'graph', 'auto'}:
        mode = 'auto'

    # comportamento legado explícito
    if mode == 'com':
        return _outlook_sync_stream_com()

    # Graph explícito
    if mode == 'graph':
        return _outlook_sync_stream_graph()

    # auto: prioriza Graph se houver integração conectada; fallback para COM em Windows
    user_id = max(1, int(request.args.get('user_id', 1)))
    has_graph_integration = False
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM user_integrations WHERE user_id = ? AND provider = 'outlook_graph' LIMIT 1",
            (user_id,)
        )
        has_graph_integration = c.fetchone() is not None
        conn.close()
    except Exception:
        has_graph_integration = False

    if has_graph_integration:
        return _outlook_sync_stream_graph()
    return _outlook_sync_stream_com()


def _outlook_sync_stream_com():
    if sys.platform != 'win32':
        def _err():
            yield f"data: {json.dumps({'phase': 'error', 'message': 'Sincronização COM com Outlook disponível somente no Windows.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    days = max(1, min(int(request.args.get('days', 60)), 365))
    return _build_outlook_stream_response(days=days, source='com', page_size=100, max_pages=1)


@app.route('/api/outlook/sync-stream-graph', methods=['GET'])
def sync_outlook_stream_graph():
    """SSE dedicado do conector Graph (OAuth + Graph API)."""
    return _outlook_sync_stream_graph()


@app.route('/api/outlook/oauth/start', methods=['GET'])
def outlook_oauth_start():
    try:
        user_id = max(1, int(request.args.get('user_id', 1)))
        auth_url = outlook_graph_build_authorize_url(user_id=user_id)
        return jsonify({'auth_url': auth_url, 'provider': 'outlook_graph', 'user_id': user_id})
    except OutlookOAuthError as e:
        logger.error(f'[Outlook][OAuth] Falha ao iniciar OAuth: {e}')
        return jsonify({'error': str(e), 'error_type': 'oauth_authentication'}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/start: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/oauth/callback', methods=['GET'])
def outlook_oauth_callback():
    try:
        error = (request.args.get('error') or '').strip()
        if error:
            desc = request.args.get('error_description') or error
            raise OutlookOAuthError(f'Autorização OAuth negada: {desc}')

        code = (request.args.get('code') or '').strip()
        state = (request.args.get('state') or '').strip()
        if not code or not state:
            raise OutlookOAuthError('Parâmetros OAuth incompletos: code/state são obrigatórios.')

        user_id = outlook_graph_parse_state(state)
        conn = get_db()
        outlook_graph_exchange_code_and_store(conn=conn, code=code, user_id=user_id)
        conn.close()
        return jsonify({'ok': True, 'provider': 'outlook_graph', 'user_id': user_id})
    except OutlookOAuthError as e:
        logger.error(f'[Outlook][OAuth] Falha na callback OAuth: {e}')
        return jsonify({'error': str(e), 'error_type': 'oauth_authentication'}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/outlook/oauth/callback: {e}')
        return jsonify({'error': str(e)}), 500


def _outlook_sync_stream_graph():
    days = max(1, min(int(request.args.get('days', 60)), 365))
    page_size = max(1, min(int(request.args.get('page_size', 50)), 200))
    max_pages = max(1, min(int(request.args.get('max_pages', 10)), 50))
    user_id = max(1, int(request.args.get('user_id', 1)))
    return _build_outlook_stream_response(days=days, source='graph', page_size=page_size, max_pages=max_pages, user_id=user_id)


def _build_outlook_stream_response(days=60, source='com', page_size=50, max_pages=10, user_id=1):
    def generate():
        def evt(d):
            return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"
        try:
            connecting_message = 'Conectando via Microsoft Graph...' if source == 'graph' else 'Lendo emails do Outlook via COM...'
            yield evt({'phase': 'connecting', 'message': connecting_message})

            try:
                if source == 'graph':
                    end_date = datetime.utcnow()
                    start_date = end_date - timedelta(days=days)
                    conn = get_db()
                    access_token = outlook_graph_get_valid_access_token(conn=conn, user_id=user_id)
                    emails = outlook_graph_fetch_messages(
                        access_token=access_token,
                        start_date=start_date,
                        end_date=end_date,
                        page_size=page_size,
                        max_pages=max_pages
                    )
                    conn.close()
                else:
                    yield evt({
                        'phase': 'reading',
                        'message': 'Consulta COM iniciada. Isso pode levar alguns minutos em caixas postais grandes.',
                        'count': 0
                    })
                    result_holder = {'emails': None, 'error': None}

                    def _run_com_fetch():
                        try:
                            result_holder['emails'] = _outlook_fetch_via_powershell(days)
                        except Exception as run_err:
                            result_holder['error'] = run_err

                    worker = threading.Thread(target=_run_com_fetch, daemon=True)
                    started_at = time.time()
                    worker.start()
                    while worker.is_alive():
                        elapsed = int(time.time() - started_at)
                        yield evt({
                            'phase': 'reading',
                            'message': f'Consulta COM em andamento... {elapsed}s decorridos.',
                            'count': 0
                        })
                        worker.join(timeout=5)

                    if result_holder.get('error') is not None:
                        raise result_holder['error']
                    emails = result_holder.get('emails') or []
            except OutlookOAuthError as e:
                logger.error(f'[Outlook][OAuth] Falha de autenticação no sync-stream ({source}): {e}')
                yield evt({'phase': 'error', 'error_type': 'oauth_authentication', 'message': str(e)})
                return
            except OutlookSyncError as e:
                logger.error(f'[Outlook][Sync] Falha na leitura Graph ({source}): {e}')
                yield evt({'phase': 'error', 'error_type': 'sync_failure', 'message': str(e)})
                return
            except Exception as e:
                logger.exception(f'[Outlook][Sync] Falha no conector {source}: {e}')
                yield evt({'phase': 'error', 'error_type': 'sync_failure', 'message': str(e)})
                return

            total_read = len(emails)
            yield evt({'phase': 'reading', 'message': f'{total_read} email(s) lidos.', 'count': total_read})

            if not emails:
                yield evt({'phase': 'done', 'total_read': 0, 'activities': [],
                           'message': f'Nenhum email encontrado nos últimos {days} dias.'})
                return

            yield evt({'phase': 'matching', 'message': f'Identificando contatos em {total_read} email(s)...', 'count': total_read})

            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT id, name, email, photo_url FROM clients WHERE email IS NOT NULL AND TRIM(email) != ""')
            clients_map = {}
            for row in c.fetchall():
                norm = (row['email'] or '').strip().lower()
                if norm:
                    clients_map[norm] = {'id': row['id'], 'name': row['name'], 'photo_url': row['photo_url'] or ''}

            activities = []
            for email_data in emails:
                subject = (email_data.get('subject') or '').strip()
                email_date = (email_data.get('date') or '').strip()
                direction = email_data.get('direction', 'received')
                sender = email_data.get('sender') or {}
                recipients = email_data.get('recipients') or []
                body_preview = (email_data.get('body_preview') or '').strip()
                if not email_date:
                    continue
                if direction == 'received':
                    candidates = [sender] if sender.get('email') else []
                    label = 'De'
                else:
                    candidates = [r for r in recipients if r.get('email')]
                    label = 'Para'
                for candidate in candidates:
                    cand_email = (candidate.get('email') or '').strip().lower()
                    if not cand_email or cand_email not in clients_map:
                        continue
                    client = clients_map[cand_email]
                    date_minute = email_date[:16]
                    c.execute(
                        '''SELECT id FROM activities WHERE client_id = ? AND contact_type = 'Email'
                           AND strftime('%Y-%m-%dT%H:%M', activity_date) = ?
                           AND information LIKE ? LIMIT 1''',
                        (client['id'], date_minute, f'{subject[:100]}%')
                    )
                    if c.fetchone():
                        continue
                    activities.append({
                        'client_id': client['id'],
                        'client_name': client['name'],
                        'client_photo_url': client['photo_url'],
                        'subject': subject,
                        'date': email_date,
                        'direction': direction,
                        'counterpart_label': label,
                        'counterpart_name': (candidate.get('name') or cand_email).strip(),
                        'counterpart_email': cand_email,
                        'body_preview': body_preview
                    })
            conn.close()

            yield evt({
                'phase': 'done',
                'total_read': total_read,
                'activities': activities,
                'message': f'{len(activities)} nova(s) atividade(s) encontrada(s) em {total_read} email(s) lidos.'
            })
        except Exception as e:
            logger.exception(f'[ERROR] SSE /api/outlook/sync-stream ({source}): {e}')
            yield evt({'phase': 'error', 'error_type': 'sync_failure', 'message': f'Erro inesperado: {str(e)}'})
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/outlook/confirm-import', methods=['POST'])
def confirm_import_outlook():
    """Salva as atividades confirmadas pelo usuário, gerando resumo LLM."""
    try:
        data = request.get_json() or {}
        activities = data.get('activities', [])
        if not activities:
            return jsonify({'imported': 0, 'message': 'Nenhuma atividade para importar.'})

        conn = get_db()
        c = conn.cursor()
        imported = 0

        for act in activities:
            client_id = act.get('client_id')
            subject = (act.get('subject') or '').strip()
            email_date = (act.get('date') or '').strip()
            label = act.get('counterpart_label', 'De')
            cname = (act.get('counterpart_name') or '').strip()
            cemail = (act.get('counterpart_email') or '').strip()
            body_preview = (act.get('body_preview') or '').strip()
            if not client_id or not email_date:
                continue

            date_minute = email_date[:16]
            c.execute(
                '''SELECT id FROM activities WHERE client_id = ? AND contact_type = 'Email'
                   AND strftime('%Y-%m-%dT%H:%M', activity_date) = ?
                   AND information LIKE ? LIMIT 1''',
                (client_id, date_minute, f'{subject[:100]}%')
            )
            if c.fetchone():
                continue

            summary = None
            if body_preview:
                raw = _sai_simple_prompt(
                    f'Resuma em 1 a 2 frases o conteúdo do email abaixo em português, '
                    f'de forma objetiva, sem mencionar remetente ou destinatário:\n'
                    f'Assunto: {subject}\nTexto: {body_preview[:1000]}\n\n'
                    'Retorne SOMENTE o resumo, sem introdução, aspas ou formatação extra.'
                )
                if raw:
                    summary = raw.strip()

            info_parts = [subject, f'{label}: {cname} <{cemail}>']
            if summary:
                info_parts.append(f'Resumo: {summary}')
            elif body_preview:
                info_parts.append(body_preview[:300])

            c.execute(
                '''INSERT INTO activities (client_id, contact_type, information, activity_date)
                   VALUES (?, 'Email', ?, ?)''',
                (client_id, '\n'.join(info_parts), email_date)
            )
            c.execute(
                '''UPDATE clients SET last_activity_date = ?
                   WHERE id = ? AND (last_activity_date IS NULL OR last_activity_date < ?)''',
                (email_date, client_id, email_date)
            )
            imported += 1

        conn.commit()
        conn.close()
        return jsonify({'imported': imported, 'message': f'{imported} atividade(s) registrada(s) com sucesso.'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/confirm-import: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/outlook/import', methods=['POST'])
def import_outlook_emails():
    """Importação via arquivo JSON (fallback / uso avançado)."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not (file.filename or '').lower().endswith('.json'):
            return jsonify({'error': 'Formato inválido. Envie um arquivo .json com emails do Outlook.'}), 400
        file.seek(0, 2)
        if file.tell() > 20 * 1024 * 1024:
            return jsonify({'error': 'Arquivo muito grande. Máximo: 20MB.'}), 400
        file.seek(0)
        try:
            data = json.loads(file.read().decode('utf-8'))
        except Exception:
            return jsonify({'error': 'Arquivo JSON inválido.'}), 400
        emails = data.get('emails', [])
        if not emails:
            return jsonify({'imported': 0, 'skipped_duplicates': 0, 'skipped_no_match': 0,
                            'message': 'Nenhum email encontrado no arquivo.'}), 200
        conn = get_db()
        imported, skipped_duplicates, skipped_no_match = _outlook_import_emails(emails, conn)
        conn.close()
        msg = f'{imported} atividade(s) importada(s)'
        if skipped_duplicates:
            msg += f', {skipped_duplicates} duplicata(s) ignorada(s)'
        msg += '.'
        return jsonify({'imported': imported, 'skipped_duplicates': skipped_duplicates,
                        'skipped_no_match': skipped_no_match, 'message': msg})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/outlook/import: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/itoca/base-status', methods=['GET'])
def itoca_base_status():
    try:
        snapshot_items, updated_at = _itoca_get_cached_base()
        return jsonify({
            'has_base': len(snapshot_items) > 0,
            'items_count': len(snapshot_items),
            'updated_at': updated_at
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/base-status: {e}')
        return jsonify({'error': f'Erro ao consultar status da base iToca: {e}'}), 500


@app.route('/api/itoca/base-update', methods=['POST'])
def itoca_base_update():
    """Inicia a atualização da base iToca e retorna progresso via SSE.
    Aceita parâmetro JSON: { "incremental": true } para indexação incremental (só o que mudou).
    Sem parâmetro ou incremental=false: indexação completa.
    """
    req_data = request.get_json(silent=True) or {}
    incremental = bool(req_data.get('incremental', False))

    def generate():
        try:
            import queue
            q = queue.Queue()

            def progress_cb(pct, msg):
                q.put({'type': 'progress', 'percent': pct, 'message': msg})

            result_holder = {}
            error_holder = {}

            def run_update():
                try:
                    result = _itoca_update_cached_base(progress_cb=progress_cb, incremental=incremental)
                    result_holder['result'] = result
                except Exception as ex:
                    error_holder['error'] = str(ex)
                finally:
                    q.put({'type': 'done'})

            t = threading.Thread(target=run_update, daemon=True)
            t.start()

            while True:
                try:
                    evt = q.get(timeout=180)
                except Exception:
                    yield f'data: {json.dumps({"type":"error","message":"Timeout aguardando indexação."}, ensure_ascii=False)}\n\n'
                    break
                if evt['type'] == 'progress':
                    payload = json.dumps({'percent': evt['percent'], 'message': evt['message']}, ensure_ascii=False)
                    yield f'data: {payload}\n\n'
                elif evt['type'] == 'done':
                    if error_holder:
                        payload = json.dumps({'type': 'error', 'message': error_holder['error']}, ensure_ascii=False)
                    else:
                        r = result_holder.get('result', {})
                        changed = r.get('changed', True)
                        msg = 'Base iToca atualizada com sucesso.' if changed else 'Base já estava atualizada. Nenhuma alteração detectada.'
                        payload = json.dumps({
                            'type': 'done',
                            'message': msg,
                            'items_count': len(r.get('items', [])),
                            'updated_at': r.get('updated_at', ''),
                            'incremental': r.get('incremental', False),
                            'changed': changed
                        }, ensure_ascii=False)
                    yield f'data: {payload}\n\n'
                    break
        except GeneratorExit:
            pass
        except Exception as ex:
            yield f'data: {json.dumps({"type":"error","message":str(ex)}, ensure_ascii=False)}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/itoca/ask', methods=['POST'])
def itoca_ask():
    try:
        data = request.get_json() or {}
        question = (data.get('question') or '').strip()
        session_id = (data.get('session_id') or '').strip()
        if not question:
            return jsonify({'error': 'Pergunta obrigatória.'}), 400

        snapshot_items, updated_at = _itoca_get_cached_base()
        if not snapshot_items:
            return jsonify({
                'error': 'Base iToca ainda não foi atualizada. Clique em "Base Update" antes da primeira pergunta.',
                'base_ready': False
            }), 409

        # Detecta se é uma query analítica/ampla (resumos, panorama, todas as contas target, etc.)
        _q_lower = question.lower()
        _analytical_kws = {'target', 'todas', 'todos', 'resumo', 'resumir', 'panorama', 'geral',
                           'visao geral', 'visão geral', 'analise', 'análise', 'situação', 'situacao',
                           'relacionamento', 'evolucao', 'evolução', 'overview', 'mapa', 'balanço', 'balanco'}
        is_analytical = any(kw in _q_lower for kw in _analytical_kws)

        snapshot_limit = 30 if is_analytical else 15
        live_limit = 15 if is_analytical else 8
        context_max = 45 if is_analytical else 25

        # Busca híbrida: snapshot em cache + busca direta no banco para agenda e wiki
        snapshot_rows = _itoca_search_in_cached_snapshot(question, snapshot_items, limit=snapshot_limit)
        live_rows = _itoca_search_context(question, limit=live_limit)

        # Para queries analíticas/target: força inclusão de todas as contas target do banco
        target_rows = []
        if is_analytical and 'target' in _q_lower:
            try:
                _conn_t = get_db()
                _cur_t = _conn_t.cursor()
                _cur_t.execute('''
                    SELECT ac.id, ac.name, ac.sector, ac.is_target,
                           MAX(act.activity_date) as last_activity,
                           COUNT(DISTINCT act.id) as total_activities,
                           COUNT(DISTINCT ap.id) as total_services,
                           COUNT(DISTINCT amc.id) as total_contacts
                    FROM accounts ac
                    LEFT JOIN activities act ON act.account_id = ac.id
                    LEFT JOIN account_presences ap ON ap.account_id = ac.id
                    LEFT JOIN account_main_contacts amc ON amc.account_id = ac.id
                    WHERE ac.is_target = 1
                    GROUP BY ac.id
                    ORDER BY last_activity DESC NULLS LAST
                ''')
                for _row in _cur_t.fetchall():
                    _rd = dict_from_row(_row)
                    _parts = ['classificacao: conta-alvo (target)']
                    if _rd.get('name'):
                        _parts.append(f'empresa: {_rd["name"]}')
                    if _rd.get('sector'):
                        _parts.append(f'setor: {_rd["sector"]}')
                    if _rd.get('last_activity'):
                        try:
                            _dt = datetime.strptime(_rd['last_activity'][:10], '%Y-%m-%d')
                            _parts.append(f'ultimo_contato: {_dt.strftime("%d/%m/%Y")}')
                        except Exception:
                            _parts.append(f'ultimo_contato: {_rd["last_activity"]}')
                    else:
                        _parts.append('ultimo_contato: sem registros')
                    if _rd.get('total_activities'):
                        _parts.append(f'total_interacoes: {_rd["total_activities"]}')
                    if _rd.get('total_services'):
                        _parts.append(f'servicos_stefanini_cadastrados: {_rd["total_services"]}')
                    if _rd.get('total_contacts'):
                        _parts.append(f'total_contatos_mapeados: {_rd["total_contacts"]}')
                    _snip = ' | '.join(_parts)
                    if _snip:
                        target_rows.append({'table': 'accounts', 'id': _rd.get('id'), 'snippet': _snip, 'search_text': _snip.lower()})
                _conn_t.close()
            except Exception as _te:
                logger.warning(f'[iToca] Erro ao buscar contas target: {_te}')

        # Para queries analíticas gerais: adiciona painel de stats do banco
        stats_rows = []
        if is_analytical:
            try:
                _conn_s = get_db()
                _cur_s = _conn_s.cursor()
                _cur_s.execute('SELECT COUNT(*) as n FROM accounts')
                _total_ac = (_cur_s.fetchone() or [0])[0]
                _cur_s.execute('SELECT COUNT(*) as n FROM accounts WHERE is_target = 1')
                _total_target = (_cur_s.fetchone() or [0])[0]
                _cur_s.execute('SELECT COUNT(*) as n FROM clients')
                _total_cl = (_cur_s.fetchone() or [0])[0]
                _cur_s.execute('SELECT COUNT(*) as n FROM activities')
                _total_act = (_cur_s.fetchone() or [0])[0]
                _cur_s.execute('SELECT COUNT(*) as n FROM account_presences')
                _total_srv = (_cur_s.fetchone() or [0])[0]
                _cur_s.execute("SELECT COUNT(*) as n FROM activities WHERE activity_date >= date('now', '-30 days')")
                _act_30d = (_cur_s.fetchone() or [0])[0]
                _conn_s.close()
                _stats_snip = (
                    f'total_contas: {_total_ac} | contas_target: {_total_target} | '
                    f'total_contatos: {_total_cl} | total_interacoes: {_total_act} | '
                    f'interacoes_ultimos_30dias: {_act_30d} | servicos_cadastrados: {_total_srv}'
                )
                stats_rows.append({'table': 'user_profile', 'id': None, 'snippet': f'PAINEL_GERAL: {_stats_snip}', 'search_text': _stats_snip.lower()})
            except Exception as _se:
                logger.warning(f'[iToca] Erro ao calcular stats analíticos: {_se}')

        # Mescla resultados: prioriza target_rows > stats > live_rows > snapshot, evita duplicatas
        seen_keys = set()
        context_rows = []
        for item in (target_rows + stats_rows + live_rows):
            key = f"{item.get('table')}:{item.get('id')}:{str(item.get('snippet',''))[:60]}"
            if key not in seen_keys:
                seen_keys.add(key)
                context_rows.append(item)
        for item in snapshot_rows:
            key = f"{item.get('table')}:{item.get('id')}:{str(item.get('snippet',''))[:60]}"
            if key not in seen_keys:
                seen_keys.add(key)
                context_rows.append(item)
        context_rows = context_rows[:context_max]

        # Busca histórico da sessão atual para enviar como contexto de conversa
        history_rows = []
        if session_id:
            try:
                conn_h = get_db()
                c_h = conn_h.cursor()
                c_h.execute(
                    'SELECT role, content FROM itoca_chat_history WHERE session_id = ? ORDER BY created_at ASC LIMIT 12',
                    (session_id,)
                )
                history_rows = [dict_from_row(r) for r in c_h.fetchall()]
                conn_h.close()
            except Exception as he:
                logger.warning(f'[iToca] Erro ao buscar histórico: {he}')

        llm_result = _itoca_call_sai_llm(question, context_rows, history_rows=history_rows)
        answer = llm_result.get('answer', '')
        confidence = llm_result.get('confidence_percent', 0)
        needs_ref = llm_result.get('needs_refinement', False)
        ref_hint = llm_result.get('refinement_hint', '')

        # Salvar no histórico se session_id fornecido
        if session_id:
            try:
                conn_h = get_db()
                c_h = conn_h.cursor()
                c_h.execute(
                    'INSERT INTO itoca_chat_history (session_id, role, content, confidence_percent, needs_refinement, refinement_hint) VALUES (?, ?, ?, NULL, 0, ?)' ,
                    (session_id, 'user', question, '')
                )
                c_h.execute(
                    'INSERT INTO itoca_chat_history (session_id, role, content, confidence_percent, needs_refinement, refinement_hint) VALUES (?, ?, ?, ?, ?, ?)',
                    (session_id, 'assistant', answer, confidence, 1 if needs_ref else 0, ref_hint)
                )
                conn_h.commit()
                conn_h.close()
            except Exception as he:
                logger.warning(f'[iToca] Erro ao salvar histórico: {he}')

        # Detectar intenção de ação em thread separada (não bloqueia a resposta)
        # Apenas executa quando o LLM principal foi usado (API configurada)
        suggested_action = None
        if llm_result.get('llm_used') and not needs_ref:
            try:
                import threading as _threading
                import queue as _queue
                result_queue = _queue.Queue()

                def _run_detector():
                    try:
                        result_queue.put(_itoca_detect_action_intent(question, answer))
                    except Exception as _e:
                        result_queue.put(None)

                t = _threading.Thread(target=_run_detector, daemon=True)
                t.start()
                t.join(timeout=12)  # aguarda até 12s para não atrasar demais a resposta

                if not result_queue.empty():
                    det = result_queue.get_nowait()
                    # Só sugere ação se confiante o suficiente (>= 0.75) E tiver campos mínimos
                    if det and det.get('action_type') and float(det.get('confidence', 0)) >= 0.75:
                        action_type = det['action_type']
                        fields = det.get('fields') or {}

                        # Valida campos mínimos por tipo — evita sugestões vazias ou genéricas
                        _REQUIRED_FIELDS = {
                            'kanban_card':         ['title'],
                            'activity':            ['contact_name', 'description'],
                            'new_contact':         ['name', 'company'],
                            'environment_mapping': ['company', 'information'],
                            'wiki_entry':          ['title', 'content'],
                            'commitment':          ['title', 'due_date'],
                        }
                        required = _REQUIRED_FIELDS.get(action_type, [])
                        has_minimum = all(
                            fields.get(f) and str(fields[f]).strip()
                            for f in required
                        )

                        # Rejeita se a descrição for idêntica ou muito similar à pergunta
                        # (sinal de que o LLM apenas repetiu a pergunta como ação)
                        desc_field = (fields.get('description') or fields.get('information') or '').strip().lower()
                        question_lower = question.strip().lower()
                        is_echo = desc_field and (
                            desc_field == question_lower or
                            (len(desc_field) > 20 and question_lower.startswith(desc_field[:40]))
                        )

                        if has_minimum and not is_echo:
                            suggested_action = {
                                'action_type': action_type,
                                'label': det['label'],
                                'confidence': det['confidence'],
                                'fields': fields
                            }
                        else:
                            logger.debug(f'[iToca][ActionDetector] Ação {action_type!r} descartada: '
                                         f'has_minimum={has_minimum}, is_echo={is_echo}')
            except Exception as det_err:
                logger.warning(f'[iToca] Erro no detector de intenção: {det_err}')

        return jsonify({
            'answer': answer,
            'confidence_percent': confidence,
            'needs_refinement': needs_ref,
            'refinement_hint': ref_hint,
            'llm_used': llm_result.get('llm_used', False),
            'items_found': len(context_rows),
            'sources': context_rows,
            'base_updated_at': updated_at,
            'base_ready': True,
            'suggested_action': suggested_action  # None ou dict com action_type, label, confidence, fields
        })
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/itoca/ask: {e}')
        return jsonify({'error': f'Erro ao consultar iToca: {e}'}), 500


@app.route('/api/itoca/execute-action', methods=['POST'])
def itoca_execute_action():
    """Executa a ação sugerida pelo detector de intenção após confirmação do usuário.

    Payload esperado:
        action_type  (str)   — tipo da ação (kanban_card, activity, new_contact, etc.)
        fields       (dict)  — campos extraídos pelo LLM

    Retorna:
        success      (bool)
        message      (str)   — mensagem de confirmação
        created_id   (int)   — ID do registro criado (quando aplicável)
        action_type  (str)
    """
    try:
        data = request.get_json() or {}
        action_type = (data.get('action_type') or '').strip().lower()
        fields = data.get('fields') or {}

        if not action_type or action_type not in _ITOCA_ACTION_LABELS:
            return jsonify({'error': f'Tipo de ação inválido: {action_type!r}'}), 400

        conn = get_db()
        c = conn.cursor()

        # ------------------------------------------------------------------ #
        # kanban_card — cria card na primeira coluna do Kanban                #
        # ------------------------------------------------------------------ #
        if action_type == 'kanban_card':
            title = (fields.get('title') or '').strip()
            description = (fields.get('description') or fields.get('title') or '').strip()
            urgency = (fields.get('urgency') or 'Média').strip()
            if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
                urgency = 'Média'
            account_name = (fields.get('account_name') or fields.get('company') or '').strip()
            contact_name = (fields.get('contact_name') or '').strip()

            if not title:
                conn.close()
                return jsonify({'error': 'Título do card é obrigatório.'}), 400

            # Resolve account_id e contact_id se fornecidos
            account_id = None
            if account_name:
                account_id = ensure_account_for_company(c, account_name)

            contact_id = None
            if contact_name:
                c.execute('SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?)) LIMIT 1', (f'%{contact_name}%',))
                row = c.fetchone()
                if row:
                    contact_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            tag = infer_kanban_tag(description)
            c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
            first_col = c.fetchone()
            if not first_col:
                conn.close()
                return jsonify({'error': 'Nenhuma coluna disponível no Kanban.'}), 400
            col_id = first_col[0] if not isinstance(first_col, sqlite3.Row) else first_col['id']

            c.execute('SELECT COALESCE(MAX(display_order), 0) FROM kanban_cards WHERE column_id = ?', (col_id,))
            next_order = (c.fetchone()[0] or 0) + 1
            c.execute(
                '''INSERT INTO kanban_cards (title, description, tag, account_id, contact_id, urgency, column_id, display_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (title, description, tag, account_id, contact_id, urgency, col_id, next_order)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Card “{title}” criado no Kanban com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # activity — registra atividade vinculada a um contato               #
        # ------------------------------------------------------------------ #
        elif action_type == 'activity':
            contact_name = (fields.get('contact_name') or fields.get('name') or '').strip()
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            description = (fields.get('description') or fields.get('information') or '').strip()
            contact_type = (fields.get('contact_type') or 'Outro').strip()

            if not description:
                conn.close()
                return jsonify({'error': 'Descrição da atividade é obrigatória.'}), 400

            # Tenta encontrar o contato pelo nome e/ou empresa
            client_id = None
            if contact_name:
                query = 'SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?))'
                params = [f'%{contact_name}%']
                if company:
                    query += ' AND LOWER(TRIM(company)) LIKE LOWER(TRIM(?))'
                    params.append(f'%{company}%')
                query += ' LIMIT 1'
                c.execute(query, params)
                row = c.fetchone()
                if row:
                    client_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not client_id:
                conn.close()
                return jsonify({
                    'error': f'Contato “{contact_name or "(não informado)"}” não encontrado. Verifique o nome e tente novamente.',
                    'needs_contact_selection': True
                }), 404

            c.execute(
                '''INSERT INTO activities (client_id, contact_type, information)
                   VALUES (?, ?, ?)''',
                (client_id, contact_type, description)
            )
            c.execute('UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?', (client_id,))
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Atividade registrada para “{contact_name}” com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # new_contact — adiciona novo contato/cliente                        #
        # ------------------------------------------------------------------ #
        elif action_type == 'new_contact':
            name = (fields.get('name') or fields.get('contact_name') or '').strip()
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            position = (fields.get('position') or fields.get('cargo') or '').strip()
            email = (fields.get('email') or '').strip()
            phone = (fields.get('phone') or fields.get('telefone') or '').strip()

            if not name or not company or not position:
                conn.close()
                return jsonify({'error': 'Nome, empresa e cargo são obrigatórios para criar um contato.'}), 400

            # Verifica duplicidade simples
            c.execute(
                'SELECT id FROM clients WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND LOWER(TRIM(company)) = LOWER(TRIM(?)) LIMIT 1',
                (name, company)
            )
            if c.fetchone():
                conn.close()
                return jsonify({
                    'error': f'Contato “{name}” da empresa “{company}” já existe no sistema.',
                    'duplicate': True
                }), 409

            c.execute(
                '''INSERT INTO clients (name, company, position, email, phone, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (name, company, position, email or None, phone or None)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Contato “{name}” ({position} na {company}) adicionado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # wiki_entry — salva conhecimento no WikiToca                        #
        # ------------------------------------------------------------------ #
        elif action_type == 'wiki_entry':
            title = (fields.get('title') or '').strip()
            content = (fields.get('content') or fields.get('description') or '').strip()
            category = (fields.get('category') or '').strip() or None
            tags = (fields.get('tags') or '').strip() or None

            if not title or not content:
                conn.close()
                return jsonify({'error': 'Título e conteúdo são obrigatórios para criar um conhecimento.'}), 400

            c.execute(
                '''INSERT INTO wiki_entries (title, category, content, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (title, category, content, tags)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Conhecimento “{title}” salvo no WikiToca com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # commitment — agenda compromisso                                    #
        # ------------------------------------------------------------------ #
        elif action_type == 'commitment':
            title = (fields.get('title') or '').strip()
            due_date = (fields.get('due_date') or '').strip()
            due_time = (fields.get('due_time') or '').strip() or None
            notes = (fields.get('notes') or fields.get('description') or title or '').strip()
            contact_name = (fields.get('contact_name') or '').strip()

            if not due_date:
                conn.close()
                return jsonify({'error': 'Data do compromisso é obrigatória.'}), 400

            # Tenta encontrar o contato
            client_id = None
            if contact_name:
                c.execute('SELECT id FROM clients WHERE LOWER(TRIM(name)) LIKE LOWER(TRIM(?)) LIMIT 1', (f'%{contact_name}%',))
                row = c.fetchone()
                if row:
                    client_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not client_id:
                conn.close()
                return jsonify({
                    'error': f'Contato “{contact_name or "(não informado)"}” não encontrado para vincular o compromisso.',
                    'needs_contact_selection': True
                }), 404

            c.execute(
                '''INSERT INTO commitments (client_id, title, notes, due_date, due_time, source_type)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (client_id, title or 'Compromisso via iToca', notes, due_date, due_time, 'itoca')
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Compromisso “{title or due_date}” agendado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        # ------------------------------------------------------------------ #
        # environment_mapping — registra resposta de mapeamento de ambiente  #
        # ------------------------------------------------------------------ #
        elif action_type == 'environment_mapping':
            company = (fields.get('company') or fields.get('account_name') or '').strip()
            card_title = (fields.get('card_title') or fields.get('question') or '').strip()
            response_text = (fields.get('response') or fields.get('answer') or fields.get('content') or '').strip()

            if not company or not response_text:
                conn.close()
                return jsonify({'error': 'Empresa e resposta são obrigatórios para o mapeamento.'}), 400

            # Encontra ou cria a conta
            account_id = ensure_account_for_company(c, company)

            # Encontra o card de mapeamento pelo título (ou cria um genérico)
            card_id = None
            if card_title:
                c.execute(
                    'SELECT id FROM environment_cards WHERE LOWER(TRIM(title)) LIKE LOWER(TRIM(?)) LIMIT 1',
                    (f'%{card_title}%',)
                )
                row = c.fetchone()
                if row:
                    card_id = row[0] if not isinstance(row, sqlite3.Row) else row['id']

            if not card_id:
                # Cria um card genérico para a resposta
                c.execute(
                    '''INSERT INTO environment_cards (title, description, created_at, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                    (card_title or 'Informação via iToca', '')
                )
                conn.commit()
                card_id = c.lastrowid

            c.execute(
                '''INSERT INTO environment_responses (card_id, account_id, response, created_at, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (card_id, account_id, response_text)
            )
            conn.commit()
            created_id = c.lastrowid
            conn.close()
            return jsonify({
                'success': True,
                'message': f'Mapeamento de “{company}” registrado com sucesso!',
                'created_id': created_id,
                'action_type': action_type
            }), 201

        conn.close()
        return jsonify({'error': f'Ação “{action_type}” não implementada.'}), 501

    except Exception as e:
        logger.exception(f'[ERROR] POST /api/itoca/execute-action: {e}')
        return jsonify({'error': f'Erro ao executar ação: {e}'}), 500


@app.route('/api/itoca/history', methods=['GET'])
def itoca_history_list():
    """Lista sessões de histórico do iToca dos últimos 30 dias."""
    try:
        conn = get_db()
        c = conn.cursor()
        # Purga registros com mais de 30 dias
        c.execute("DELETE FROM itoca_chat_history WHERE created_at < datetime('now', '-30 days')")
        conn.commit()
        # Retorna sessões distintas com data e primeira pergunta
        c.execute('''
            SELECT session_id,
                   MIN(created_at) AS started_at,
                   MAX(created_at) AS last_at,
                   COUNT(*) AS msg_count,
                   (SELECT content FROM itoca_chat_history h2
                    WHERE h2.session_id = h.session_id AND h2.role = 'user'
                    ORDER BY h2.created_at ASC LIMIT 1) AS first_question
            FROM itoca_chat_history h
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT 60
        ''')
        sessions = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(sessions)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/history: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/itoca/history/<session_id>', methods=['GET'])
def itoca_history_session(session_id):
    """Retorna todas as mensagens de uma sessão específica."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'SELECT id, role, content, confidence_percent, needs_refinement, refinement_hint, created_at FROM itoca_chat_history WHERE session_id = ? ORDER BY created_at ASC',
            (session_id,)
        )
        messages = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(messages)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/itoca/history/{session_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/itoca/history/<session_id>', methods=['DELETE'])
def itoca_history_delete(session_id):
    """Deleta uma sessão específica do histórico."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM itoca_chat_history WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão removida do histórico.'})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/itoca/history/{session_id}: {e}')
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

def _autopic_get_role_via_llm(name, company):
    """Usa o SAI (ou OpenRouter como fallback) para descobrir o cargo da pessoa na empresa.
    Retorna string com o cargo, ou None se não conseguir.
    """
    llm_prompt = (
        f"Qual é o cargo ou função profissional de '{name}' na empresa '{company}'? "
        "Retorne SOMENTE o cargo em português, sem texto adicional, sem aspas, sem ponto final. "
        "Exemplos de resposta: CEO, Diretor Comercial, Gerente de Marketing, Engenheiro de Software. "
        "Se não souber com certeza, retorne null."
    )
    raw = _sai_simple_prompt(llm_prompt)
    if raw:
        role = raw.strip().split('\n')[0].strip(' "\'.')
        if role.lower() not in ('null', 'none', '', 'não sei', 'desconhecido'):
            logger.info(f'[AutoPic][LLM] Cargo encontrado via SAI: {role!r}')
            return role[:80]

    # Fallback: OpenRouter
    or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
    if or_key:
        or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
        model = (or_settings.get('openrouter_model') or 'stepfun/step-3.5-flash:free').strip() or 'stepfun/step-3.5-flash:free'
        site_url = (or_settings.get('openrouter_site_url') or 'http://localhost').strip() or 'http://localhost'
        app_name = (or_settings.get('openrouter_app_name') or 'TocaDoCoelho').strip() or 'TocaDoCoelho'
        try:
            or_payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'Você é um especialista em mercado corporativo. Responda SOMENTE com o cargo, sem texto adicional.'},
                    {'role': 'user', 'content': llm_prompt}
                ],
                'temperature': 0.1
            }
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(or_payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {or_key}',
                    'HTTP-Referer': site_url,
                    'X-Title': app_name
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            choices = data.get('choices') or []
            role = ((choices[0].get('message') or {}).get('content', '') if choices else '').strip().split('\n')[0].strip(' "\'.')
            if role and role.lower() not in ('null', 'none', '', 'não sei', 'desconhecido'):
                logger.info(f'[AutoPic][LLM] Cargo encontrado via OpenRouter: {role!r}')
                return role[:80]
        except Exception as e:
            logger.warning(f'[AutoPic][LLM] Falha ao buscar cargo via OpenRouter: {e}')

    return None


@app.route('/api/clients/autofind-photo-candidates', methods=['GET'])
def clients_autofind_photo_candidates():
    try:
        name = (request.args.get('name') or '').strip()
        company = (request.args.get('company') or '').strip()
        logger.info(f'[AutoPic] GET /autofind-photo-candidates: name={name!r} company={company!r}')

        if not name and not company:
            logger.warning('[AutoPic] GET /autofind-photo-candidates: nome e empresa vazios, abortando.')
            return jsonify({'error': 'Informe ao menos nome ou empresa.'}), 400

        candidates = []
        queries_tried = []

        # Enriquecimento via LLM: descobrir o cargo da pessoa — limitado a 10s para não travar a UI.
        # O _sai_simple_prompt tem timeout de 45s; usamos concurrent.futures para encurtar.
        role = None
        if name and company:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(_autopic_get_role_via_llm, name, company)
                    try:
                        role = _fut.result(timeout=10)
                    except concurrent.futures.TimeoutError:
                        logger.warning(f'[AutoPic] Timeout 10s ao buscar cargo via LLM para {name!r}, prosseguindo sem cargo.')
            except Exception as e:
                logger.warning(f'[AutoPic] Falha ao obter cargo via LLM: {e}')

        def _merge_candidates(existing, new_urls, limit=6):
            seen = set(existing)
            result = list(existing)
            for u in new_urls:
                if u not in seen:
                    seen.add(u)
                    result.append(u)
            return result[:limit]

        # Estratégia 1 (primária): nome ENTRE ASPAS + empresa sem aspas.
        # As aspas no nome são essenciais: sem elas "Henrique Netto" vira dois tokens separados
        # e o Bing pode combinar com a dupla sertaneja "Netto & Henrique" ou similares.
        # Com aspas, o Bing exige a frase exata e prioriza o profissional da empresa.
        if name and company:
            q1 = f'"{name}" {company}'
            queries_tried.append(q1)
            logger.info(f'[AutoPic] Estratégia 1 (nome entre aspas + empresa): query={q1!r}')
            candidates = _find_image_candidates_on_web(q1, limit=6)
            logger.info(f'[AutoPic] Estratégia 1 retornou {len(candidates)} candidato(s)')

        # Estratégia 2: nome entre aspas + cargo (LLM) + empresa — mais precisa quando há namesakes
        if len(candidates) < 3 and name and company and role:
            q2 = f'"{name}" {role} {company}'
            queries_tried.append(q2)
            logger.info(f'[AutoPic] Estratégia 2 (nome aspas + cargo LLM + empresa): query={q2!r}')
            extra = _find_image_candidates_on_web(q2, limit=6)
            logger.info(f'[AutoPic] Estratégia 2 retornou {len(extra)} candidato(s)')
            candidates = _merge_candidates(candidates, extra)

        # Estratégia 3: nome + empresa sem aspas (mais abrangente, pode trazer mais resultados)
        if len(candidates) < 3 and name and company:
            q3 = f'{name} {company}'
            queries_tried.append(q3)
            logger.info(f'[AutoPic] Estratégia 3 (sem aspas): query={q3!r}')
            extra = _find_image_candidates_on_web(q3, limit=6)
            logger.info(f'[AutoPic] Estratégia 3 retornou {len(extra)} candidato(s)')
            candidates = _merge_candidates(candidates, extra)

        # Estratégia 4: apenas nome (último recurso)
        if len(candidates) < 3:
            q4 = name or company
            queries_tried.append(q4)
            logger.info(f'[AutoPic] Estratégia 4 (apenas nome): query={q4!r}')
            extra = _find_image_candidates_on_web(q4, limit=6)
            logger.info(f'[AutoPic] Estratégia 4 retornou {len(extra)} candidato(s)')
            candidates = _merge_candidates(candidates, extra)

        logger.info(f'[AutoPic] Total final: {len(candidates)} candidato(s) após {len(queries_tried)} estratégia(s). '
                    f'Queries tentadas: {queries_tried}. Cargo LLM: {role!r}')
        return jsonify({'query': queries_tried[0] if queries_tried else '', 'candidates': candidates, 'role': role})
    except Exception as e:
        logger.exception(f'[AutoPic] ERRO em GET /autofind-photo-candidates: {e}')
        return jsonify({'error': f'Erro ao buscar imagens: {e}'}), 500


@app.route('/api/clients/autofind-photo', methods=['POST'])
def clients_autofind_photo():
    try:
        data = request.get_json() or {}
        image_url = (data.get('image_url') or '').strip()
        person_name = (data.get('name') or '').strip() or 'autofind'
        logger.info(f'[AutoPic] POST /autofind-photo: person_name={person_name!r} image_url={image_url[:120]!r}')
        if not image_url:
            return jsonify({'error': 'URL da imagem não informada.'}), 400

        safe_prefix = secure_filename(person_name) or 'autofind'
        photo_url = _download_remote_image_to_uploads(image_url, prefix=safe_prefix)
        logger.info(f'[AutoPic] POST /autofind-photo: imagem salva com sucesso em {photo_url!r}')
        return jsonify({'photo_url': photo_url})
    except Exception as e:
        logger.exception(f'[AutoPic] ERRO em POST /autofind-photo: {type(e).__name__}: {e}')
        return jsonify({'error': f'Erro ao importar imagem selecionada: {e}'}), 500


@app.route('/api/clients/autofind-photo-base64', methods=['POST'])
def clients_autofind_photo_base64():
    """Recebe uma imagem em base64 (data URL), salva no servidor e retorna a URL local."""
    try:
        data = request.get_json() or {}
        data_url = (data.get('data_url') or '').strip()
        person_name = (data.get('name') or '').strip() or 'autofind'
        if not data_url:
            return jsonify({'error': 'data_url não informada.'}), 400

        # Formato esperado: data:image/jpeg;base64,<dados>
        if not data_url.startswith('data:image/'):
            return jsonify({'error': 'Formato de data URL inválido.'}), 400

        header, encoded = data_url.split(',', 1)
        # Extrair extensão do tipo MIME
        mime_type = header.split(';')[0].replace('data:', '')
        ext_map = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}
        ext = ext_map.get(mime_type, '.jpg')

        img_data = base64.b64decode(encoded)
        if len(img_data) > 6 * 1024 * 1024:
            return jsonify({'error': 'Imagem muito grande (máximo 6MB).'}), 400

        safe_prefix = secure_filename(person_name) or 'autofind'
        filename = secure_filename(f"{safe_prefix}-{int(time.time()*1000)}{ext}")
        path = UPLOAD_DIR / filename
        with open(path, 'wb') as f:
            f.write(img_data)

        return jsonify({'photo_url': f'/uploads/{filename}'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/clients/autofind-photo-base64: {e}')
        return jsonify({'error': f'Erro ao salvar imagem: {e}'}), 500


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
        linkedin = request.form.get('linkedin', '').strip()
        area_of_activity = request.form.get('area_of_activity', '').strip()
        is_cold_contact = 1 if request.form.get('is_cold_contact') in ('1', 'true', 'on') else 0
        is_target = 1 if request.form.get('is_target') in ('1', 'true', 'on') else 0
        force_create = request.form.get('force_create') in ('1', 'true', 'on')
        autofind_photo_url = (request.form.get('autofind_photo_url') or '').strip()
        
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

        photo_url = autofind_photo_url or None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO clients (name, company, position, area_of_activity, email, phone, linkedin, photo_url, is_target, is_cold_contact)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (name, company, position, area_of_activity or None, email or None, phone or None, linkedin or None, photo_url, is_target, is_cold_contact))
        client_id = c.lastrowid
        ensure_account_for_company(c, company)
        conn.commit()
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
        linkedin = request.form.get('linkedin', '').strip()
        area_of_activity = request.form.get('area_of_activity', '').strip()
        is_cold_contact = 1 if request.form.get('is_cold_contact') in ('1', 'true', 'on') else 0
        remove_photo = request.form.get('remove_photo', '0') == '1'
        autofind_photo_url = (request.form.get('autofind_photo_url') or '').strip()
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
        
        photo_url = None if remove_photo else (autofind_photo_url or client['photo_url'])
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'
        
        c.execute('''UPDATE clients SET name = ?, company = ?, position = ?, area_of_activity = ?, email = ?, phone = ?, linkedin = ?, photo_url = ?, is_target = ?, is_cold_contact = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (name, company, position, area_of_activity or None, email or None, phone or None, linkedin or None, photo_url, is_target, is_cold_contact, client_id))
        ensure_account_for_company(c, company)
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

        allowed_fields = {
            'id': ('id', 'ID'),
            'name': ('name', 'Nome'),
            'company': ('company', 'Empresa'),
            'position': ('position', 'Cargo'),
            'area_of_activity': ('area_of_activity', 'Área de Atuação'),
            'email': ('email', 'Email'),
            'phone': ('phone', 'Telefone'),
            'photo_url': ('photo_url', 'Foto (URL)'),
            'is_target': ('is_target', 'Contato-Alvo'),
            'is_cold_contact': ('is_cold_contact', 'Contato Frio'),
            'created_at': ('created_at', 'Data de Cadastro'),
            'updated_at': ('updated_at', 'Última Atualização'),
        }

        default_fields = ['id', 'name', 'company', 'position', 'email', 'phone', 'created_at']
        requested_fields = (request.args.get('fields') or '').strip()

        selected_fields = []
        if requested_fields:
            seen = set()
            for raw_field in requested_fields.split(','):
                field = raw_field.strip()
                if not field or field in seen:
                    continue
                if field in allowed_fields:
                    selected_fields.append(field)
                    seen.add(field)

            if not selected_fields:
                return jsonify({'error': 'Nenhum campo válido foi informado para exportação.'}), 400
        else:
            selected_fields = default_fields

        conn = get_db()
        c = conn.cursor()
        db_fields = ', '.join([allowed_fields[field][0] for field in selected_fields])
        c.execute(f'SELECT {db_fields} FROM clients ORDER BY name')
        rows = c.fetchall()
        conn.close()
        
        # Criar CSV em memoria
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([allowed_fields[field][1] for field in selected_fields])

        for row in rows:
            writer.writerow([row[field] if row[field] is not None else '' for field in selected_fields])
        
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
            linkedin = row[5].strip() if len(row) > 5 else None
            
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
                'phone': phone,
                'linkedin': linkedin
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
                c.execute('''INSERT INTO clients (name, company, position, email, phone, linkedin, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                         (row_data['name'], row_data['company'], row_data['position'], 
                          row_data['email'], row_data['phone'], row_data.get('linkedin')))
                ensure_account_for_company(c, row_data['company'])
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

# Rotas de Kanban
@app.route('/api/kanban/columns', methods=['GET'])
def list_kanban_columns():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""SELECT kc.*, COUNT(kb.id) AS cards_count
                     FROM kanban_columns kc
                     LEFT JOIN kanban_cards kb ON kb.column_id = kc.id
                     GROUP BY kc.id
                     ORDER BY kc.display_order, kc.id""")
        rows = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        print(f'[ERROR] GET /api/kanban/columns: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns', methods=['POST'])
def create_kanban_column():
    try:
        title = (request.json.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COALESCE(MAX(display_order), 0) FROM kanban_columns')
        next_order = (c.fetchone()[0] or 0) + 1
        c.execute('INSERT INTO kanban_columns (title, display_order) VALUES (?, ?)', (title, next_order))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({'id': new_id, 'message': 'Sessão criada com sucesso'}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/kanban/columns: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns/<int:column_id>', methods=['PUT'])
def update_kanban_column(column_id):
    try:
        title = (request.json.get('title') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM kanban_columns WHERE id = ?', (column_id,))
        current = c.fetchone()
        if not current:
            conn.close()
            return jsonify({'error': 'Sessão não encontrada'}), 404
        current = dict_from_row(current)
        if int(current.get('is_locked') or 0) == 1:
            conn.close()
            return jsonify({'error': 'Sessão bloqueada não pode ser editada'}), 403

        c.execute('UPDATE kanban_columns SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (title, column_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão atualizada com sucesso'})
    except Exception as e:
        print(f'[ERROR] PUT /api/kanban/columns/{column_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/columns/<int:column_id>', methods=['DELETE'])
def delete_kanban_column(column_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM kanban_columns WHERE id = ?', (column_id,))
        current = c.fetchone()
        if not current:
            conn.close()
            return jsonify({'error': 'Sessão não encontrada'}), 404
        current = dict_from_row(current)
        if int(current.get('is_locked') or 0) == 1:
            conn.close()
            return jsonify({'error': 'Sessão bloqueada não pode ser apagada'}), 403

        c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
        first_column = c.fetchone()
        first_column_id = first_column[0] if first_column else None

        if first_column_id and first_column_id != column_id:
            c.execute('UPDATE kanban_cards SET column_id = ?, updated_at = CURRENT_TIMESTAMP WHERE column_id = ?', (first_column_id, column_id))

        c.execute('DELETE FROM kanban_columns WHERE id = ?', (column_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sessão removida com sucesso'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/kanban/columns/{column_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards', methods=['GET'])
def list_kanban_cards():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""SELECT kb.*,
                            acc.name AS account_name,
                            acc.logo_url AS account_logo_url,
                            cl.name AS contact_name,
                            cl.photo_url AS contact_photo_url,
                            (SELECT MAX(kca.created_at) FROM kanban_card_activities kca WHERE kca.card_id = kb.id) AS last_activity_at
                     FROM kanban_cards kb
                     LEFT JOIN accounts acc ON acc.id = kb.account_id
                     LEFT JOIN clients cl ON cl.id = kb.contact_id
                     ORDER BY kb.column_id, kb.display_order, kb.id""")
        rows = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        print(f'[ERROR] GET /api/kanban/cards: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards', methods=['POST'])
def create_kanban_card():
    try:
        data = request.json or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        tag = (data.get('tag') or '').strip() or infer_kanban_tag(description)
        account_id = data.get('account_id')
        contact_id = data.get('contact_id')
        urgency = (data.get('urgency') or 'Média').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            urgency = 'Média'
        if not title or not description:
            return jsonify({'error': 'Título e descrição são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
        first = c.fetchone()
        if not first:
            conn.close()
            return jsonify({'error': 'Nenhuma sessão disponível no Kanban'}), 400
        first_column_id = first[0]

        c.execute('SELECT COALESCE(MAX(display_order), 0) FROM kanban_cards WHERE column_id = ?', (first_column_id,))
        next_order = (c.fetchone()[0] or 0) + 1

        c.execute('''INSERT INTO kanban_cards (title, description, tag, account_id, contact_id, urgency, column_id, display_order)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (title, description, tag, account_id, contact_id, urgency, first_column_id, next_order))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return jsonify({'id': new_id, 'message': 'Card criado com sucesso'}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/kanban/cards: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['PUT'])
def update_kanban_card(card_id):
    try:
        data = request.json or {}
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        tag = (data.get('tag') or '').strip() or infer_kanban_tag(description)
        account_id = data.get('account_id')
        contact_id = data.get('contact_id')
        urgency = (data.get('urgency') or 'Média').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            urgency = 'Média'
        if not title or not description:
            return jsonify({'error': 'Título e descrição são obrigatórios'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('''UPDATE kanban_cards
                     SET title = ?, description = ?, tag = ?, account_id = ?, contact_id = ?, urgency = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (title, description, tag, account_id, contact_id, urgency, card_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Card atualizado com sucesso'})
    except Exception as e:
        print(f'[ERROR] PUT /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['GET'])
def get_kanban_card(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT kb.*, kc.title as column_title,
                            acc.name AS account_name, acc.logo_url AS account_logo_url,
                            cl.name AS contact_name, cl.photo_url AS contact_photo_url, cl.position AS contact_position,
                            (SELECT MAX(kca.created_at) FROM kanban_card_activities kca WHERE kca.card_id = kb.id) AS last_activity_at
                     FROM kanban_cards kb
                     JOIN kanban_columns kc ON kc.id = kb.column_id
                     LEFT JOIN accounts acc ON acc.id = kb.account_id
                     LEFT JOIN clients cl ON cl.id = kb.contact_id
                     WHERE kb.id = ?''', (card_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        card = dict_from_row(row)
        c.execute('SELECT id, content, created_at FROM kanban_card_activities WHERE card_id = ? ORDER BY created_at DESC, id DESC', (card_id,))
        card['activities'] = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        return jsonify(card)
    except Exception as e:
        print(f'[ERROR] GET /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>/activities', methods=['POST'])
def add_kanban_card_activity(card_id):
    try:
        content = (request.json.get('content') or '').strip()
        if not content:
            return jsonify({'error': 'Atividade é obrigatória'}), 400
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM kanban_cards WHERE id = ?', (card_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404
        c.execute('INSERT INTO kanban_card_activities (card_id, content) VALUES (?, ?)', (card_id, content))
        conn.commit()
        new_id = c.lastrowid
        c.execute('SELECT id, content, created_at FROM kanban_card_activities WHERE id = ?', (new_id,))
        created = dict_from_row(c.fetchone())
        conn.close()
        return jsonify({'message': 'Atividade adicionada', 'activity': created}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/kanban/cards/{card_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/kanban/cards/<int:card_id>', methods=['DELETE'])
def delete_kanban_card(card_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM kanban_cards WHERE id = ?', (card_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Card removido com sucesso'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/kanban/cards/{card_id}: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/kanban/cards/<int:card_id>/urgency', methods=['PATCH'])
def update_kanban_card_urgency(card_id):
    try:
        urgency = (request.json.get('urgency') or '').strip() or 'Média'
        if urgency not in ['Baixa', 'Média', 'Alta', 'Crítica']:
            return jsonify({'error': 'Urgência inválida'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM kanban_cards WHERE id = ?', (card_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404

        c.execute('UPDATE kanban_cards SET urgency = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (urgency, card_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Urgência atualizada com sucesso'})
    except Exception as e:
        print(f'[ERROR] PATCH /api/kanban/cards/{card_id}/urgency: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/kanban/cards/<int:card_id>/move', methods=['PATCH'])
def move_kanban_card(card_id):
    try:
        data = request.json or {}
        column_id = data.get('column_id')
        position = int(data.get('position') or 0)
        if not column_id:
            return jsonify({'error': 'Sessão de destino é obrigatória'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM kanban_cards WHERE id = ?', (card_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Card não encontrado'}), 404

        c.execute('SELECT id FROM kanban_columns WHERE id = ?', (column_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Sessão de destino não encontrada'}), 404

        c.execute('''SELECT id FROM kanban_cards
                     WHERE column_id = ? AND id != ?
                     ORDER BY display_order, id''', (column_id, card_id))
        ids = [row[0] for row in c.fetchall()]
        if position < 0:
            position = 0
        if position > len(ids):
            position = len(ids)
        ids.insert(position, card_id)

        for order, cid in enumerate(ids, start=1):
            c.execute('UPDATE kanban_cards SET column_id = ?, display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                      (column_id, order, cid))

        conn.commit()
        conn.close()
        return jsonify({'message': 'Card movido com sucesso'})
    except Exception as e:
        print(f'[ERROR] PATCH /api/kanban/cards/{card_id}/move: {e}')
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
def _normalize_merge_text(value):
    return str(value or '').strip().lower()


def _normalize_merge_phone(value):
    digits = re.sub(r'\D+', '', str(value or ''))
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) == 10:
        return f"{digits[:2]}9{digits[2:]}"
    return digits


def _is_empty_merge_value(value):
    return value is None or str(value).strip() == ''


def _merge_clients_from_db(temp_db_path):
    incoming_conn = sqlite3.connect(str(temp_db_path))
    incoming_conn.row_factory = sqlite3.Row
    current_conn = sqlite3.connect(str(DB_PATH))
    current_conn.row_factory = sqlite3.Row

    try:
        incoming_cur = incoming_conn.cursor()
        current_cur = current_conn.cursor()

        incoming_cur.execute('PRAGMA table_info(clients)')
        incoming_client_columns = [row['name'] for row in incoming_cur.fetchall()]
        if not incoming_client_columns:
            return {
                'processed': 0,
                'imported': 0,
                'updated': 0,
                'unchanged': 0,
                'conflicts': 0,
                'skipped': 0,
                'conflict_rows': []
            }

        current_cur.execute('PRAGMA table_info(clients)')
        current_client_columns = [row['name'] for row in current_cur.fetchall()]

        updatable_columns = [col for col in incoming_client_columns if col in current_client_columns and col != 'id']
        if not updatable_columns:
            return {
                'processed': 0,
                'imported': 0,
                'updated': 0,
                'unchanged': 0,
                'conflicts': 0,
                'skipped': 0,
                'conflict_rows': []
            }

        def load_current_clients():
            current_cur.execute('SELECT * FROM clients')
            rows = [dict(row) for row in current_cur.fetchall()]
            index_name = {}
            index_email = {}
            index_phone = {}
            for row in rows:
                rid = row.get('id')
                name_key = _normalize_merge_text(row.get('name'))
                email_key = _normalize_merge_text(row.get('email'))
                phone_key = _normalize_merge_phone(row.get('phone'))
                if name_key:
                    index_name.setdefault(name_key, rid)
                if email_key:
                    index_email.setdefault(email_key, rid)
                if phone_key:
                    index_phone.setdefault(phone_key, rid)
            return rows, index_name, index_email, index_phone

        rows, index_name, index_email, index_phone = load_current_clients()
        current_by_id = {row['id']: row for row in rows}

        incoming_cur.execute('SELECT * FROM clients ORDER BY id ASC')
        incoming_rows = [dict(row) for row in incoming_cur.fetchall()]

        summary = {
            'processed': len(incoming_rows),
            'imported': 0,
            'updated': 0,
            'unchanged': 0,
            'conflicts': 0,
            'skipped': 0,
            'conflict_rows': []
        }

        for incoming in incoming_rows:
            name_key = _normalize_merge_text(incoming.get('name'))
            email_key = _normalize_merge_text(incoming.get('email'))
            phone_key = _normalize_merge_phone(incoming.get('phone'))

            match_id = None
            match_basis = None
            if name_key and name_key in index_name:
                match_id = index_name[name_key]
                match_basis = 'name'
            elif email_key and email_key in index_email:
                match_id = index_email[email_key]
                match_basis = 'email'
            elif phone_key and phone_key in index_phone:
                match_id = index_phone[phone_key]
                match_basis = 'phone'

            if not match_id:
                insert_cols = [col for col in updatable_columns if col in incoming]
                insert_values = [incoming.get(col) for col in insert_cols]
                placeholders = ','.join(['?'] * len(insert_cols))
                current_cur.execute(
                    f"INSERT INTO clients ({','.join(insert_cols)}) VALUES ({placeholders})",
                    tuple(insert_values)
                )
                new_id = current_cur.lastrowid
                summary['imported'] += 1
                if name_key:
                    index_name.setdefault(name_key, new_id)
                if email_key:
                    index_email.setdefault(email_key, new_id)
                if phone_key:
                    index_phone.setdefault(phone_key, new_id)
                continue

            current_row = current_by_id.get(match_id) or {}
            updates = {}
            conflict_fields = []
            for col in updatable_columns:
                incoming_val = incoming.get(col)
                current_val = current_row.get(col)
                if _is_empty_merge_value(incoming_val):
                    continue
                if _is_empty_merge_value(current_val):
                    updates[col] = incoming_val
                    continue
                if str(incoming_val).strip() == str(current_val).strip():
                    continue
                conflict_fields.append(col)

            if conflict_fields:
                summary['conflicts'] += 1
                summary['skipped'] += 1
                summary['conflict_rows'].append({
                    'incoming_name': incoming.get('name') or '',
                    'match_id': match_id,
                    'match_basis': match_basis or 'none',
                    'fields': conflict_fields[:8]
                })
                continue

            if updates:
                set_sql = ', '.join([f"{col} = ?" for col in updates.keys()])
                params = list(updates.values()) + [match_id]
                current_cur.execute(f'UPDATE clients SET {set_sql} WHERE id = ?', tuple(params))
                summary['updated'] += 1
                for col, value in updates.items():
                    current_row[col] = value
            else:
                summary['unchanged'] += 1

        current_conn.commit()
        return summary
    finally:
        incoming_conn.close()
        current_conn.close()


@app.route('/api/backup/database', methods=['GET'])
def backup_database():
    try:
        from flask import send_file
        import tempfile
        import shutil
        include_uploads = str(request.args.get('include_uploads', '')).strip().lower() in {'1', 'true', 'yes', 'sim', 'on'}
        
        # Criar cópia temporária do banco
        temp_dir = tempfile.mkdtemp()
        temp_db = Path(temp_dir) / 'toca-do-coelho-backup.db'
        shutil.copy2(str(DB_PATH), str(temp_db))

        if include_uploads:
            temp_zip = Path(temp_dir) / 'toca-do-coelho-backup.zip'
            with zipfile.ZipFile(str(temp_zip), mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(str(temp_db), arcname='database/toca-do-coelho.db')
                if UPLOAD_DIR.exists():
                    for file_path in UPLOAD_DIR.rglob('*'):
                        if file_path.is_file():
                            relative = file_path.relative_to(UPLOAD_DIR)
                            zf.write(str(file_path), arcname=str(Path('uploads') / relative))

            return send_file(
                str(temp_zip),
                as_attachment=True,
                download_name=f'toca-do-coelho-backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip',
                mimetype='application/zip'
            )
        
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
        
        mode = str(request.form.get('mode', 'replace_all') or 'replace_all').strip().lower()
        if mode not in {'replace_all', 'merge'}:
            return jsonify({'error': 'Modo de importação inválido. Use replace_all ou merge.'}), 400

        uploaded_name = (file.filename or '').strip().lower()
        is_zip_backup = uploaded_name.endswith('.zip')
        is_db_backup = uploaded_name.endswith('.db')
        if not is_zip_backup and not is_db_backup:
            return jsonify({'error': 'Formato inválido. Envie um arquivo .db ou .zip de backup.'}), 400
        
        # Criar backup do banco atual antes de restaurar
        backup_dir = DATA_DIR / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f'pre-restore-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db'
        backup_uploads_path = backup_dir / f'pre-restore-uploads-{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip'
        
        import shutil
        shutil.copy2(str(DB_PATH), str(backup_path))
        print(f'[Database] Backup de segurança criado em {backup_path}')

        # Backup de segurança dos uploads atuais (garante rollback dos arquivos visuais)
        with zipfile.ZipFile(str(backup_uploads_path), mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            if UPLOAD_DIR.exists():
                for file_path in UPLOAD_DIR.rglob('*'):
                    if file_path.is_file():
                        rel = file_path.relative_to(UPLOAD_DIR)
                        zf.write(str(file_path), arcname=str(Path('uploads') / rel))
        print(f'[Database] Backup de segurança dos uploads criado em {backup_uploads_path}')
        
        # Salvar arquivo temporário
        temp_path = DATA_DIR / 'temp_restore.db'
        temp_zip_path = DATA_DIR / 'temp_restore.zip'
        if temp_path.exists():
            temp_path.unlink()
        if temp_zip_path.exists():
            temp_zip_path.unlink()
        
        if is_zip_backup:
            file.save(str(temp_zip_path))
            with zipfile.ZipFile(str(temp_zip_path), mode='r') as zf:
                db_member = None
                for name in zf.namelist():
                    normalized = name.replace('\\', '/')
                    if normalized.endswith('/'):
                        continue
                    if normalized in {'database/toca-do-coelho.db', 'toca-do-coelho.db'} or normalized.lower().endswith('.db'):
                        db_member = name
                        break
                if not db_member:
                    temp_zip_path.unlink(missing_ok=True)
                    return jsonify({'error': 'Backup .zip inválido: arquivo de banco (.db) não encontrado.'}), 400
                with zf.open(db_member, 'r') as db_src, open(temp_path, 'wb') as db_out:
                    shutil.copyfileobj(db_src, db_out)
        else:
            file.save(str(temp_path))
        
        # Validar se é um banco SQLite válido
        try:
            test_conn = sqlite3.connect(str(temp_path))
            test_conn.execute('SELECT name FROM sqlite_master WHERE type="table"')
            test_conn.close()
        except Exception as e:
            temp_path.unlink()
            return jsonify({'error': 'Arquivo não é um banco de dados SQLite válido'}), 400
        
        if mode == 'merge':
            merge_summary = _merge_clients_from_db(temp_path)
            temp_path.unlink(missing_ok=True)
            temp_zip_path.unlink(missing_ok=True)
            return jsonify({
                'message': 'Fusão concluída! Nenhum dado existente foi apagado.',
                'mode': 'merge',
                'backup_location': str(backup_path),
                'backup_uploads_location': str(backup_uploads_path),
                'merge_summary': merge_summary
            }), 200

        # Substituir banco atual
        shutil.move(str(temp_path), str(DB_PATH))
        print(f'[Database] Banco de dados restaurado com sucesso')

        restored_uploads = 0
        if is_zip_backup and temp_zip_path.exists():
            extracted_files = []
            with zipfile.ZipFile(str(temp_zip_path), mode='r') as zf:
                for member in zf.infolist():
                    normalized = member.filename.replace('\\', '/')
                    if member.is_dir() or not normalized.startswith('uploads/'):
                        continue
                    relative = Path(normalized.replace('uploads/', '', 1)).as_posix().strip('/')
                    if not relative:
                        continue
                    if relative.startswith('../') or '/..' in f'/{relative}':
                        continue
                    destination = (UPLOAD_DIR / relative).resolve()
                    upload_root = UPLOAD_DIR.resolve()
                    if upload_root not in destination.parents and destination != upload_root:
                        continue
                    extracted_files.append((member, destination))

                # Para manter o estado visual EXATAMENTE como no backup, limpa uploads antes de restaurar
                if UPLOAD_DIR.exists():
                    shutil.rmtree(str(UPLOAD_DIR))
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

                for member, destination in extracted_files:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, 'r') as src, open(destination, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    restored_uploads += 1
            temp_zip_path.unlink(missing_ok=True)
        
        return jsonify({
            'message': 'Banco de dados restaurado com sucesso! Recarregue a página.',
            'mode': 'replace_all',
            'backup_location': str(backup_path),
            'backup_uploads_location': str(backup_uploads_path),
            'restored_upload_files': restored_uploads
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
                    'description': 'Faltam: ' + ', '.join(missing_fields),
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
        sync_accounts_from_clients()
        conn = get_db(); c = conn.cursor()
        c.execute('''SELECT name, COALESCE(is_target, 0) as is_target FROM accounts
                     WHERE name IS NOT NULL AND TRIM(name) != ''
                     ORDER BY COALESCE(is_target, 0) DESC, name COLLATE NOCASE''')
        companies = [row['name'] for row in c.fetchall()]
        c.execute('SELECT name FROM account_sectors ORDER BY name COLLATE NOCASE')
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
        sync_accounts_from_clients()
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


def _account_autofill_parse_llm_raw(raw):
    """Extrai dict de dados corporativos de uma resposta bruta de LLM (SAI ou OpenRouter)."""
    def _try_parse_json(value):
        if not value:
            return None
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value.strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        m = re.search(r'\{[^{}]*\}', value, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return None

    parsed = _try_parse_json(raw) or {}
    if 'answer' not in parsed and 'average_revenue_brl' not in parsed:
        for key in ('output', 'result', 'text', 'content', 'response', 'data', 'message'):
            candidate = parsed.get(key)
            nested = _try_parse_json(candidate)
            if nested:
                parsed = nested
                break

    answer = parsed.get('answer') if isinstance(parsed, dict) else ''
    answer_obj = _try_parse_json(answer) if isinstance(answer, str) else None
    if answer_obj:
        parsed = answer_obj

    average_revenue_brl = parsed.get('average_revenue_brl') if isinstance(parsed, dict) else None
    professionals_count = parsed.get('professionals_count') if isinstance(parsed, dict) else None
    global_presence_raw = (parsed.get('global_presence') or '') if isinstance(parsed, dict) else ''

    global_presence = ''
    if global_presence_raw:
        gp_lower = str(global_presence_raw).strip().lower()
        if 'global' in gp_lower:
            global_presence = 'Global'
        elif 'latam' in gp_lower or 'latina' in gp_lower:
            global_presence = 'Latam'
        elif 'brasil' in gp_lower or 'brazil' in gp_lower:
            global_presence = 'Brasil'

    try:
        pc = int(professionals_count) if professionals_count is not None else None
    except Exception:
        pc = None

    try:
        rev = float(average_revenue_brl) if average_revenue_brl is not None else None
    except Exception:
        rev = None

    return {'average_revenue_brl': rev, 'professionals_count': pc, 'global_presence': global_presence}


def _account_autofill_via_sai(account_name):
    """Busca dados corporativos da empresa via SAI LLM com fallback para OpenRouter."""
    llm_prompt = (
        f"Quais são os dados corporativos da empresa '{account_name}'? "
        "Retorne SOMENTE um JSON válido, sem texto adicional, no formato: "
        '{"average_revenue_brl": 3500000000, "professionals_count": 50000, "global_presence": "Global"} '
        "Onde average_revenue_brl é o faturamento médio anual em reais (número inteiro, sem símbolos), "
        "professionals_count é o número de funcionários/profissionais (número inteiro), "
        "global_presence é 'Brasil' se opera principalmente no Brasil, 'Latam' se opera em países da América Latina além do Brasil, "
        "'Global' se opera em múltiplos continentes. "
        "Use null para campos dos quais não tem certeza."
    )

    # --- Tentativa 1: SAI (simple prompt template) ---
    raw = _sai_simple_prompt(llm_prompt)
    if raw is not None:
        result = _account_autofill_parse_llm_raw(raw)
        result['source'] = 'SAI'
        logger.info(f'[AccountAutoFill][SAI] resultado: {result}')
        return result

    # --- Tentativa 2: OpenRouter ---
    or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
    if or_key:
        or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
        model = (or_settings.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
        site_url = (or_settings.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
        app_name = (or_settings.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
        try:
            or_payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'Você é um analista corporativo. Responda SEMPRE e SOMENTE com um JSON válido, sem texto adicional.'},
                    {'role': 'user', 'content': llm_prompt}
                ],
                'temperature': 0.1
            }
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(or_payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {or_key}',
                    'HTTP-Referer': site_url,
                    'X-Title': app_name
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            choices = data.get('choices') or []
            raw = (choices[0].get('message') or {}).get('content', '') if choices else ''
            result = _account_autofill_parse_llm_raw(raw)
            result['source'] = 'OpenRouter'
            logger.info(f'[AccountAutoFill][OpenRouter] resultado: {result}')
            return result
        except Exception as e:
            logger.warning(f'[AccountAutoFill][OpenRouter] falha: {e}')

    logger.info(f'[AccountAutoFill] Nenhum LLM configurado para empresa: {account_name!r}')
    return {'average_revenue_brl': None, 'professionals_count': None, 'global_presence': '', 'source': 'sem_llm'}


def _portfolio_extract_pdf_text(file_storage):
    if not file_storage:
        return ''
    if not PDFPLUMBER_AVAILABLE:
        raise RuntimeError('Leitura de PDF indisponível no servidor (pdfplumber não instalado).')

    file_bytes = file_storage.read()
    if not file_bytes:
        return ''

    text_parts = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in (pdf.pages or []):
            try:
                text_parts.append(page.extract_text() or '')
            except Exception:
                continue
    return '\n'.join(part.strip() for part in text_parts if part and part.strip()).strip()


def _portfolio_parse_llm_raw(raw):
    def _try_parse_json(value):
        if not value:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {'items': value}
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {'items': parsed}
        except Exception:
            pass
        m = re.search(r'\{[\s\S]*\}', stripped)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return None

    parsed = _try_parse_json(raw) or {}
    if 'items' not in parsed:
        for key in ('output', 'result', 'text', 'content', 'response', 'data', 'message', 'answer'):
            candidate = parsed.get(key)
            nested = _try_parse_json(candidate)
            if nested:
                parsed = nested
                break

    title = (parsed.get('title') or '').strip() if isinstance(parsed, dict) else ''
    summary = (parsed.get('summary') or '').strip() if isinstance(parsed, dict) else ''
    raw_items = parsed.get('items') if isinstance(parsed, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    for item in raw_items:
        if isinstance(item, dict):
            pain = (item.get('pain') or '').strip()
            solution = (item.get('solution') or '').strip()
            if pain or solution:
                items.append({'pain': pain, 'solution': solution})

    if not title:
        title = 'Oferta sem título'
    if not summary:
        summary = 'Resumo não informado.'
    if not items:
        items = [{'pain': 'Dor não identificada', 'solution': 'Solução não identificada'}]
    return {'title': title, 'summary': summary, 'items': items}


def _portfolio_generate_offer_from_llm(raw_input):
    llm_prompt = (
        "Você é um especialista em posicionamento comercial B2B. "
        "Analise o material abaixo e extraia um portfólio comercial em português (Brasil). "
        "Retorne SOMENTE JSON válido no formato: "
        '{"title":"Título objetivo da oferta","summary":"Resumo executivo curto das ofertas/cases",'
        '"items":[{"pain":"Dor do cliente","solution":"Solução ofertada"}]}. '
        "Regras: gere entre 3 e 12 itens úteis; não invente informações fora do texto; "
        "use frases curtas e claras; não inclua markdown.\n\n"
        f"MATERIAL:\n{raw_input[:30000]}"
    )

    raw = _sai_simple_prompt(llm_prompt)
    source = 'SAI'

    if raw is None:
        or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
        if not or_key:
            return None, 'sem_llm'
        or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
        model = (or_settings.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
        site_url = (or_settings.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
        app_name = (or_settings.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
        try:
            or_payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'Você é um analista comercial. Responda SEMPRE e SOMENTE com JSON válido.'},
                    {'role': 'user', 'content': llm_prompt}
                ],
                'temperature': 0.2
            }
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(or_payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {or_key}',
                    'HTTP-Referer': site_url,
                    'X-Title': app_name
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            choices = data.get('choices') or []
            raw = (choices[0].get('message') or {}).get('content', '') if choices else ''
            source = 'OpenRouter'
        except Exception as e:
            logger.warning(f'[Portfolio][OpenRouter] Falha ao gerar oferta: {e}')
            return None, 'sem_llm'

    return _portfolio_parse_llm_raw(raw), source


def _portfolio_fetch_offer(c, offer_id):
    c.execute('SELECT * FROM portfolio_offers WHERE id = ?', (offer_id,))
    offer = dict_from_row(c.fetchone())
    if not offer:
        return None
    c.execute('SELECT * FROM portfolio_offer_items WHERE offer_id = ? ORDER BY sort_order ASC, id ASC', (offer_id,))
    offer['items'] = [dict_from_row(row) for row in c.fetchall()]
    return offer


@app.route('/api/portfolio/offers', methods=['GET'])
def list_portfolio_offers():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM portfolio_offers ORDER BY datetime(created_at) DESC, id DESC')
        offers = [dict_from_row(row) for row in c.fetchall()]
        for offer in offers:
            c.execute('SELECT * FROM portfolio_offer_items WHERE offer_id = ? ORDER BY sort_order ASC, id ASC', (offer['id'],))
            offer['items'] = [dict_from_row(item) for item in c.fetchall()]
        conn.close()
        return jsonify(offers)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao listar ofertas: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers', methods=['POST'])
def create_portfolio_offer():
    try:
        input_text = (request.form.get('raw_input') or '').strip()
        file_obj = request.files.get('pdf_file')
        pdf_text = _portfolio_extract_pdf_text(file_obj) if file_obj else ''
        raw_input = (input_text + '\n\n' + pdf_text).strip() if input_text and pdf_text else (input_text or pdf_text)

        if not raw_input:
            return jsonify({'error': 'Informe um texto ou envie um PDF para análise.'}), 400

        parsed, source = _portfolio_generate_offer_from_llm(raw_input)
        if not parsed:
            return jsonify({'error': 'Nenhum serviço de IA configurado (SAI ou OpenRouter).'}), 503

        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO portfolio_offers (title, summary, raw_input, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
            (parsed['title'], parsed['summary'], raw_input)
        )
        offer_id = c.lastrowid
        for idx, item in enumerate(parsed.get('items') or []):
            c.execute(
                '''INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (offer_id, (item.get('pain') or '').strip(), (item.get('solution') or '').strip(), idx)
            )
        conn.commit()
        offer = _portfolio_fetch_offer(c, offer_id)
        conn.close()
        if offer is None:
            return jsonify({'error': 'Falha ao carregar oferta criada.'}), 500
        offer['llm_source'] = source
        return jsonify(offer), 201
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao criar oferta: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>', methods=['PUT'])
def update_portfolio_offer(offer_id):
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        summary = (data.get('summary') or '').strip()
        if not title:
            return jsonify({'error': 'Título é obrigatório.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offers WHERE id = ?', (offer_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        c.execute(
            'UPDATE portfolio_offers SET title = ?, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (title, summary, offer_id)
        )
        conn.commit()
        offer = _portfolio_fetch_offer(c, offer_id)
        conn.close()
        return jsonify(offer)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao atualizar oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>', methods=['DELETE'])
def delete_portfolio_offer(offer_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM portfolio_offer_items WHERE offer_id = ?', (offer_id,))
        c.execute('DELETE FROM portfolio_offers WHERE id = ?', (offer_id,))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        conn.commit()
        conn.close()
        return jsonify({'message': 'Oferta removida com sucesso.'})
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao remover oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items/<int:item_id>', methods=['PUT'])
def update_portfolio_offer_item(offer_id, item_id):
    try:
        data = request.get_json() or {}
        pain = (data.get('pain') or '').strip()
        solution = (data.get('solution') or '').strip()
        sort_order = data.get('sort_order')
        if not pain and not solution:
            return jsonify({'error': 'Informe dor e/ou solução.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Item não encontrado.'}), 404

        if sort_order is None:
            c.execute(
                '''UPDATE portfolio_offer_items
                   SET pain = ?, solution = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND offer_id = ?''',
                (pain, solution, item_id, offer_id)
            )
        else:
            try:
                sort_order_int = int(sort_order)
            except Exception:
                return jsonify({'error': 'sort_order inválido.'}), 400
            c.execute(
                '''UPDATE portfolio_offer_items
                   SET pain = ?, solution = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND offer_id = ?''',
                (pain, solution, sort_order_int, item_id, offer_id)
            )

        conn.commit()
        c.execute('SELECT * FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item)
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao atualizar item {item_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items', methods=['POST'])
def create_portfolio_offer_item(offer_id):
    try:
        data = request.get_json() or {}
        pain = (data.get('pain') or '').strip()
        solution = (data.get('solution') or '').strip()
        if not pain and not solution:
            return jsonify({'error': 'Informe dor e/ou solução.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM portfolio_offers WHERE id = ?', (offer_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Oferta não encontrada.'}), 404
        c.execute('SELECT COALESCE(MAX(sort_order), -1) AS max_sort FROM portfolio_offer_items WHERE offer_id = ?', (offer_id,))
        max_sort = (dict_from_row(c.fetchone()) or {}).get('max_sort', -1)
        next_sort = int(max_sort) + 1
        c.execute(
            '''INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
            (offer_id, pain, solution, next_sort)
        )
        item_id = c.lastrowid
        conn.commit()
        c.execute('SELECT * FROM portfolio_offer_items WHERE id = ?', (item_id,))
        item = dict_from_row(c.fetchone())
        conn.close()
        return jsonify(item), 201
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao criar item para oferta {offer_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/portfolio/offers/<int:offer_id>/items/<int:item_id>', methods=['DELETE'])
def delete_portfolio_offer_item(offer_id, item_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM portfolio_offer_items WHERE id = ? AND offer_id = ?', (item_id, offer_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Item não encontrado.'}), 404
        conn.commit()
        conn.close()
        return jsonify({'message': 'Item removido com sucesso.'})
    except Exception as e:
        logger.exception(f'[Portfolio] Erro ao remover item {item_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/autofill', methods=['POST'])
def account_autofill():
    """Preenche automaticamente campos de uma conta com dados da empresa via SAI LLM e busca de imagem."""
    try:
        data = request.get_json() or {}
        account_name = (data.get('account_name') or '').strip()
        if not account_name:
            return jsonify({'error': 'Nome da conta não informado.'}), 400

        company_data = _account_autofill_via_sai(account_name)

        average_revenue_formatted = ''
        raw_revenue = company_data.get('average_revenue_brl')
        if raw_revenue is not None:
            try:
                cents = int(round(float(raw_revenue) * 100))
                average_revenue_formatted = format_currency_br(cents)
            except Exception:
                pass

        logo_url = None
        try:
            candidates = _find_image_candidates_on_web(f'{account_name} logo empresa', limit=4)
            if candidates:
                logo_url = candidates[0]
        except Exception as e:
            logger.warning(f'[AccountAutoFill] Falha ao buscar logo: {e}')

        return jsonify({
            'average_revenue': average_revenue_formatted,
            'professionals_count': company_data.get('professionals_count', ''),
            'global_presence': company_data.get('global_presence', ''),
            'logo_url': logo_url,
            'source': company_data.get('source', 'SAI')
        })
    except Exception as e:
        logger.exception(f'[AccountAutoFill] Erro: {e}')
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# LinkedIn Profile Summarizer
# ---------------------------------------------------------------------------

def _linkedin_try_fetch_public(url):
    """Tenta buscar dados públicos de um perfil LinkedIn. Retorna texto ou None."""
    if not url or 'linkedin.com' not in url:
        return None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            raw_html = resp.read().decode('utf-8', errors='ignore')
        # Extrai texto visível removendo tags HTML
        clean = re.sub(r'<style[^>]*>.*?</style>', ' ', raw_html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<script[^>]*>.*?</script>', ' ', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', ' ', clean)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Se LinkedIn redirecionou para login, o conteúdo tem pouca informação útil
        if len(clean) < 300 or 'Sign in' in clean or 'authwall' in url:
            return None
        return clean[:8000]  # Limita para não exceder contexto do LLM
    except Exception as e:
        logger.debug(f'[LinkedIn] Falha ao buscar URL pública: {e}')
        return None


def _linkedin_generate_summary_via_llm(profile_content, meeting_context='', data_is_rich=True):
    """Gera resumo executivo do perfil LinkedIn via LLM (SAI → OpenRouter)."""
    ctx_part = f'\n\nCONTEXTO DA REUNIÃO: {meeting_context}' if meeting_context.strip() else ''

    if data_is_rich:
        quality_instruction = (
            'IMPORTANTE: Use SOMENTE as informações explicitamente presentes no perfil abaixo. '
            'Seja ESPECÍFICO e DETALHADO: cite nomes reais de empresas, cargos exatos, anos, projetos, '
            'números e realizações concretas mencionados no perfil. '
            'NÃO generalize, NÃO invente informações que não estejam no texto. '
        )
    else:
        quality_instruction = (
            'ATENÇÃO: Os dados disponíveis são LIMITADOS (perfil parcialmente acessível). '
            'Use null para campos que não estiverem explicitamente nos dados fornecidos. '
            'NÃO invente nem generalize — prefira null a informação genérica. '
        )

    llm_prompt = (
        'Analise as informações abaixo de um perfil profissional do LinkedIn e gere um resumo executivo '
        f'para preparar uma reunião de negócios com esta pessoa. {quality_instruction}'
        f'PERFIL LINKEDIN:\n{profile_content}{ctx_part}\n\n'
        'Retorne SOMENTE um JSON válido, sem texto adicional, com exatamente estes campos: '
        '{"nome": "Nome completo da pessoa", '
        '"cargo_atual": "Cargo exato e empresa atual", '
        '"trajetoria": ["experiência específica 1 com empresa e período", "experiência 2", "experiência 3"], '
        '"formacao": ["curso, instituição e ano se disponível", "outra formação"], '
        '"competencias": ["competência específica 1", "competência 2", "competência 3", "competência 4", "competência 5"], '
        '"pontos_conversa": ["ponto de conversa concreto 1", "ponto 2", "ponto 3", "ponto 4"], '
        '"insights": ["insight específico sobre o perfil 1", "insight 2"], '
        '"tom_sugerido": "tom recomendado com justificativa baseada no perfil"} '
        'Use null para campos não encontrados. Responda em português (BR).'
    )

    # Tentativa 1: SAI
    raw = _sai_simple_prompt(llm_prompt)
    if raw:
        logger.info('[LinkedIn][SAI] Resumo gerado com sucesso')
        return raw, 'SAI'

    # Tentativa 2: OpenRouter
    or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
    if or_key:
        or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
        model = (or_settings.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
        site_url = (or_settings.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
        app_name = (or_settings.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'
        try:
            or_payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': 'Você é um analista de inteligência executiva. Responda SEMPRE e SOMENTE com um JSON válido, sem texto adicional.'},
                    {'role': 'user', 'content': llm_prompt}
                ],
                'temperature': 0.3
            }
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(or_payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {or_key}',
                    'HTTP-Referer': site_url,
                    'X-Title': app_name
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            choices = data.get('choices') or []
            raw = (choices[0].get('message') or {}).get('content', '') if choices else ''
            if raw:
                logger.info('[LinkedIn][OpenRouter] Resumo gerado com sucesso')
                return raw, 'OpenRouter'
        except Exception as e:
            logger.warning(f'[LinkedIn][OpenRouter] Falha: {e}')

    return None, 'sem_llm'


def _linkedin_parse_summary(raw):
    """Extrai e valida JSON do resumo gerado pelo LLM."""
    if not raw:
        return None
    # Tenta JSON direto
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Tenta extrair JSON do texto
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


@app.route('/api/linkedin/summarize', methods=['POST'])
def linkedin_summarize():
    """Gera resumo executivo de um perfil LinkedIn para preparação de reunião."""
    try:
        data = request.get_json() or {}
        linkedin_url = (data.get('linkedin_url') or '').strip()
        profile_text = (data.get('profile_text') or '').strip()
        meeting_context = (data.get('meeting_context') or '').strip()

        if not linkedin_url and not profile_text:
            return jsonify({'error': 'Informe a URL do LinkedIn ou cole o texto do perfil.'}), 400

        # Tenta buscar perfil público se URL fornecida e texto não informado
        fetched_text = None
        if linkedin_url and not profile_text:
            fetched_text = _linkedin_try_fetch_public(linkedin_url)

        # Determina qualidade dos dados: texto colado pelo usuário = rico; URL = limitado
        data_is_rich = bool(profile_text) or (fetched_text and len(fetched_text) > 2000)
        limited_data = not data_is_rich

        profile_content = profile_text or fetched_text or ''
        if not profile_content and linkedin_url:
            profile_content = f'URL do perfil LinkedIn: {linkedin_url}'

        raw, source = _linkedin_generate_summary_via_llm(profile_content, meeting_context, data_is_rich=data_is_rich)
        if not raw:
            return jsonify({'error': 'Nenhum serviço de IA configurado (SAI ou OpenRouter).'}), 503

        parsed = _linkedin_parse_summary(raw)

        # Tenta buscar foto e baixar localmente (evita CORS no html2canvas)
        photo_url = None
        if parsed and parsed.get('nome'):
            try:
                nome = parsed['nome']
                cargo = parsed.get('cargo_atual', '')
                query = f'{nome} {cargo} foto perfil profissional'.strip()
                candidates = _find_image_candidates_on_web(query, limit=3)
                if candidates:
                    photo_url = _download_remote_image_to_uploads(candidates[0], prefix='linkedin-profile')
            except Exception as e:
                logger.debug(f'[LinkedIn] Falha ao buscar/baixar foto: {e}')

        return jsonify({
            'summary': parsed,
            'raw': raw if not parsed else None,
            'source': source,
            'fetched_from_url': fetched_text is not None,
            'limited_data': limited_data,
            'photo_url': photo_url
        })
    except Exception as e:
        logger.exception(f'[LinkedIn] Erro: {e}')
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------

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
        autofill_logo_url = (request.form.get('autofill_logo_url') or '').strip()
        if not name:
            return jsonify({'error': 'Nome da conta é obrigatório'}), 400
        conn = get_db(); c = conn.cursor()
        logo_url = autofill_logo_url or None
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
        remove_logo = request.form.get('remove_logo', '0') in ('1', 'true', 'True')
        autofill_logo_url = (request.form.get('autofill_logo_url') or '').strip()
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        row = dict_from_row(c.fetchone())
        if not row:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        logo_url = None if remove_logo else (autofill_logo_url or row.get('logo_url'))
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
        delivery_cell = (data.get('delivery_cell') or '').strip() or None
        service_id = (data.get('service_id') or '').strip() or None
        current_revenue_cents = parse_currency_to_cents(data.get('current_revenue'))
        validity_month = (data.get('validity_month') or '').strip() or None
        focal_client_id = data.get('focal_client_id')
        focal_client_id = int(focal_client_id) if str(focal_client_id).isdigit() else None
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT name FROM accounts WHERE id = ?', (account_id,))
        account = c.fetchone()
        if not account:
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''INSERT INTO account_presences (account_id, delivery_name, stf_owner, delivery_cell, service_id, current_revenue_cents, validity_month, focal_client_id, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (account_id, delivery_name, stf_owner, delivery_cell, service_id, current_revenue_cents, validity_month, focal_client_id))
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
        delivery_cell = (data.get('delivery_cell') or '').strip() or None
        service_id = (data.get('service_id') or '').strip() or None
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
                     SET delivery_name=?, stf_owner=?, delivery_cell=?, service_id=?, current_revenue_cents=?, validity_month=?, focal_client_id=?, updated_at=CURRENT_TIMESTAMP
                     WHERE id=? AND account_id=?''',
                  (delivery_name, stf_owner, delivery_cell, service_id, current_revenue_cents, validity_month, focal_client_id, presence_id, account_id))
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


@app.route('/api/accounts/<int:account_id>/activities', methods=['GET'])
def get_account_activities(account_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT id FROM accounts WHERE id = ?', (account_id,))
        if not c.fetchone():
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        c.execute('''SELECT id, account_id, description, activity_date, created_at
                     FROM account_activities
                     WHERE account_id = ?
                     ORDER BY activity_date DESC, created_at DESC
                     LIMIT 100''', (account_id,))
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close(); return jsonify(rows)
    except Exception as e:
        print(f'[ERROR] GET /api/accounts/{account_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/activities', methods=['POST'])
def create_account_activity(account_id):
    try:
        data = request.get_json() or {}
        description = (data.get('description') or '').strip()
        activity_date = (data.get('activity_date') or '').strip() or None
        if not description:
            return jsonify({'error': 'Descrição é obrigatória'}), 400
        conn = get_db(); c = conn.cursor()
        c.execute('SELECT id FROM accounts WHERE id = ?', (account_id,))
        if not c.fetchone():
            conn.close(); return jsonify({'error': 'Conta não encontrada'}), 404
        if activity_date:
            c.execute('''INSERT INTO account_activities (account_id, description, activity_date)
                         VALUES (?, ?, ?)''', (account_id, description, activity_date))
        else:
            c.execute('''INSERT INTO account_activities (account_id, description)
                         VALUES (?, ?)''', (account_id, description))
        conn.commit()
        activity_id = c.lastrowid
        conn.close()
        return jsonify({'id': activity_id, 'message': 'Atividade registrada'}), 201
    except Exception as e:
        print(f'[ERROR] POST /api/accounts/{account_id}/activities: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/<int:account_id>/activities/<int:activity_id>', methods=['DELETE'])
def delete_account_activity(account_id, activity_id):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute('DELETE FROM account_activities WHERE id = ? AND account_id = ?', (activity_id, account_id))
        conn.commit(); conn.close()
        return jsonify({'message': 'Atividade removida'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/accounts/{account_id}/activities/{activity_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/cancel', methods=['POST'])
def cancel_automapping():
    try:
        data = request.get_json() or {}
        request_id = (data.get('request_id') or '').strip()
        if not request_id:
            return jsonify({'error': 'request_id é obrigatório'}), 400
        _mark_automapping_cancelled(request_id)
        return jsonify({'message': 'Cancelamento registrado'})
    except Exception as e:
        print(f'[ERROR] POST /api/automapping/cancel: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping', methods=['POST'])
def run_automapping():
    try:
        data = request.get_json() or {}
        company = (data.get('company') or '').strip()
        country = (data.get('country') or '').strip()
        industry = (data.get('industry') or '').strip()
        force = bool(data.get('force'))
        request_id = (data.get('request_id') or '').strip()

        if not company or not country or not industry:
            return jsonify({'error': 'company, country e industry são obrigatórios'}), 400

        if _is_automapping_cancelled(request_id, consume=True):
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        query_key = _normalize_automapping_key(company, country, industry)

        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, result_json, created_at FROM automapping_runs
                     WHERE query_key = ?
                       AND datetime(created_at) >= datetime('now', '-20 days')
                     ORDER BY datetime(created_at) DESC
                     LIMIT 1''', (query_key,))
        cached = c.fetchone()

        if cached and not force:
            conn.close()
            return jsonify({
                'already_exists': True,
                'message': 'Já existe um AutoMapping para os mesmos dados nos últimos 20 dias.',
                'run_id': cached['id'],
                'created_at': cached['created_at'],
                'result': json.loads(cached['result_json'])
            }), 200

        if _is_automapping_cancelled(request_id, consume=True):
            conn.close()
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        try:
            evidence_results, section_errors, execution_meta = _run_tavily_search(company, country, industry)
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else str(e)
            conn.close()
            return jsonify({'error': f'Falha ao consultar Tavily: {detail[:400]}'}), 502
        except Exception as e:
            conn.close()
            return jsonify({'error': f'Falha ao consultar Tavily: {str(e)}'}), 502

        if _is_automapping_cancelled(request_id, consume=True):
            conn.close()
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        result_payload = _build_automapping_payload(company, country, industry, evidence_results, section_errors, execution_meta)

        c.execute('SELECT 1 FROM clients WHERE LOWER(TRIM(company)) = LOWER(TRIM(?)) LIMIT 1', (company,))
        result_payload['client_exists'] = bool(c.fetchone())

        if _is_automapping_cancelled(request_id, consume=True):
            conn.close()
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        try:
            llm_summary, llm_meta = _run_openrouter_synthesis(result_payload)
            result_payload['llm_summary'] = llm_summary
            result_payload['llm_meta'] = llm_meta
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='ignore') if hasattr(e, 'read') else str(e)
            conn.close()
            return jsonify({'error': f'Falha ao consultar OpenRouter: {detail[:400]}'}), 502
        except Exception as e:
            conn.close()
            return jsonify({'error': f'Falha ao consultar OpenRouter: {str(e)}'}), 502

        if _is_automapping_cancelled(request_id, consume=True):
            conn.close()
            return jsonify({'cancelled': True, 'message': 'AutoMapping cancelado pelo usuário.'}), 409

        c.execute('INSERT INTO automapping_runs (company, country, industry, query_key, result_json) VALUES (?, ?, ?, ?, ?)',
                  (company, country, industry, query_key, json.dumps(result_payload, ensure_ascii=False)))
        run_id = c.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'already_exists': False,
            'run_id': run_id,
            'result': result_payload
        }), 200

    except Exception as e:
        print(f'[ERROR] POST /api/automapping: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs/<int:run_id>', methods=['GET'])
def get_automapping_run(run_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM automapping_runs WHERE id = ?', (run_id,))
        run = c.fetchone()
        conn.close()
        if not run:
            return jsonify({'error': 'Execução não encontrada'}), 404
        payload = dict_from_row(run)
        payload['result'] = json.loads(payload['result_json'])
        return jsonify(payload)
    except Exception as e:
        print(f'[ERROR] GET /api/automapping/runs/{run_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs/<int:run_id>', methods=['DELETE'])
def delete_automapping_run(run_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM automapping_runs WHERE id = ?', (run_id,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if not deleted:
            return jsonify({'error': 'Execução não encontrada'}), 404
        return jsonify({'message': 'Log de AutoMapping removido com sucesso'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/automapping/runs/{run_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/automapping/runs', methods=['GET'])
def list_automapping_runs():
    try:
        days = request.args.get('days', '20')
        try:
            days = max(1, min(60, int(days)))
        except Exception:
            days = 20

        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, company, country, industry, result_json, created_at
                     FROM automapping_runs
                     WHERE datetime(created_at) >= datetime('now', ?)
                     ORDER BY datetime(created_at) DESC''', (f'-{days} days',))
        rows = c.fetchall()
        conn.close()

        runs = []
        for row in rows:
            parsed = dict_from_row(row)
            result = json.loads(parsed.get('result_json') or '{}')
            sections = result.get('sections') or {}
            queries = {
                section_key: section_val.get('query_used')
                for section_key, section_val in sections.items()
                if isinstance(section_val, dict) and section_val.get('query_used')
            }
            runs.append({
                'id': parsed.get('id'),
                'company': parsed.get('company'),
                'country': parsed.get('country'),
                'industry': parsed.get('industry'),
                'created_at': parsed.get('created_at'),
                'queries': queries,
                'sections_count': len(queries)
            })

        return jsonify({'days': days, 'runs': runs})
    except Exception as e:
        print(f'[ERROR] GET /api/automapping/runs: {e}')
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────
# WikiToca – Conhecimentos registrados
# ─────────────────────────────────────────────────────────────

@app.route('/api/wikitoca/entries', methods=['GET'])
def list_wiki_entries():
    print('[DEBUG] GET /api/wikitoca/entries chamado')
    try:
        q = (request.args.get('q') or '').strip()
        conn = get_db()
        c = conn.cursor()
        if q:
            like = f'%{q}%'
            c.execute(
                '''SELECT * FROM wiki_entries
                   WHERE title LIKE ? OR content LIKE ? OR category LIKE ? OR tags LIKE ?
                   ORDER BY updated_at DESC''',
                (like, like, like, like)
            )
        else:
            c.execute('SELECT * FROM wiki_entries ORDER BY updated_at DESC')
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        print(f'[DEBUG] GET /api/wikitoca/entries retornando {len(rows)} registros')
        return jsonify(rows)
    except Exception as e:
        print(f'[ERROR] GET /api/wikitoca/entries: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRIES_LIST_ERROR', 'Erro ao listar conhecimentos.', details=str(e),
                         hint='Verifique se o banco de dados está acessível.')


@app.route('/api/wikitoca/entries', methods=['POST'])
def create_wiki_entry():
    print('[DEBUG] POST /api/wikitoca/entries chamado')
    try:
        data = request.get_json(force=True) or {}
        print(f'[DEBUG] POST /api/wikitoca/entries payload: {data}')
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()
        category = (data.get('category') or '').strip() or None
        tags = (data.get('tags') or '').strip() or None
        if not title or not content:
            print('[WARN] POST /api/wikitoca/entries: titulo ou conteudo ausente')
            return api_error(400, 'WIKI_ENTRY_MISSING_FIELDS', 'Título e conteúdo são obrigatórios.')
        conn = get_db()
        c = conn.cursor()
        c.execute(
            '''INSERT INTO wiki_entries (title, category, content, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
            (title, category, content, tags)
        )
        conn.commit()
        entry_id = c.lastrowid
        c.execute('SELECT * FROM wiki_entries WHERE id = ?', (entry_id,))
        entry = dict_from_row(c.fetchone())
        conn.close()
        print(f'[DEBUG] POST /api/wikitoca/entries criado id={entry_id}')
        return jsonify(entry), 201
    except Exception as e:
        print(f'[ERROR] POST /api/wikitoca/entries: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_CREATE_ERROR', 'Erro ao criar conhecimento.', details=str(e))


@app.route('/api/wikitoca/entries/<int:entry_id>', methods=['PUT'])
def update_wiki_entry(entry_id):
    print(f'[DEBUG] PUT /api/wikitoca/entries/{entry_id} chamado')
    try:
        data = request.get_json(force=True) or {}
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()
        category = (data.get('category') or '').strip() or None
        tags = (data.get('tags') or '').strip() or None
        if not title or not content:
            return api_error(400, 'WIKI_ENTRY_MISSING_FIELDS', 'Título e conteúdo são obrigatórios.')
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM wiki_entries WHERE id = ?', (entry_id,))
        if not c.fetchone():
            conn.close()
            print(f'[WARN] PUT /api/wikitoca/entries/{entry_id}: nao encontrado')
            return api_error(404, 'WIKI_ENTRY_NOT_FOUND', 'Conhecimento não encontrado.')
        c.execute(
            '''UPDATE wiki_entries
               SET title = ?, category = ?, content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (title, category, content, tags, entry_id)
        )
        conn.commit()
        c.execute('SELECT * FROM wiki_entries WHERE id = ?', (entry_id,))
        entry = dict_from_row(c.fetchone())
        conn.close()
        print(f'[DEBUG] PUT /api/wikitoca/entries/{entry_id} atualizado')
        return jsonify(entry)
    except Exception as e:
        print(f'[ERROR] PUT /api/wikitoca/entries/{entry_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_UPDATE_ERROR', 'Erro ao atualizar conhecimento.', details=str(e))


@app.route('/api/wikitoca/entries/<int:entry_id>', methods=['DELETE'])
def delete_wiki_entry(entry_id):
    print(f'[DEBUG] DELETE /api/wikitoca/entries/{entry_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id FROM wiki_entries WHERE id = ?', (entry_id,))
        if not c.fetchone():
            conn.close()
            return api_error(404, 'WIKI_ENTRY_NOT_FOUND', 'Conhecimento não encontrado.')
        c.execute('DELETE FROM wiki_entries WHERE id = ?', (entry_id,))
        conn.commit()
        conn.close()
        print(f'[DEBUG] DELETE /api/wikitoca/entries/{entry_id} removido')
        return jsonify({'message': 'Conhecimento excluído com sucesso.'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/wikitoca/entries/{entry_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_ENTRY_DELETE_ERROR', 'Erro ao excluir conhecimento.', details=str(e))


# ─────────────────────────────────────────────────────────────
# WikiToca – Documentos
# ─────────────────────────────────────────────────────────────

ALLOWED_WIKI_EXTENSIONS = {'.pdf', '.xls', '.xlsx', '.doc', '.docx'}


@app.route('/api/wikitoca/documents', methods=['GET'])
def list_wiki_documents():
    print('[DEBUG] GET /api/wikitoca/documents chamado')
    try:
        q = (request.args.get('q') or '').strip()
        conn = get_db()
        c = conn.cursor()
        if q:
            like = f'%{q}%'
            c.execute(
                '''SELECT * FROM wiki_documents
                   WHERE title LIKE ? OR original_name LIKE ?
                   ORDER BY updated_at DESC''',
                (like, like)
            )
        else:
            c.execute('SELECT * FROM wiki_documents ORDER BY updated_at DESC')
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()
        print(f'[DEBUG] GET /api/wikitoca/documents retornando {len(rows)} documentos')
        return jsonify(rows)
    except Exception as e:
        print(f'[ERROR] GET /api/wikitoca/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOCS_LIST_ERROR', 'Erro ao listar documentos.', details=str(e))


@app.route('/api/wikitoca/documents', methods=['POST'])
def upload_wiki_documents():
    print('[DEBUG] POST /api/wikitoca/documents chamado')
    try:
        files = request.files.getlist('files')
        print(f'[DEBUG] POST /api/wikitoca/documents arquivos recebidos: {[f.filename for f in files]}')
        if not files or all(not f.filename for f in files):
            return api_error(400, 'WIKI_DOC_NO_FILE', 'Nenhum arquivo enviado.')
        title = (request.form.get('title') or '').strip()
        conn = get_db()
        c = conn.cursor()
        created = []
        for f in files:
            if not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_WIKI_EXTENSIONS:
                print(f'[WARN] POST /api/wikitoca/documents: extensao rejeitada: {ext}')
                continue
            original_name = f.filename
            safe_name = secure_filename(f'wiki_{int(datetime.now().timestamp())}_{original_name}')
            save_path = WIKI_UPLOAD_DIR / safe_name
            f.save(str(save_path))
            file_size = save_path.stat().st_size
            file_url = f'/uploads/wikitoca/{safe_name}'
            doc_title = title or original_name
            c.execute(
                '''INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, file_size,
                                              created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (doc_title, safe_name, original_name, file_url, ext, file_size)
            )
            conn.commit()
            doc_id = c.lastrowid
            c.execute('SELECT * FROM wiki_documents WHERE id = ?', (doc_id,))
            created.append(dict_from_row(c.fetchone()))
            print(f'[DEBUG] POST /api/wikitoca/documents salvo id={doc_id} nome={original_name}')
        conn.close()
        if not created:
            return api_error(400, 'WIKI_DOC_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, XLS, XLSX, DOC, DOCX.')
        return jsonify(created), 201
    except Exception as e:
        print(f'[ERROR] POST /api/wikitoca/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_UPLOAD_ERROR', 'Erro ao enviar documento.', details=str(e))


@app.route('/api/wikitoca/documents/<int:document_id>', methods=['DELETE'])
def delete_wiki_document(document_id):
    print(f'[DEBUG] DELETE /api/wikitoca/documents/{document_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM wiki_documents WHERE id = ?', (document_id,))
        row = dict_from_row(c.fetchone())
        if not row:
            conn.close()
            return api_error(404, 'WIKI_DOC_NOT_FOUND', 'Documento não encontrado.')
        file_path = WIKI_UPLOAD_DIR / row['file_name']
        if file_path.exists():
            file_path.unlink()
        c.execute('DELETE FROM wiki_documents WHERE id = ?', (document_id,))
        conn.commit()
        conn.close()
        print(f'[DEBUG] DELETE /api/wikitoca/documents/{document_id} removido')
        return jsonify({'message': 'Documento removido com sucesso.'})
    except Exception as e:
        print(f'[ERROR] DELETE /api/wikitoca/documents/{document_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_DELETE_ERROR', 'Erro ao remover documento.', details=str(e))


# WikiToca - Export/Import XLSX

@app.route('/api/wikitoca/entries/export-xlsx', methods=['GET'])
def export_wikitoca_xlsx():
    try:
        print('[DEBUG] GET /api/wikitoca/entries/export-xlsx chamado')
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Exportação XLSX requer openpyxl instalado'}), 500
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT title, category, tags, content FROM wiki_entries ORDER BY updated_at DESC')
        rows = c.fetchall()
        conn.close()
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Conhecimentos'
        headers = ['Título', 'Categoria', 'Tags', 'Descrição']
        ws.append(headers)
        header_fill = PatternFill(start_color='34D399', end_color='34D399', fill_type='solid')
        for col_idx, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 30
        ws.column_dimensions['D'].width = 60
        for row in rows:
            ws.append([
                row['title'] or '',
                row['category'] or '',
                row['tags'] or '',
                row['content'] or ''
            ])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        from flask import send_file
        return send_file(
            output,
            as_attachment=True,
            download_name='wikitoca_conhecimentos.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        print(f'[ERROR] GET /api/wikitoca/entries/export-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/wikitoca/entries/template-xlsx', methods=['GET'])
def wikitoca_template_xlsx():
    try:
        print('[DEBUG] GET /api/wikitoca/entries/template-xlsx chamado')
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Template XLSX requer openpyxl instalado'}), 500
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Conhecimentos'
        headers = ['Título', 'Categoria', 'Descrição']
        ws.append(headers)
        header_fill = PatternFill(start_color='34D399', end_color='34D399', fill_type='solid')
        for col_idx, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 60
        ws.append(['Exemplo de título', 'Comercial', 'Descreva aqui o conhecimento a ser registrado.'])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        from flask import send_file
        return send_file(
            output,
            as_attachment=True,
            download_name='wikitoca_template.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        print(f'[ERROR] GET /api/wikitoca/entries/template-xlsx: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/wikitoca/entries/import-xlsx', methods=['POST'])
def import_wikitoca_xlsx():
    try:
        print('[DEBUG] POST /api/wikitoca/entries/import-xlsx chamado')
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado'}), 400
        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith('.xlsx'):
            return jsonify({'error': 'Envie um arquivo .xlsx'}), 400
        if not OPENPYXL_AVAILABLE:
            return jsonify({'error': 'Importação XLSX requer openpyxl instalado'}), 500
        import openpyxl
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        try:
            wb = openpyxl.load_workbook(tmp_path, data_only=True)
            ws = wb.active
            rows_data = list(ws.iter_rows(values_only=True))
        finally:
            _os.unlink(tmp_path)
        if not rows_data:
            return jsonify({'error': 'Arquivo vazio'}), 400
        # Detectar colunas pelo cabeçalho
        header = [str(c).strip().lower() if c else '' for c in rows_data[0]]
        def find_col(names):
            for name in names:
                if name in header:
                    return header.index(name)
            return None
        col_title = find_col(['título', 'titulo', 'title'])
        col_cat = find_col(['categoria', 'category'])
        col_desc = find_col(['descrição', 'descricao', 'description', 'conteúdo', 'conteudo', 'content'])
        if col_title is None or col_desc is None:
            return jsonify({'error': 'Colunas obrigatórias não encontradas. O arquivo deve ter colunas Título e Descrição.'}), 400
        # Função de geração de tags (mesma lógica do frontend)
        stopwords = {'a','o','os','as','de','da','do','das','dos','e','é','em','no','na','nos','nas','um','uma','uns','umas','para','por','com','sem','que','se','ao','aos','à','às','ou','como','mais','menos','ja','não','sim'}
        def generate_tags(title, content):
            import re
            text = f'{title or ""} {content or ""}'.lower()
            words = re.findall(r'[a-záàãâéêíóôõúüç0-9-]{3,}', text)
            rank = {}
            for w in words:
                if w in stopwords or w.isdigit():
                    continue
                rank[w] = rank.get(w, 0) + 1
            sorted_words = sorted(rank.items(), key=lambda x: (-x[1], x[0]))
            return ', '.join(w for w, _ in sorted_words[:6])
        conn = get_db()
        c = conn.cursor()
        ok = 0
        fail = 0
        errors = []
        for idx, row in enumerate(rows_data[1:], start=2):
            try:
                title = str(row[col_title]).strip() if row[col_title] else ''
                category = str(row[col_cat]).strip() if col_cat is not None and row[col_cat] else ''
                content = str(row[col_desc]).strip() if row[col_desc] else ''
                if not title or not content:
                    fail += 1
                    errors.append(f'Linha {idx}: título ou descrição vazia')
                    continue
                tags = generate_tags(title, content)
                now = datetime.utcnow().isoformat() + 'Z'
                c.execute(
                    'INSERT INTO wiki_entries (title, category, tags, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (title, category, tags, content, now, now)
                )
                ok += 1
            except Exception as row_err:
                fail += 1
                errors.append(f'Linha {idx}: {str(row_err)}')
        conn.commit()
        conn.close()
        print(f'[DEBUG] POST /api/wikitoca/entries/import-xlsx: {ok} importados, {fail} erros')
        return jsonify({'imported': ok, 'failed': fail, 'errors': errors[:10]}), 200
    except Exception as e:
        print(f'[ERROR] POST /api/wikitoca/entries/import-xlsx: {e}')
        return jsonify({'error': str(e)}), 500




@app.route('/api/autotoca/accounts', methods=['GET'])
def autotoca_accounts():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name FROM accounts ORDER BY name COLLATE NOCASE')
        rows = c.fetchall()
        conn.close()
        accounts = [{'id': row['id'], 'name': row['name']} for row in rows]
        return jsonify([{'id': 0, 'name': 'OUTRO'}] + accounts)
    except Exception as e:
        logger.exception(f'[AutoToca] GET /api/autotoca/accounts: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/upload', methods=['POST'])
def autotoca_upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Nome de arquivo inválido.'}), 400
        
        # Verificar se deve converter para PDF (parâmetro convert_to_pdf)
        convert_to_pdf = request.form.get('convert_to_pdf', 'false').lower() == 'true'
        original_filename = secure_filename(file.filename)
        
        # Se deve converter para PDF
        if convert_to_pdf and not original_filename.lower().endswith('.pdf'):
            try:
                # Salvar arquivo temporário
                temp_path = AUTOTOCA_UPLOAD_DIR / f"temp_{uuid.uuid4().hex}_{original_filename}"
                file.save(str(temp_path))
                
                # Converter para PDF
                pdf_filename = original_filename.rsplit('.', 1)[0] + '.pdf'
                safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{pdf_filename}"
                target = AUTOTOCA_UPLOAD_DIR / safe_name
                
                # Se é um arquivo de imagem, converter para PDF
                file_ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
                if file_ext in {'jpg', 'jpeg', 'png', 'gif', 'bmp'}:
                    try:
                        from PIL import Image
                        img = Image.open(str(temp_path))
                        if img.mode == 'RGBA':
                            img = img.convert('RGB')
                        img.save(str(target), 'PDF')
                        logger.info(f'[AutoToca] Imagem convertida para PDF: {original_filename} -> {pdf_filename}')
                    except Exception as e:
                        logger.warning(f'[AutoToca] Falha ao converter imagem para PDF: {e}. Usando arquivo original.')
                        target = AUTOTOCA_UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
                        file.seek(0)
                        file.save(str(target))
                        pdf_filename = original_filename
                elif file_ext in {'docx', 'doc', 'txt', 'html', 'htm'}:
                    try:
                        # Para documentos Word, usar python-docx
                        if file_ext in {'docx', 'doc'} and PYTHON_DOCX_AVAILABLE:
                            from reportlab.lib.pagesizes import letter
                            from reportlab.pdfgen import canvas
                            doc = python_docx.Document(str(temp_path))
                            c = canvas.Canvas(str(target), pagesize=letter)
                            y = 750
                            for para in doc.paragraphs:
                                if para.text.strip():
                                    text = para.text[:100]
                                    c.drawString(50, y, text)
                                    y -= 20
                                    if y < 50:
                                        c.showPage()
                                        y = 750
                            c.save()
                            logger.info(f'[AutoToca] Documento convertido para PDF: {original_filename} -> {pdf_filename}')
                        else:
                            # Fallback: copiar arquivo original
                            shutil.copy2(str(temp_path), str(target))
                    except Exception as e:
                        logger.warning(f'[AutoToca] Falha ao converter documento para PDF: {e}. Usando arquivo original.')
                        shutil.copy2(str(temp_path), str(target))
                else:
                    # Para outros formatos, apenas copiar
                    shutil.copy2(str(temp_path), str(target))
                
                # Remover arquivo temporário
                try:
                    temp_path.unlink()
                except:
                    pass
                
                return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': pdf_filename})
            except Exception as e:
                logger.exception(f'[AutoToca] Erro ao converter arquivo para PDF: {e}')
                # Fallback: salvar arquivo original
                safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
                target = AUTOTOCA_UPLOAD_DIR / safe_name
                file.seek(0)
                file.save(str(target))
                return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': original_filename})
        else:
            # Sem conversão, salvar normalmente
            safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{original_filename}"
            target = AUTOTOCA_UPLOAD_DIR / safe_name
            file.save(str(target))
            return jsonify({'path': str(target), 'url': f'/uploads/autotoca/{safe_name}', 'name': file.filename})
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/upload: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/address-suggestion', methods=['POST'])
def autotoca_address_suggestion():
    try:
        data = request.get_json(force=True) or {}
        account_name = (data.get('account_name') or '').strip()
        if not account_name:
            return jsonify({'error': 'Conta inválida para busca de endereço.'}), 400

        service = AccountAddressService()
        heuristic_result = service.find_headquarter_address(account_name)

        sai_result = _autotoca_suggest_address_via_sai(
            account_name,
            heuristic_address=heuristic_result.get('suggested_address', ''),
            heuristic_source=heuristic_result.get('source', '')
        )

        if sai_result and sai_result.get('suggested_address'):
            sai_confidence = (sai_result.get('confidence') or 'medium').lower().strip()
            if sai_confidence != 'low' or not heuristic_result.get('suggested_address'):
                return jsonify(sai_result)

        result = heuristic_result
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/address-suggestion: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/support-files', methods=['GET'])
def autotoca_support_files():
    try:
        files = []
        for path in sorted(AUTOTOCA_SUPPORT_FILES_DIR.glob('*')):
            if not path.is_file():
                continue
            if path.suffix.lower() != '.pdf':
                continue
            files.append({
                'name': path.name,
                'url': f'/assets/autotoca/chamado-juridico/{urllib.parse.quote(path.name)}'
            })
        return jsonify(files)
    except Exception as e:
        logger.exception(f'[AutoToca] GET /api/autotoca/support-files: {e}')
        return jsonify({'error': str(e)}), 500


def _autotoca_suggest_address_via_sai(account_name: str, heuristic_address: str = '', heuristic_source: str = ''):
    """Tenta obter endereço de sede via SAI LLM; retorna dict padronizado ou None."""
    settings_map = _load_app_settings_map(['itoca_sai_api_key', 'itoca_sai_template_id', 'itoca_sai_base_url'])
    api_key = (settings_map.get('itoca_sai_api_key') or '').strip() or (os.environ.get('ITOCA_SAI_API_KEY', '') or '').strip()
    template_id = (settings_map.get('itoca_sai_template_id') or '').strip() or '69ac3c87024adc2d2bdc19f5'
    base_url = (settings_map.get('itoca_sai_base_url') or '').strip() or 'https://sai-library.saiapplications.com'

    if not api_key:
        return None

    question = (
        f"Qual é o endereço da sede/matriz no Brasil da empresa '{account_name}'? "
        "Retorne SOMENTE um JSON válido no formato: "
        "{\"suggested_address\":\"...\",\"confidence\":\"high|medium|low\",\"source\":\"...\"}. "
        "Se não encontrar com segurança, retorne suggested_address vazio e confidence low."
    )
    context_sources = (
        f"Empresa: {account_name}.\n"
        f"Sugestão heurística anterior: {heuristic_address or 'nenhuma'}.\n"
        f"Fonte heurística: {heuristic_source or 'n/a'}."
    )

    url = f'{base_url}/api/templates/{template_id}/execute'
    headers = {
        'Content-Type': 'application/json',
        'X-Api-Key': api_key,
    }
    payload = {
        'inputs': {
            'question': question,
            'context_sources': context_sources,
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f'[AutoToca][Address][SAI] falha na chamada SAI: {e}')
        return None

    def _try_parse_json(value):
        if not value:
            return None
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value.strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    parsed = _try_parse_json(raw) or {}
    if 'answer' not in parsed:
        for key in ('output', 'result', 'text', 'content', 'response', 'data', 'message'):
            candidate = parsed.get(key)
            nested = _try_parse_json(candidate)
            if nested:
                parsed = nested
                break

    answer = parsed.get('answer') if isinstance(parsed, dict) else ''
    answer_obj = _try_parse_json(answer) if isinstance(answer, str) else None
    if answer_obj:
        parsed = answer_obj

    suggested = (parsed.get('suggested_address') or '').strip() if isinstance(parsed, dict) else ''
    confidence = (parsed.get('confidence') or 'medium').strip().lower() if isinstance(parsed, dict) else 'medium'
    source = (parsed.get('source') or '').strip() if isinstance(parsed, dict) else ''

    # fallback: quando o template devolve texto livre em "answer"
    if not suggested and isinstance(answer, str):
        for line in [ln.strip(' -•\t') for ln in answer.splitlines() if ln.strip()]:
            if AccountAddressService._is_candidate_address(line):
                suggested = line
                break

    if not suggested or not AccountAddressService._is_candidate_address(suggested):
        return None

    if confidence not in ('high', 'medium', 'low'):
        confidence = 'medium'

    return {
        'suggested_address': suggested,
        'source': source or 'SAI LLM (iToca)',
        'confidence': confidence,
    }



@app.route('/api/autotoca/chamado-juridico/playwright', methods=['POST'])
def autotoca_chamado_juridico_playwright():
    try:
        data = request.get_json(force=True) or {}
        conta = (data.get('conta') or '').strip()
        if not conta:
            return jsonify({'ok': False, 'error': 'Conta é obrigatória.'}), 400
        payload = {'forms_url': data.get('forms_url'), 'target_value': conta}
        try:
            result = _run_autotoca_playwright_fill(payload)
        except Exception as exc:
            logger.exception('[AutoToca] Falha no Playwright')
            result = {'ok': False, 'strategy': 'playwright', 'reason': 'playwright_failed', 'error': str(exc)}
        if not result.get('ok'):
            result['fallback'] = _run_autotoca_selenium_fill(payload)
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/chamado-juridico/playwright: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/autotoca/linkedin/teste', methods=['POST'])
def autotoca_teste_linkedin():
    try:
        data = request.get_json(force=True) or {}
        name = (data.get('name') or '').strip()
        company = (data.get('company') or '').strip()
        if not name or not company:
            return jsonify({'ok': False, 'error': 'Informe nome e empresa.'}), 400
        return jsonify({'ok': True, 'items': _linkedin_mock_candidates(name, company), 'mode': 'safe_fallback'})
    except Exception as e:
        logger.exception(f'[AutoToca] POST /api/autotoca/linkedin/teste: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

# Servir arquivos estaticos

@app.route('/uploads/accounts/<filename>')
def serve_account_upload(filename):
    return send_from_directory(str(ACCOUNT_UPLOAD_DIR), filename)

@app.route('/uploads/wikitoca/<filename>')
def serve_wikitoca_upload(filename):
    return send_from_directory(str(WIKI_UPLOAD_DIR), filename)

@app.route('/uploads/autotoca/<filename>')
def serve_autotoca_upload(filename):
    return send_from_directory(str(AUTOTOCA_UPLOAD_DIR), filename)

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


@app.errorhandler(Exception)
def handle_unexpected_exception(error):
    if isinstance(error, HTTPException):
        return error
    logger.exception(f'[Unhandled] Erro inesperado: {error}')
    return jsonify({'error': 'Erro interno inesperado. Consulte os logs para suporte.'}), 500

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
