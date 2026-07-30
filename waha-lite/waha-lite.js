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
const { execSync } = require('child_process');
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

// Tempo máximo (ms) para a sessão sair de STARTING/autenticada e ficar pronta (WORKING).
// Passou disso sem QR e sem ready = sessão travada → reciclar.
const READY_TIMEOUT_MS = parseInt(process.env.WAHA_READY_TIMEOUT_MS || '75000', 10);
// Quantas vezes recriar o cliente automaticamente antes de desistir.
const MAX_RECREATE     = parseInt(process.env.WAHA_MAX_RECREATE || '3', 10);
const GATEWAY_VERSION  = 4;
const GATEWAY_CAPABILITIES = [
  'chat-list-match',
  'sync-diagnostics',
  'cached-message-fetch',
  'bounded-history-fetch',
];

// Versão do WhatsApp Web a fixar — workaround para o bug "trava em 99% → LOGOUT" do
// whatsapp-web.js com as versões 2.3000.x (issue upstream #5758). Fixar uma versão
// conhecida via webVersionCache evita que o WhatsApp Web atualize para uma versão que a
// lib ainda não suporta. Vazio = não fixa (usa o padrão do whatsapp-web.js).
//
// Pode ser configurada SEM editar este arquivo, por (em ordem de prioridade):
//   1) variável de ambiente WAHA_WEB_VERSION
//   2) arquivo "web-version.txt" ao lado deste script (1 linha com a versão)
// Ex. de versão: 2.3000.1041467552-alpha  (lista em github.com/wppconnect-team/wa-version)
function resolveWebVersion() {
  const fromEnv = (process.env.WAHA_WEB_VERSION || '').trim();
  if (fromEnv) return fromEnv;
  try {
    const f = path.join(__dirname, 'web-version.txt');
    if (fs.existsSync(f)) {
      const v = fs.readFileSync(f, 'utf8').trim();
      if (v && !v.startsWith('#')) return v;
    }
  } catch (_) { /* sem arquivo = sem fixar */ }
  return '';
}
const WEB_VERSION = resolveWebVersion();

// ---------------------------------------------------------------------------
// Logging — timestamp ISO + nível + PID. Substitui os console.log "secos".
// ---------------------------------------------------------------------------
function log(level, ...args) {
  const ts   = new Date().toISOString();
  const msg  = args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
  const line = `[${ts}] [${level}] [pid:${process.pid}] ${msg}`;
  if (level === 'ERROR')      console.error(line);
  else if (level === 'WARN')  console.warn(line);
  else                        console.log(line);
}

function safeError(err) {
  const name = err && err.name ? err.name : 'Error';
  const message = err && err.message ? err.message : String(err || '');
  const redacted = message
    .replace(/(?<!\d)\d{10,15}(?:@(c\.us|lid))?/gi, '<contato>')
    .replace(/(x-api-key|authorization)(\s*[:=]\s*)([^\s,;]+)/gi, '$1$2<redigido>')
    .slice(0, 600);
  return redacted ? `${name}: ${redacted}` : name;
}

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
      log('INFO', `Navegador encontrado: ${p}`);
      return p;
    }
  }
  log('ERROR', 'Nenhum navegador (Chrome/Edge) encontrado nos caminhos conhecidos.');
  return null;
}

// ---------------------------------------------------------------------------
// Estado da sessão WhatsApp
// ---------------------------------------------------------------------------
let waClient      = null;
let clientStatus  = 'STOPPED';  // STOPPED | STARTING | SCAN_QR_CODE | WORKING
let currentQr     = null;
let initError     = null;
let chromePid     = null;       // PID do Chrome controlado pelo Puppeteer (p/ kill forçado)
let recreateCount = 0;          // quantas vezes já reciclamos o cliente
let readyWatchdog = null;       // timer que detecta sessão travada

/** Remove os arquivos de lock que o Chrome deixa quando o processo morre sujo. */
function cleanSessionLocks() {
  const sessionDir = path.join(DATA_DIR, `session-${SESSION_NAME}`);
  for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
    try {
      fs.unlinkSync(path.join(sessionDir, lf));
      log('WARN', `Lock de sessão removido: ${lf}`);
    } catch (_) { /* não existe = ok */ }
  }
}

