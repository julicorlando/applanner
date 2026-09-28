import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import makeWASocket, { DisconnectReason, useMultiFileAuthState } from '@whiskeysockets/baileys';
import pino from 'pino';
import QRCode from 'qrcode';

const secret = process.env.MASTER_WHATSAPP_GATEWAY_TOKEN || '';
const callback = process.env.MASTER_WHATSAPP_CALLBACK_URL || '';
let callbackHost = '';
try {
  const target = new URL(callback);
  // Prevent posting the internal bearer token to a public or unexpected host.
  if (target.protocol === 'http:' && target.hostname === 'web' && target.port === '8000') callbackHost = target.host;
} catch { /* reported in status */ }
const directory = '/app/session/auth';
const pendingFile = '/app/session/pending.json';
let socket;
let state = 'disconnected';
let qr = null;
let reconnect;
let pending = [];
let callbackError = '';
let flushing = false;
const logger = pino({ level: 'warn' });
const contactJid = /^\d{10,20}@(s\.whatsapp\.net|lid)$/;

function inboundText(message) {
  const content = message?.ephemeralMessage?.message || message?.viewOnceMessageV2?.message || message || {};
  return content.conversation || content.extendedTextMessage?.text ||
    content.imageMessage?.caption || content.videoMessage?.caption ||
    content.documentMessage?.caption || content.documentWithCaptionMessage?.message?.documentMessage?.caption ||
    (content.imageMessage ? '[Imagem recebida no WhatsApp]' : '') ||
    (content.audioMessage ? '[Áudio recebido no WhatsApp]' : '') ||
    (content.documentMessage ? '[Documento recebido no WhatsApp]' : '') ||
    (content.videoMessage ? '[Vídeo recebido no WhatsApp]' : '');
}

async function flush() {
  if (flushing || !callback || !secret || !callbackHost || !pending.length) return;
  flushing = true;
  try { while (pending.length) {
    try {
      const response = await fetch(callback, {
        method: 'POST', redirect: 'manual', headers: {
          'Content-Type': 'application/json', Authorization: `Bearer ${secret}`,
          Host: callbackHost, 'X-Forwarded-Proto': 'https',
        },
        body: JSON.stringify(pending[0]), signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) {
        const contentType = response.headers.get('content-type') || '';
        let detail = '';
        if (contentType.includes('application/json')) {
          try { detail = String((await response.json()).error || '').slice(0, 180); } catch { /* status still available */ }
        }
        callbackError = response.status === 400 && !detail
          ? `O Django respondeu HTTP 400 antes de processar o callback (${callbackHost}). Confira os logs do serviço web no Coolify para identificar a recusa.`
          : `O Django recusou o callback (HTTP ${response.status}). ${detail}`.trim();
        logger.warn({ status: response.status, detail, event: pending[0]?.event || 'message' }, 'Master WhatsApp callback rejected');
        break;
      }
      pending.shift();
      await fs.writeFile(pendingFile, JSON.stringify(pending), { mode: 0o600 });
      callbackError = '';
    } catch (error) { callbackError = 'Sem conexão com o Django para receber respostas.'; logger.warn({ error }, 'Master WhatsApp callback failed'); break; }
  } } finally { flushing = false; }
}

async function connect() {
  if (socket || state === 'connecting' || !secret) return;
  clearTimeout(reconnect);
  state = 'connecting';
  qr = null;
  const { state: auth, saveCreds } = await useMultiFileAuthState(directory);
  const client = makeWASocket({ auth, logger, printQRInTerminal: false, syncFullHistory: false });
  socket = client;
  client.ev.on('creds.update', saveCreds);
  client.ev.on('connection.update', async update => {
    if (socket !== client) return;
    if (update.qr) {
      qr = await QRCode.toDataURL(update.qr, { margin: 2, width: 320 });
      state = 'qr';
    }
    if (update.connection === 'open') { state = 'connected'; qr = null; }
    if (update.connection === 'close') {
      socket = undefined;
      qr = null;
      state = 'disconnected';
      const reason = update.lastDisconnect?.error?.output?.statusCode;
      if (reason === DisconnectReason.loggedOut) await fs.rm(directory, { recursive: true, force: true });
      else reconnect = setTimeout(() => connect().catch(() => { state = 'disconnected'; }), 3000);
    }
  });
  client.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      const from = [msg.key?.remoteJidAlt, msg.key?.remoteJid].find(jid => contactJid.test(jid || '') && jid.endsWith('@s.whatsapp.net'))
        || msg.key?.remoteJid;
      if (msg.key?.fromMe || !contactJid.test(from || '') || !msg.key?.id) continue;
      pending.push({ from, id: msg.key.id, name: msg.pushName || '', text: inboundText(msg.message) });
      await fs.writeFile(pendingFile, JSON.stringify(pending), { mode: 0o600 });
    }
    await flush();
  });
  client.ev.on('messages.update', async updates => {
    for (const { key, update } of updates) {
      const code = Number(update?.status);
      if (!key?.fromMe || !key.id || !contactJid.test(key.remoteJid || '') || code < 3) continue;
      const status = code >= 4 ? 'read' : 'delivered';
      pending.push({ event: 'receipt', to: key.remoteJid, id: key.id, status });
      await fs.writeFile(pendingFile, JSON.stringify(pending), { mode: 0o600 });
    }
    await flush();
  });
}

