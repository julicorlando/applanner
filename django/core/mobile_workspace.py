"""Compact mobile shortcuts derived from the same permissions as the operation."""
from django.urls import reverse


def navigation(request):
    user=getattr(request,'user',None)
    if not user or not user.is_authenticated or not request.path.startswith(('/app/','/master/','/billing/')):
        return {}
    if getattr(request,'billing_locked',False):
        items=[{'title':'Pagamento','icon':'card','url':reverse('billing-subscription-status')}]
    elif request.path.startswith('/master/') and user.is_superuser:
        items=[{'title':'Painel','icon':'home','url':reverse('master-home')},
               {'title':'Empresas','icon':'users','url':reverse('master-resource-list',args=['empresas'])},
               {'title':'Financeiro','icon':'card','url':reverse('master-finance-dashboard')},
               {'title':'WhatsApp','icon':'chat','url':reverse('master-whatsapp')}]
    elif user.role=='professional':
        items=[{'title':'Minha agenda','icon':'calendar','url':reverse('professional-area')}]
    else:
        from tenants.models import Tenant
        tenant=user.tenant if user.tenant_id else None
        if user.is_superuser:
            tenant=Tenant.objects.filter(pk=request.session.get('portal_tenant_id'),deleted_at__isnull=True,archived_at__isnull=True).first()
        if not tenant:
            return {}
        from .portal import available_modules, _role_resource_write
        routes={(m['slug'],r['slug']) for m in available_modules(user,tenant) for r in m['resources']}
        items=[]
        definitions=[('agenda','agendamentos','Agenda','calendar'),('arena','reservas','Reservas','calendar'),
                     ('agenda','clientes','Clientes','users'),('agenda','servicos','Serviços','scissors'),
                     ('financeiro','lancamentos','Financeiro','card')]
        for module,resource,title,icon in definitions:
            if (module,resource) not in routes: continue
            url=reverse('operation-today') if resource in {'agendamentos','reservas'} else reverse('portal-resource-list',args=[module,resource])
            item={'title':title,'icon':icon,'url':url}
            if resource in {'agendamentos','reservas'} and _role_resource_write(user,module,resource):
                item['create_url']=reverse('portal-resource-create',args=[module,resource])
            items.append(item)
            if len(items)==4: break
        if not items: items=[{'title':'Início','icon':'home','url':reverse('portal-home')}]
    for item in items:
        item['active']=request.path==item['url'] or (item['url'] not in {'/app/','/master/'} and request.path.startswith(item['url']))
    return {'mobile_workspace_nav':items}