/**
 * Mata processos Chrome que usam o diretório desta sessão (órfãos de execuções
 * anteriores). Sem isto, um Chrome deixado rodando impede novas inicializações com
 * "browser is already running" mesmo após cleanSessionLocks() remover os arquivos
 * — porque o Chrome vivo regenera o SingletonLock imediatamente.
 * Só executa no Windows; no Linux/macOS o Puppeteer fecha o Chrome corretamente.
 */
async function killOrphanChrome() {
  if (process.platform !== 'win32') return;
  try {
    const out = execSync(
      'wmic process where "name=\'chrome.exe\'" get ProcessId,CommandLine /format:list',
      { encoding: 'utf8', timeout: 8000 }
    );
    const pids = [];
    for (const block of out.split(/(?:\r?\n){2,}/)) {
      if (/waha-sessions/i.test(block)) {
        const m = block.match(/ProcessId=(\d+)/i);
        if (m && m[1] !== '0') pids.push(m[1]);
      }
    }
    for (const pid of pids) {
      try {
        execSync(`taskkill /F /T /PID ${pid}`, { timeout: 3000 });
        log('INFO', `Chrome órfão (PID ${pid}) encerrado.`);
      } catch (_) { /* pode já ter morrido */ }
    }
    if (pids.length) {
      await new Promise((r) => setTimeout(r, 1500)); // aguarda processos sumirem
    }
  } catch (e) {
    log('WARN', `killOrphanChrome: ${e.message}`);
  }
}

/** Mata o Chrome do Puppeteer à força, caso o destroy() não o feche. */
function killChrome() {
  if (!chromePid) return;
  try {
    process.kill(chromePid);
    log('WARN', `Chrome (PID ${chromePid}) encerrado à força.`);
  } catch (_) { /* já morreu */ }
  chromePid = null;
}

function clearReadyWatchdog() {
  if (readyWatchdog) { clearTimeout(readyWatchdog); readyWatchdog = null; }
}

/** Arma o watchdog: se em READY_TIMEOUT_MS a sessão não ficar pronta (e não
 *  estiver legitimamente esperando o scan do QR), recicla o cliente. */
function armReadyWatchdog() {
  clearReadyWatchdog();
  readyWatchdog = setTimeout(() => {
    if (clientStatus === 'WORKING') return;            // conectou, tudo certo
    if (clientStatus === 'SCAN_QR_CODE') {             // esperando o usuário escanear
      log('INFO', 'Aguardando leitura do QR code pelo usuário — watchdog re-armado.');
      armReadyWatchdog();
      return;
    }
    // STARTING há tempo demais = autenticou mas nunca ficou pronto → travou.
    log('WARN', `Sessão presa em '${clientStatus}' por mais de ${Math.round(READY_TIMEOUT_MS / 1000)}s sem ficar pronta.`);
    recycleClient('timeout aguardando ready (autenticado mas não conectou)');
  }, READY_TIMEOUT_MS);
}

/** Destrói o cliente atual fechando o Chrome (com timeout de segurança). */
async function destroyClient() {
  clearReadyWatchdog();
  const c = waClient;
  waClient = null;
  if (c) {
    try {
      await Promise.race([
        c.destroy(),
        new Promise((resolve) => setTimeout(resolve, 8000)),
      ]);
      log('INFO', 'Cliente WhatsApp destruído.');
    } catch (e) {
      log('WARN', `Falha ao destruir cliente: ${e.message}`);
    }
  }
  killChrome();
}

/** Recicla o cliente: destrói, limpa locks e recria. Limitado a MAX_RECREATE. */
async function recycleClient(reason) {
  if (recreateCount >= MAX_RECREATE) {
    clearReadyWatchdog(); // impede watchdog de re-disparar após desistirmos
    initError    = `Não foi possível conectar após ${MAX_RECREATE} tentativas (${reason}). ` +
                   'Abra o WhatsApp no celular, confira a conexão e reinicie o Toca do Coelho.';
    clientStatus = 'STOPPED';
    log('ERROR', initError);
    return;
  }
  recreateCount++;
  log('WARN', `Reciclando cliente WhatsApp (tentativa ${recreateCount}/${MAX_RECREATE}) — motivo: ${reason}`);
  await destroyClient();
  cleanSessionLocks();
  await killOrphanChrome(); // mata Chrome órfão que regeneraria o lock imediatamente
  cleanSessionLocks();      // remove locks que o Chrome órfão possa ter recriado
  setTimeout(() => {
    if (!waClient) {
      clientStatus = 'STARTING';
      waClient     = createWaClient();
    }
  }, 2500);
}

