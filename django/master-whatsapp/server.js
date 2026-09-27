import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import makeWASocket, { DisconnectReason, useMultiFileAuthState } from '@whiskeysockets/baileys';
import pino from 'pino';
import QRCode from 'qrcode';

const secret = process.env.MASTER_WHATSAPP_GATEWAY_TOKEN || '';
const callback = process.env.MASTER_WHATSAPP_CALLBACK_URL || '';
const directory = '/app/session/auth';
const pendingFile = '/app/session/pending.json';
let socket;
let state = 'disconnected';
let qr = null;
let reconnect;
let pending = [];
const logger = pino({ level: 'warn' });

async function flush() {
  if (!callback || !secret || !pending.length) return;
  while (pending.length) {
    try {
      const response = await fetch(callback, {
        method: 'POST', headers: {'Content-Type': 'application/json', Authorization: `Bearer ${secret}`},
        body: JSON.stringify(pending[0]), signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) break;
      pending.shift();
      await fs.writeFile(pendingFile, JSON.stringify(pending), { mode: 0o600 });
    } catch { break; }
  }
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
      const from = msg.key?.remoteJid;
      if (msg.key?.fromMe || !/^\d{10,15}@s\.whatsapp\.net$/.test(from || '') || !msg.key?.id) continue;
      pending.push({ from, id: msg.key.id, name: msg.pushName || '', text: msg.message?.conversation || msg.message?.extendedTextMessage?.text || '' });
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
    if (req.method === 'GET' && req.url === '/status') return reply(res, 200, { state, qr });
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
        if (raw.length > 10000) return reply(res, 413, { error: 'Mensagem muito longa.' });
      }
      const data = JSON.parse(raw);
      if (!/^\d{10,15}@s\.whatsapp\.net$/.test(data.to || '') || !data.text || data.text.length > 4096) {
        return reply(res, 400, { error: 'Destinatário ou mensagem inválidos.' });
      }
      const message = await socket.sendMessage(data.to, { text: data.text });
      return reply(res, 200, { id: message.key.id });
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
