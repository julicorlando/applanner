"""Versioned, bounded flow graphs. No executable code or secrets in the graph."""
import json
import math
import re
from django.core.exceptions import ValidationError

TYPES={'start','message','menu','input','condition','set','api','ai','wait','handoff','finish','legacy','knowledge','commercial'}
NAME=re.compile(r'^[a-z][a-z0-9_]{0,39}$')
ID=re.compile(r'^[a-z][a-z0-9_-]{0,59}$')

def variable(value):
    if not isinstance(value,str) or not NAME.fullmatch(value):
        raise ValidationError('Use uma variável com letras minúsculas, números e _.')
    return value

def validate_graph(graph):
    if not isinstance(graph,dict) or graph.get('version')!=2:
        raise ValidationError('Formato de fluxo inválido.')
    if len(json.dumps(graph))>150000:
        raise ValidationError('O fluxo excede o tamanho permitido.')
    nodes=graph.get('nodes')
    if not isinstance(nodes,list) or not 1<=len(nodes)<=80:
        raise ValidationError('O fluxo precisa ter de 1 a 80 blocos.')
    ids=set()
    for node in nodes:
        if not isinstance(node,dict) or not ID.fullmatch(str(node.get('id',''))) or node['id'] in ids:
            raise ValidationError('Cada bloco precisa de um identificador exclusivo e válido.')
        ids.add(node['id'])
        if node.get('type') not in TYPES:raise ValidationError('Tipo de bloco não reconhecido.')
        if not isinstance(node.get('label',''),str) or len(node.get('label',''))>80:raise ValidationError('Nome do bloco inválido.')
        for k in ('x','y'):
            value=node.get(k,0)
            if type(value) not in (float,int) or not math.isfinite(value) or not 0<=value<=6000:raise ValidationError('Posição do bloco inválida.')
        config=node.get('config',{})
        outputs=node.get('outputs',{})
        if not isinstance(config,dict) or not isinstance(outputs,dict) or len(outputs)>12:raise ValidationError('Configuração do bloco inválida.')
        if any(not isinstance(k,str) or not ID.fullmatch(k) or not isinstance(v,str) for k,v in outputs.items()):raise ValidationError('Conexão inválida.')
        if any(k.lower() in {'token','password','secret','api_key','authorization','headers','code'} for k in config):raise ValidationError('Credenciais e código não podem ser armazenados nos blocos.')
        for k in ('text','prompt','value','path','body','expected'):
            if k in config and (not isinstance(config[k],str) or len(config[k])>4000):raise ValidationError('Texto do bloco muito longo ou inválido.')
        kind=node['type']
        if kind in {'input','set','api','ai'}:variable(config.get('variable',''))
        if kind=='ai' and 'applanner_only' in config and type(config['applanner_only']) is not bool:raise ValidationError('A restrição ApPlanner deve ser ativada ou desativada.')
        if kind=='input' and config.get('validation','text') not in {'text','email','phone','number'}:raise ValidationError('Validação de entrada inválida.')
        if kind=='knowledge' and (not isinstance(config.get('variable'),str) or not re.fullmatch(r'[a-z_][a-z0-9_]{0,39}',config['variable'])):raise ValidationError('Variável da pergunta inválida.')
        if kind=='condition':
            if not isinstance(config.get('variable'),str) or not re.fullmatch(r'[a-z_][a-z0-9_.]{0,99}',config['variable']):raise ValidationError('Variável da condição inválida.')
            if config.get('operator') not in {'equals','contains','exists','gt','lt'}:raise ValidationError('Operador inválido.')
        if kind=='api':
            if not ID.fullmatch(config.get('integration','')):raise ValidationError('Selecione uma integração cadastrada.')
            if config.get('method','GET') not in {'GET','POST'}:raise ValidationError('Use GET ou POST.')
            if not config.get('path','/').startswith('/') or config.get('path','/').startswith('//') or any(c in config.get('path','/') for c in '\r\n\\'):raise ValidationError('Caminho da API inválido.')
            if config.get('body'):
                try:json.loads(config['body'])
                except (ValueError,TypeError):raise ValidationError('O corpo da API deve ser JSON válido; use variáveis dentro de strings.')
        if kind=='wait' and (type(config.get('seconds')) is not int or not 1<=config['seconds']<=86400):raise ValidationError('A espera deve ter de 1 a 86400 segundos.')
        if kind=='menu':
            options=config.get('options',[])
            if not isinstance(options,list) or not 1<=len(options)<=10:raise ValidationError('O menu precisa ter de 1 a 10 opções.')
            option_ids=set()
            for option in options:
                if not isinstance(option,dict) or not ID.fullmatch(str(option.get('id',''))) or option['id'] in option_ids:raise ValidationError('Opção de menu inválida.')
                option_ids.add(option['id'])
                if not isinstance(option.get('label'),str) or not 1<=len(option['label'])<=100:raise ValidationError('Nome da opção inválido.')
                words=option.get('keywords',[])
                if not isinstance(words,list) or len(words)>10 or any(not isinstance(w,str) or not 1<=len(w)<=60 for w in words):raise ValidationError('Palavras da opção inválidas.')
        if kind=='legacy' and (not isinstance(config.get('keywords',[]),list) or any(not isinstance(k,str) or len(k)>60 for k in config.get('keywords',[]))):raise ValidationError('Palavras inválidas.')
        allowed=({'next'} if kind=='start' else {'next','error'} if kind in {'message','set','api','ai','input','wait','legacy','knowledge','commercial'} else {'yes','no'} if kind=='condition' else {o['id'] for o in config['options']}|{'invalid'} if kind=='menu' else set())
        if set(outputs)-allowed:raise ValidationError('Saída incompatível com o bloco.')
        if kind=='start' and not outputs.get('next'):raise ValidationError('Conecte o início a um bloco.')
    if graph.get('start') not in ids or sum(n['type']=='start' for n in nodes)!=1 or next(n for n in nodes if n['id']==graph['start'])['type']!='start':raise ValidationError('Defina um único bloco inicial.')
    if any(target and target not in ids for node in nodes for target in node.get('outputs',{}).values()):raise ValidationError('Uma conexão aponta para um bloco inexistente.')
    by_id={n['id']:n for n in nodes}
    # Automatic cycles would flood messages or repeatedly call an external API.
    checked=set()
    def visit(key,path):
        if not key or by_id[key]['type'] in {'input','menu','wait','legacy','handoff','finish','commercial'}:return
        if key in path:raise ValidationError('Há um ciclo sem espera ou entrada do cliente.')
        if key in checked:return
        for target in by_id[key].get('outputs',{}).values():visit(target,path|{key})
        checked.add(key)
    for key in ids:visit(key,set())
    return graph

