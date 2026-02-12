#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import sqlite3
import webbrowser
from datetime import datetime
from pathlib import Path
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
DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho' if sys.platform == 'win32' else Path.home() / '.toca-do-coelho'
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'toca-do-coelho.db'
UPLOAD_DIR = DATA_DIR / 'uploads'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
        email TEXT,
        phone TEXT,
        photo_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    # Adicionar coluna last_activity_date à tabela clients se não existir
    c.execute("PRAGMA table_info(clients)")
    columns = [col[1] for col in c.fetchall()]
    if 'last_activity_date' not in columns:
        c.execute('ALTER TABLE clients ADD COLUMN last_activity_date TIMESTAMP')
    
    conn.commit()
    
    # Migração: adicionar colunas se não existirem
    try:
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
        phone = request.form.get('phone', '').strip()
        
        if not name or not company or not position:
            return jsonify({'error': 'Nome, empresa e cargo sao obrigatorios'}), 400
        
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
        c.execute('''INSERT INTO clients (name, company, position, email, phone, photo_url)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (name, company, position, email or None, phone or None, photo_url))
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
        phone = request.form.get('phone', '').strip()
        
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
        
        photo_url = client['photo_url']
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = UPLOAD_DIR / filename
                file.save(str(filepath))
                photo_url = f'/uploads/{filename}'
        
        c.execute('''UPDATE clients SET name = ?, company = ?, position = ?, email = ?, phone = ?, photo_url = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (name, company, position, email or None, phone or None, photo_url, client_id))
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
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada'}), 201
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
        
        # Atualizar last_activity_date do cliente
        c.execute('''UPDATE clients SET last_activity_date = CURRENT_TIMESTAMP WHERE id = ?''',
                  (client_id,))
        conn.commit()
        conn.close()
        
        print(f'[DEBUG] Atividade criada com ID: {activity_id}')
        return jsonify({'id': activity_id, 'message': 'Atividade registrada'}), 201
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
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            if not OPENPYXL_AVAILABLE:
                return jsonify({'error': 'Instale openpyxl: pip install openpyxl'}), 400
            
            try:
                from openpyxl import load_workbook
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                    file.save(tmp.name)
                    wb = load_workbook(tmp.name, data_only=True)
                    ws = wb.active
                    
                    for idx, row in enumerate(ws.iter_rows(values_only=True)):
                        if idx == 0:
                            continue
                        # Converter valores para string e limpar
                        row_data = []
                        for cell in row:
                            if cell is None:
                                row_data.append('')
                            else:
                                # Converter para string e remover caracteres especiais
                                val = str(cell).strip()
                                # Verificar se contem caracteres invalidos
                                if any(ord(c) > 127 and ord(c) < 160 for c in val):
                                    val = val.encode('utf-8', errors='ignore').decode('utf-8')
                                row_data.append(val)
                        rows.append(row_data)
                    
                    os.unlink(tmp.name)
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

# Servir arquivos estaticos
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
