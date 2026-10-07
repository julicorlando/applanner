"""Deterministic runner shared by real conversations and the no-side-effect simulator."""
from datetime import timedelta
from decimal import Decimal,InvalidOperation
import re
import unicodedata
from django.utils import timezone
from .master_integrations import call_api,call_ai


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold()) if not unicodedata.combining(c)).strip()


def lookup(variables,path):
    value=variables
    for part in path.split('.'):
        if isinstance(value,dict):value=value.get(part,'')
        elif isinstance(value,list) and part.isdigit() and int(part)<len(value):value=value[int(part)]
        else:return ''
    return value


def expand(value,variables):
    return re.sub(r'\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}',lambda m:str(lookup(variables,m[1]))[:4000 if m[1]=='public_plans' else 2000],str(value))[:4000]


def expand_json(value,variables):
    if isinstance(value,str):return expand(value,variables)
    if isinstance(value,list):return [expand_json(v,variables) for v in value]
    if isinstance(value,dict):return {k:expand_json(v,variables) for k,v in value.items()}
    return value


def condition(config,variables):
    value=lookup(variables,config['variable']);expected=expand(config.get('expected',''),variables);op=config['operator']
    if op=='exists':return value not in ('',None,[],{})
    if op=='equals':return normalized(value)==normalized(expected)
    if op=='contains':return normalized(expected) in normalized(value)
    try:
        left,right=Decimal(str(value)),Decimal(expected)
        return left.is_finite() and right.is_finite() and (left>right if op=='gt' else left<right)
    except (ValueError,InvalidOperation):return False


def valid_input(value,kind):
    if kind=='email':
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        try:validate_email(value)
        except ValidationError:return False
    if kind=='phone' and not 10<=len(re.sub(r'\D','',value))<=15:return False
    if kind=='number':
        try:
            if not Decimal(value.replace(',','.')).is_finite():return False
        except InvalidOperation:return False
    return bool(value.strip()) and len(value)<=2000