function createWaClient() {
  const executablePath = findBrowser();
  if (!executablePath) {
    initError    = 'Chrome ou Edge não encontrado. Instale o Google Chrome para usar o WhatsApp Update.';
    clientStatus = 'STOPPED';
    return null;
  }

  log('INFO', `Inicializando cliente WhatsApp (sessão='${SESSION_NAME}', data='${DATA_DIR}')...`);

  const clientOptions = {
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
  };

  // Fixa a versão do WhatsApp Web (workaround do bug 99%/LOGOUT), se configurada.
  if (WEB_VERSION) {
    clientOptions.webVersion = WEB_VERSION;
    clientOptions.webVersionCache = {
      type: 'remote',
      remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html',
    };
    log('INFO', `Fixando WhatsApp Web na versão ${WEB_VERSION} (webVersionCache remoto).`);
  } else {
    log('INFO', 'Versão do WhatsApp Web não fixada (padrão do whatsapp-web.js). Defina WAHA_WEB_VERSION ou web-version.txt se travar em 99%.');
  }

  const client = new Client(clientOptions);

  // Captura o PID do Chrome assim que o Puppeteer o sobe (best effort).
  const captureChromePid = () => {
    if (chromePid) return;
    try {
      const proc = client.pupBrowser && client.pupBrowser.process && client.pupBrowser.process();
      if (proc && proc.pid) {
        chromePid = proc.pid;
        log('INFO', `Chrome iniciado (PID ${chromePid}).`);
      }
    } catch (_) { /* ainda não disponível */ }
  };

  // loading_screen e change_state são OURO p/ diagnosticar o "autenticado mas travado":
  // mostram exatamente em que ponto da sincronização o WhatsApp Web parou.
  client.on('loading_screen', (percent, message) => {
    captureChromePid();
    log('INFO', `Carregando WhatsApp Web: ${percent}% ${message || ''}`.trim());
  });

  client.on('change_state', (state) => {
    log('INFO', `Mudança de estado interno do WhatsApp: ${state}`);
  });

  client.on('qr', (qr) => {
    captureChromePid();
    clientStatus = 'SCAN_QR_CODE';
    currentQr    = qr;
    initError    = null;
    log('INFO', 'QR code disponível — aguardando leitura pelo celular.');
  });

  client.on('authenticated', () => {
    captureChromePid();
    // QR escaneado (ou sessão restaurada): saímos do estado de QR e passamos a cobrar o
    // 'ready' via watchdog. Sem isto o status ficava preso em SCAN_QR_CODE e o watchdog
    // achava que ainda esperava o scan do usuário — re-armando para sempre em vez de
    // reciclar quando a sincronização travava (caso real visto em produção).
    if (clientStatus === 'SCAN_QR_CODE') {
      clientStatus = 'STARTING';
      currentQr    = null;
    }
    log('INFO', 'Sessão autenticada — aguardando sincronização (ready)...');
  });

  client.on('ready', () => {
    clientStatus  = 'WORKING';
    currentQr     = null;
    initError     = null;
    recreateCount = 0;            // sucesso: zera o contador de reciclagens
    clearReadyWatchdog();
    captureChromePid();
    log('INFO', 'WhatsApp conectado e pronto (WORKING).');
  });

  client.on('auth_failure', (msg) => {
    log('ERROR', `Falha de autenticação: ${msg}`);
    clientStatus = 'STOPPED';
    initError    = `Falha de autenticação: ${msg}`;
    clearReadyWatchdog();
    waClient     = null;
  });

  client.on('disconnected', (reason) => {
    log('WARN', `Desconectado: ${reason}`);
    clientStatus = 'STOPPED';
    currentQr    = null;
    clearReadyWatchdog();
    waClient     = null;
    killChrome();
  });

  client.initialize()
    .then(() => {
      captureChromePid();
    })
    .catch((err) => {
      const msg = (err && err.message) || String(err);
      // Chrome deixa lock quando o Node morre com o browser aberto.
      if (msg.includes('browser is already running')) {
        log('WARN', `Chrome travado da sessão anterior: ${msg}`);
        clientStatus = 'STARTING';
        recycleClient('browser já estava rodando (lock órfão)');
        return;
      }
      log('ERROR', `Erro ao inicializar: ${err && err.stack ? err.stack : msg}`);
      clientStatus = 'STOPPED';
      initError    = msg;
      clearReadyWatchdog();
      waClient     = null;
    });

  armReadyWatchdog();
  return client;
}

