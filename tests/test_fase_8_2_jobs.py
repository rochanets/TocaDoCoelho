import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app as toca


def _columns(conn, table):
    return {
        row[1]
        for row in conn.execute(f'PRAGMA table_info({table})').fetchall()
    }


def test_f82_schema_is_additive_and_complete(db_path):
    conn = toca.get_db()
    try:
        assert {
            'payload_json', 'runner_id', 'heartbeat_at', 'expires_at',
        } <= _columns(conn, 'background_tasks')
        assert {
            'claim_token', 'claimed_at', 'attempt_count',
        } <= _columns(conn, 'scheduled_sends')
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {'job_runtime_state', 'job_execution_claims'} <= tables
    finally:
        conn.close()


def test_run_key_claim_is_at_most_once(db_path):
    calls = []
    key = f'test:once:{uuid.uuid4().hex}'

    first = toca._run_distributed_job(
        key,
        lambda: calls.append('first') or 'ok',
        run_key='cycle-1',
    )
    second = toca._run_distributed_job(
        key,
        lambda: calls.append('second') or 'ok',
        run_key='cycle-1',
    )

    assert first['executed'] is True
    assert second == {'executed': False, 'reason': 'already_claimed'}
    assert calls == ['first']


def test_skip_releases_claim_for_safe_retry(db_path):
    key = f'test:skip:{uuid.uuid4().hex}'
    skipped = toca._run_distributed_job(key, lambda: 'skip', run_key='cycle')
    retried = toca._run_distributed_job(key, lambda: 'done', run_key='cycle')

    assert skipped['reason'] == 'skipped'
    assert retried['executed'] is True
    assert retried['result'] == 'done'


def test_failed_effect_claim_blocks_automatic_retry(db_path):
    key = f'test:failed:{uuid.uuid4().hex}'

    with pytest.raises(RuntimeError, match='ambiguous'):
        toca._run_distributed_job(
            key,
            lambda: (_ for _ in ()).throw(RuntimeError('ambiguous')),
            run_key='cycle',
        )

    retry = toca._run_distributed_job(key, lambda: 'duplicate', run_key='cycle')
    assert retry == {'executed': False, 'reason': 'already_claimed'}

    conn = toca.get_db()
    row = conn.execute(
        'SELECT status FROM job_execution_claims WHERE job_key = ? AND run_key = ?',
        (key, 'cycle'),
    ).fetchone()
    conn.close()
    assert row['status'] == 'failed'


def test_background_task_survives_worker_cache_change(db_path, monkeypatch):
    task_id = uuid.uuid4().hex
    monkeypatch.setattr(toca, '_auth_enabled', lambda: True)
    conn = toca.get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO organizations (name) VALUES ('Org Tasks')")
    org_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO users (org_id, email, full_name, role) "
        "VALUES (?, 'task-owner@example.com', 'Task Owner', 'member')",
        (org_id,),
    )
    owner_id = cursor.lastrowid
    conn.commit()
    conn.close()

    with toca.app.test_request_context('/'):
        monkeypatch.setattr(toca, 'current_user_id', lambda: owner_id)
        toca._bg_task_register_persistent(task_id, 'test', owner_id=owner_id)
        toca._bg_task_set(task_id, {
            'status': 'done',
            'progress': 100,
            'result': {'value': 42},
        })

        with toca._bg_tasks_lock:
            toca._bg_tasks.pop(task_id, None)
            toca._bg_task_owners.pop(task_id, None)
            toca._bg_persistent_kinds.pop(task_id, None)

        recovered = toca._bg_task_get(task_id)
        assert recovered['status'] == 'done'
        assert recovered['result'] == {'value': 42}

        with toca._bg_tasks_lock:
            toca._bg_tasks.pop(task_id, None)
            toca._bg_task_owners.pop(task_id, None)
        monkeypatch.setattr(toca, 'current_user_id', lambda: 999)
        assert toca._bg_task_get(task_id) == {}


