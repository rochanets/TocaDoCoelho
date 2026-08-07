# -*- coding: utf-8 -*-
"""Override do caminho do banco via TOCA_DB_PATH.

Sem isso não existe NENHUMA forma de subir o app apontando para um banco de
teste — DB_PATH era uma constante hardcoded para o banco real do usuário em
%APPDATA%, e um teste manual já contaminou o banco de produção por causa
disso. O override precisa valer no momento do import (é quando as migrações
rodam), então o teste usa um subprocess com o ambiente modificado.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_toca_db_path_redireciona_o_banco_inteiro(tmp_path):
    destino = tmp_path / 'banco-isolado.db'
    env = dict(os.environ, TOCA_DB_PATH=str(destino))
    out = subprocess.run(
        [sys.executable, '-c', 'import app; print(app.DB_PATH)'],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert str(destino) in out.stdout
    assert destino.exists(), 'as migrações do import deviam ter criado o banco no caminho apontado'
