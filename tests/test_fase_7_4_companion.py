# -*- coding: utf-8 -*-
"""Fase 7.4: contrato seguro e persistente do Toca Companion."""

from io import BytesIO
from pathlib import Path

import app as toca


ROOT = Path(__file__).resolve().parents[1]


def _auth_on(monkeypatch):
    monkeypatch.setenv("TOCA_AUTH_ENABLED", "1")
    monkeypatch.setitem(toca.app.config, "SESSION_COOKIE_SECURE", False)


def _seed_user(client, *, email="companion@corp.com"):
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES (?)", (f"Org {email}",))
    org_id = cur.lastrowid
    cur.execute(
        """INSERT INTO users (org_id, email, full_name, role)
           VALUES (?, ?, ?, 'admin')""",
        (org_id, email, email),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return user_id


def _pair_device(client, *, name="Notebook corporativo", version="1.0.0"):
    pairing = client.post("/api/companion/pairings")
    assert pairing.status_code == 201, pairing.get_json()
    pairing_code = pairing.get_json()["pairing_code"]
    claim = client.post(
        "/api/companion/v1/pairings/claim",
        json={
            "pairing_code": pairing_code,
            "device_name": name,
            "platform": "windows",
            "app_version": version,
        },
    )
    assert claim.status_code == 201, claim.get_json()
    return pairing_code, claim.get_json()


def _robot_form():
    return {
        "conta": "Conta Companion",
        "endereco": "Rua de Teste, 100",
        "minuta_tipo": "cliente",
        "assinatura_plataforma": "stefanini",
        "descricao_pedido": "Renovação contratual",
        "havera_reajuste": "nao",
        "houve_reoneracao": "nao",
        "inclui_novos_servicos": "nao",
        "e_prorrogacao_vigencia": "nao",
    }


def _enqueue_robot(client, *, key="f74-request-1", data=None):
    response = client.post(
        "/api/autotoca/chamado-juridico/robot",
        data=data or _robot_form(),
        headers={"Idempotency-Key": key},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202, response.get_json()
    return response.get_json()


def _device_headers(token, lease=None):
    headers = {"Authorization": f"Bearer {token}"}
    if lease:
        headers["X-Toca-Task-Lease"] = lease
    return headers


def test_pairing_is_one_time_and_secrets_are_hashed(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    pairing_code, device = _pair_device(client)

    repeated = client.post(
        "/api/companion/v1/pairings/claim",
        json={
            "pairing_code": pairing_code,
            "device_name": "Outro",
            "platform": "windows",
            "app_version": "1.0.0",
        },
    )
    assert repeated.status_code in {404, 409}

    conn = toca.get_db()
    row = conn.execute(
        "SELECT code_hash, claimed_at FROM companion_pairings"
    ).fetchone()
    stored_device = conn.execute(
        "SELECT token_hash FROM companion_devices WHERE id = ?",
        (device["device_id"],),
    ).fetchone()
    conn.close()

    assert pairing_code.replace("-", "") not in row["code_hash"]
    assert row["claimed_at"] is not None
    assert device["device_token"] not in stored_device["token_hash"]


def test_device_routes_require_bearer_even_though_login_gate_is_bypassed(
    client, monkeypatch
):
    _auth_on(monkeypatch)
    response = client.post("/api/companion/v1/tasks/next", json={})
    assert response.status_code == 401
    assert response.get_json()["code"] == "COMPANION_AUTH_REQUIRED"


def test_web_robot_is_queued_and_idempotent(client, monkeypatch):
    _auth_on(monkeypatch)
    user_id = _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )

    first = _enqueue_robot(client, key="same-request")
    second = _enqueue_robot(client, key="same-request")

    assert first["execution"] == "companion"
    assert second["task_id"] == first["task_id"]
    assert second["history_id"] == first["history_id"]
    assert second["idempotent_replay"] is True

    conn = toca.get_db()
    task = conn.execute(
        "SELECT * FROM companion_tasks WHERE id = ?", (first["task_id"],)
    ).fetchone()
    task_count = conn.execute(
        "SELECT COUNT(*) AS n FROM companion_tasks WHERE owner_id = ?",
        (user_id,),
    ).fetchone()["n"]
    history_count = conn.execute(
        "SELECT COUNT(*) AS n FROM chamado_juridico_history WHERE owner_id = ?",
        (user_id,),
    ).fetchone()["n"]
    conn.close()

    assert task["status"] == "queued"
    assert task["idempotency_key"] == "same-request"
    assert task_count == 1
    assert history_count == 1


def test_device_claims_task_with_lease_and_completes_state_machine(
    client, monkeypatch
):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    queued = _enqueue_robot(client)
    token = device["device_token"]

    claim = client.post(
        "/api/companion/v1/tasks/next",
        json={"app_version": "1.1.0"},
        headers=_device_headers(token),
    )
    assert claim.status_code == 200, claim.get_json()
    task = claim.get_json()
    assert task["task_id"] == queued["task_id"]
    assert task["status"] == "leased"
    assert task["payload"]["constraints"] == {
        "allow_submit": False,
        "requires_user_review": True,
    }
    lease = task["lease_token"]

    running = client.patch(
        f"/api/companion/v1/tasks/{task['task_id']}",
        json={"status": "running", "progress": 25, "step": "Abrindo Forms"},
        headers=_device_headers(token, lease),
    )
    assert running.status_code == 200, running.get_json()

    awaiting = client.patch(
        f"/api/companion/v1/tasks/{task['task_id']}",
        json={
            "status": "awaiting_user",
            "progress": 90,
            "step": "Aguardando revisão do usuário",
        },
        headers=_device_headers(token, lease),
    )
    assert awaiting.status_code == 200, awaiting.get_json()

    completed = client.patch(
        f"/api/companion/v1/tasks/{task['task_id']}",
        json={
            "status": "succeeded",
            "progress": 100,
            "step": "Preenchimento concluído",
            "result": {
                "submitted": False,
                "filled": ["Conta", "Endereço"],
            },
        },
        headers=_device_headers(token, lease),
    )
    assert completed.status_code == 200, completed.get_json()

    legacy_poll = client.get(
        f"/api/autotoca/chamado-juridico/robot/tasks/{task['task_id']}"
    )
    assert legacy_poll.status_code == 200
    body = legacy_poll.get_json()
    assert body["status"] == "done"
    assert body["companion_status"] == "succeeded"
    assert body["result"]["submitted"] is False


def test_auto_submit_is_rejected_by_server(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    queued = _enqueue_robot(client)
    token = device["device_token"]
    task = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(token),
    ).get_json()

    running = client.patch(
        f"/api/companion/v1/tasks/{queued['task_id']}",
        json={"status": "running"},
        headers=_device_headers(token, task["lease_token"]),
    )
    assert running.status_code == 200
    forbidden = client.patch(
        f"/api/companion/v1/tasks/{queued['task_id']}",
        json={"status": "succeeded", "result": {"submitted": True}},
        headers=_device_headers(token, task["lease_token"]),
    )
    assert forbidden.status_code == 422
    assert forbidden.get_json()["code"] == "COMPANION_AUTO_SUBMIT_FORBIDDEN"


def test_task_and_device_are_scoped_to_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    owner_a = _seed_user(client, email="a@corp.com")
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    queued = _enqueue_robot(client)

    owner_b = _seed_user(client, email="b@corp.com")
    assert owner_b != owner_a
    assert client.get(
        f"/api/companion/tasks/{queued['task_id']}"
    ).status_code == 404
    assert client.delete(
        f"/api/companion/devices/{device['device_id']}"
    ).status_code == 404

    no_task = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(device["device_token"]),
    )
    assert no_task.status_code == 200
    assert no_task.get_json()["task_id"] == queued["task_id"]


def test_queued_task_can_be_cancelled_before_claim(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    queued = _enqueue_robot(client)

    cancelled = client.post(
        f"/api/companion/tasks/{queued['task_id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["status"] == "cancelled"

    no_task = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(device["device_token"]),
    )
    assert no_task.status_code == 204


def test_queued_task_expires_even_without_connected_device(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    queued = _enqueue_robot(client, key="expires-without-device")
    conn = toca.get_db()
    conn.execute(
        "UPDATE companion_tasks SET expires_at = ? WHERE id = ?",
        ("2000-01-01 00:00:00", queued["task_id"]),
    )
    conn.commit()
    conn.close()

    status = client.get(
        f"/api/autotoca/chamado-juridico/robot/tasks/{queued['task_id']}"
    )
    assert status.status_code == 200
    assert status.get_json()["status"] == "error"
    assert status.get_json()["companion_status"] == "expired"
    assert status.get_json()["error_code"] == "COMPANION_TASK_EXPIRED"


def test_active_task_receives_cancel_requested(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    queued = _enqueue_robot(client)
    token = device["device_token"]
    task = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(token),
    ).get_json()

    cancel = client.post(
        f"/api/companion/tasks/{queued['task_id']}/cancel"
    )
    assert cancel.get_json()["status"] == "cancel_requested"

    heartbeat = client.patch(
        f"/api/companion/v1/tasks/{queued['task_id']}",
        json={"progress": 10},
        headers=_device_headers(token, task["lease_token"]),
    )
    assert heartbeat.status_code == 200
    assert heartbeat.get_json()["cancel_requested"] is True

    acknowledged = client.patch(
        f"/api/companion/v1/tasks/{queued['task_id']}",
        json={"status": "cancelled", "step": "Execução cancelada"},
        headers=_device_headers(token, task["lease_token"]),
    )
    assert acknowledged.status_code == 200


def test_task_file_download_requires_matching_device_and_lease(
    client, monkeypatch
):
    _auth_on(monkeypatch)
    _seed_user(client)
    monkeypatch.setattr(
        toca, "_chamado_juridico_default_support_file", lambda: None
    )
    _, device = _pair_device(client)
    data = _robot_form()
    data["proposta_comercial_tecnica"] = (
        BytesIO(b"%PDF-1.4 companion-test"),
        "proposta.pdf",
    )
    queued = _enqueue_robot(client, key="file-task", data=data)
    token = device["device_token"]
    claimed = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(token),
    ).get_json()
    assert claimed["files"][0]["original_name"] == "proposta.pdf"
    assert "stored_path" not in claimed["files"][0]

    url = claimed["files"][0]["download_url"]
    denied = client.get(url, headers=_device_headers(token))
    assert denied.status_code == 403
    downloaded = client.get(
        url,
        headers=_device_headers(token, claimed["lease_token"]),
    )
    assert downloaded.status_code == 200
    assert downloaded.data == b"%PDF-1.4 companion-test"

    conn = toca.get_db()
    file_row = conn.execute(
        "SELECT * FROM companion_task_files WHERE task_id = ?",
        (queued["task_id"],),
    ).fetchone()
    conn.close()
    assert file_row["size_bytes"] == len(b"%PDF-1.4 companion-test")
    assert len(file_row["sha256"]) == 64

    Path(file_row["stored_path"]).write_bytes(b"arquivo alterado")
    integrity_error = client.get(
        url,
        headers=_device_headers(token, claimed["lease_token"]),
    )
    assert integrity_error.status_code == 409
    assert (
        integrity_error.get_json()["code"]
        == "COMPANION_FILE_INTEGRITY_MISMATCH"
    )


def test_revoked_device_token_stops_work(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(client)
    _, device = _pair_device(client)
    revoked = client.delete(
        f"/api/companion/devices/{device['device_id']}"
    )
    assert revoked.status_code == 204
    denied = client.post(
        "/api/companion/v1/tasks/next",
        json={},
        headers=_device_headers(device["device_token"]),
    )
    assert denied.status_code == 401


def test_update_manifest_requires_checksum_and_compares_versions(
    client, monkeypatch
):
    _auth_on(monkeypatch)
    _seed_user(client)
    _, device = _pair_device(client, version="1.0.0")
    monkeypatch.setenv("TOCA_COMPANION_LATEST_VERSION", "1.2.0")
    monkeypatch.setenv("TOCA_COMPANION_MIN_VERSION", "1.1.0")
    monkeypatch.setenv(
        "TOCA_COMPANION_DOWNLOAD_URL",
        "https://downloads.example/companion.exe",
    )
    monkeypatch.setenv("TOCA_COMPANION_DOWNLOAD_SHA256", "a" * 64)

    response = client.get(
        "/api/companion/v1/manifest?current_version=1.0.0",
        headers=_device_headers(device["device_token"]),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["update_available"] is True
    assert body["update_required"] is True
    assert body["download"]["sha256"] == "a" * 64

    blocked = client.post(
        "/api/companion/v1/tasks/next",
        json={"app_version": "1.0.0"},
        headers=_device_headers(device["device_token"]),
    )
    assert blocked.status_code == 426
    assert blocked.get_json()["code"] == "COMPANION_UPDATE_REQUIRED"

    monkeypatch.setenv(
        "TOCA_COMPANION_DOWNLOAD_URL",
        "http://downloads.example/companion.exe",
    )
    insecure = client.get(
        "/api/companion/v1/manifest?current_version=1.0.0",
        headers=_device_headers(device["device_token"]),
    )
    assert insecure.get_json()["download"] is None


def test_desktop_keeps_direct_robot_contract(client, monkeypatch):
    monkeypatch.delenv("TOCA_AUTH_ENABLED", raising=False)
    response = client.post("/api/companion/pairings")
    assert response.status_code == 409
    assert response.get_json()["code"] == "COMPANION_WEB_ONLY"

    script = (ROOT / "routes" / "autotoca.py").read_text(encoding="utf-8")
    assert "if _auth_enabled():" in script
    assert "target=_forms_robot_process_async" in script


def test_frontend_uses_idempotency_and_real_companion_cancel():
    script = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    assert "'Idempotency-Key': _cjGetRobotIdempotencyKey()" in script
    assert "/companion/tasks/${taskId}/cancel" in script
