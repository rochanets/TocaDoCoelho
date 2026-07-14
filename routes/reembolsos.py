# -*- coding: utf-8 -*-
# Rotas do submódulo "reembolsos" do AutoToca (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`.

REEMBOLSO_ROBOT_TASKS = {}
REEMBOLSO_ROBOT_TASKS_LOCK = threading.Lock()


def _reembolso_task_set(task_id, updates):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        task = REEMBOLSO_ROBOT_TASKS.get(task_id, {})
        task.update(updates)
        REEMBOLSO_ROBOT_TASKS[task_id] = task


def _reembolso_task_get(task_id):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        return dict(REEMBOLSO_ROBOT_TASKS.get(task_id) or {})


def _reembolso_task_cleanup(task_id, delay=300):
    def _cleanup():
        time.sleep(delay)
        with REEMBOLSO_ROBOT_TASKS_LOCK:
            REEMBOLSO_ROBOT_TASKS.pop(task_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


@app.route('/api/autotoca/reembolsos/origem-historico', methods=['GET'])
def reembolsos_origem_historico():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT texto FROM reembolso_origem_historico ORDER BY created_at DESC, id DESC LIMIT 30')
        rows = c.fetchall()
        conn.close()
        return jsonify([{'texto': r['texto']} for r in rows])
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /origem-historico: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/conta-endereco/<int:account_id>', methods=['GET'])
def reembolsos_conta_endereco(account_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?', (account_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({'endereco': row['endereco'] if row else None})
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /conta-endereco/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500
