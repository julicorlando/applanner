"""Local MEI reading copy from authorized XML (NT 008/2026 field groups).
This uses portable PDF fonts; the authoritative fiscal document is the XML.
Only values from XML; one A4 page, consultation QR and homologation watermark.
"""
import base64,io
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape
from lxml import etree
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from .nfse_national import NS,FiscalError


def render_danfse(xml):
    root=etree.fromstring(xml,etree.XMLParser(resolve_entities=False,no_network=True))
    inf=root.find('{%s}infNFSe'%NS);dps=inf.find('.//{%s}infDPS'%NS)
    if root.tag!='{%s}NFSe'%NS or inf is None or dps is None or root.getroottree().docinfo.doctype:raise FiscalError('XML não autorizado para representação fiscal.')
    def get(path,base=inf):return base.findtext(path,namespaces={'n':NS}) or '-'
    def d(path):return get(path,dps)
    def date(value):
        try:return datetime.fromisoformat(value).strftime('%d/%m/%Y %H:%M:%S' if 'T' in value else '%d/%m/%Y')
        except ValueError:return value
    def money(value):
        if value=='-':return value
        from decimal import Decimal
        try:return 'R$ '+f'{Decimal(value):,.2f}'.replace(',','X').replace('.',',').replace('X','.')
        except Exception:return value
    key=(inf.get('Id') or '')[3:]
    if len(key)!=50 or not key.isdigit():raise FiscalError('Chave da NFS-e inválida para gerar PDF.')
    output=io.BytesIO();c=canvas.Canvas(output,pagesize=A4,pageCompression=0)
    c.setTitle('NFS-e '+get('n:nNFSe'));c.setAuthor('ApPlanner')
    width,height=A4;left=2*mm;right=width-2*mm;w=right-left;y=height-2*mm
    style=ParagraphStyle('fiscal',fontName='Helvetica',fontSize=7,leading=8,textColor='black')
    def text(value,x,top,available,maximum=16*mm,*,bold=False,size=7):
        st=ParagraphStyle('field',parent=style,fontName='Helvetica-Bold' if bold else 'Helvetica',fontSize=size,leading=size+1)
        clean=''.join(ch for ch in str(value) if ord(ch)>=32 or ch=='\n')
        p=Paragraph(escape(clean).replace('\n','<br/>'),st);_,h=p.wrap(available,maximum)
        if h>maximum:raise FiscalError('Conteúdo fiscal excedeu o espaço do PDF. O XML autorizado permanece disponível.')
        p.drawOn(c,x,top-h)
    def line(top,h,gray=False):
        c.setFillGray(.95 if gray else 1);c.setStrokeGray(0);c.setLineWidth(.5);c.rect(left,top-h,w,h,fill=1,stroke=1);c.setFillGray(0)
    def heading(title):
        nonlocal y
        h=5*mm;line(y,h,True);text(title,left+1.5*mm,y-1*mm,w-3*mm,4*mm,bold=True);y-=h
    def cells(values,h=9*mm):
        nonlocal y
        line(y,h);cw=w/len(values)
        for i,(label,value) in enumerate(values):
            x=left+i*cw
            if i:c.line(x,y,x,y-h)
            text(label,x+1*mm,y-1*mm,cw-2*mm,4*mm,bold=True,size=6)
            text(value,x+1*mm,y-4.5*mm,cw-2*mm,h-5*mm)
        y-=h
    line(y,12*mm,True)
    logo=Path(__file__).with_name('nfse_logo.b64')
    if logo.exists():c.drawImage(ImageReader(io.BytesIO(base64.b64decode(logo.read_bytes()))),left+2*mm,y-9.5*mm,width=40*mm,height=8.5*mm,preserveAspectRatio=True,mask='auto')
    text('NFS-e\nRepresentação auxiliar do XML',left+54*mm,y-1.5*mm,94*mm,10*mm,bold=True,size=9)
    text(get('n:xLocEmi')+' / '+get('n:emit/n:enderNac/n:UF'),left+155*mm,y-1*mm,48*mm,8*mm)
    text('Ambiente: '+('Produção' if d('n:tpAmb')=='1' else 'Homologação'),left+155*mm,y-8*mm,48*mm,4*mm,size=6)
    y-=12*mm
    ident_top=y;line(y,28*mm)
    text('CHAVE DE ACESSO DA NFS-e',left+1*mm,y-1*mm,148*mm,4*mm,bold=True)
    text(key,left+1*mm,y-5*mm,148*mm,4*mm)
    for j,fields in enumerate([
        [('Número da NFS-e',get('n:nNFSe')),('Competência',date(d('n:dCompet'))),('Emissão da NFS-e',date(get('n:dhProc')))],
        [('Número da DPS',d('n:nDPS')),('Série da DPS',d('n:serie')),('Emissão da DPS',date(d('n:dhEmi')))],
        [('Emitente da NFS-e',{'1':'Prestador','2':'Tomador','3':'Intermediário'}.get(d('n:tpEmit'),d('n:tpEmit'))),('Situação',{'100':'NFS-e gerada','102':'NFS-e de decisão judicial','103':'NFS-e avulsa','107':'NFS-e MEI'}.get(get('n:cStat'),get('n:cStat'))),('Finalidade',d('n:IBSCBS/n:finNFSe'))]]):
        for i,(label,value) in enumerate(fields):
            x=left+i*51*mm;top=ident_top-(9+j*6)*mm
            text(label,x+1*mm,top,49*mm,3*mm,bold=True,size=6);text(value,x+1*mm,top-2.8*mm,49*mm,4*mm)
    url='https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave='+key
    widget=QrCodeWidget(url);bounds=widget.getBounds();size=18*mm;drawing=Drawing(size,size,transform=[size/(bounds[2]-bounds[0]),0,0,size/(bounds[3]-bounds[1]),0,0]);drawing.add(widget)
    renderPDF.draw(drawing,c,left+174*mm,ident_top-20*mm)
    text('Consulte a autenticidade pelo QR Code ou pela chave no portal nacional da NFS-e.',left+156*mm,ident_top-20*mm,47*mm,8*mm,size=6)
    y-=28*mm
    def person(title,path,fallback=None):
        heading(title)
        def v(s):
            value=d(path+'/'+s)
            return get(fallback+'/'+s) if value=='-' and fallback else value
        doc=v('n:CNPJ')
        if doc=='-':doc=v('n:CPF')
        if doc=='-':doc=v('n:NIF')
        cells([('CNPJ / CPF / NIF',doc),('Inscrição municipal',v('n:IM')),('Telefone',v('n:fone'))])
        cells([('Nome / nome empresarial',v('n:xNome')),('E-mail',v('n:email'))])
        address=' '.join(x for x in [v('n:end/n:xLgr'),v('n:end/n:nro'),v('n:end/n:xCpl'),v('n:end/n:xBairro')] if x!='-')
        if not address and fallback:address=' '.join(value for value in [get(fallback+'/n:enderNac/'+s) for s in ['n:xLgr','n:nro','n:xBairro']] if value!='-')
        cells([('Endereço',address or '-'),('Código IBGE / CEP',(get(fallback+'/n:enderNac/n:cMun') if fallback and v('n:end/n:endNac/n:cMun')=='-' else v('n:end/n:endNac/n:cMun'))+' / '+(get(fallback+'/n:enderNac/n:CEP') if fallback and v('n:end/n:endNac/n:CEP')=='-' else v('n:end/n:endNac/n:CEP')))],h=12*mm)
    person('PRESTADOR / FORNECEDOR','n:prest','n:emit')
    cells([('Simples Nacional na competência',{'2':'Optante — MEI','1':'Não optante','3':'Optante — ME/EPP'}.get(d('n:prest/n:regTrib/n:opSimpNac'),'-')),('Regime de apuração pelo SN',d('n:prest/n:regTrib/n:regApTribSN'))])
    person('TOMADOR / ADQUIRENTE','n:toma')
    heading('DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e')
    heading('INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e')
    heading('SERVIÇO PRESTADO')
    cells([('Código de tributação nacional',d('n:serv/n:cServ/n:cTribNac')),('Código de tributação municipal',d('n:serv/n:cServ/n:cTribMun')),('Local de prestação',get('n:xLocPrestacao'))])
    line(y,46*mm);text('Descrição do serviço',left+1*mm,y-1*mm,w-2*mm,4*mm,bold=True,size=6);text(d('n:serv/n:cServ/n:xDescServ'),left+1*mm,y-5*mm,w-2*mm,40*mm);y-=46*mm
    heading('TRIBUTAÇÃO MUNICIPAL (ISSQN)')
    cells([('Tributação do ISSQN',{'1':'Operação tributável','2':'Imunidade','3':'Exportação','4':'Não incidência'}.get(d('n:valores/n:trib/n:tribMun/n:tribISSQN'),'-')),('Regime especial',d('n:prest/n:regTrib/n:regEspTrib')),('Município de incidência',get('n:xLocIncid'))])
    cells([('Valor do serviço',money(d('n:valores/n:vServPrest/n:vServ'))),('Base de cálculo',money(get('n:valores/n:vBC'))),('Alíquota aplicada',get('n:valores/n:pAliqAplic')),('ISSQN apurado',money(get('n:valores/n:vISSQN')))])
    heading('TRIBUTAÇÃO FEDERAL')
    cells([('IRRF',money(d('n:valores/n:trib/n:tribFed/n:vRetIRRF'))),('CP',money(d('n:valores/n:trib/n:tribFed/n:vRetCP'))),('CSLL',money(d('n:valores/n:trib/n:tribFed/n:vRetCSLL'))),('PIS / COFINS',d('n:valores/n:trib/n:tribFed/n:piscofins/n:CST'))])
    heading('TRIBUTAÇÃO IBS / CBS')
    cells([('CST',d('n:IBSCBS/n:valores/n:trib/n:gIBSCBS/n:CST')),('Classificação tributária',d('n:IBSCBS/n:valores/n:trib/n:gIBSCBS/n:cClassTrib')),('IBS total',money(get('n:IBSCBS/n:totCIBS/n:vIBSTot'))),('CBS total',money(get('n:IBSCBS/n:totCIBS/n:vCBSTot')))])
    heading('TOTAIS DA NFS-e')
    cells([('Valor do serviço',money(d('n:valores/n:vServPrest/n:vServ'))),('Retenções totais',money(get('n:valores/n:vTotalRet'))),('Valor líquido da NFS-e',money(get('n:valores/n:vLiq'))),('Valor líquido + IBS/CBS',money(get('n:IBSCBS/n:totCIBS/n:vTotNF')))])
    heading('INFORMAÇÕES COMPLEMENTARES')
    remaining=y-4*mm
    if remaining<10*mm:raise FiscalError('Dados fiscais excederam o espaço de uma página.')
    line(y,remaining);text(d('n:serv/n:infoCompl/n:xInfComp'),left+1*mm,y-2*mm,w-2*mm,remaining-3*mm)
    c.setLineWidth(1);c.rect(left,2*mm,w,height-4*mm,fill=0,stroke=1)
    if d('n:tpAmb')!='1':
        c.setFillColorRGB(1,0,0);c.setFont('Helvetica-Bold',9);c.drawString(left+54*mm,height-13*mm,'NFS-e SEM VALIDADE JURÍDICA')
    c.showPage();c.save();return output.getvalue()
