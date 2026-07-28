"""Concorrência real da F8.2 contra PostgreSQL."""

import os
import threading
import uuid

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


def test_postgres_advisory_lock_allows_only_one_worker():
    job_key = f'test:pg-lock:{uuid.uuid4().hex}'
    entered = threading.Event()
    release = threading.Event()
    calls = []
    holder_result = {}

    def _holder_body():
        calls.append('holder')
        entered.set()
        assert release.wait(timeout=10)
        return 'holder-done'

    def _holder():
        holder_result.update(toca._run_distributed_job(job_key, _holder_body))

    thread = threading.Thread(target=_holder)
    thread.start()
    assert entered.wait(timeout=10)

    contender = toca._run_distributed_job(
        job_key,
        lambda: calls.append('contender'),
    )
    assert contender == {'executed': False, 'reason': 'lock_unavailable'}

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert holder_result['executed'] is True
    assert calls == ['holder']

    after_release = toca._run_distributed_job(job_key, lambda: 'next')
    assert after_release['executed'] is True
    assert after_release['result'] == 'next'


def test_postgres_claim_and_task_payload_are_shared():
    job_key = f'test:pg-claim:{uuid.uuid4().hex}'
    first = toca._run_distributed_job(job_key, lambda: 'sent', run_key='one')
    duplicate = toca._run_distributed_job(job_key, lambda: 'duplicate', run_key='one')
    assert first['executed'] is True
    assert duplicate['reason'] == 'already_claimed'

    task_id = uuid.uuid4().hex
    toca._bg_task_register_persistent(task_id, 'pg-test')
    toca._bg_task_set(task_id, {
        'status': 'done',
        'progress': 100,
        'result': {'worker': 'a'},
    })
    with toca._bg_tasks_lock:
        toca._bg_tasks.pop(task_id, None)
        toca._bg_task_owners.pop(task_id, None)
        toca._bg_persistent_kinds.pop(task_id, None)

    recovered = toca._bg_task_get(task_id)
    assert recovered['result'] == {'worker': 'a'}
