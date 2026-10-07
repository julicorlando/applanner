import re
import json

from django import forms
from django.db import transaction
from django.utils import timezone

from .models import MasterWhatsAppConversation, MasterWhatsAppFlow, MasterWhatsAppMessage


class MasterFlowForm(forms.ModelForm):
    positions_text=forms.CharField(required=False,widget=forms.HiddenInput())
    steps_text=forms.CharField(required=False,label="Etapas e respostas",widget=forms.Textarea(attrs={
        "rows":12,"placeholder":"inicio | planos;preço | Temos planos para sua empresa. Qual segmento? | segmento | não\nsegmento | barbearia;salão | Vou chamar nossa equipe comercial. | | sim",
    }))

    class Meta:
        model=MasterWhatsAppFlow
        fields=["enabled","greeting","fallback","handoff"]
        labels={"enabled":"Ativar respostas automáticas do Master",
                "greeting":"Primeira mensagem","fallback":"Quando não entender",
                "handoff":"Ao transferir para uma pessoa"}
        widgets={"greeting":forms.Textarea(attrs={"rows":2}),
                 "fallback":forms.Textarea(attrs={"rows":2}),
                 "handoff":forms.Textarea(attrs={"rows":2})}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.is_bound:
            self.fields["steps_text"].initial="\n".join(
                " | ".join((step.get("id",""),";".join(step.get("keywords",[])),
                    step.get("reply",""),step.get("next",""),"sim" if step.get("handoff") else "não", "fim" if step.get("finish") else ""))
                for step in (self.instance.steps or [])
            )

            self.fields["positions_text"].initial=json.dumps({step["id"]:step.get("position",{}) for step in (self.instance.steps or [])})

    def clean(self):
        data=super().clean()
        try:
            positions=json.loads(data.get("positions_text") or "{}")
            if not isinstance(positions,dict) or len(positions)>30:
                raise ValueError
            for step in data.get("steps_text",[]):
                pos=positions.get(step["id"],{})
                if pos:
                    if not isinstance(pos,dict) or any(type(pos.get(k)) not in (int,float) or not 0<=pos[k]<=(1600 if k=='x' else 3900) for k in ('x','y')):
                        raise ValueError
                    step["position"]={k:pos[k] for k in ('x','y')}
        except (ValueError,TypeError):
            self.add_error("positions_text","Posições dos blocos inválidas.")
        return data

    def clean_steps_text(self):
        lines=[line.strip() for line in self.cleaned_data.get("steps_text","").splitlines() if line.strip()]
        if len(lines)>30:
            raise forms.ValidationError("O fluxo aceita até 30 etapas.")
        result=[]
        for index,line in enumerate(lines,start=1):
            parts=[item.strip() for item in line.split("|")]
            if len(parts) not in {5,6}:
                raise forms.ValidationError(f"Linha {index}: use etapa | palavras;sinônimos | resposta | próxima etapa | sim/não.")
            step,keywords,reply,next_step,handoff=parts[:5]
            finish=len(parts)==6 and parts[5]=="fim"
            if len(parts)==6 and parts[5] not in {"","fim"}:
                raise forms.ValidationError("O final deve ser vazio ou fim.")
            if finish and (next_step or handoff.lower()=="sim"):
                raise forms.ValidationError("Finalizar não pode ter próxima etapa ou transferência.")
            words=[word.strip().lower() for word in keywords.split(";") if word.strip()]
            if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}",step)
                or next_step and not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}",next_step)
                or not words or any(len(word)>60 for word in words)
                or not reply or len(reply)>1000 or handoff.lower() not in {"sim","não","nao"}):
                raise forms.ValidationError(f"Linha {index}: etapa, palavras ou resposta inválidas.")
            result.append({"id":step,"keywords":words,"reply":reply,"next":next_step,
                           "handoff":handoff.lower()=="sim","finish":finish})
        identifiers={item["id"] for item in result}
        if len(identifiers)!=len(result):
            raise forms.ValidationError("Cada etapa precisa ter um nome exclusivo.")
        if any(item["next"] and item["next"] not in identifiers for item in result):
            raise forms.ValidationError("A próxima etapa deve existir no fluxo.")
        if result and "inicio" not in identifiers:
            raise forms.ValidationError("Inclua uma etapa chamada inicio.")
        return result


@transaction.atomic
def process_master_automation(message_id):
    """Runs on Celery; locks the conversation to avoid duplicate auto replies."""
    incoming=MasterWhatsAppMessage.objects.select_related("conversation").get(pk=message_id)
    conversation=MasterWhatsAppConversation.objects.select_for_update().get(pk=incoming.conversation_id)
    flow=MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).first()
    if incoming.direction!="in" or incoming.flow_processed_at or not flow or conversation.human_handoff:
        return

    content=incoming.body.casefold()
    if not conversation.flow_state or conversation.flow_state=="__finished__":
        response=flow.greeting
        conversation.flow_state="inicio"
    elif "atendimento" in content or "humano" in content:
        response=flow.handoff
        conversation.human_handoff=True
    else:
        step=next((item for item in flow.steps
                   if item["id"]==conversation.flow_state
                   and any(keyword.casefold() in content for keyword in item["keywords"])),None)
        response=step["reply"] if step else flow.fallback
        if step:
            conversation.flow_state="__finished__" if step.get("finish") else step["next"] or conversation.flow_state
            conversation.human_handoff=step["handoff"]
    from .master_whatsapp import _gateway, record_outbound_message
    sent=_gateway("POST","/send",{"to":conversation.wa_id,"text":response})
    record_outbound_message(conversation=conversation,sent=sent,body=response,sent_by=None)
    incoming.flow_processed_at=timezone.now()
    incoming.save(update_fields=["flow_processed_at"])
    conversation.last_message_at=timezone.now()
    conversation.save(update_fields=["flow_state","human_handoff","last_message_at","updated_at"])
    if conversation.human_handoff:
        MasterWhatsAppMessage.objects.filter(
            conversation=conversation,direction="in",flow_processed_at__isnull=True,
            pk__lt=incoming.pk,
        ).update(flow_processed_at=timezone.now())
