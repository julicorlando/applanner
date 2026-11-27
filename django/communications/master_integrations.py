"""Public HTTPS only, pinned DNS, bounded responses and encrypted credentials."""
import ipaddress
import json
import socket
from urllib.parse import urlsplit
import certifi
import urllib3
from django.core.exceptions import ValidationError
from core.crypto import decrypt_json,decrypt_text


def public_endpoint(value,resolve=True):
    parsed=urlsplit(value)
    try:port=parsed.port
    except ValueError:raise ValidationError('Porta da API inválida.')
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or port not in (None,443) or parsed.fragment:
        raise ValidationError('Use uma API pública com HTTPS na porta 443, sem credenciais na URL.')
    host=parsed.hostname.encode('idna').decode()
    if host in {'localhost','metadata.google.internal'} or host.endswith(('.localhost','.local','.internal')):
        raise ValidationError('Endereços internos não são permitidos.')
    try:literal=ipaddress.ip_address(host)
    except ValueError:literal=None
    if literal is not None and not literal.is_global:raise ValidationError('Endereços internos não são permitidos.')
    if not resolve:return parsed,host,None
    try:addresses={item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
    except OSError:raise ValidationError('Não foi possível resolver o endereço da API.') from None
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValidationError('A API deve resolver apenas para endereços públicos.')
    return parsed,host,sorted(addresses)[0]


def request_json(url,method,body=None,token='',idempotency_key=''):
    parsed,host,address=public_endpoint(url)
    headers={'Host':host,'Accept':'application/json','Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    if idempotency_key:headers['X-Idempotency-Key']=idempotency_key
    payload=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    if payload and len(payload)>20000:raise ValueError('Corpo da API muito grande.')
    pool=urllib3.HTTPSConnectionPool(address,port=443,assert_hostname=host,server_hostname=host,
        cert_reqs='CERT_REQUIRED',ca_certs=certifi.where(),timeout=urllib3.Timeout(connect=5,read=12),maxsize=1)
    response=None
    try:
        response=pool.request(method,parsed.path or '/' if not parsed.query else (parsed.path or '/')+'?'+parsed.query,
            body=payload,headers=headers,redirect=False,retries=False,preload_content=False)
        if not 200<=response.status<300:raise ValueError('A API recusou a chamada (HTTP '+str(response.status)+').')
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Resposta da API excede 64 KB.')
        return json.loads(raw.decode())
    except (urllib3.exceptions.HTTPError,UnicodeError,json.JSONDecodeError):
        raise ValueError('Não foi possível obter uma resposta JSON válida da API.') from None
    finally:
        if response:response.close()
        pool.close()


def integrations(flow):
    return decrypt_json(flow.integrations_encrypted).get('items',[]) if flow.integrations_encrypted else []


def call_api(flow,node,variables,key):
    from .master_runtime import expand,expand_json
    config=node['config'];item=next((i for i in integrations(flow) if i['name']==config['integration'] and i.get('enabled')),None)
    if not item:raise ValueError('Integração não configurada ou desativada.')
    path=expand(config.get('path','/'),variables)
    if not path.startswith('/') or path.startswith('//') or any(c in path for c in '\r\n\\'):raise ValueError('Caminho inválido.')
    url=item['url'].rstrip('/')+path
    body=expand_json(json.loads(config['body']),variables) if config.get('body') else None
    return request_json(url,config.get('method','GET'),body,item.get('token',''),key)


def call_ai(flow,node,variables,incoming):
    from .master_runtime import expand
    if not flow.ai_enabled or not flow.ai_key_encrypted or not flow.ai_model:
        raise ValueError('Configure a chave, o modelo e habilite a IA no Master.')
    result=request_json('https://api.openai.com/v1/chat/completions','POST',{
        'model':flow.ai_model,'messages':[{'role':'system','content':expand(node['config'].get('prompt','Responda de forma breve em português.'),variables)},
        {'role':'user','content':incoming[:2000] or 'Continue o atendimento conforme as instruções.'}],
        'max_completion_tokens':600,'store':False},decrypt_text(flow.ai_key_encrypted))
    try:text=result['choices'][0]['message']['content']
    except (KeyError,IndexError,TypeError):raise ValueError('A IA não retornou texto.') from None
    if not isinstance(text,str) or not text.strip():raise ValueError('A IA não retornou texto.')
    return text[:4000]
