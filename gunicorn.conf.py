"""Configuração do Gunicorn para a imagem web do TocaDoCoelho.

Tudo é sobreponível por variável de ambiente para facilitar o deploy.
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# A F8.2 permite múltiplos workers quando o runtime usa PostgreSQL e ativa
# TOCA_MULTIWORKER_JOBS_ENABLED. Advisory locks, claims duráveis e o task store
# compartilhado impedem duplicação dos jobs iniciados em cada processo.
workers = int(os.getenv('WEB_CONCURRENCY', '1'))

timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))

# Logs no stdout/stderr (padrão de container — o orquestrador coleta).
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOGLEVEL', 'info')
