"""Configuração do Gunicorn para a imagem web do TocaDoCoelho.

Tudo é sobreponível por variável de ambiente para facilitar o deploy.
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# IMPORTANTE — 1 worker por padrão.
# Os agendadores/pollers de tarefas longas ainda vivem em MEMÓRIA do processo
# (dict `_tasks` + `threading.Thread`, `_start_inbound_poller`,
# `_start_scheduled_jobs`). Com múltiplos workers cada um subiria sua própria
# cópia desses jobs, duplicando envios/pollings. Só aumente WEB_CONCURRENCY
# depois da Fase 6 (externalizar tarefas para Celery/RQ + Redis).
workers = int(os.getenv('WEB_CONCURRENCY', '1'))

timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))

# Logs no stdout/stderr (padrão de container — o orquestrador coleta).
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOGLEVEL', 'info')