def run_graph(graph,flow,state,context,waiting,incoming,*,resume=False,simulation=False,event_key='',knowledge_handler=None,ai_handler=None,intake_handler=None):
    nodes={n['id']:n for n in graph['nodes']};variables=dict(context.get('variables',{}))
    variables['_message']=incoming[:2000]
    messages=[];trace=[];wake=None;handoff=False;error='';external=0
    state=state if state in nodes else graph['start']
    def say(text):
        if len(messages)>=8:raise ValueError('Limite de mensagens por execução atingido.')
        value=expand(text,variables)
        if value.strip():messages.append(value)
    if waiting=='wait':
        if not resume:return {'state':state,'context':{'variables':variables},'waiting':waiting,'messages':[],'trace':[],'wake_seconds':None,'handoff':False,'error':''}
        state=nodes[state].get('outputs',{}).get('next','');waiting=''
    elif waiting=='commercial':
        from .master_sales import sales_turn
        variables,replies,done=(intake_handler or sales_turn)(variables,incoming)
        for reply in replies:say(reply)
        if done:state=nodes[state].get('outputs',{}).get('next','');waiting=''
    elif waiting in {'menu','input','legacy'}:
        node=nodes[state];cfg=node.get('config',{});outputs=node.get('outputs',{})
        if waiting=='menu':
            match=next((o for i,o in enumerate(cfg['options'],1) if normalized(incoming) in [normalized(w) for w in o.get('keywords',[])+[o['label'],str(i)]]),None)
            if not match:
                if outputs.get('invalid'):state=outputs['invalid'];waiting=''
                else:say('Escolha uma das opções do menu.');return {'state':state,'context':{'variables':variables},'waiting':waiting,'messages':messages,'trace':[{'node':state,'result':'opção inválida'}],'wake_seconds':None,'handoff':False,'error':''}
            else:variables['choice']=match['label'];state=outputs.get(match['id'],'');waiting=''
        elif waiting=='input':
            if not valid_input(incoming,cfg.get('validation','text')):
                say(cfg.get('invalid_text','O dado informado é inválido. Tente novamente.'))
                return {'state':state,'context':{'variables':variables},'waiting':waiting,'messages':messages,'trace':[{'node':state,'result':'entrada inválida'}],'wake_seconds':None,'handoff':False,'error':''}
            variables[cfg['variable']]=incoming[:2000].replace(',','.') if cfg.get('validation')=='number' else incoming[:2000];state=outputs.get('next','');waiting=''
        else:
            if not any(normalized(k) in normalized(incoming) for k in cfg.get('keywords',[])):
                say(flow.fallback);return {'state':state,'context':{'variables':variables},'waiting':waiting,'messages':messages,'trace':[],'wake_seconds':None,'handoff':False,'error':''}
            say(cfg.get('text',''))
            if cfg.get('handoff'):handoff=True;state=''
            elif cfg.get('finish'):state=''
            else:state=outputs.get('next') or node['id']
            waiting=''
            # Legacy transitions wait for another inbound message, exactly as before.
            if state in nodes and nodes[state]['type']=='legacy':waiting='legacy'
    for index in range(24):
        if not state or waiting:break
        node=nodes[state];kind=node['type'];cfg=node.get('config',{});out=node.get('outputs',{})
        trace.append({'node':state,'type':kind,'result':'executado'})
        try:
            if kind in {'start','message'}:say(cfg.get('text',''));state=out.get('next','')
            elif kind=='menu':
                say(cfg.get('text','')+'\n'+'\n'.join(f'{i}. '+o['label'] for i,o in enumerate(cfg['options'],1)));waiting='menu'
            elif kind=='input':say(cfg.get('text','Informe o dado solicitado.'));waiting='input'
            elif kind=='legacy':waiting='legacy'
            elif kind=='knowledge':
                from .master_sales import answer_question
                say((knowledge_handler or answer_question)(variables.get(cfg['variable'],incoming)));state=out.get('next','')
            elif kind=='commercial':
                from .master_sales import sales_turn
                variables,replies,done=(intake_handler or sales_turn)(variables,incoming,first=True)
                for reply in replies:say(reply)
                if done:state=out.get('next','')
                else:waiting='commercial'
            elif kind=='set':variables[cfg['variable']]=expand(cfg.get('value',''),variables);state=out.get('next','')
            elif kind=='condition':state=out.get('yes' if condition(cfg,variables) else 'no','')
            elif kind in {'api','ai'}:
                external+=1
                if external>3:raise ValueError('Limite de integrações por execução atingido.')
                if simulation:
                    value={'simulated':True,'result':'Resposta simulada'} if kind=='api' else 'Resposta simulada da IA.'
                    trace[-1]['result']='simulado, sem chamada externa'
                elif kind=='api':value=call_api(flow,node,variables,f'flow-{event_key}-{node["id"]}-{index}')
                elif ai_handler:value=ai_handler(flow,node,variables,incoming)
                elif cfg.get('applanner_only'):
                    from .master_assistant import grounded_answer
                    value=grounded_answer(flow,node,variables,incoming)
                else:value=call_ai(flow,node,variables,incoming)
                variables[cfg['variable']]=value
                if kind=='ai' and cfg.get('send_output',True):say(value)
                state=out.get('next','')
            elif kind=='wait':waiting='wait';wake=cfg['seconds']
            elif kind=='handoff':say(cfg.get('text') or flow.handoff);handoff=True;state=''
            elif kind=='finish':say(cfg.get('text','Obrigado pelo contato!'));state=''
        except Exception as exc:
            # Never echo secrets, network response bodies or exception details.
            error='Falha no bloco '+node['id']+' ('+type(exc).__name__+').'
            trace[-1]['result']=error
            state=out.get('error','')
            if not state:
                handoff=True
                if len(messages)<8:say(flow.handoff)
    else:
        error='O fluxo excedeu 24 blocos nesta execução.';handoff=True;state=''
    return {'state':state or '__finished__','context':{'variables':variables},'waiting':waiting,'messages':messages,'trace':trace,'wake_seconds':wake,'handoff':handoff,'error':error}
