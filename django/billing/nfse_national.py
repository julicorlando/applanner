"""MEI DPS 1.01, signed locally; only fixed national government HTTPS hosts."""
import base64
import gzip
import io
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from functools import lru_cache
from decimal import Decimal

import requests
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from django.utils import timezone
from lxml import etree
from signxml import XMLSigner, methods
from core.crypto import decrypt_text

NS='http://www.sped.fazenda.gov.br/nfse'
MAX_XML=5*1024*1024
SCHEMA=Path(__file__).parent/'nfse_schemas'/'DPS_v1.01.xsd'
SEFIN={'production':'https://sefin.nfse.gov.br/SefinNacional','homologation':'https://sefin.producaorestrita.nfse.gov.br/SefinNacional'}

class SchemaResolver(etree.Resolver):
    def resolve(self,url,public_id,context):
        if Path(url).name=='tiposSimples_v1.01.xsd':
            # The official series facet contains PCRE anchors, literal in XSD regex.
            # Keep the downloaded files intact; normalize only this known facet in memory.
            raw=(SCHEMA.parent/'tiposSimples_v1.01.xsd').read_bytes()
            raw=raw.replace(b'value="^0{0,4}\\d{1,5}$"',b'value="0{0,4}\\d{1,5}"')
            return self.resolve_string(raw,context,base_url=str(SCHEMA.parent/'tiposSimples_v1.01.xsd'))
        return None


@lru_cache(maxsize=1)
def dps_schema():
    parser=etree.XMLParser(resolve_entities=False,no_network=True)
    parser.resolvers.add(SchemaResolver())
    return etree.XMLSchema(etree.parse(str(SCHEMA),parser))


class FiscalError(Exception):
    def __init__(self,message,*,uncertain=False,rejected=False):
        super().__init__(message);self.uncertain=uncertain;self.rejected=rejected


def digits(value):
    return re.sub(r'\D','',value or '')


def valid_document(value):
    value=digits(value)
    if len(value) not in (11,14) or len(set(value))==1:return False
    if len(value)==11:
        first=sum(int(x)*w for x,w in zip(value[:9],range(10,1,-1)))
        a=(first*10%11)%10
        b=(sum(int(x)*w for x,w in zip(value[:9]+str(a),range(11,1,-1)))*10%11)%10
    else:
        def digit(s,weights):
            rem=sum(int(x)*w for x,w in zip(s,weights))%11
            return 0 if rem<2 else 11-rem
        a=digit(value[:12],[5,4,3,2,9,8,7,6,5,4,3,2])
        b=digit(value[:12]+str(a),[6,5,4,3,2,9,8,7,6,5,4,3,2])
    return value[-2:]==f'{a}{b}'


def certificate_data(raw,password,document):
    try:
        key,cert,chain=pkcs12.load_key_and_certificates(raw,password.encode() if password else None)
        if not isinstance(key,rsa.RSAPrivateKey) or key.key_size<2048 or cert is None:raise ValueError
        now=timezone.now()
        if not cert.not_valid_before_utc<=now<cert.not_valid_after_utc:raise ValueError
        # ICP-Brasil CNPJ in subjectAltName, OID 2.16.76.1.3.3 (DER string).
        names=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        documents=[]
        for name in names:
            if isinstance(name,x509.OtherName) and name.type_id.dotted_string=='2.16.76.1.3.3':
                data=name.value
                if len(data)>=2 and data[0] in (4,12,19,22) and data[1]<128:
                    documents.append(data[2:2+data[1]].decode('ascii'))
        if document not in documents:raise ValueError
        return key,cert,chain
    except Exception as exc:
        raise FiscalError('Certificado A1 inválido, vencido, senha incorreta ou CNPJ diferente do emissor.') from exc


def credentials(config):
    return certificate_data(base64.b64decode(decrypt_text(config.certificate_encrypted)),decrypt_text(config.certificate_password_encrypted),config.document)