function reply(res, status, data) {
  res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  res.end(JSON.stringify(data));
}

http.createServer(async (req, res) => {
  const supplied = req.headers.authorization || '';
  const expected = `Bearer ${secret}`;
  if (!secret || supplied.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))) {
    return reply(res, 403, { error: 'Acesso negado.' });
  }
  try {
    if (req.method === 'GET' && req.url === '/status') return reply(res, 200, {
      state, qr, pending: pending.length,
      callbackError: callbackHost ? callbackError : 'O callback interno precisa apontar para web:8000 no Compose.',
    });
    if (req.method === 'POST' && req.url === '/connect') {
      await connect();
      return reply(res, 200, { state });
    }
    if (req.method === 'POST' && req.url === '/disconnect') {
      clearTimeout(reconnect);
      const active = socket;
      socket = undefined;
      state = 'disconnected'; qr = null;
      if (active) await active.logout().catch(() => {});
      await fs.rm(directory, { recursive: true, force: true });
      return reply(res, 200, { state });
    }
    if (req.method === 'POST' && req.url === '/send') {
      if (state !== 'connected' || !socket) return reply(res, 409, { error: 'Conecte o WhatsApp antes de enviar.' });
      let raw = '';
      for await (const chunk of req) {
        raw += chunk;
        if (raw.length > 8 * 1024 * 1024) return reply(res, 413, { error: 'Arquivo muito grande.' });
      }
      const data = JSON.parse(raw);
      if (!contactJid.test(data.to || '') || typeof data.text !== 'string' || data.text.length > 4096 || (!data.text.trim() && !data.file)) {
        return reply(res, 400, { error: 'Destinatário ou mensagem inválidos.' });
      }
      let content = { text: data.text };
      if (data.file) {
        const file = data.file;
        if (typeof file.base64 !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(file.base64) ||
            !['image/png', 'image/jpeg', 'image/webp', 'application/pdf'].includes(file.mime) ||
            typeof file.name !== 'string' || file.name.length > 120) {
          return reply(res, 400, { error: 'Tipo de anexo inválido.' });
        }
        const media = Buffer.from(file.base64, 'base64');
        if (!media.length || media.length > 5 * 1024 * 1024) return reply(res, 413, { error: 'Arquivo muito grande.' });
        if (file.mime === 'application/pdf') {
          if (media.subarray(0, 5).toString() !== '%PDF-') return reply(res, 400, { error: 'PDF inválido.' });
          content = { document: media, mimetype: file.mime, fileName: file.name };
        } else {
          if (file.mime === 'image/png' && !media.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex')) ||
              file.mime === 'image/jpeg' && !media.subarray(0, 3).equals(Buffer.from('ffd8ff', 'hex')) ||
              file.mime === 'image/webp' && media.subarray(8, 12).toString() !== 'WEBP') {
            return reply(res, 400, { error: 'Imagem inválida.' });
          }
          content = { image: media, mimetype: file.mime };
        }
        if (data.text.trim()) content.caption = data.text;
      }
      let recipient = data.to;
      if (recipient.endsWith('@s.whatsapp.net')) {
        const [found] = await socket.onWhatsApp(recipient);
        if (!found?.exists) return reply(res, 404, { error: 'Este número não foi encontrado no WhatsApp. Confira DDD e código do país.' });
        recipient = found.jid || recipient;
      }
      const message = await socket.sendMessage(recipient, content);
      if (!message?.key?.id) return reply(res, 503, { error: 'O WhatsApp não confirmou o envio. Tente novamente.' });
      return reply(res, 200, { id: message.key.id, to: recipient });
    }
    return reply(res, 404, { error: 'Rota não encontrada.' });
  } catch (error) {
    logger.error({ error }, 'Gateway error');
    return reply(res, 503, { error: 'Não foi possível acessar o WhatsApp agora.' });
  }
}).listen(3100, '0.0.0.0');

try { pending = JSON.parse(await fs.readFile(pendingFile, 'utf8')); } catch { pending = []; }
setInterval(() => flush().catch(() => {}), 5000).unref();
try { await fs.access(path.join(directory, 'creds.json')); await connect(); } catch { state = 'disconnected'; }
