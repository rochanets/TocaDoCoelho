# WAHA

Há dois runtimes deliberadamente separados:

- desktop/local: o launcher continua iniciando o `waha-lite` em `localhost:3001`;
- produção web: o único sidecar suportado está em
  `docker-compose.production.yml`, sem porta publicada.

Os Compose legados isolados foram removidos na F8.3 para evitar topologias
divergentes e uso acidental de `latest`. Configuração, QR, persistência e
recuperação estão em `docs/fase-8-waha-sidecar.md`.
