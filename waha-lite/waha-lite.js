'use strict';

/**
 * WAHA-lite: mini-servidor HTTP que implementa os endpoints da WAHA API
 * necessários pelo Toca do Coelho. Usa whatsapp-web.js + Chrome/Edge do
 * sistema — sem Docker, sem Chromium embutido.
 *
 * Endpoints implementados:
 *   GET  /api/sessions/:session
 *   POST /api/sessions
 *   GET  /api/:session/auth/qr?format=image
 *   GET  /api/:session/chats/:chatId/messages
 *   GET  /ping
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const qrcode = require('qrcode');
const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Configuração via variáveis de ambiente (definidas pelo launcher.py)
// ---------------------------------------------------------------------------
const API_KEY      = process.env.WAHA_API_KEY      || '';
const SESSION_NAME = process.env.WAHA_SESSION_NAME || 'default';
const PORT         = parseInt(process.env.WAHA_PORT || '3001', 10);
const DATA_DIR     = process.env.WAHA_DATA_DIR     || path.join(__dirname, '.waha-sessions');

const app = express();
app.use(express.json());

// Middleware de autenticação (opcional — só ativo se API_KEY estiver definida)
if (API_KEY) {
  app.use((req, res, next) => {
    if (req.path === '/ping') return next();
    if (req.headers['x-api-key'] !== API_KEY) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
  });
}

// ---------------------------------------------------------------------------
// Detectar Chrome ou Edge no sistema (Win10/11 sempre tem Edge)
// ---------------------------------------------------------------------------
function findBrowser() {
  const pf   = process.env['ProgramFiles']      || 'C:\\Program Files';
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const la   = process.env['LOCALAPPDATA']       || '';

  const candidates = [
    path.join(la,   'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(pf,   'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(pf,   'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    // Linux/macOS (dev)
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ];

  for (const p of candidates) {
    if (p && fs.existsSync(p)) {
      console.log(`[WAHA-lite] Navegador: ${p}`);
      return p;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Estado da sessão WhatsApp
// ---------------------------------------------------------------------------
let waClient     = null;
let clientStatus = 'STOPPED';  // STOPPED | STARTING | SCAN_QR_CODE | WORKING
let currentQr    = null;
let initError    = null;

function createWaClient() {
  const executablePath = findBrowser();
  if (!executablePath) {
    initError    = 'Chrome ou Edge não encontrado. Instale o Google Chrome para usar o WhatsApp Update.';
    clientStatus = 'STOPPED';
    console.error('[WAHA-lite] ERRO:', initError);
    return null;
  }

  const client = new Client({
    authStrategy: new LocalAuth({
      clientId: SESSION_NAME,
      dataPath:  DATA_DIR,
    }),
    puppeteer: {
      executablePath,
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--no-first-run',
        '--disable-extensions',
        '--disable-background-timer-throttling',
      ],
    },
  });

  client.on('qr', async (qr) => {
    clientStatus = 'SCAN_QR_CODE';
    currentQr    = qr;
    initError    = null;
    console.log('[WAHA-lite] QR code disponível — aguardando scan.');
  });

  client.on('authenticated', () => {
    console.log('[WAHA-lite] Sessão autenticada.');
  });

  client.on('ready', () => {
    clientStatus = 'WORKING';
    currentQr    = null;
    initError    = null;
    console.log('[WAHA-lite] WhatsApp conectado e pronto.');
  });

  client.on('auth_failure', (msg) => {
    console.error('[WAHA-lite] Falha de autenticação:', msg);
    clientStatus = 'STOPPED';
    waClient     = null;
  });

  client.on('disconnected', (reason) => {
    console.log('[WAHA-lite] Desconectado:', reason);
    clientStatus = 'STOPPED';
    currentQr    = null;
    waClient     = null;
  });

  client.initialize().catch((err) => {
    const msg = err.message || '';
    // Chrome deixa arquivos de lock quando o Node.js trava com o browser aberto.
    // Limpa o lock e tenta uma vez mais antes de desistir.
    if (msg.includes('browser is already running')) {
      console.warn('[WAHA-lite] Chrome travado da sessão anterior — limpando lock e retentando...');
      const sessionDir = path.join(DATA_DIR, `session-${SESSION_NAME}`);
      for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
        try { fs.unlinkSync(path.join(sessionDir, lf)); } catch (_) {}
      }
      waClient = null;
      setTimeout(() => {
        if (!waClient) {
          clientStatus = 'STARTING';
          waClient     = createWaClient();
        }
      }, 2000);
      return;
    }
    console.error('[WAHA-lite] Erro ao inicializar:', msg);
    clientStatus = 'STOPPED';
    initError    = msg;
    waClient     = null;
  });

  return client;
}

// ---------------------------------------------------------------------------
// Rotas
// ---------------------------------------------------------------------------

/** GET /ping — healthcheck */
app.get('/ping', (_req, res) => res.json({ ok: true }));

