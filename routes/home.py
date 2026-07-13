# -*- coding: utf-8 -*-
# Rotas do domínio "home" (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`, com URLs idênticas às originais.

# ===========================================================================
# Radar do Dia (Bloco 5) — motor de sugestões priorizado por score.
# Categorias geradas aqui; Blocos 9/10/11/12 adicionam categorias próprias
# inserindo em daily_suggestions com seus suggestion_type.
# ===========================================================================

RADAR_MAX_ACTIVE = 8            # sugestões ativas exibidas por dia
RADAR_KANBAN_STALL_DAYS = 5     # dias parado para card de urgência Alta


def _radar_generate_ranked(c):
    """Gera a lista completa de sugestões candidatas, ordenada por score
    (maior primeiro). Consultas agregadas — sem N+1 por cliente."""
    now_dt = datetime.now()
    today = now_dt.strftime('%Y-%m-%d')
    get_thresholds = _home_status_thresholds(c)
    suggestions = []

    # ---- 1. Contatos atrasados (threshold por cargo) + nunca contatados ----
    c.execute("""
        SELECT cl.id, cl.name, cl.company, cl.position, cl.last_activity_date,
               COALESCE(cl.is_target, 0) AS is_target,
               (SELECT COUNT(*) FROM commitments co
                WHERE co.client_id = cl.id AND co.due_date < ?
                  AND NOT EXISTS (SELECT 1 FROM activities a
                                  WHERE a.client_id = co.client_id
                                    AND date(a.activity_date) >= co.due_date)) AS overdue_fups
        FROM clients cl
        WHERE COALESCE(cl.is_archived, 0) = 0 AND COALESCE(cl.is_cold_contact, 0) = 0
    """, (today,))
    for row in c.fetchall():
        green, yellow = get_thresholds(row['position'])
        status, days = _home_status_for(row['last_activity_date'], green, yellow, now_dt)
        target_bonus = 2.0 if row['is_target'] else 0.0
        fup_bonus = 3.0 * min(row['overdue_fups'], 3)
        if not row['last_activity_date']:
            # Nunca contatado: prioridade máxima da categoria
            score = 100.0 + target_bonus + fup_bonus
            desc = 'Nunca contatado'
        elif status == 'atrasado' and days is not None:
            score = 10.0 * (days / max(yellow, 1)) + target_bonus + fup_bonus
            desc = f'Sem contato há {days} dias (limite do cargo: {yellow})'
        else:
            continue
        suggestions.append({
            'type': 'contact_overdue', 'score': score,
            'title': f'Contatar {row["name"]} ({row["company"]})',
            'description': desc,
            'target_id': row['id'],
            'target_data': json.dumps({'client_id': row['id'], 'days': days}),
        })

    # ---- 2. Follow-ups vencidos sem atividade posterior (fecha o loop) ----
    c.execute("""
        SELECT co.id AS commitment_id, co.title, co.due_date,
               cl.id AS client_id, cl.name, cl.company,
               COALESCE(cl.is_target, 0) AS is_target,
               CAST(julianday(?) - julianday(co.due_date) AS INTEGER) AS days_overdue
        FROM commitments co
        JOIN clients cl ON cl.id = co.client_id
        WHERE co.due_date < ?
          AND COALESCE(cl.is_archived, 0) = 0 AND COALESCE(cl.is_cold_contact, 0) = 0
          AND NOT EXISTS (SELECT 1 FROM activities a
                          WHERE a.client_id = co.client_id
                            AND date(a.activity_date) >= co.due_date)
    """, (today, today))
    for row in c.fetchall():
        suggestions.append({
            'type': 'followup_overdue',
            'score': 50.0 + 0.5 * max(row['days_overdue'] or 0, 0) + (2.0 if row['is_target'] else 0.0),
            'title': f'Follow-up vencido: {row["name"]} ({row["company"]})',
            'description': f'"{row["title"]}" venceu em {row["due_date"]} sem atividade registrada depois',
            'target_id': row['commitment_id'],
            'target_data': json.dumps({'commitment_id': row['commitment_id'], 'client_id': row['client_id'],
                                       'due_date': row['due_date']}),
        })

    # ---- 3. Cards de Kanban com urgência Alta parados há mais de N dias ----
    c.execute("""
        SELECT k.id, k.title, k.updated_at,
               CAST(julianday('now', 'localtime') - julianday(k.updated_at) AS INTEGER) AS stalled_days,
               a.name AS account_name
        FROM kanban_cards k
        LEFT JOIN kanban_columns col ON col.id = k.column_id
        LEFT JOIN accounts a ON a.id = k.account_id
        WHERE LOWER(COALESCE(k.urgency, '')) IN ('alta', 'high')
          AND LOWER(COALESCE(col.title, '')) NOT LIKE '%conclu%'
          AND LOWER(COALESCE(col.title, '')) NOT LIKE '%finaliz%'
          AND julianday('now', 'localtime') - julianday(k.updated_at) > ?
    """, (RADAR_KANBAN_STALL_DAYS,))
    for row in c.fetchall():
        extra = f' — {row["account_name"]}' if row['account_name'] else ''
        suggestions.append({
            'type': 'kanban_stalled',
            'score': 15.0 + 0.5 * (row['stalled_days'] or 0),
            'title': f'Destravar card "{row["title"]}"{extra}',
            'description': f'Urgência Alta parado há {row["stalled_days"]} dias no Kanban',
            'target_id': row['id'],
            'target_data': json.dumps({'card_id': row['id']}),
        })

    # ---- 3a. Mudança de emprego detectada pela extensão (Bloco 11) ----
    c.execute("""
        SELECT ev.id, ev.empresa_antiga, ev.empresa_nova, ev.cargo_novo,
               ev.potential_new_account, cl.id AS client_id, cl.name
        FROM job_change_events ev
        JOIN clients cl ON cl.id = ev.client_id
        WHERE ev.status = 'pendente'
    """)
    for row in c.fetchall():
        extra = ' — conta nova em potencial' if row['potential_new_account'] else ''
        cargo = f' como {row["cargo_novo"]}' if row['cargo_novo'] else ''
        suggestions.append({
            'type': 'job_change',
            'score': 70.0,
            'title': f'{row["name"]} mudou para {row["empresa_nova"]}',
            'description': f'Saiu da {row["empresa_antiga"]}{cargo}. Reative o relacionamento e avalie abrir a conta{extra}.',
            'target_id': row['id'],
            'target_data': json.dumps({'event_id': row['id'], 'client_id': row['client_id'],
                                       'empresa_nova': row['empresa_nova'],
                                       'potential_new_account': bool(row['potential_new_account'])},
                                      ensure_ascii=False),
        })

    # ---- 3b. Multithreading: contas target single-threaded (Bloco 10) ----
    try:
        grouping_map = _thread_grouping_map(c)
        c.execute("SELECT id, name FROM accounts WHERE COALESCE(is_target, 0) = 1")
        for acc in c.fetchall():
            score = _account_thread_score(c, acc['id'], acc['name'], 1, grouping_map, get_thresholds)
            if not score['single_threaded']:
                continue
            missing = score['missing_levels'][0] if score['missing_levels'] else 'outro nível'
            plural = 'contato ativo' if score['active_contacts'] == 1 else 'contatos ativos'
            suggestions.append({
                'type': 'multithreading',
                'score': 25.0 + (5.0 if score['active_contacts'] == 0 else 0.0),
                'title': f'Mapear mais um decisor na conta {acc["name"]}',
                'description': f'{score["active_contacts"]} {plural} — risco de concentração. Nível ausente: {missing}',
                'target_id': acc['id'],
                'target_data': json.dumps({'account_id': acc['id'], 'company': acc['name'],
                                           'missing_level': missing}, ensure_ascii=False),
            })
    except Exception as e:
        logger.debug(f'[Radar] score de multithreading indisponível: {e}')

    # ---- 3c. Whitespace de ofertas em contas target (Bloco 12) ----
    try:
        c.execute("SELECT COUNT(*) FROM portfolio_offers")
        if c.fetchone()[0] > 0:
            c.execute("""SELECT a.id, a.name FROM accounts a
                         WHERE COALESCE(a.is_target, 0) = 1
                           AND EXISTS (SELECT 1 FROM account_presences p
                                       WHERE p.account_id = a.id
                                         AND COALESCE(p.early_terminated, 0) = 0)""")
            for acc in c.fetchall():
                ws = _account_whitespace(c, acc['id'])
                if not ws['missing']:
                    continue
                offer = ws['missing'][0]
                present_names = ', '.join(o['title'] for o in ws['present'][:3]) or 'nenhuma oferta ainda'
                suggestions.append({
                    'type': 'whitespace',
                    'score': 12.0,
                    'title': f'Apresentar {offer["title"]} para a conta {acc["name"]}',
                    'description': f'Oferta nunca explorada nesta conta (já usa: {present_names})',
                    'target_id': acc['id'],
                    'target_data': json.dumps({'account_id': acc['id'], 'company': acc['name'],
                                               'offer': offer['title'],
                                               'present': [o['title'] for o in ws['present'][:5]]},
                                              ensure_ascii=False),
                })
    except Exception as e:
        logger.debug(f'[Radar] whitespace indisponível: {e}')

    # ---- 4. Cadastros incompletos (baixa prioridade, consulta agregada) ----
    c.execute("""
        SELECT id, name, company, email, phone, photo_url,
               COALESCE(is_target, 0) AS is_target
        FROM clients
        WHERE COALESCE(is_archived, 0) = 0 AND COALESCE(is_cold_contact, 0) = 0
          AND (email IS NULL OR email = '' OR phone IS NULL OR phone = '')
    """)
    for row in c.fetchall():
        missing = []
        if not row['email']:
            missing.append('e-mail')
        if not row['phone']:
            missing.append('telefone')
        if not row['photo_url']:
            missing.append('foto')
        suggestions.append({
            'type': 'incomplete_profile',
            'score': 1.0 + (1.0 if row['is_target'] else 0.0),
            'title': f'Completar cadastro de {row["name"]} ({row["company"]})',
            'description': 'Faltam: ' + ', '.join(missing),
            'target_id': row['id'],
            'target_data': json.dumps({'client_id': row['id'], 'missing': missing}),
        })

    # Dedup (tipo + alvo) e ranking
    unique, seen = [], set()
    for sug in suggestions:
        key = (sug['type'], sug['target_data'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(sug)
    unique.sort(key=lambda s: s['score'], reverse=True)
    return unique


def _radar_fill_today(c, today, limit=RADAR_MAX_ACTIVE):
    """Completa as sugestões do dia até `limit` ativas, usando o ranking.
    Retorna quantas foram inseridas."""
    c.execute("""SELECT suggestion_type, target_data FROM daily_suggestions
                 WHERE date = ?""", (today,))
    existing_keys = {(r['suggestion_type'], r['target_data']) for r in c.fetchall()}
    c.execute("""SELECT COUNT(*) FROM daily_suggestions
                 WHERE date = ? AND completed = 0
                   AND (snoozed_until IS NULL OR snoozed_until <= ?)""", (today, today))
    active = c.fetchone()[0]
    if active >= limit:
        return 0
    inserted = 0
    for sug in _radar_generate_ranked(c):
        if active + inserted >= limit:
            break
        if (sug['type'], sug['target_data']) in existing_keys:
            continue
        c.execute("""INSERT INTO daily_suggestions
                     (date, suggestion_type, title, description, target_id, target_data, score)
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (today, sug['type'], sug['title'], sug['description'],
                   sug['target_id'], sug['target_data'], sug['score']))
        existing_keys.add((sug['type'], sug['target_data']))
        inserted += 1
    return inserted


@app.route('/api/suggestions/today', methods=['GET'])
def get_today_suggestions():
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = get_db()
        c = conn.cursor()
        _radar_fill_today(c, today)
        conn.commit()
        c.execute("""SELECT * FROM daily_suggestions
                     WHERE date = ? AND (snoozed_until IS NULL OR snoozed_until <= ?)
                     ORDER BY completed ASC, score DESC, id ASC""", (today, today))
        result = [dict_from_row(row) for row in c.fetchall()]
        conn.close()
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/suggestions/today: {e}')
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

        c.execute("""UPDATE daily_suggestions
                     SET completed = 1, completed_at = CURRENT_TIMESTAMP
                     WHERE id = ?""", (suggestion_id,))

        # Reposição: traz a próxima sugestão do ranking para o mesmo dia
        today = datetime.now().strftime('%Y-%m-%d')
        _radar_fill_today(c, today)
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sugestão marcada como concluída'})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/suggestions/{suggestion_id}/complete: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/suggestions/<int:suggestion_id>/snooze', methods=['POST'])
def snooze_suggestion(suggestion_id):
    """Adia uma sugestão por N dias (default 1)."""
    try:
        data = request.get_json(silent=True) or {}
        days = int(data.get('days') or 1)
        until = (datetime.now() + timedelta(days=max(days, 1))).strftime('%Y-%m-%d')
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE daily_suggestions SET snoozed_until = ? WHERE id = ?', (until, suggestion_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Sugestão não encontrada'}), 404
        today = datetime.now().strftime('%Y-%m-%d')
        _radar_fill_today(c, today)
        conn.commit()
        conn.close()
        return jsonify({'message': f'Sugestão adiada até {until}', 'snoozed_until': until})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/suggestions/{suggestion_id}/snooze: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/home/cobertura-detail', methods=['GET'])
def home_cobertura_detail():
    """Detalhamento conta-a-conta da Cobertura de Relacionamento (últimos 30 dias).
    Considera 3 fontes de atividade por conta:
      1. account_activities diretamente ligadas à conta
      2. activities de clientes vinculados via account_main_contacts
      3. activities de qualquer contato cujo clients.company bate com accounts.name (fallback)
    Atividades duplicadas nas fontes 2 e 3 são deduplicadas por ID.
    """
    try:
        conn = get_db()
        c = conn.cursor()

        # Subconsultas correlacionadas garantem deduplicação correta entre os 3 caminhos
        c.execute("""
            SELECT
                acc.id,
                acc.name,
                COALESCE(acc.is_target, 0) AS is_target,
                -- Atividades diretas na conta (account_activities)
                (
                    SELECT COUNT(DISTINCT aa.id) FROM account_activities aa
                    WHERE aa.account_id = acc.id
                    AND aa.activity_date >= date('now', '-30 days')
                ) AS aa_count,
                -- Atividades de contatos ligados à conta (via account_main_contacts OU nome da empresa)
                -- UNION garante que a mesma activity.id não seja contada duas vezes
                (
                    SELECT COUNT(*) FROM (
                        SELECT DISTINCT a.id FROM activities a
                        WHERE a.activity_date >= date('now', '-30 days')
                        AND (
                            a.client_id IN (
                                SELECT amc.client_id FROM account_main_contacts amc
                                WHERE amc.account_id = acc.id
                            )
                            OR
                            a.client_id IN (
                                SELECT cl.id FROM clients cl
                                WHERE LOWER(TRIM(cl.company)) = LOWER(TRIM(acc.name))
                                AND cl.company IS NOT NULL AND TRIM(cl.company) != ''
                            )
                        )
                    )
                ) AS cl_count,
                -- Data da atividade mais recente (qualquer fonte)
                (
                    SELECT MAX(last_dt) FROM (
                        SELECT activity_date AS last_dt FROM account_activities
                        WHERE account_id = acc.id
                        AND activity_date >= date('now', '-30 days')
                        UNION ALL
                        SELECT a2.activity_date AS last_dt FROM activities a2
                        WHERE a2.activity_date >= date('now', '-30 days')
                        AND (
                            a2.client_id IN (
                                SELECT amc2.client_id FROM account_main_contacts amc2
                                WHERE amc2.account_id = acc.id
                            )
                            OR
                            a2.client_id IN (
                                SELECT cl2.id FROM clients cl2
                                WHERE LOWER(TRIM(cl2.company)) = LOWER(TRIM(acc.name))
                                AND cl2.company IS NOT NULL AND TRIM(cl2.company) != ''
                            )
                        )
                    )
                ) AS last_activity
            FROM accounts acc
            ORDER BY acc.name ASC
        """)

        all_rows = []
        for r in c.fetchall():
            rd = dict_from_row(r)
            rd['activity_count'] = (rd.pop('aa_count') or 0) + (rd.pop('cl_count') or 0)
            all_rows.append(rd)

        conn.close()

        covered   = sorted([r for r in all_rows if r['activity_count'] > 0],
                           key=lambda x: -x['activity_count'])
        uncovered = sorted([r for r in all_rows if r['activity_count'] == 0],
                           key=lambda x: (-(x.get('is_target') or 0), (x.get('name') or '').lower()))

        total = len(all_rows)
        return jsonify({
            'period_label':  'Últimos 30 dias',
            'total':         total,
            'covered_count': len(covered),
            'cobertura_pct': round(len(covered) / total * 100) if total > 0 else 0,
            'covered':   covered,
            'uncovered': uncovered,
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/home/cobertura-detail: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/home/overview', methods=['GET'])
def home_overview():
    """Agregados do módulo Home (dashboard executivo).
    Query params:
      period: 'all' (default) | 'months'
      months: lista de YYYY-MM separados por vírgula (se period=months)
    """
    try:
        period = (request.args.get('period') or 'all').strip().lower()
        months_arg = (request.args.get('months') or '').strip()
        months_filter = []
        if period == 'months' and months_arg:
            months_filter = [m.strip() for m in months_arg.split(',') if re.match(r'^\d{4}-\d{2}$', m.strip())]

        include_archived = request.args.get('include_archived') == '1'
        include_cold = request.args.get('include_cold') == '1'

        def client_filter(alias='c'):
            """Retorna fragmento AND para filtrar clientes arquivados/frios conforme flags."""
            clauses = []
            if not include_archived:
                clauses.append(f"COALESCE({alias}.is_archived, 0) = 0")
            if not include_cold:
                clauses.append(f"COALESCE({alias}.is_cold_contact, 0) = 0")
            return (' AND ' + ' AND '.join(clauses)) if clauses else ''

        conn = get_db()
        c = conn.cursor()

        # Thresholds de status — universal + regras por cargo
        c.execute("SELECT key, value FROM app_settings WHERE key IN ('status_green_days', 'status_yellow_days')")
        s_map = {row['key']: row['value'] for row in c.fetchall()}
        try:
            green_days = int(s_map.get('status_green_days') or 7)
        except Exception:
            green_days = 7
        try:
            yellow_days = int(s_map.get('status_yellow_days') or 14)
        except Exception:
            yellow_days = 14

        # Regras por cargo (espelha exatamente o que o frontend usa)
        c.execute('SELECT position, green_days, yellow_days FROM status_rules')
        _rules_map = {
            (row['position'] or '').strip().lower(): (int(row['green_days']), int(row['yellow_days']))
            for row in c.fetchall()
            if row['position']
        }

        def _get_thresholds(position):
            """Retorna (green_days, yellow_days) para o cargo dado, igual à lógica do frontend."""
            key = (position or '').strip().lower()
            return _rules_map.get(key, (green_days, yellow_days))

        def month_clause(col):
            if not months_filter:
                return '', []
            ph = ','.join(['?'] * len(months_filter))
            return f" AND strftime('%Y-%m', {col}) IN ({ph})", list(months_filter)

        # --- KPIs base ---
        c.execute("SELECT COUNT(*) AS n FROM accounts")
        total_accounts = c.fetchone()['n']

        c.execute(f"SELECT COUNT(*) AS n FROM clients c WHERE 1=1{client_filter()}")
        total_contacts = c.fetchone()['n']

        # Status snapshot — usa clients.last_activity_date (igual ao frontend)
        # e aplica regras por cargo (igual ao getStatus() do frontend)
        c.execute(f"""
            SELECT c.id, c.position, c.last_activity_date AS last_date
            FROM clients c
            WHERE 1=1{client_filter()}
        """)
        em_dia = atencao = atrasado = 0
        now_dt = datetime.now()
        for row in c.fetchall():
            g, y = _get_thresholds(row['position'])
            last = row['last_date']
            if not last:
                atrasado += 1
                continue
            try:
                base = str(last).replace('T', ' ').split('.')[0].split('+')[0].strip()
                d = datetime.strptime(base[:19], '%Y-%m-%d %H:%M:%S') if len(base) >= 19 else datetime.strptime(base[:10], '%Y-%m-%d')
                days = (now_dt - d).days
            except Exception:
                atrasado += 1
                continue
            if days < g:
                em_dia += 1
            elif days < y:
                atencao += 1
            else:
                atrasado += 1

        # Cobertura de relacionamento — janela FIXA de 30 dias (independente do filtro de período)
        # 3 caminhos: atividade direta na conta | account_main_contacts → activities | fallback por nome
        mf_a, mfp_a = month_clause('a.activity_date')
        mf_aa, mfp_aa = month_clause('aa.activity_date')
        c.execute("""
            SELECT COUNT(DISTINCT acc_id) AS n FROM (
                SELECT aa.account_id AS acc_id
                FROM account_activities aa
                WHERE aa.activity_date >= date('now', '-30 days')
                UNION
                SELECT amc.account_id AS acc_id
                FROM account_main_contacts amc
                JOIN activities a ON a.client_id = amc.client_id
                WHERE a.activity_date >= date('now', '-30 days')
                UNION
                SELECT acc2.id AS acc_id
                FROM accounts acc2
                JOIN clients cl2 ON LOWER(TRIM(cl2.company)) = LOWER(TRIM(acc2.name))
                JOIN activities a2 ON a2.client_id = cl2.id
                WHERE cl2.company IS NOT NULL AND TRIM(cl2.company) != ''
                AND a2.activity_date >= date('now', '-30 days')
            )
        """)
        covered_accounts = c.fetchone()['n'] or 0
        cobertura_pct = round((covered_accounts / total_accounts) * 100) if total_accounts > 0 else 0

        # --- Top 10 contas por faturamento (soma das presenças STF) ---
        # Exclui serviços encerrados antecipadamente (early_terminated=1)
        # Se houver filtro de período, também exclui serviços cujo contrato já encerrou antes do início do período
        fat_params = []
        fat_contract_clause = "AND COALESCE(p.early_terminated, 0) = 0"
        if months_filter:
            min_month = min(months_filter)
            fat_contract_clause += " AND (p.contract_end_date IS NULL OR p.contract_end_date >= ?)"
            fat_params.append(min_month)
        c.execute(f"""
            SELECT a.name, COALESCE(SUM(p.current_revenue_cents), 0) AS receita
            FROM accounts a
            LEFT JOIN account_presences p ON p.account_id = a.id
                AND (p.billing_type IS NULL OR p.billing_type = 'Mensal')
                {fat_contract_clause}
            GROUP BY a.id, a.name
            HAVING receita > 0
            ORDER BY receita DESC
            LIMIT 10
        """, fat_params)
        top_faturamento = [{'name': r['name'], 'revenue_cents': r['receita']} for r in c.fetchall()]

        c.execute(f"""
            SELECT a.name, COALESCE(SUM(p.current_revenue_cents), 0) AS receita
            FROM accounts a
            LEFT JOIN account_presences p ON p.account_id = a.id
                AND p.billing_type = 'Unico'
                {fat_contract_clause}
            GROUP BY a.id, a.name
            HAVING receita > 0
            ORDER BY receita DESC
            LIMIT 10
        """, fat_params)
        top_faturamento_unico = [{'name': r['name'], 'revenue_cents': r['receita']} for r in c.fetchall()]

        # --- Top 10 contas com mais interações no período ---
        c.execute(f"""
            WITH client_acts AS (
                SELECT cl.company AS acc, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE cl.company IS NOT NULL AND TRIM(cl.company) != '' {mf_a}{client_filter('cl')}
                GROUP BY cl.company
            ),
            acc_acts AS (
                SELECT acc.name AS acc, COUNT(*) AS n
                FROM account_activities aa JOIN accounts acc ON acc.id = aa.account_id
                WHERE 1=1 {mf_aa}
                GROUP BY acc.name
            )
            SELECT acc AS name, SUM(n) AS total FROM (
                SELECT * FROM client_acts UNION ALL SELECT * FROM acc_acts
            )
            GROUP BY acc
            ORDER BY total DESC
            LIMIT 10
        """, mfp_a + mfp_aa)
        top_interacoes = [{'name': r['name'], 'count': r['total']} for r in c.fetchall()]

        # --- Top 5 contas TARGET com menor interação no período ---
        # (inclui target com 0 interações)
        c.execute(f"""
            SELECT a.name,
                   COALESCE((
                       SELECT COUNT(*) FROM activities ac
                       JOIN clients cl ON cl.id = ac.client_id
                       WHERE cl.company = a.name
                       {mf_a.replace('a.activity_date', 'ac.activity_date')}
                   ), 0)
                   +
                   COALESCE((
                       SELECT COUNT(*) FROM account_activities aa2
                       WHERE aa2.account_id = a.id
                       {mf_aa.replace('aa.activity_date', 'aa2.activity_date')}
                   ), 0) AS total
            FROM accounts a
            WHERE COALESCE(a.is_target, 0) = 1
            ORDER BY total ASC, a.name ASC
            LIMIT 5
        """, mfp_a + mfp_aa)
        target_menor_interacao = [{'name': r['name'], 'count': r['total']} for r in c.fetchall()]

        # --- Interações por cargo (donut) ---
        c.execute(f"""
            SELECT cl.position AS cargo, COUNT(*) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE cl.position IS NOT NULL AND TRIM(cl.position) != '' {mf_a}{client_filter('cl')}
            GROUP BY cl.position
            ORDER BY n DESC
            LIMIT 8
        """, mfp_a)
        interacoes_cargo = [{'name': r['cargo'], 'count': r['n']} for r in c.fetchall()]

        # --- Evolução mensal de interações (últimos 12 meses, ignora filtro de período) ---
        c.execute("""
            WITH all_acts AS (
                SELECT strftime('%Y-%m', activity_date) AS ym FROM activities
                UNION ALL
                SELECT strftime('%Y-%m', activity_date) AS ym FROM account_activities
            )
            SELECT ym, COUNT(*) AS n
            FROM all_acts
            WHERE ym IS NOT NULL
            GROUP BY ym
            ORDER BY ym ASC
        """)
        evolucao_raw = {r['ym']: r['n'] for r in c.fetchall()}
        # Gera últimos 12 meses com base na data atual
        evolucao_mensal = []
        cur = now_dt.replace(day=1)
        ms = []
        for _ in range(12):
            ms.append(cur.strftime('%Y-%m'))
            # voltar 1 mês
            if cur.month == 1:
                cur = cur.replace(year=cur.year - 1, month=12)
            else:
                cur = cur.replace(month=cur.month - 1)
        for ym in reversed(ms):
            evolucao_mensal.append({'ym': ym, 'count': evolucao_raw.get(ym, 0)})

        # --- Canal de Relacionamento (contact_type) ---
        c.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(a.contact_type), ''), 'Outro') AS canal, COUNT(*) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE 1=1 {mf_a}{client_filter('cl')}
            GROUP BY canal
            ORDER BY n DESC
        """, mfp_a)
        canais = [{'name': r['canal'], 'count': r['n']} for r in c.fetchall()]

        # --- Heatmap dia da semana × período do dia (a partir de activities.activity_date) ---
        # SQLite: strftime('%w') -> 0=Dom .. 6=Sáb; strftime('%H') -> hora
        # Períodos: manhã (06-12), tarde (12-18), noite (18-06)
        c.execute(f"""
            SELECT strftime('%w', a.activity_date) AS dow,
                   CAST(strftime('%H', a.activity_date) AS INTEGER) AS hr,
                   COUNT(*) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE a.activity_date IS NOT NULL {mf_a}{client_filter('cl')}
            GROUP BY dow, hr
        """, mfp_a)
        heatmap = {}
        for r in c.fetchall():
            dow = int(r['dow']) if r['dow'] is not None else 0
            hr = int(r['hr'] or 0)
            if 6 <= hr < 12:
                periodo = 'Manhã'
            elif 12 <= hr < 18:
                periodo = 'Tarde'
            else:
                periodo = 'Noite'
            key = (dow, periodo)
            heatmap[key] = heatmap.get(key, 0) + r['n']
        heatmap_list = [{'dow': k[0], 'periodo': k[1], 'count': v} for k, v in heatmap.items()]

        # --- Funil de Engajamento ---
        ativas = total_contacts  # já respeita os filtros de arquivado/frio
        c.execute(f"""
            SELECT COUNT(DISTINCT a.client_id) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE a.activity_date >= date('now', '-30 day'){client_filter('cl')}
        """)
        com_contato_mes = c.fetchone()['n'] or 0
        c.execute(f"""
            SELECT COUNT(DISTINCT a.client_id) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE 1=1{client_filter('cl')}
        """)
        com_interacao = c.fetchone()['n'] or 0
        c.execute(f"""
            SELECT a.client_id, COUNT(*) AS n
            FROM activities a JOIN clients cl ON cl.id = a.client_id
            WHERE 1=1{client_filter('cl')}
            GROUP BY a.client_id
            HAVING n >= 3
        """)
        engajadas = len(c.fetchall())
        alta_proximidade = em_dia

        funil = [
            {'label': 'Contas Ativas', 'count': ativas},
            {'label': 'Com Contato no Mês', 'count': com_contato_mes},
            {'label': 'Com Interação', 'count': com_interacao},
            {'label': 'Engajadas', 'count': engajadas},
            {'label': 'Alta Proximidade', 'count': alta_proximidade},
        ]

        # --- Tempo médio sem contato (buckets) ---
        # Usa clients.last_activity_date para consistência com o frontend
        c.execute(f"""
            SELECT c.last_activity_date AS last_date
            FROM clients c
            WHERE 1=1{client_filter()}
        """)
        buckets = {'0-7': 0, '8-14': 0, '15-30': 0, '+30': 0}
        for row in c.fetchall():
            last = row['last_date']
            if not last:
                buckets['+30'] += 1
                continue
            try:
                base = str(last).replace('T', ' ').split('.')[0].split('+')[0].strip()
                d = datetime.strptime(base[:19], '%Y-%m-%d %H:%M:%S') if len(base) >= 19 else datetime.strptime(base[:10], '%Y-%m-%d')
                days = (now_dt - d).days
            except Exception:
                buckets['+30'] += 1
                continue
            if days <= 7:
                buckets['0-7'] += 1
            elif days <= 14:
                buckets['8-14'] += 1
            elif days <= 30:
                buckets['15-30'] += 1
            else:
                buckets['+30'] += 1
        tempo_sem_contato = [{'bucket': k, 'count': v} for k, v in buckets.items()]

        # --- Novos contatos por mês (últimos 12 meses) ---
        c.execute(f"""
            SELECT strftime('%Y-%m', created_at) AS ym, COUNT(*) AS n
            FROM clients c
            WHERE 1=1{client_filter()}
            GROUP BY ym
            ORDER BY ym ASC
        """)
        novos_raw = {r['ym']: r['n'] for r in c.fetchall()}
        novos_contatos = []
        for ym in reversed(ms):
            novos_contatos.append({'ym': ym, 'count': novos_raw.get(ym, 0)})

        # --- Insights & Alertas ---
        # Contas estratégicas (target) sem contato há >20 dias
        c.execute("""
            SELECT a.name,
                   MAX(COALESCE(
                       (SELECT MAX(ac.activity_date) FROM activities ac JOIN clients cl2 ON cl2.id=ac.client_id WHERE cl2.company=a.name),
                       (SELECT MAX(aa2.activity_date) FROM account_activities aa2 WHERE aa2.account_id=a.id)
                   )) AS last_act
            FROM accounts a
            WHERE COALESCE(a.is_target,0)=1
            GROUP BY a.id, a.name
        """)
        target_sem_contato = 0
        for r in c.fetchall():
            last = r['last_act']
            if not last:
                target_sem_contato += 1
                continue
            try:
                base = str(last).replace('T', ' ').split('.')[0].split('+')[0].strip()
                d = datetime.strptime(base[:19], '%Y-%m-%d %H:%M:%S') if len(base) >= 19 else datetime.strptime(base[:10], '%Y-%m-%d')
                if (now_dt - d).days > 20:
                    target_sem_contato += 1
            except Exception:
                target_sem_contato += 1

        # Crescimento m/m de interações por conta (ranking completo + top 3)
        crescimento_top = []
        crescimento_ranking = []
        crescimento_ym_atual = ''
        crescimento_ym_anterior = ''
        if len(evolucao_mensal) >= 2:
            ym_atual = evolucao_mensal[-1]['ym']
            ym_anterior = evolucao_mensal[-2]['ym']
            crescimento_ym_atual = ym_atual
            crescimento_ym_anterior = ym_anterior
            c.execute("""
                WITH acts AS (
                    SELECT cl.company AS acc, strftime('%Y-%m', a.activity_date) AS ym
                    FROM activities a JOIN clients cl ON cl.id = a.client_id
                    WHERE cl.company IS NOT NULL AND TRIM(cl.company) != ''
                    UNION ALL
                    SELECT acc.name AS acc, strftime('%Y-%m', aa.activity_date) AS ym
                    FROM account_activities aa JOIN accounts acc ON acc.id = aa.account_id
                )
                SELECT acc,
                       SUM(CASE WHEN ym = ? THEN 1 ELSE 0 END) AS atual,
                       SUM(CASE WHEN ym = ? THEN 1 ELSE 0 END) AS anterior
                FROM acts
                GROUP BY acc
                HAVING atual > 0 OR anterior > 0
            """, (ym_atual, ym_anterior))
            for r in c.fetchall():
                atual = int(r['atual'] or 0)
                anterior = int(r['anterior'] or 0)
                if anterior > 0:
                    growth_pct = round(((atual - anterior) / anterior) * 100)
                    is_new = False
                else:
                    growth_pct = None  # crescimento "infinito" — conta nova nesse mês
                    is_new = True
                crescimento_ranking.append({
                    'name': r['acc'],
                    'atual': atual,
                    'anterior': anterior,
                    'growth_pct': growth_pct,
                    'is_new': is_new,
                })
            # Ordena: novas (atual>0, anterior=0) primeiro com maior atual, depois pct desc
            def _rank_key(item):
                if item['is_new']:
                    return (-2, -item['atual'])
                if item['growth_pct'] is None:
                    return (0, 0)
                return (-1 if item['growth_pct'] > 0 else (0 if item['growth_pct'] == 0 else 1), -item['growth_pct'])
            crescimento_ranking.sort(key=_rank_key)
            # Top 3 só com crescimento positivo (≥1%)
            crescimento_top = [
                {'name': it['name'], 'growth_pct': it['growth_pct']}
                for it in crescimento_ranking
                if not it['is_new'] and it['growth_pct'] is not None and it['growth_pct'] > 0
            ][:3]

        target_risco_atencao = 0
        c.execute("""
            SELECT a.name,
                   (SELECT MAX(ac.activity_date) FROM activities ac JOIN clients cl2 ON cl2.id=ac.client_id WHERE cl2.company=a.name) AS la_cli,
                   (SELECT MAX(aa2.activity_date) FROM account_activities aa2 WHERE aa2.account_id=a.id) AS la_acc
            FROM accounts a
            WHERE COALESCE(a.is_target,0)=1
        """)
        for r in c.fetchall():
            last = r['la_cli'] or r['la_acc']
            if not last:
                target_risco_atencao += 1
                continue
            try:
                base = str(last).replace('T', ' ').split('.')[0].split('+')[0].strip()
                d = datetime.strptime(base[:19], '%Y-%m-%d %H:%M:%S') if len(base) >= 19 else datetime.strptime(base[:10], '%Y-%m-%d')
                if green_days <= (now_dt - d).days < yellow_days:
                    target_risco_atencao += 1
            except Exception as e:
                logger.debug(f'[_rank_key] exceção ignorada: {e}')

        # --- Meses disponíveis (para o filtro) ---
        c.execute("""
            SELECT DISTINCT ym FROM (
                SELECT strftime('%Y-%m', activity_date) AS ym FROM activities WHERE activity_date IS NOT NULL
                UNION
                SELECT strftime('%Y-%m', activity_date) AS ym FROM account_activities WHERE activity_date IS NOT NULL
                UNION
                SELECT strftime('%Y-%m', created_at) AS ym FROM clients WHERE created_at IS NOT NULL
            )
            WHERE ym IS NOT NULL
            ORDER BY ym DESC
        """)
        meses_disponiveis = [r['ym'] for r in c.fetchall()]

        conn.close()

        return jsonify({
            'period': period,
            'months_filter': months_filter,
            'meses_disponiveis': meses_disponiveis,
            'kpis': {
                'total_accounts': total_accounts,
                'total_contacts': total_contacts,
                'em_dia': em_dia,
                'atencao': atencao,
                'atrasado': atrasado,
                'cobertura_pct': cobertura_pct,
            },
            'top_faturamento': top_faturamento,
            'top_faturamento_unico': top_faturamento_unico,
            'top_interacoes': top_interacoes,
            'target_menor_interacao': target_menor_interacao,
            'interacoes_cargo': interacoes_cargo,
            'evolucao_mensal': evolucao_mensal,
            'canais': canais,
            'heatmap': heatmap_list,
            'funil': funil,
            'tempo_sem_contato': tempo_sem_contato,
            'novos_contatos': novos_contatos,
            'insights': {
                'target_sem_contato_20d': target_sem_contato,
                'crescimento_top': crescimento_top,
                'crescimento_ranking': crescimento_ranking,
                'crescimento_ym_atual': crescimento_ym_atual,
                'crescimento_ym_anterior': crescimento_ym_anterior,
                'target_em_risco': target_risco_atencao,
                'meta_cobertura_pct': 80,
            },
        })
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/home/overview: {e}')
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/home/drilldown', methods=['GET'])
def home_drilldown():
    """Drill-down detalhado para os elementos do Dashboard Executivo.
    Query params:
      type: accounts | contacts | status | account | cargo | canal | evolucao
      status: em_dia | atencao | atrasado    (quando type=status)
      account_id / account_name              (quando type=account)
      cargo / canal / ym                      (filtros específicos)
      include_archived, include_cold: '1'
    """
    try:
        dtype = (request.args.get('type') or '').strip().lower()
        include_archived = request.args.get('include_archived') == '1'
        include_cold = request.args.get('include_cold') == '1'

        conn = get_db()
        c = conn.cursor()
        now_dt = datetime.now()
        get_thresholds = _home_status_thresholds(c)

        def client_filter(alias='c'):
            clauses = []
            if not include_archived:
                clauses.append(f"COALESCE({alias}.is_archived, 0) = 0")
            if not include_cold:
                clauses.append(f"COALESCE({alias}.is_cold_contact, 0) = 0")
            return (' AND ' + ' AND '.join(clauses)) if clauses else ''

        # -------- TYPE: accounts (Total de Contas) --------
        if dtype == 'accounts':
            c.execute(f"""
                SELECT a.id, a.name, a.logo_url, a.is_target, a.sector,
                       (SELECT COUNT(*) FROM clients cl
                        WHERE LOWER(TRIM(cl.company)) = LOWER(TRIM(a.name)){client_filter('cl')}) AS contacts,
                       COALESCE((SELECT SUM(p.current_revenue_cents) FROM account_presences p
                                 WHERE p.account_id = a.id
                                   AND (p.billing_type IS NULL OR p.billing_type = 'Mensal')
                                   AND COALESCE(p.early_terminated, 0) = 0), 0) AS revenue_cents,
                       (SELECT MAX(aa.activity_date) FROM account_activities aa WHERE aa.account_id = a.id) AS last_activity
                FROM accounts a
                ORDER BY revenue_cents DESC, a.name ASC
            """)
            items = [{
                'id': r['id'], 'name': r['name'], 'logo_url': r['logo_url'],
                'is_target': bool(r['is_target']), 'sector': r['sector'],
                'contacts': r['contacts'], 'revenue_cents': r['revenue_cents'],
                'last_activity': r['last_activity'],
            } for r in c.fetchall()]
            return jsonify({'type': dtype, 'title': 'Todas as Contas', 'count': len(items), 'items': items})

        # -------- TYPE: contacts (Total de Contatos) --------
        if dtype == 'contacts':
            c.execute(f"""
                SELECT c.id, c.name, c.company, c.position, c.photo_url, c.is_target,
                       c.last_activity_date AS last_activity
                FROM clients c
                WHERE 1=1{client_filter()}
                ORDER BY c.name COLLATE NOCASE ASC
            """)
            items = []
            for r in c.fetchall():
                st, days = _home_status_for(r['last_activity'], *get_thresholds(r['position']), now_dt)
                items.append({
                    'id': r['id'], 'name': r['name'], 'company': r['company'],
                    'position': r['position'], 'photo_url': r['photo_url'],
                    'is_target': bool(r['is_target']), 'last_activity': r['last_activity'],
                    'status': st, 'days': days,
                })
            items.sort(key=lambda x: _home_sort_key(x['name']))
            return jsonify({'type': dtype, 'title': 'Todos os Contatos', 'count': len(items), 'items': items})

        # -------- TYPE: status (Em Dia / Atenção / Atrasado) --------
        if dtype == 'status':
            wanted = (request.args.get('status') or '').strip().lower()
            labels = {'em_dia': 'Em Dia', 'atencao': 'Atenção', 'atrasado': 'Atrasado'}
            if wanted not in labels:
                return jsonify({'error': 'status inválido'}), 400
            c.execute(f"""
                SELECT c.id, c.name, c.company, c.position, c.photo_url, c.is_target,
                       c.last_activity_date AS last_activity
                FROM clients c
                WHERE 1=1{client_filter()}
                ORDER BY c.name COLLATE NOCASE ASC
            """)
            items = []
            for r in c.fetchall():
                st, days = _home_status_for(r['last_activity'], *get_thresholds(r['position']), now_dt)
                if st != wanted:
                    continue
                items.append({
                    'id': r['id'], 'name': r['name'], 'company': r['company'],
                    'position': r['position'], 'photo_url': r['photo_url'],
                    'is_target': bool(r['is_target']), 'last_activity': r['last_activity'],
                    'status': st, 'days': days,
                })
            items.sort(key=lambda x: _home_sort_key(x['name']))
            return jsonify({'type': dtype, 'status': wanted, 'title': f'Contatos — {labels[wanted]}',
                            'count': len(items), 'items': items})

        # -------- TYPE: account (clique numa conta: faturamento/interações/target) --------
        if dtype == 'account':
            acc_id = request.args.get('account_id')
            acc_name = (request.args.get('account_name') or '').strip()
            if acc_id:
                c.execute("SELECT * FROM accounts WHERE id = ?", (acc_id,))
            elif acc_name:
                c.execute("SELECT * FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (acc_name,))
            else:
                return jsonify({'error': 'account_id ou account_name obrigatório'}), 400
            acc = c.fetchone()
            if not acc:
                return jsonify({'error': 'conta não encontrada'}), 404
            acc = dict(acc)

            # Serviços Stefanini (presences)
            c.execute("""
                SELECT p.delivery_name, p.stf_owner, p.delivery_cell, p.service_id,
                       p.current_revenue_cents, p.billing_type, p.validity_month,
                       p.contract_end_date, COALESCE(p.early_terminated, 0) AS early_terminated
                FROM account_presences p
                WHERE p.account_id = ?
                ORDER BY COALESCE(p.early_terminated,0) ASC, p.current_revenue_cents DESC
            """, (acc['id'],))
            services = [{
                'name': r['delivery_name'], 'owner': r['stf_owner'], 'cell': r['delivery_cell'],
                'service_id': r['service_id'], 'revenue_cents': r['current_revenue_cents'],
                'billing_type': r['billing_type'], 'validity_month': r['validity_month'],
                'contract_end_date': r['contract_end_date'], 'early_terminated': bool(r['early_terminated']),
            } for r in c.fetchall()]
            total_active = sum((s['revenue_cents'] or 0) for s in services
                               if not s['early_terminated'] and (s['billing_type'] in (None, 'Mensal')))

            # Contatos vinculados — por nome da empresa (igual à página da conta),
            # incluindo arquivados/frios conforme flags, ordem alfabética
            c.execute(f"""
                SELECT cl.id, cl.name, cl.position, cl.photo_url, cl.email,
                       cl.last_activity_date AS last_activity
                FROM clients cl
                WHERE LOWER(TRIM(cl.company)) = LOWER(TRIM(?)){client_filter('cl')}
                ORDER BY cl.name COLLATE NOCASE ASC
            """, (acc['name'],))
            contacts = []
            for r in c.fetchall():
                st, days = _home_status_for(r['last_activity'], *get_thresholds(r['position']), now_dt)
                contacts.append({
                    'id': r['id'], 'name': r['name'], 'position': r['position'],
                    'photo_url': r['photo_url'], 'email': r['email'], 'last_activity': r['last_activity'],
                    'status': st, 'days': days,
                })
            contacts.sort(key=lambda x: _home_sort_key(x['name']))

            # Últimas interações (account_activities + activities dos contatos da conta)
            c.execute("""
                SELECT * FROM (
                    SELECT aa.description AS info, 'Conta' AS canal, aa.activity_date AS dt, NULL AS contato
                    FROM account_activities aa WHERE aa.account_id = ?
                    UNION ALL
                    SELECT COALESCE(a.information, a.description) AS info,
                           COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') AS canal,
                           a.activity_date AS dt, cl.name AS contato
                    FROM activities a JOIN clients cl ON cl.id = a.client_id
                    WHERE LOWER(TRIM(cl.company)) = LOWER(TRIM(?))
                )
                ORDER BY dt DESC LIMIT 12
            """, (acc['id'], acc['name']))
            timeline = [{
                'info': r['info'], 'canal': r['canal'], 'dt': r['dt'], 'contato': r['contato'],
            } for r in c.fetchall()]

            # Canal breakdown da conta
            c.execute("""
                SELECT COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') AS canal, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE LOWER(TRIM(cl.company)) = LOWER(TRIM(?))
                GROUP BY canal ORDER BY n DESC
            """, (acc['name'],))
            canal_breakdown = [{'name': r['canal'], 'count': r['n']} for r in c.fetchall()]

            return jsonify({
                'type': dtype,
                'account': {
                    'id': acc['id'], 'name': acc['name'], 'logo_url': acc.get('logo_url'),
                    'is_target': bool(acc.get('is_target')), 'sector': acc.get('sector'),
                },
                'revenue_active_cents': total_active,
                'services': services,
                'contacts': contacts,
                'timeline': timeline,
                'canal_breakdown': canal_breakdown,
            })

        # -------- TYPE: cargo (fatia da pizza "Interações por Cargo") --------
        if dtype == 'cargo':
            cargo = (request.args.get('cargo') or '').strip()
            if not cargo:
                return jsonify({'error': 'cargo obrigatório'}), 400
            c.execute(f"""
                SELECT cl.id, cl.name, cl.company, cl.photo_url, cl.last_activity_date AS last_activity,
                       COUNT(a.id) AS n
                FROM clients cl LEFT JOIN activities a ON a.client_id = cl.id
                WHERE LOWER(TRIM(cl.position)) = LOWER(TRIM(?)){client_filter('cl')}
                GROUP BY cl.id ORDER BY n DESC, cl.name ASC
            """, (cargo,))
            contacts = []
            total = 0
            for r in c.fetchall():
                total += r['n']
                contacts.append({
                    'id': r['id'], 'name': r['name'], 'company': r['company'],
                    'photo_url': r['photo_url'], 'count': r['n'], 'last_activity': r['last_activity'],
                })
            c.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') AS canal, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE LOWER(TRIM(cl.position)) = LOWER(TRIM(?)){client_filter('cl')}
                GROUP BY canal ORDER BY n DESC
            """, (cargo,))
            canal_breakdown = [{'name': r['canal'], 'count': r['n']} for r in c.fetchall()]
            return jsonify({'type': dtype, 'cargo': cargo, 'title': f'Cargo — {cargo}',
                            'total_interacoes': total, 'contacts': contacts, 'canal_breakdown': canal_breakdown})

        # -------- TYPE: canal (fatia da pizza "Canal de Relacionamento") --------
        if dtype == 'canal':
            canal = (request.args.get('canal') or '').strip()
            if not canal:
                return jsonify({'error': 'canal obrigatório'}), 400
            c.execute(f"""
                SELECT cl.company AS acc, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') = ?
                  AND cl.company IS NOT NULL AND TRIM(cl.company) != ''{client_filter('cl')}
                GROUP BY cl.company ORDER BY n DESC LIMIT 15
            """, (canal,))
            accounts = [{'name': r['acc'], 'count': r['n']} for r in c.fetchall()]
            c.execute(f"""
                SELECT cl.name, cl.company, cl.position, cl.photo_url, COUNT(*) AS n,
                       MAX(a.activity_date) AS last_activity
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') = ?{client_filter('cl')}
                GROUP BY cl.id ORDER BY n DESC LIMIT 30
            """, (canal,))
            contacts = [{
                'name': r['name'], 'company': r['company'], 'position': r['position'],
                'photo_url': r['photo_url'], 'count': r['n'], 'last_activity': r['last_activity'],
            } for r in c.fetchall()]
            total = sum(x['count'] for x in accounts)
            return jsonify({'type': dtype, 'canal': canal, 'title': f'Canal — {canal}',
                            'total': total, 'accounts': accounts, 'contacts': contacts})

        # -------- TYPE: evolucao (clique num mês da Evolução Mensal) --------
        if dtype == 'evolucao':
            ym = (request.args.get('ym') or '').strip()
            if not re.match(r'^\d{4}-\d{2}$', ym):
                return jsonify({'error': 'ym inválido (YYYY-MM)'}), 400
            # contas contatadas no mês
            c.execute(f"""
                SELECT cl.company AS acc, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE strftime('%Y-%m', a.activity_date) = ?
                  AND cl.company IS NOT NULL AND TRIM(cl.company) != ''{client_filter('cl')}
                GROUP BY cl.company ORDER BY n DESC
            """, (ym,))
            accounts = [{'name': r['acc'], 'count': r['n']} for r in c.fetchall()]
            # canal breakdown do mês
            c.execute(f"""
                SELECT COALESCE(NULLIF(TRIM(a.contact_type),''),'Outro') AS canal, COUNT(*) AS n
                FROM activities a JOIN clients cl ON cl.id = a.client_id
                WHERE strftime('%Y-%m', a.activity_date) = ?{client_filter('cl')}
                GROUP BY canal ORDER BY n DESC
            """, (ym,))
            canal_breakdown = [{'name': r['canal'], 'count': r['n']} for r in c.fetchall()]
            # total do mês (client + account activities)
            c.execute("""
                SELECT (SELECT COUNT(*) FROM activities WHERE strftime('%Y-%m', activity_date) = ?) +
                       (SELECT COUNT(*) FROM account_activities WHERE strftime('%Y-%m', activity_date) = ?) AS n
            """, (ym, ym))
            total = c.fetchone()['n'] or 0
            # mês anterior para delta
            y, m = [int(x) for x in ym.split('-')]
            pm = (y - 1, 12) if m == 1 else (y, m - 1)
            prev_ym = f'{pm[0]:04d}-{pm[1]:02d}'
            c.execute("""
                SELECT (SELECT COUNT(*) FROM activities WHERE strftime('%Y-%m', activity_date) = ?) +
                       (SELECT COUNT(*) FROM account_activities WHERE strftime('%Y-%m', activity_date) = ?) AS n
            """, (prev_ym, prev_ym))
            prev_total = c.fetchone()['n'] or 0
            return jsonify({'type': dtype, 'ym': ym, 'title': f'Interações — {ym}',
                            'total': total, 'prev_total': prev_total, 'delta': total - prev_total,
                            'accounts': accounts, 'canal_breakdown': canal_breakdown})

        # -------- TYPE: target_risk (insight "Risco de perda de proximidade") --------
        if dtype == 'target_risk':
            # Espelha exatamente a lógica de target_risco_atencao do overview:
            # contas target sem contato OU na janela de atenção (green <= dias < yellow)
            g_uni, y_uni = get_thresholds(None)
            c.execute("""
                SELECT a.id, a.name, a.logo_url, a.sector,
                       (SELECT MAX(ac.activity_date) FROM activities ac JOIN clients cl2 ON cl2.id=ac.client_id WHERE LOWER(TRIM(cl2.company))=LOWER(TRIM(a.name))) AS la_cli,
                       (SELECT MAX(aa2.activity_date) FROM account_activities aa2 WHERE aa2.account_id=a.id) AS la_acc
                FROM accounts a
                WHERE COALESCE(a.is_target,0)=1
            """)
            items = []
            for r in c.fetchall():
                last = r['la_cli'] or r['la_acc']
                em_risco = False
                days = None
                if not last:
                    em_risco = True
                else:
                    try:
                        base = str(last).replace('T', ' ').split('.')[0].split('+')[0].strip()
                        d = datetime.strptime(base[:19], '%Y-%m-%d %H:%M:%S') if len(base) >= 19 else datetime.strptime(base[:10], '%Y-%m-%d')
                        days = (now_dt - d).days
                        if g_uni <= days < y_uni:
                            em_risco = True
                    except Exception:
                        em_risco = True
                if not em_risco:
                    continue
                # contagem de contatos por nome da empresa
                c.execute(f"SELECT COUNT(*) AS n FROM clients cl WHERE LOWER(TRIM(cl.company))=LOWER(TRIM(?)){client_filter('cl')}", (r['name'],))
                ncont = c.fetchone()['n']
                items.append({
                    'id': r['id'], 'name': r['name'], 'logo_url': r['logo_url'], 'sector': r['sector'],
                    'last_activity': last, 'days': days, 'contacts': ncont,
                })
            items.sort(key=lambda x: (x['days'] is None, -(x['days'] or 0), x['name'].lower()))
            return jsonify({'type': dtype, 'title': 'Contas Target em Risco de Proximidade',
                            'count': len(items), 'items': items})

        return jsonify({'error': f'type desconhecido: {dtype}'}), 400
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/home/drilldown: {e}')
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ===========================================================================
# Gatilhos de contato com pretexto pronto (Bloco 9)
# ===========================================================================

def _context_trigger_scan():
    """Job semanal: para contas target, busca notícias recentes relevantes via
    _openrouter_web_prompt (LLM com web) e cria sugestões 'context_trigger'."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM accounts WHERE COALESCE(is_target, 0) = 1 ORDER BY name LIMIT 12")
    target_accounts = c.fetchall()
    today = datetime.now().strftime('%Y-%m-%d')
    created = 0
    for row in target_accounts:
        raw = _openrouter_web_prompt(
            f'Procure notícias recentes (últimos 30 dias) relevantes sobre a empresa "{row["name"]}" no Brasil. '
            'Retorne SOMENTE JSON válido no formato: '
            '{"noticias": [{"manchete": "...", "resumo": "1 a 2 frases", "data": "YYYY-MM-DD", '
            '"relevancia": "alta|media|baixa"}]}. '
            'No máximo 2 notícias, apenas fatos novos com potencial de pretexto comercial '
            '(expansão, investimento, troca de executivos, resultados, aquisições). '
            'Se não houver nada relevante, retorne {"noticias": []}.'
        )
        if not raw:
            continue
        try:
            parsed = _extract_json_object_from_text(raw) or json.loads(raw)
        except Exception:
            continue
        for news in (parsed or {}).get('noticias', [])[:2]:
            manchete = (news.get('manchete') or '').strip()
            if not manchete or (news.get('relevancia') or '').lower() == 'baixa':
                continue
            # não repete a mesma manchete nos últimos 14 dias
            c.execute("""SELECT 1 FROM daily_suggestions
                         WHERE suggestion_type = 'context_trigger'
                           AND target_data LIKE ?
                           AND date >= date('now', 'localtime', '-14 days')""",
                      (f'%{manchete[:60]}%',))
            if c.fetchone():
                continue
            c.execute("""INSERT INTO daily_suggestions
                         (date, suggestion_type, title, description, target_id, target_data, score)
                         VALUES (?, ?, ?, ?, ?, ?, ?)""",
                      (today, 'context_trigger',
                       f'Gatilho: {row["name"]} — {manchete[:80]}',
                       (news.get('resumo') or '')[:240],
                       row['id'],
                       json.dumps({'account_id': row['id'], 'company': row['name'],
                                   'manchete': manchete, 'resumo': news.get('resumo'),
                                   'data': news.get('data')}, ensure_ascii=False),
                       55.0))
            created += 1
    conn.commit()
    conn.close()
    logger.info(f'[ContextTrigger] {created} gatilhos de contexto criados')
    return created


_register_scheduled_job('context_trigger_last_run', 7, _context_trigger_scan)


@app.route('/api/suggestions/context-scan', methods=['POST'])
def context_trigger_scan_now():
    """Dispara manualmente o scan de gatilhos (útil para testar)."""
    try:
        created = _context_trigger_scan()
        return jsonify({'ok': True, 'created': created})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/suggestions/context-scan: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/suggestions/<int:suggestion_id>/draft', methods=['POST'])
def suggestion_generate_draft(suggestion_id):
    """Gera rascunho de mensagem (OpenRouter → SAI) para uma sugestão do Radar:
    gatilho + últimas 3 atividades do contato + tom profissional pt-BR."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM daily_suggestions WHERE id = ?', (suggestion_id,))
        sug = dict_from_row(c.fetchone())
        if not sug:
            conn.close()
            return jsonify({'error': 'Sugestão não encontrada'}), 404
        data = json.loads(sug.get('target_data') or '{}')

        # Resolve o contato: direto (client_id) ou principal da conta (mais recente)
        client = None
        if data.get('client_id'):
            c.execute('SELECT * FROM clients WHERE id = ?', (data['client_id'],))
            client = dict_from_row(c.fetchone())
        elif data.get('company'):
            c.execute("""SELECT * FROM clients
                         WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
                           AND COALESCE(is_archived, 0) = 0 AND COALESCE(is_cold_contact, 0) = 0
                         ORDER BY last_activity_date DESC NULLS LAST LIMIT 1""", (data['company'],))
            client = dict_from_row(c.fetchone())
        if not client:
            conn.close()
            return jsonify({'error': 'Nenhum contato ativo encontrado para esta sugestão.'}), 404

        c.execute("""SELECT contact_type, information, activity_date FROM activities
                     WHERE client_id = ? ORDER BY activity_date DESC LIMIT 3""", (client['id'],))
        acts = c.fetchall()
        conn.close()
        history = '\n'.join(
            f"- {a['activity_date'][:10] if a['activity_date'] else ''} ({a['contact_type']}): {(a['information'] or '')[:200]}"
            for a in acts
        ) or '(sem atividades registradas)'

        gatilho = f"{sug['title']}\n{sug.get('description') or ''}"
        if data.get('manchete'):
            gatilho += f"\nNotícia: {data['manchete']} — {data.get('resumo') or ''}"
        if data.get('offer'):
            usados = ', '.join(data.get('present') or []) or 'nenhuma oferta contratada ainda'
            gatilho += (f"\nAbordagem consultiva sobre a oferta '{data['offer']}', nunca explorada nesta conta. "
                        f"A conta já usa: {usados} — cite isso como contexto.")

        raw = _llm_prompt(
            f"Escreva uma mensagem curta de WhatsApp (3 a 5 frases, tom profissional e caloroso, "
            f"português do Brasil, sem assinatura) de um executivo de contas para {client['name']} "
            f"({client.get('position') or 'contato'} na {client.get('company') or 'empresa'}). "
            f"Pretexto do contato:\n{gatilho}\n\n"
            f"Últimas interações (use algo daqui para personalizar):\n{history}\n\n"
            "Retorne SOMENTE o texto da mensagem, sem aspas nem comentários.",
            log_tag='RadarDraft'
        )
        if not raw:
            return jsonify({'error': 'Nenhum provedor de LLM configurado ou disponível.'}), 503
        return jsonify({
            'draft': raw.strip(),
            'client': {'id': client['id'], 'name': client['name'], 'phone': client.get('phone')},
        })
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/suggestions/{suggestion_id}/draft: {e}')
        return jsonify({'error': str(e)}), 500

# ===========================================================================
# Revisão de sexta + plano de segunda (Bloco 14)
# ===========================================================================

def _weekly_review_data(c):
    """Compila os dados reais da semana: toques, contatos que esfriaram,
    follow-ups criados vs. cumpridos e sugestões pendentes do Radar."""
    now_dt = datetime.now()
    week_ago = now_dt - timedelta(days=7)
    get_thresholds = _home_status_thresholds(c)

    c.execute("SELECT COUNT(*) FROM activities WHERE activity_date >= ?",
              (week_ago.strftime('%Y-%m-%d %H:%M:%S'),))
    touches = c.fetchone()[0]

    # Esfriaram: estavam 'em_dia' há 7 dias e hoje estão 'atenção'/'atrasado'
    cooled = []
    c.execute("""SELECT id, name, company, position, last_activity_date FROM clients
                 WHERE COALESCE(is_archived, 0) = 0 AND COALESCE(is_cold_contact, 0) = 0
                   AND last_activity_date IS NOT NULL""")
    for row in c.fetchall():
        green, yellow = get_thresholds(row['position'])
        status_now, _ = _home_status_for(row['last_activity_date'], green, yellow, now_dt)
        status_before, _ = _home_status_for(row['last_activity_date'], green, yellow, week_ago)
        if status_before == 'em_dia' and status_now in ('atencao', 'atrasado'):
            cooled.append({'id': row['id'], 'name': row['name'], 'company': row['company'],
                           'status': status_now})

    c.execute("SELECT COUNT(*) FROM commitments WHERE created_at >= ?",
              (week_ago.strftime('%Y-%m-%d %H:%M:%S'),))
    fups_created = c.fetchone()[0]
    c.execute("""SELECT COUNT(*) FROM commitments co
                 WHERE co.due_date >= ? AND co.due_date <= ?
                   AND EXISTS (SELECT 1 FROM activities a
                               WHERE a.client_id = co.client_id
                                 AND date(a.activity_date) >= co.due_date)""",
              (week_ago.strftime('%Y-%m-%d'), now_dt.strftime('%Y-%m-%d')))
    fups_done = c.fetchone()[0]

    c.execute("""SELECT title, suggestion_type FROM daily_suggestions
                 WHERE date = ? AND completed = 0
                   AND (snoozed_until IS NULL OR snoozed_until <= ?)
                 ORDER BY score DESC""",
              (now_dt.strftime('%Y-%m-%d'), now_dt.strftime('%Y-%m-%d')))
    pending = [dict(r) for r in c.fetchall()]

    # Plano da próxima semana: ranking do Radar distribuído pelos dias úteis
    ranked = _radar_generate_ranked(c)[:10]
    weekdays = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta']
    plan = []
    for i, sug in enumerate(ranked):
        # 2 itens por dia útil, transbordando para sexta
        plan.append({'day': weekdays[min(i // 2, 4)], 'title': sug['title'], 'type': sug['type']})
    return {
        'week_start': week_ago.strftime('%Y-%m-%d'),
        'touches': touches,
        'cooled': cooled,
        'followups_created': fups_created,
        'followups_done': fups_done,
        'pending_suggestions': pending,
        'next_week_plan': plan,
    }


@app.route('/api/week-review', methods=['GET'])
def week_review():
    """Versão 'Minha Semana' — disponível a qualquer momento na Home."""
    try:
        conn = get_db()
        data = _weekly_review_data(conn.cursor())
        conn.close()
        return jsonify(data)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/week-review: {e}')
        return jsonify({'error': str(e)}), 500


def _weekly_review_text(data):
    lines = [
        f"Toques significativos na semana: {data['touches']}",
        f"Follow-ups criados: {data['followups_created']} | cumpridos: {data['followups_done']}",
    ]
    if data['cooled']:
        lines.append('Contatos que esfriaram na semana:')
        lines += [f"- {c['name']} ({c['company']}) → {c['status']}" for c in data['cooled'][:15]]
    else:
        lines.append('Nenhum contato esfriou nesta semana. 🎉')
    if data['pending_suggestions']:
        lines.append(f"Sugestões do Radar não tratadas hoje: {len(data['pending_suggestions'])}")
        lines += [f"- {s['title']}" for s in data['pending_suggestions'][:10]]
    return '\n'.join(lines)


def _weekly_plan_text(data):
    if not data['next_week_plan']:
        return 'Sem pendências priorizadas — bom descanso!'
    lines = []
    current_day = None
    for item in data['next_week_plan']:
        if item['day'] != current_day:
            current_day = item['day']
            lines.append(f"## {current_day}")
        lines.append(f"- {item['title']}")
    return '\n'.join(lines)


def _friday_review_job():
    """Sexta-feira após o meio-dia (hora configurável): compila revisão da
    semana + plano da próxima e envia por e-mail (mecanismo do Bloco 13)."""
    now = datetime.now()
    if now.weekday() != 4:  # 4 = sexta
        return 'skip'
    try:
        hour = int(_resolve_setting('weekly_review_hour', 'WEEKLY_REVIEW_HOUR') or 12)
    except Exception:
        hour = 12
    if now.hour < hour:
        return 'skip'
    conn = get_db()
    data = _weekly_review_data(conn.cursor())
    conn.close()
    date_label = now.strftime('%d/%m/%Y')
    sections = [
        ('Revisão da semana', _weekly_review_text(data)),
        ('Plano da próxima semana (pré-priorizado pelo Radar do Dia)', _weekly_plan_text(data)),
    ]
    pdf_bytes = _briefings_to_pdf(f'Revisão de sexta — {date_label}', sections)
    attachments = []
    if pdf_bytes:
        attachments.append({'name': f'revisao-semana-{now.strftime("%Y-%m-%d")}.pdf',
                            'content_bytes': base64.b64encode(pdf_bytes).decode('ascii'),
                            'content_type': 'application/pdf'})
    body = ('<p>Sexta-feira! 🐇 Segue a revisão da semana e o plano de segunda'
            + (' (PDF em anexo)' if attachments else '') + ':</p>'
            + ''.join(f'<h3>{html.escape(s[0])}</h3><pre style="white-space:pre-wrap; font-family:inherit;">{html.escape(s[1])}</pre>'
                      for s in sections))
    _outlook_send_mail(None, f'🐇 Revisão de sexta + plano de segunda — {date_label}', body, attachments)


_register_scheduled_job('weekly_review_last_run', 1, _friday_review_job)


@app.route('/api/week-review/send-email', methods=['POST'])
def week_review_send_now():
    """Dispara manualmente o e-mail de revisão (ignora dia/hora)."""
    try:
        conn = get_db()
        data = _weekly_review_data(conn.cursor())
        conn.close()
        now = datetime.now()
        date_label = now.strftime('%d/%m/%Y')
        sections = [
            ('Revisão da semana', _weekly_review_text(data)),
            ('Plano da próxima semana (pré-priorizado pelo Radar do Dia)', _weekly_plan_text(data)),
        ]
        pdf_bytes = _briefings_to_pdf(f'Revisão de sexta — {date_label}', sections)
        attachments = []
        if pdf_bytes:
            attachments.append({'name': f'revisao-semana-{now.strftime("%Y-%m-%d")}.pdf',
                                'content_bytes': base64.b64encode(pdf_bytes).decode('ascii'),
                                'content_type': 'application/pdf'})
        body = ('<p>Segue a revisão da semana e o plano de segunda:</p>'
                + ''.join(f'<h3>{html.escape(s[0])}</h3><pre style="white-space:pre-wrap; font-family:inherit;">{html.escape(s[1])}</pre>'
                          for s in sections))
        _outlook_send_mail(None, f'🐇 Revisão da semana — {date_label}', body, attachments)
        return jsonify({'ok': True})
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/week-review/send-email: {e}')
        return jsonify({'error': str(e)}), 500