def build_dps(row,config,profile):
    key,cert,_=credentials(config)
    root=etree.Element('{%s}DPS'%NS,nsmap={None:NS},versao='1.01')
    ident=f'DPS{config.municipality_code}2{config.document}{config.series:05d}{row.pk:015d}'
    def node(parent,name,value=None):
        el=etree.SubElement(parent,'{%s}%s'%(NS,name))
        if value is not None:el.text=str(value)
        return el
    inf=node(root,'infDPS');inf.set('Id',ident)
    for name,value in [('tpAmb',1 if config.environment=='production' else 2),('dhEmi',timezone.localtime(timezone.now()).isoformat(timespec='seconds')),('verAplic','ApPlanner_1.0'),('serie',config.series),('nDPS',row.pk),('dCompet',timezone.localtime(row.payment.paid_at).date().isoformat()),('tpEmit',1),('cLocEmi',config.municipality_code)]:node(inf,name,value)
    prest=node(inf,'prest');node(prest,'CNPJ',config.document)
    trib=node(prest,'regTrib');node(trib,'opSimpNac',2);node(trib,'regEspTrib',0)
    toma=node(inf,'toma');node(toma,'CNPJ' if len(profile.document)==14 else 'CPF',profile.document);node(toma,'xNome',profile.legal_name)
    end=node(toma,'end');nac=node(end,'endNac');node(nac,'cMun',profile.municipality_code);node(nac,'CEP',profile.postal_code)
    node(end,'xLgr',profile.street);node(end,'nro',profile.number)
    if profile.complement:node(end,'xCpl',profile.complement)
    node(end,'xBairro',profile.district);node(toma,'email',profile.email)
    serv=node(inf,'serv');loc=node(serv,'locPrest');node(loc,'cLocPrestacao',config.municipality_code)
    code=node(serv,'cServ');node(code,'cTribNac',config.service_code)
    if config.municipal_service_code:node(code,'cTribMun',config.municipal_service_code)
    node(code,'xDescServ',f'{config.service_description} · Pagamento {row.payment_id} · Competência {row.reference_month:%m/%Y}')
    valores=node(inf,'valores');v=node(valores,'vServPrest');node(v,'vServ',f'{row.amount:.2f}')
    trib=node(valores,'trib');mun=node(trib,'tribMun');node(mun,'tribISSQN',1);node(mun,'tpRetISSQN',1)
    total=node(trib,'totTrib');node(total,'indTotTrib',0)
    signed=XMLSigner(method=methods.enveloped,signature_algorithm='rsa-sha256',digest_algorithm='sha256',c14n_algorithm='http://www.w3.org/TR/2001/REC-xml-c14n-20010315').sign(root,key=key,cert=cert.public_bytes(serialization.Encoding.PEM),reference_uri='#'+ident)
    try:dps_schema().assertValid(signed)
    except etree.DocumentInvalid as exc:raise FiscalError('Dados da DPS não atendem ao leiaute nacional. Revise o cadastro fiscal e o código do serviço.') from exc
    return ident,etree.tostring(signed,encoding='utf-8',xml_declaration=True)