def legacy_graph(flow):
    nodes=[{'id':'start','type':'start','label':'Início','x':600,'y':40,'config':{'text':flow.greeting},'outputs':{'next':'inicio'}}]
    for i,s in enumerate(flow.steps or []):
        p=s.get('position') or {}
        kind='legacy'
        nodes.append({'id':s['id'],'type':kind,'label':s['id'],'x':p.get('x',400+(i%3)*350),'y':p.get('y',250+(i//3)*300),'config':{'text':s.get('reply',''),'keywords':s.get('keywords',[]),'handoff':s.get('handoff',False),'finish':s.get('finish',False)},'outputs':{'next':s.get('next','')}})
    if not flow.steps:
        nodes.append({'id':'inicio','type':'menu','label':'Como podemos ajudar?','x':600,'y':250,'config':{'text':'Escolha uma opção:','options':[{'id':'option_1','label':'Conhecer os planos','keywords':['1','planos']},{'id':'option_2','label':'Falar com atendente','keywords':['2','atendimento']}]},'outputs':{'option_1':'planos','option_2':'equipe'}})
        nodes.append({'id':'planos','type':'message','label':'Planos','x':350,'y':550,'config':{'text':'Conte qual é o segmento da sua empresa. Nossa equipe ajudará a escolher o plano.'},'outputs':{'next':'equipe'}})
        nodes.append({'id':'equipe','type':'handoff','label':'Atendimento humano','x':850,'y':550,'config':{'text':flow.handoff},'outputs':{}})
    return {'version':2,'start':'start','nodes':nodes}