/** GET /api/sessions/:session — status da sessão */
app.get('/api/sessions/:session', (_req, res) => {
  res.json({
    name:   SESSION_NAME,
    status: clientStatus,
    ...(initError ? { error: initError } : {}),
  });
});

/** POST /api/sessions — cria/inicia sessão */
app.post('/api/sessions', (_req, res) => {
  if (!waClient) {
    clientStatus = 'STARTING';
    waClient     = createWaClient();
  }
  res.json({ name: SESSION_NAME, status: clientStatus });
});

/** POST /api/sessions/:session/start — (re)inicia a sessão (compat WAHA).
 *  Necessário para o app reerguer uma sessão STOPPED/FAILED sem reiniciar o Toca. */
app.post('/api/sessions/:session/start', (_req, res) => {
  if (!waClient || clientStatus === 'STOPPED') {
    clientStatus = 'STARTING';
    currentQr    = null;
    initError    = null;
    waClient     = createWaClient();
  }
  res.json({ name: SESSION_NAME, status: clientStatus });
});

/** GET /api/:session/auth/qr — QR code (format=image → PNG binário) */
app.get('/api/:session/auth/qr', async (req, res) => {
  if (!currentQr) {
    return res.status(404).json({ error: 'QR não disponível' });
  }
  if (req.query.format === 'image') {
    try {
      const png = await qrcode.toBuffer(currentQr, { type: 'png' });
      res.setHeader('Content-Type', 'image/png');
      return res.send(png);
    } catch (err) {
      return res.status(500).json({ error: err.message });
    }
  }
  res.json({ value: currentQr });
});

/** GET /api/:session/chats/:chatId/messages — mensagens filtradas por timestamp */
app.get('/api/:session/chats/:chatId/messages', async (req, res) => {
  if (!waClient || clientStatus !== 'WORKING') {
    return res.status(503).json({ error: 'WhatsApp não conectado', status: clientStatus });
  }

  const { chatId } = req.params;
  const limit = Math.min(parseInt(req.query.limit || '500', 10), 2000);
  const gteTs = parseInt(req.query['filter.timestamp.gte'] || '0', 10);
  const lteTs = parseInt(req.query['filter.timestamp.lte'] || String(Math.floor(Date.now() / 1000)), 10);

  try {
    const chat     = await waClient.getChatById(chatId);
    const messages = await chat.fetchMessages({ limit });

    const filtered = messages
      .filter((m) => {
        const ts = m.timestamp;
        return (!gteTs || ts >= gteTs) && (!lteTs || ts <= lteTs);
      })
      .map((m) => ({
        id:       { id: m.id.id, fromMe: m.fromMe, _serialized: m.id._serialized },
        body:     m.body || m._data?.caption || '',
        type:     m.type,
        timestamp: m.timestamp,
        from:     m.from,
        to:       m.to,
        fromMe:   m.fromMe,
        hasMedia: m.hasMedia,
      }));

    res.json(filtered);
  } catch (_err) {
    // Chat inexistente = sem conversa com este contato
    res.status(404).json({ error: _err.message });
  }
});

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------
app.listen(PORT, '127.0.0.1', () => {
  console.log(`[WAHA-lite] Servidor na porta ${PORT}`);
  console.log(`[WAHA-lite] Sessão: ${SESSION_NAME} | Data: ${DATA_DIR}`);
  // Inicia a sessão automaticamente ao subir
  if (!waClient) {
    clientStatus = 'STARTING';
    waClient     = createWaClient();
  }
});

// Graceful shutdown — destroça o cliente para fechar o Chrome antes de sair.
// Sem isso o processo Chrome fica orfão e impede reinicializações subsequentes.
async function gracefulShutdown() {
  if (waClient) {
    try { await waClient.destroy(); } catch (_) {}
  }
  process.exit(0);
}
process.on('SIGTERM', gracefulShutdown);
process.on('SIGINT',  gracefulShutdown);