class NationalClient:
    def __init__(self,config,environment):
        self.config=config;self.environment=environment
        if environment not in SEFIN:raise FiscalError('Ambiente fiscal inválido.')

    @contextmanager
    def connection(self):
        key,cert,chain=credentials(self.config)
        with tempfile.TemporaryDirectory(prefix='applanner-nfse-') as folder:
            keypath=Path(folder)/'key.pem';certpath=Path(folder)/'cert.pem'
            keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));keypath.chmod(0o600)
            certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM)+b''.join(x.public_bytes(serialization.Encoding.PEM) for x in chain or []));certpath.chmod(0o600)
            with requests.Session() as session:
                session.cert=(str(certpath),str(keypath))
                yield session

    def request(self,method,path,*,payload=None,pdf=False,missing_ok=False):
        base=SEFIN[self.environment]
        try:
            with self.connection() as session:
                with session.request(method,base+path,json=payload,timeout=(10,30),allow_redirects=False,stream=True) as response:
                    if missing_ok and response.status_code==404:return None
                    content=b''
                    for chunk in response.iter_content(65536):
                        content+=chunk
                        if len(content)>(10*1024*1024 if pdf else MAX_XML*2):raise FiscalError('Resposta fiscal excedeu o limite seguro.',uncertain=True)
                    if response.status_code>=500 or response.status_code==429:raise FiscalError('Emissor nacional indisponível. A nota será consultada antes de reenviar.',uncertain=True)
                    if not 200<=response.status_code<300:
                        # Do not persist arbitrary response bodies containing fiscal PII.
                        import json
                        codes=[]
                        try:
                            data=json.loads(content)
                            for error in data.get('erros',[]):
                                code=str(error.get('Codigo',error.get('codigo','')))
                                if re.fullmatch(r'[A-Za-z0-9_-]{1,40}',code):codes.append(code)
                        except (ValueError,TypeError,AttributeError):pass
                        raise FiscalError(f'Emissor recusou a solicitação (HTTP {response.status_code}; códigos: {", ".join(codes) or "não informado"}). Revise os dados e o credenciamento.',uncertain=method!='POST' or response.status_code in (408,409),rejected=method=='POST' and response.status_code in (400,422))
                    if pdf:
                        if not content.startswith(b'%PDF-'):raise FiscalError('DANFSe ainda não disponível.',uncertain=True)
                        return content
                    import json
                    data=json.loads(content)
                    if not isinstance(data,dict):raise ValueError
                    return data
        except requests.RequestException as exc:raise FiscalError('Não foi possível consultar o emissor nacional. Resultado incerto; faremos consulta antes de reenviar.',uncertain=True) from exc
        except (ValueError,TypeError) as exc:raise FiscalError('Resposta fiscal inválida; emissão pendente de consulta.',uncertain=True) from exc

    def lookup(self,dps_id):return self.request('GET','/dps/'+dps_id,missing_ok=True)
    def submit(self,xml):return self.request('POST','/nfse',payload={'dpsXmlGZipB64':base64.b64encode(gzip.compress(xml)).decode()})
    def invoice(self,key):return self.request('GET','/nfse/'+key)


def invoice_xml(data,row):
    try:
        key=data['chaveAcesso']
        if not re.fullmatch(r'\d{50}',key):raise ValueError
        packed=base64.b64decode(data['nfseXmlGZipB64'],validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:xml=stream.read(MAX_XML+1)
        if len(xml)>MAX_XML:raise ValueError
        root=etree.fromstring(xml,etree.XMLParser(resolve_entities=False,no_network=True))
        if root.tag!='{%s}NFSe'%NS or root.getroottree().docinfo.doctype:raise ValueError
        inf=root.find('{%s}infNFSe'%NS);dps=inf.find('.//{%s}infDPS'%NS)
        if inf.get('Id')!='NFS'+key or dps.get('Id')!=row.dps_id:raise ValueError
        def val(path):return dps.findtext(path,namespaces={'n':NS})
        if val('n:prest/n:CNPJ')!=row.issuer_document or val('n:tpAmb')!=('1' if row.fiscal_environment=='production' else '2') or Decimal(val('n:valores/n:vServPrest/n:vServ'))!=row.amount:raise ValueError
        original=etree.fromstring(base64.b64decode(decrypt_text(row.signed_dps_encrypted)),etree.XMLParser(resolve_entities=False,no_network=True)).find('{%s}infDPS'%NS)
        for path in ['n:toma/n:CNPJ','n:toma/n:CPF','n:dCompet','n:serv/n:cServ/n:cTribNac']:
            if val(path)!=original.findtext(path,namespaces={'n':NS}):raise ValueError
        number=inf.findtext('{%s}nNFSe'%NS)
        if not number or len(number)>80:raise ValueError
        return key,number,xml
    except Exception as exc:raise FiscalError('A resposta fiscal não corresponde à DPS, emissor, ambiente ou valor registrado.',uncertain=True) from exc
