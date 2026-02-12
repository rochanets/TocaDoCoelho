#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

# Diretorio de dados
DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho' if sys.platform == 'win32' else Path.home() / '.toca-do-coelho'
DB_PATH = DATA_DIR / 'toca-do-coelho.db'

print("=" * 60)
print("  RESETAR BANCO DE DADOS - TOCA DO COELHO")
print("=" * 60)
print()

if DB_PATH.exists():
    print(f"[INFO] Banco de dados encontrado em: {DB_PATH}")
    print("[INFO] Deletando banco de dados antigo...")
    DB_PATH.unlink()
    print("[✓] Banco de dados deletado com sucesso!")
    print()
    print("[INFO] Próxima vez que você rodar o app.py, um novo banco será criado automaticamente.")
    print("[✓] Pronto! Execute INICIAR.bat para continuar.")
else:
    print(f"[INFO] Nenhum banco de dados encontrado em: {DB_PATH}")
    print("[✓] Nada a fazer!")

print()
print("=" * 60)