def test_startup_only_interrupts_stale_tasks(db_path):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recent = (now - timedelta(minutes=1)).isoformat(timespec='seconds')
    stale = (now - timedelta(minutes=30)).isoformat(timespec='seconds')
    conn = toca.get_db()
    conn.execute(
        '''INSERT INTO background_tasks
           (task_id, kind, status, heartbeat_at, updated_at)
           VALUES ('recent-task', 'test', 'processing', ?, ?)''',
        (recent, recent),
    )
    conn.execute(
        '''INSERT INTO background_tasks
           (task_id, kind, status, heartbeat_at, updated_at)
           VALUES ('stale-task', 'test', 'processing', ?, ?)''',
        (stale, stale),
    )
    conn.executemany(
        '''INSERT INTO scheduled_sends
           (channel, email_to, message, scheduled_for, status, claimed_at)
           VALUES ('email', 'dest@example.com', ?, '2099-01-01 10:00',
                   'processing', ?)''',
        [
            ('legacy-processing', None),
            ('recent-processing', recent),
            ('stale-processing', stale),
        ],
    )
    conn.commit()
    conn.close()

    toca._mark_interrupted_background_tasks()

    conn = toca.get_db()
    rows = {
        row['task_id']: row['status']
        for row in conn.execute(
            "SELECT task_id, status FROM background_tasks "
            "WHERE task_id IN ('recent-task', 'stale-task')"
        ).fetchall()
    }
    sends = {
        row['message']: row['status']
        for row in conn.execute(
            "SELECT message, status FROM scheduled_sends "
            "WHERE message LIKE '%-processing'"
        ).fetchall()
    }
    conn.close()
    assert rows == {'recent-task': 'processing', 'stale-task': 'interrupted'}
    assert sends == {
        'legacy-processing': 'error',
        'recent-processing': 'processing',
        'stale-processing': 'error',
    }


def test_operational_cleanup_keeps_fresh_and_failed_state(db_path):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = (now - timedelta(hours=1)).isoformat(timespec='seconds')
    fresh = (now + timedelta(hours=1)).isoformat(timespec='seconds')
    old = (now - timedelta(days=31)).isoformat(timespec='seconds')
    conn = toca.get_db()
    conn.executemany(
        '''INSERT INTO background_tasks
           (task_id, kind, status, expires_at)
           VALUES (?, 'test', 'done', ?)''',
        [('expired-task', expired), ('fresh-task', fresh)],
    )
    conn.executemany(
        '''INSERT INTO job_execution_claims
           (job_key, run_key, owner_id, status, completed_at)
           VALUES (?, 'cycle', 'test-runner', ?, ?)''',
        [
            ('old-success', 'succeeded', old),
            ('old-failure', 'failed', old),
            ('fresh-success', 'succeeded', fresh),
        ],
    )
    conn.commit()
    conn.close()

    result = toca._operational_state_cleanup_job()

    conn = toca.get_db()
    tasks = {
        row['task_id']
        for row in conn.execute(
            "SELECT task_id FROM background_tasks "
            "WHERE task_id IN ('expired-task', 'fresh-task')"
        )
    }
    claims = {
        row['job_key']
        for row in conn.execute(
            "SELECT job_key FROM job_execution_claims "
            "WHERE job_key IN ('old-success', 'old-failure', 'fresh-success')"
        )
    }
    conn.close()
    assert result == {'expired_tasks': 1, 'old_claims': 1}
    assert tasks == {'fresh-task'}
    assert claims == {'old-failure', 'fresh-success'}


def test_scheduled_send_claim_is_atomic(db_path):
    conn = toca.get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO scheduled_sends
           (channel, email_to, message, scheduled_for, status)
           VALUES ('email', 'dest@example.com', 'oi', '2099-01-01 10:00', 'pending')'''
    )
    send_id = cursor.lastrowid
    assert toca._scheduled_send_claim(cursor, send_id) is True
    conn.commit()
    assert toca._scheduled_send_claim(cursor, send_id) is False
    conn.rollback()
    row = conn.execute(
        'SELECT status, attempt_count, claim_token FROM scheduled_sends WHERE id = ?',
        (send_id,),
    ).fetchone()
    conn.close()
    assert row['status'] == 'processing'
    assert row['attempt_count'] == 1
    assert row['claim_token']


def test_admin_job_status_exposes_shared_state(client):
    key = f'test:status:{uuid.uuid4().hex}'
    toca._run_distributed_job(key, lambda: 'ok')

    response = client.get('/api/admin/jobs/status')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['backend'] == 'sqlite'
    assert any(row['job_key'] == key for row in payload['states'])
    json.dumps(payload)
