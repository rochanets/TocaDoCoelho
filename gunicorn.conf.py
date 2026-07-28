"""Configuração do Gunicorn para a imagem web do TocaDoCoelho.

Tudo é sobreponível por variável de ambiente para facilitar o deploy.
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '3000')}"

# IMPORTANTE — 1 worker durante a F8.1.
# Os agendadores/pollers e parte das tarefas longas ainda são iniciados por
# processo. A validação fail-closed do runtime de produção recusa outro valor
# até a liderança distribuída e a persistência compartilhada da F8.2.
workers = int(os.getenv('WEB_CONCURRENCY', '1'))

timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))

# Logs no stdout/stderr (padrão de container — o orquestrador coleta).
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('GUNICORN_LOGLEVEL', 'info')
