# WAHA local

Suba com `docker compose -f docker-compose.waha.yml up -d`.
Por padrão, o WAHA fica exposto em `http://localhost:3001` para não conflitar com o Toca do Coelho, que roda em `http://localhost:3000`.
Se precisar usar outra URL, defina `WAHA_BASE_URL` antes de iniciar o app.
O Dashboard tenta enviar via WAHA primeiro e usa WhatsApp Web apenas como contingência.
