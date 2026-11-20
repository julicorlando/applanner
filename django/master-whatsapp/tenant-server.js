import http from 'node:http';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import makeWASocket, { DisconnectReason, useMultiFileAuthState } from '@whiskeysockets/baileys';
import pino from 'pino';
import { loggerOptions } from './logging.js';
import QRCode from 'qrcode';

const secret=process.env.MASTER_WHATSAPP_GATEWAY_TOKEN || '';
const callback='http://web:8000/webhooks/tenant-whatsapp/';
const root='/app/session/tenant';
const sessions=new Map();
const sendsInFlight=new Map();
const logger=pino(loggerOptions);
const jidPattern=/^\d{10,20}@(s\.whatsapp\.net|lid)$/;
const phonePattern=/^\d{10,20}$/;
const textOf=m=>m?.conversation || m?.extendedTextMessage?.text || m?.ephemeralMessage?.message?.conversation || '';
const reply=(res,code,data)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
const fileOf=id=>`${root}/${id}/pending.json`;
async function save(session){await fs.mkdir(`${root}/${session.id}`,{recursive:true});await fs.writeFile(fileOf(session.id),JSON.stringify(session.pending),{mode:0o600});}
async function flush(session){
  if(session.flushing || !secret || !session.pending.length)return;
  session.flushing=true;
  try{while(session.pending.length){
    try{
      const response=await fetch(callback,{method:'POST',redirect:'manual',headers:{Authorization:`Bearer ${secret}`,'Content-Type':'application/json',Host:'web:8000','X-Forwarded-Proto':'https'},body:JSON.stringify({tenant_id:session.id,...session.pending[0]}),signal:AbortSignal.timeout(8000)});
      if(!response.ok){session.error=`Django recusou o callback (HTTP ${response.status}).`;break;}
      session.pending.shift();await save(session);session.error='';
    }catch(error){session.error='Sem conexão com o Django para receber respostas.';logger.warn({error,id:session.id},'Tenant callback failed');break;}
  }}finally{session.flushing=false;}
}
async function getSession(id){
  if(!sessions.has(id)){
    let pending=[];try{pending=JSON.parse(await fs.readFile(fileOf(id),'utf8'));if(!Array.isArray(pending))pending=[];}catch{}
    sessions.set(id,{id,pending,state:'disconnected',qr:null,socket:null,timer:null,flushing:false,error:''});
  }
  return sessions.get(id);
}
async function connect(session){
  if(!secret || session.socket || session.state==='connecting')return;
  clearTimeout(session.timer);session.state='connecting';session.qr=null;
  const authDir=`${root}/${session.id}/auth`;
  await fs.mkdir(authDir,{recursive:true});
  const {state,saveCreds}=await useMultiFileAuthState(authDir);
  const socket=makeWASocket({auth:state,logger,printQRInTerminal:false,syncFullHistory:false});
  session.socket=socket;
  socket.ev.on('creds.update',saveCreds);
  socket.ev.on('connection.update',async update=>{
    if(session.socket!==socket)return;
    if(update.qr){session.qr=await QRCode.toDataURL(update.qr,{margin:2,width:320});session.state='qr';}
    if(update.connection==='open'){session.state='connected';session.qr=null;}
    if(update.connection==='close'){
      session.socket=null;session.qr=null;session.state='disconnected';
      const reason=update.lastDisconnect?.error?.output?.statusCode;
      if(reason===DisconnectReason.loggedOut)await fs.rm(authDir,{recursive:true,force:true});
      else session.timer=setTimeout(()=>connect(session).catch(error=>logger.warn({error},'Reconnect failed')),3000);
    }
  });
  socket.ev.on('messages.upsert',async({messages,type})=>{
    if(type!=='notify')return;
    for(const m of messages){
      const from=[m.key?.remoteJidAlt,m.key?.remoteJid].find(j=>jidPattern.test(j||'')&&j.endsWith('@s.whatsapp.net'))||m.key?.remoteJid;
      if(m.key?.fromMe||!jidPattern.test(from||'')||!m.key?.id)continue;
      session.pending.push({from,id:m.key.id,name:m.pushName||'',text:textOf(m.message)});await save(session);
    }
    await flush(session);
  });
  socket.ev.on('messages.update',async updates=>{
    for(const {key,update} of updates){
      const code=Number(update?.status);
      if(!key?.fromMe||!key.id||!jidPattern.test(key.remoteJid||'')||code<3)continue;
      session.pending.push({event:'receipt',to:key.remoteJid,id:key.id,status:code>=4?'read':'delivered'});await save(session);
    }
    await flush(session);
  });
}
http.createServer(async(req,res)=>{
  const supplied=req.headers.authorization||'',expected=`Bearer ${secret}`;
  if(!secret||supplied.length!==expected.length||!crypto.timingSafeEqual(Buffer.from(supplied),Buffer.from(expected)))return reply(res,403,{error:'Acesso negado.'});
  const match=/^\/tenant\/([1-9]\d{0,9})\/(status|connect|disconnect|send)$/.exec(req.url||'');
  if(!match)return reply(res,404,{error:'Rota não encontrada.'});
  const session=await getSession(match[1]);
  try{
    if(req.method==='GET'&&match[2]==='status')return reply(res,200,{state:session.state,qr:session.qr,pending:session.pending.length,callbackError:session.error});
    if(req.method==='POST'&&match[2]==='connect'){await connect(session);return reply(res,200,{state:session.state});}
    if(req.method==='POST'&&match[2]==='disconnect'){
      clearTimeout(session.timer);const active=session.socket;session.socket=null;session.state='disconnected';session.qr=null;
      if(active)await active.logout().catch(()=>{});
      await fs.rm(`${root}/${session.id}/auth`,{recursive:true,force:true});return reply(res,200,{state:session.state});
    }
    if(req.method==='POST'&&match[2]==='send'){
      if(session.state!=='connected'||!session.socket)return reply(res,409,{error:'Conecte o WhatsApp antes de enviar.'});
      let body='';for await(const chunk of req){body+=chunk;if(body.length>8192)return reply(res,413,{error:'Mensagem muito longa.'});}
      const data=JSON.parse(body),to=String(data.to||'');
      const jid=jidPattern.test(to)?to:phonePattern.test(to)?`${to}@s.whatsapp.net`:'';
      if(!jid||typeof data.text!=='string'||!data.text.trim()||data.text.length>4096)return reply(res,400,{error:'Destinatário ou texto inválido.'});
      const key=data.idempotencyKey;
      if(key!==undefined&&(typeof key!=='string'||!/^[a-zA-Z0-9_-]{1,120}$/.test(key)))return reply(res,400,{error:'Chave de envio inválida.'});
      const hash=key?crypto.createHash('sha256').update(`${session.id}:${key}`).digest('hex'):'';
      const digest=crypto.createHash('sha256').update(JSON.stringify({to:jid,text:data.text})).digest('hex');
      const send=async()=>{
        const directory=`${root}/${session.id}/flow-receipts`,filename=key?`${directory}/${hash}.json`:'';
        if(filename){try{
          const saved=JSON.parse(await fs.readFile(filename,'utf8'));
          if(saved.digest!==digest)throw new Error('Chave reutilizada com conteúdo diferente.');
          return saved.result;
        }catch(error){if(error.code!=='ENOENT')throw error;}}
        let recipient=jid;
        if(jid.endsWith('@s.whatsapp.net')){
          const [found]=await session.socket.onWhatsApp(jid);
          if(!found?.exists)throw new Error('Número não encontrado no WhatsApp.');
          recipient=found.jid||jid;
        }
        const sent=await session.socket.sendMessage(recipient,{text:data.text},key?{messageId:hash.slice(0,32).toUpperCase()}:undefined);
        if(!sent?.key?.id)throw new Error('Envio não confirmado.');
        const result={id:sent.key.id,to:recipient};
        if(filename){
          await fs.mkdir(directory,{recursive:true,mode:0o700});
          const temp=filename+'.'+crypto.randomUUID()+'.tmp';
          await fs.writeFile(temp,JSON.stringify({digest,result}),{mode:0o600});await fs.rename(temp,filename);
        }
        return result;
      };
      if(!key)return reply(res,200,await send());
      if(sendsInFlight.has(hash)){
        const active=sendsInFlight.get(hash);
        if(active.digest!==digest)throw new Error('Chave reutilizada com conteúdo diferente.');
        return reply(res,200,await active.promise);
      }
      const promise=send();sendsInFlight.set(hash,{digest,promise});
      try{return reply(res,200,await promise);}finally{sendsInFlight.delete(hash);}
    }
    return reply(res,405,{error:'Método não permitido.'});
  }catch(error){logger.error({error,id:session.id},'Tenant gateway error');return reply(res,503,{error:'WhatsApp indisponível no momento.'});}
}).listen(3100,'0.0.0.0');
try{for(const id of await fs.readdir(root)){if(!/^\d+$/.test(id))continue;const session=await getSession(id);try{await fs.access(`${root}/${id}/auth/creds.json`);await connect(session);}catch{}}}catch{}
setInterval(()=>{for(const session of sessions.values())flush(session).catch(()=>{});},5000).unref();
