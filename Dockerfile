# Imagem WEB do TocaDoCoelho — Fase 0 da migração desktop → web multiusuário.
# Empacota o app Flask servido por Gunicorn. NÃO inclui as dependências
# desktop-only (robô Playwright, pywin32, bandeja) nem a stack pesada
# de áudio/ML local. A imagem inclui geração server-side (ReportLab/Pillow),
# leitura digital segura (pdfplumber/python-docx) e transcrição curta via REST
# do Azure Speech F0; OCR, formatos legados e modelos locais ficam de fora.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TOCA_DATA_DIR=/data

WORKDIR /app

# Dependências primeiro (camada de cache separada do código).
COPY requirements-web.txt ./
RUN pip install --upgrade pip && pip install -r requirements-web.txt

# Código da aplicação.
COPY . .

# Usuário não-root + diretório de dados persistível (volume).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
EXPOSE 3000

# Liveness: bate no /healthz (sem auth, sem DB).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=4).status == 200 else 1)"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
