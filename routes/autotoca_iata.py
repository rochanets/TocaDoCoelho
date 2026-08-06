# -*- coding: utf-8 -*-
# Rotas do iAta dentro do AutoToca.
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a get_db, logger, json, dict_from_row e afins.

from integrations import iata as iata_lib


def _iata_save_record(header, managers, extras, raw_text, previous_record_id,
                      body_markdown=None):
    """Grava a ata e a hierarquia. Devolve o id do registro.

    Uma única conexão/transação cobre o INSERT em iata_records e a escrita
    da hierarquia: se `_iata_write_hierarchy` levantar no meio, nada foi
    commitado ainda, e fechar a conexão sem commit descarta o INSERT também
    — não sobra um registro órfão sem hierarquia.
    """
    header = header or {}
    body = body_markdown or iata_lib.render_markdown(header, managers, extras)
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO iata_records
               (title, meeting_date, meeting_time, topic, participants, ata_json,
                insights_json, raw_text, previous_record_id, body_markdown,
                body_edited, reparse_failed, format_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,0,2)''',
            (header.get('title') or 'Ata sem título',
             header.get('meeting_date'), header.get('meeting_time'),
             header.get('topic') or '',
             json.dumps(header.get('participants') or [], ensure_ascii=False),
             json.dumps({'header': header, 'managers': managers, 'extras': extras or {}},
                        ensure_ascii=False),
             json.dumps((extras or {}).get('insights') or [], ensure_ascii=False),
             raw_text or '', previous_record_id, body))
        record_id = c.lastrowid
        _iata_write_hierarchy(c, record_id, managers)
        conn.commit()
        return record_id
    finally:
        conn.close()


def _iata_write_hierarchy(c, record_id, managers):
    """(Re)escreve as tabelas da hierarquia para uma ata."""
    c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
    for m_ordem, manager in enumerate(managers or []):
        c.execute('INSERT INTO iata_managers (record_id, name, display_order) VALUES (?,?,?)',
                  (record_id, manager.get('name') or iata_lib.GERENTE_NAO_IDENTIFICADO, m_ordem))
        manager_id = c.lastrowid
        for a_ordem, account in enumerate(manager.get('accounts') or []):
            nome_conta = account.get('name') or ''
            c.execute(
                '''INSERT INTO iata_accounts
                   (record_id, manager_id, account_id, name, name_norm,
                    match_confidence, match_confirmed, display_order)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (record_id, manager_id, account.get('account_id'), nome_conta,
                 iata_lib.normalize_name(nome_conta), account.get('match_confidence'),
                 1 if account.get('match_confirmed') else 0, a_ordem))
            conta_id = c.lastrowid
            for o_ordem, opp in enumerate(account.get('opportunities') or []):
                nome_opp = opp.get('name') or ''
                c.execute(
                    '''INSERT INTO iata_opportunities
                       (record_id, iata_account_id, name, name_norm, previous_status,
                        update_text, responsible, carried_over, prev_opportunity_id,
                        match_confidence, display_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (record_id, conta_id, nome_opp, iata_lib.normalize_name(nome_opp),
                     opp.get('previous_status'), opp.get('update_text'),
                     opp.get('responsible'), 1 if opp.get('carried_over') else 0,
                     opp.get('prev_opportunity_id'), opp.get('match_confidence'), o_ordem))


def _iata_read_hierarchy(c, record_id):
    """Lê a hierarquia no formato canônico, com os ids do banco.

    O resultado precisa servir como `previous_managers` para
    `iata_lib.reconcile` na próxima ata: cada oportunidade carrega `id`,
    `name`, `update_text` e `responsible` (usados pelo reconcile), além dos
    demais campos persistidos. `carried_over` e `match_confirmed` voltam
    como bool — como foram gravados (True/False) na hierarquia de entrada,
    não como 0/1 do SQLite.
    """
    c.execute('SELECT * FROM iata_managers WHERE record_id = ? ORDER BY display_order, id',
              (record_id,))
    managers = [dict_from_row(r) for r in c.fetchall()]
    for manager in managers:
        c.execute('''SELECT * FROM iata_accounts WHERE manager_id = ?
                     ORDER BY display_order, id''', (manager['id'],))
        contas = [dict_from_row(r) for r in c.fetchall()]
        for conta in contas:
            conta['match_confirmed'] = bool(conta.get('match_confirmed'))
            c.execute('''SELECT * FROM iata_opportunities WHERE iata_account_id = ?
                         ORDER BY display_order, id''', (conta['id'],))
            conta['opportunities'] = [dict_from_row(r) for r in c.fetchall()]
            for opp in conta['opportunities']:
                opp['carried_over'] = bool(opp.get('carried_over'))
        manager['accounts'] = contas
    return managers


def _iata_load_record(record_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM iata_records WHERE id = ?', (record_id,))
        row = c.fetchone()
        if not row:
            return None
        registro = dict_from_row(row)
        try:
            registro['participants'] = json.loads(registro.get('participants') or '[]')
        except Exception:
            registro['participants'] = []
        ata_json = {}
        try:
            ata_json = json.loads(registro.get('ata_json') or '{}')
        except Exception:
            ata_json = {}
        if not isinstance(ata_json, dict):
            ata_json = {}
        try:
            registro['insights_json'] = json.loads(registro.get('insights_json') or '[]')
        except Exception:
            registro['insights_json'] = []
        registro['ata_json'] = ata_json
        registro['extras'] = ata_json.get('extras') or {}
        registro['header'] = ata_json.get('header') or {}
        registro['managers'] = _iata_read_hierarchy(c, record_id)
        return registro
    finally:
        conn.close()


@app.route('/api/autotoca/iata', methods=['GET'])
def list_iata_records():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, title, meeting_date, meeting_time, topic, participants,
                            format_version, body_edited, reparse_failed, created_at
                     FROM iata_records ORDER BY datetime(created_at) DESC, id DESC''')
        registros = []
        for row in c.fetchall():
            r = dict_from_row(row)
            try:
                r['participants'] = json.loads(r.get('participants') or '[]')
            except Exception:
                r['participants'] = []
            registros.append(r)
        conn.close()
        return jsonify(registros)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao listar registros: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['GET'])
def get_iata_record(record_id):
    try:
        registro = _iata_load_record(record_id)
        if not registro:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify(registro)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao buscar registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['DELETE'])
def delete_iata_record(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        # get_db() já liga PRAGMA foreign_keys=ON (o ON DELETE CASCADE do
        # schema cobriria isto sozinho), mas apagamos as filhas explicitamente
        # mesmo assim: não depender de um PRAGMA por conexão para uma
        # exclusão que não pode deixar hierarquia órfã para trás.
        c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_records WHERE id = ?', (record_id,))
        removidos = c.rowcount
        conn.commit()
        conn.close()
        if not removidos:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify({'message': 'Ata removida com sucesso.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao remover registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500