// ---------------------------------------------------------------------------
// Rotas
// ---------------------------------------------------------------------------

/** GET /ping — healthcheck e negociação de compatibilidade com o AutoToca */
app.get('/ping', (_req, res) => res.json({
  ok: true,
  status: clientStatus,
  pid: process.pid,
  gatewayVersion: GATEWAY_VERSION,
  capabilities: GATEWAY_CAPABILITIES,
}));

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
    log('INFO', 'POST /api/sessions — iniciando sessão.');
    recreateCount = 0;
    clientStatus  = 'STARTING';
    waClient      = createWaClient();
  }
  res.json({ name: SESSION_NAME, status: clientStatus });
});

/** POST /api/sessions/:session/start — (re)inicia a sessão (compat WAHA).
 *  Necessário para o app reerguer uma sessão STOPPED/FAILED sem reiniciar o Toca. */
app.post('/api/sessions/:session/start', (_req, res) => {
  if (!waClient || clientStatus === 'STOPPED') {
    log('INFO', `POST /api/sessions/${SESSION_NAME}/start — (re)iniciando sessão.`);
    recreateCount = 0;
    clientStatus  = 'STARTING';
    currentQr     = null;
    initError     = null;
    waClient      = createWaClient();
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

// Cache curto dos chats já sincronizados. Consultar getChats() para cada contato
// deixa o WhatsApp Update muito lento, mas depender apenas de getChatById(numero@c.us)
// falha nas contas migradas para LID. O cache é renovado entre execuções longas.
let chatsCache = null;
let chatsCacheAt = 0;
const CHATS_CACHE_MS = 60000;

async function getChatsCached() {
  const now = Date.now();
  if (chatsCache && (now - chatsCacheAt) < CHATS_CACHE_MS) return chatsCache;
  chatsCache = await waClient.getChats();
  chatsCacheAt = now;
  log('INFO', `Cache de conversas renovado: ${chatsCache.length} chat(s) disponíveis.`);
  return chatsCache;
}

/** Variantes brasileiras com e sem o 9º dígito, sem registrar o telefone. */
function phoneVariants(digits) {
  const variants = new Set([digits]);
  const withNine = digits.match(/^55(\d{2})9(\d{8})$/);
  if (withNine) variants.add(`55${withNine[1]}${withNine[2]}`);
  const withoutNine = digits.match(/^55(\d{2})(\d{8})$/);
  if (withoutNine) variants.add(`55${withoutNine[1]}9${withoutNine[2]}`);
  return variants;
}

/**
 * Localiza um chat sem depender exclusivamente do WID numérico adivinhado.
 * Retorna também a estratégia para que o log explique como o contato foi casado.
 */
async function findChat(rawChatId) {
  const digits = rawChatId.split('@')[0];
  const variants = phoneVariants(digits);
  let availableChats = 0;

  try {
    const chats = await getChatsCached();
    availableChats = chats.length;
    for (const chat of chats) {
      if (chat.isGroup) continue;
      const user = chat.id && chat.id.user;
      if (user && variants.has(user)) {
        return { chatId: chat.id._serialized, strategy: 'chat-list', availableChats };
      }
    }
  } catch (err) {
    log('WARN', `Busca na lista de chats falhou (${safeError(err)}).`);
  }

  try {
    const numberId = await waClient.getNumberId(digits);
    const wid = numberId && numberId._serialized;
    if (wid) {
      // Não chama getChatById aqui: além de repetir uma ida ao Puppeteer, ele
      // serializa o modelo inteiro do chat. O endpoint abaixo usa o WID resolvido
      // para ler somente as mensagens recentes em uma única avaliação.
      return { chatId: wid, strategy: 'number-id', availableChats };
    }
  } catch (err) {
    log('WARN', `Resolução por number-id falhou (${safeError(err)}).`);
  }

  return { chatId: null, strategy: 'not-found', availableChats };
}

function syncLogTag(req) {
  const raw = String(req.headers['x-toca-sync-id'] || '');
  return /^[a-zA-Z0-9_-]{1,32}$/.test(raw) ? `[sync:${raw}] ` : '';
}

/**
 * Lê apenas o cache recente do chat em uma única chamada ao Puppeteer.
 * Não usa Chat.fetchMessages(limit), pois esse método baixa páginas antigas até
 * preencher o limite solicitado e pode bloquear o Chrome por vários minutos.
 */
async function fetchCachedMessages(chatId, gteTs, lteTs, limit) {
  return await waClient.pupPage.evaluate(
    async ({ chatId, gteTs, lteTs, limit }) => {
      const chat = await window.WWebJS.getChat(chatId, { getAsModel: false });
      if (!chat) return { found: false, cachedCount: 0, historyPages: 0, messages: [] };

      let all = chat.msgs.getModelsArray().filter((msg) => !msg.isNotification);
      let historyPages = 0;
      const maxHistoryPages = 2;

      // Carrega no máximo duas páginas adicionais, somente quando a mensagem
      // mais antiga em cache ainda está dentro do período solicitado. Isso traz
      // contexto suficiente para o resumo sem tentar completar 500 mensagens.
      while (gteTs && all.length && historyPages < maxHistoryPages) {
        const oldestTs = Math.min(...all.map((msg) => Number(msg.t || 0)).filter(Boolean));
        if (!oldestTs || oldestTs <= gteTs) break;
        const loaded = await window
          .require('WAWebChatLoadMessages')
          .loadEarlierMsgs({ chat });
        if (!loaded || !loaded.length) break;
        historyPages += 1;
        const byId = new Map();
        for (const msg of [...loaded, ...all]) {
          if (msg.isNotification) continue;
          const key = msg.id && (msg.id._serialized || msg.id.id);
          if (key) byId.set(key, msg);
        }
        all = [...byId.values()];
      }

      const inPeriod = all
        .filter((msg) => {
          const ts = Number(msg.t || 0);
          return (!gteTs || ts >= gteTs) && (!lteTs || ts <= lteTs);
        })
        .sort((a, b) => Number(a.t || 0) - Number(b.t || 0))
        .slice(-limit);

      const serialized = inPeriod.map((msg) => {
        const id = msg.id || {};
        const serializeWid = (wid) => {
          if (!wid) return '';
          return typeof wid === 'object' ? (wid._serialized || '') : String(wid);
        };
        return {
          id: {
            id: id.id || '',
            fromMe: Boolean(id.fromMe),
            _serialized: id._serialized || '',
          },
          body: msg.directPath
            ? (msg.caption || '')
            : (msg.body || msg.pollName || msg.eventName || ''),
          type: msg.type || '',
          timestamp: Number(msg.t || 0),
          from: serializeWid(msg.from),
          to: serializeWid(msg.to),
          fromMe: Boolean(id.fromMe),
          hasMedia: Boolean(msg.directPath),
        };
      });

      return {
        found: true,
        cachedCount: all.length,
        historyPages,
        messages: serialized,
      };
    },
    { chatId, gteTs, lteTs, limit },
  );
}

/** GET /api/:session/chats/:chatId/messages — mensagens filtradas por timestamp */
app.get('/api/:session/chats/:chatId/messages', async (req, res) => {
  const tag = syncLogTag(req);
  const startedAt = Date.now();

  if (!waClient || clientStatus !== 'WORKING') {
    log('WARN', `${tag}Consulta recusada: sessão em estado ${clientStatus}.`);
    return res.status(503).json({
      error: 'WhatsApp não conectado',
      code: 'SESSION_NOT_WORKING',
      status: clientStatus,
    });
  }

  const { chatId: rawChatId } = req.params;
  const requestedLimit = parseInt(req.query.limit || '500', 10);
  const limit = Math.min(Number.isFinite(requestedLimit) ? Math.max(requestedLimit, 1) : 500, 2000);
  const gteTs = parseInt(req.query['filter.timestamp.gte'] || '0', 10);
  const lteTs = parseInt(req.query['filter.timestamp.lte'] || String(Math.floor(Date.now() / 1000)), 10);

  try {
    const match = await findChat(rawChatId);
    res.setHeader('X-WAHA-Match-Strategy', match.strategy);
    res.setHeader('X-WAHA-Available-Chats', String(match.availableChats));

    if (!match.chatId) {
      log(
        'INFO',
        `${tag}Conversa não localizada; chats disponíveis=${match.availableChats}; ` +
        `estratégia=${match.strategy}; duração=${Date.now() - startedAt}ms.`
      );
      return res.status(404).json({
        error: 'Sem conversa sincronizada para este contato.',
        code: 'CHAT_NOT_FOUND',
        diagnostics: { availableChats: match.availableChats, strategy: match.strategy },
      });
    }

    const result = await fetchCachedMessages(match.chatId, gteTs, lteTs, limit);
    if (!result.found) {
      return res.status(404).json({
        error: 'Conversa registrada, mas não carregada no WhatsApp Web.',
        code: 'CHAT_NOT_LOADED',
      });
    }
    const filtered = result.messages;

    res.setHeader('X-WAHA-Fetched-Messages', String(result.cachedCount));
    res.setHeader('X-WAHA-Filtered-Messages', String(filtered.length));
    res.setHeader('X-WAHA-History-Pages', String(result.historyPages));
    log(
      'INFO',
      `${tag}Consulta concluída: estratégia=${match.strategy}; cache=${result.cachedCount}; ` +
      `páginas_adicionais=${result.historyPages}; no período=${filtered.length}; ` +
      `duração=${Date.now() - startedAt}ms.`
    );
    return res.json(filtered);
  } catch (err) {
    log(
      'ERROR',
      `${tag}Falha ao consultar mensagens (${safeError(err)}); ` +
      `duração=${Date.now() - startedAt}ms.`
    );
    return res.status(500).json({
      error: 'Falha interna ao consultar a conversa.',
      code: 'MESSAGE_LOOKUP_FAILED',
    });
  }
});

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------
const server = app.listen(PORT, '127.0.0.1', async () => {
  log('INFO', '='.repeat(60));
  log('INFO', `WAHA-lite iniciado | Node ${process.version} | ${process.platform}`);
  log('INFO', `Porta: ${PORT} | Sessão: ${SESSION_NAME}`);
  log('INFO', `Data dir: ${DATA_DIR}`);
  log('INFO', '='.repeat(60));
  // Inicia a sessão automaticamente ao subir.
  // Mata Chrome órfão de sessões anteriores antes de tentar inicializar:
  // sem isto o Chrome de uma execução anterior regenera o SingletonLock e
  // bloqueia todas as tentativas com "browser is already running".
  if (!waClient) {
    await killOrphanChrome();
    cleanSessionLocks();
    clientStatus = 'STARTING';
    waClient     = createWaClient();
  }
});

// EADDRINUSE = outra instância já está na porta. Antes isso virava um crash com
// stack trace cru ("Unhandled 'error' event"); agora encerramos limpo para não
// brigar pela porta nem corromper a sessão da instância que já está rodando.
server.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    log('ERROR', `Porta ${PORT} já está em uso — outra instância do WAHA-lite já está ativa. ` +
                 'Encerrando esta instância para não conflitar.');
    process.exit(0);
  }
  log('ERROR', `Erro no servidor HTTP: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});

// Nada deve morrer em silêncio: registra com timestamp em vez de stack trace cru.
process.on('uncaughtException', (err) => {
  log('ERROR', `uncaughtException: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
process.on('unhandledRejection', (reason) => {
  log('ERROR', `unhandledRejection: ${reason && reason.stack ? reason.stack : reason}`);
});

// Graceful shutdown — destrói o cliente (fecha o Chrome) antes de sair.
// Sem isso o Chrome fica órfão e impede reinicializações ("browser is already running").
async function gracefulShutdown(signal) {
  log('INFO', `Recebido ${signal} — encerrando WAHA-lite...`);
  await destroyClient();
  process.exit(0);
}
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT',  () => gracefulShutdown('SIGINT'));
