import json
from functools import partial
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect,render
from django.views.decorators.http import require_POST
from .models import ChatbotFlow,MasterWhatsAppFlow,TenantWhatsAppConnection
from .tenant_whatsapp import _management
from .tenant_flow import available,company_graph,company_variables,validate_company_graph,answer_company,company_intake
from .master_runtime import run_graph


class TenantFlowForm(forms.ModelForm):
    graph_json=forms.CharField(widget=forms.HiddenInput())
    integrations_json=forms.CharField(required=False,initial='[]',widget=forms.HiddenInput())
    positions_text=forms.CharField(required=False,widget=forms.HiddenInput())
    steps_text=forms.CharField(required=False,widget=forms.HiddenInput())
    class Meta:
        model=ChatbotFlow
        fields=['enabled','greeting','fallback','handoff','ai_enabled']
        labels={'enabled':'Ativar respostas automáticas da empresa','greeting':'Primeira mensagem','fallback':'Quando não entender','handoff':'Ao transferir para uma pessoa','ai_enabled':'Usar a IA central do ApPlanner'}
        widgets={k:forms.Textarea(attrs={'rows':2}) for k in ['greeting','fallback','handoff']}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.is_bound:self.fields['graph_json'].initial=json.dumps(self.instance.graph or company_graph(),ensure_ascii=False)

    def clean_graph_json(self):
        try:return validate_company_graph(json.loads(self.cleaned_data['graph_json']))
        except (ValueError,TypeError) as exc:raise forms.ValidationError('JSON do fluxo inválido.') from exc

    def save(self,commit=True):
        row=super().save(commit=False);row.graph=self.cleaned_data['graph_json']
        if commit:row.save()
        return row


def selected(request):
    tenant=_management(request)
    if not tenant:raise PermissionDenied('Selecione a empresa antes de configurar o chatbot.')
    if not available(tenant):raise PermissionDenied('O WhatsApp não está disponível para esta empresa. Confira o plano e o pagamento.')
    return tenant


@login_required
def builder(request):
    tenant=selected(request)
    flow,_=ChatbotFlow.objects.get_or_create(tenant=tenant)
    form=TenantFlowForm(request.POST or None,instance=flow)
    shared=MasterWhatsAppFlow.objects.filter(pk=1).first()
    ready=bool(shared and shared.ai_enabled and shared.ai_model and shared.ai_key_encrypted)
    if request.method=='POST' and form.is_valid():
        qr=TenantWhatsAppConnection.objects.filter(tenant=tenant,enabled=True).exists()
        cloud=bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and tenant.metadata.get('whatsapp_phone_number_id')==settings.WHATSAPP_PHONE_NUMBER_ID)
        if form.cleaned_data['enabled'] and not (qr or cloud):form.add_error('enabled','Conecte o WhatsApp da empresa antes de ativar o chatbot.')
        else:
            form.save();messages.success(request,'Chatbot da empresa salvo. A configuração da API central foi preservada.')
            return redirect('tenant-whatsapp-chatbot')
    return render(request,'master/whatsapp_flow.html',{'tenant':tenant,'tenant_flow':True,'form':form,'flow':flow,'commercial_template':company_graph(),'shared_ai_ready':ready,'shared_ai_model':shared.ai_model if shared else ''})


@login_required
@require_POST
def simulate(request):
    tenant=selected(request)
    if len(request.body)>180000:return JsonResponse({'error':'Simulação muito grande.'},status=400)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict):raise ValueError
        graph=validate_company_graph(data.get('graph'))
        context=data.get('context') or {'variables':{}}
        if not isinstance(context,dict) or not isinstance(context.get('variables',{}),dict) or len(json.dumps(context))>30000:raise ValueError
        incoming=data.get('incoming','')
        if not isinstance(incoming,str) or len(incoming)>2000:raise ValueError
        flow=ChatbotFlow.objects.filter(tenant=tenant).first() or ChatbotFlow(tenant=tenant)
        if any(not isinstance(v,(str,int,float,bool,type(None))) for v in context.get('variables',{}).values()):raise ValueError
        context.setdefault('variables',{}).update(company_variables(tenant));context['variables'].setdefault('contact_phone','5581000000000')
        result=run_graph(graph,flow,str(data.get('state') or graph['start']),context,str(data.get('waiting') or ''),incoming,
            resume=bool(data.get('resume')),simulation=True,knowledge_handler=partial(answer_company,tenant),intake_handler=partial(company_intake,tenant))
        return JsonResponse(result)
    except (ValueError,TypeError,KeyError,ValidationError):return JsonResponse({'error':'Fluxo ou dados da simulação inválidos.'},status=400)
