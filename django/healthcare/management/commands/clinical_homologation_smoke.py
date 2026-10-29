"""Create fictitious, non-login demo data and exercise deployed clinical views."""
import json
from datetime import time
from io import BytesIO
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.utils import timezone
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from billing.models import Module,TenantModule,Plan,Subscription,PlanModule
from scheduling.models import Professional,Customer,Service,ProfessionalAvailability
from tenants.models import Tenant,Unit
from healthcare.models import ClinicalRegistration,MedicalRecordEntry
from healthcare.services import create_record,read_record
from healthcare.dentistry import save_dental_encounter
from healthcare.clinical import save_structured_record,attach_document
from healthcare import clinic_views


class Command(BaseCommand):
    help="Dados exclusivamente fictícios e smoke clínico em homologação; não cria senhas nem acesso público autenticado."
    def handle(self,*args,**options):
        if settings.DEPLOYMENT_ENVIRONMENT!="homologacao":raise CommandError("Este comando só funciona em homologacao.")
        datasets=[]
        for category,council,jurisdiction in (("odontologia","CRO","PE"),("fisioterapia","CREFITO","1")):
            tenant,_=Tenant.objects.get_or_create(slug="homolog-"+category,defaults={"name":"Clínica fictícia de "+category,"category":category,
                "status":"active","public_enabled":True,"public_booking_enabled":True,"public_slug":"homolog-"+category})
            plan,_=Plan.objects.get_or_create(slug="homolog-"+category,defaults={"name":"Homologação "+category,"monthly_price":0,"public_visible":False,"features":{"professionals":1}})
            for slug in ("medical_records","dentistry" if council=="CRO" else "physiotherapy","packages"):
                module,_=Module.objects.get_or_create(slug=slug,defaults={"name":slug})
                TenantModule.objects.update_or_create(tenant=tenant,module=module,defaults={"enabled":True})
                PlanModule.objects.update_or_create(plan=plan,module=module,defaults={"enabled":True})
            Subscription.objects.get_or_create(tenant=tenant,plan=plan,defaults={"status":"active","started_at":timezone.now(),"payment_method":"pix","contracted_price":0,"base_contracted_price":0,"provider_environment":"sandbox"})
            doctor,_=User.objects.get_or_create(email=category+"@homolog.invalid",defaults={"tenant":tenant,"role":"professional","is_active":True,"email_verified_at":timezone.now()})
            if not doctor.password:
                doctor.set_unusable_password();doctor.save(update_fields=["password"])
            if doctor.has_usable_password():raise CommandError("Conta de demonstração recebeu senha; use outra base de testes isolada.")
            professional,_=Professional.objects.get_or_create(tenant=tenant,user=doctor,defaults={"name":"Profissional fictício — "+category,"public_slug":"profissional-ficticio"})
            ClinicalRegistration.objects.get_or_create(professional=professional,defaults={"council":council,"number":"999999","jurisdiction":jurisdiction,"specialties":"Dados fictícios"})
            unit,_=Unit.objects.get_or_create(tenant=tenant,name="Unidade fictícia",defaults={"is_primary":True,"active":True})
            service,_=Service.objects.get_or_create(tenant=tenant,name="Atendimento fictício",defaults={"unit":unit,"duration_minutes":30,"price":0})
            for day in range(1,8):ProfessionalAvailability.objects.get_or_create(tenant=tenant,professional=professional,weekday=day,defaults={"start_time":time(9),"end_time":time(17)})
            customer,_=Customer.objects.get_or_create(tenant=tenant,name="Paciente fictício de homologação")
            reception,_=User.objects.get_or_create(email="recepcao-"+category+"@homolog.invalid",defaults={"tenant":tenant,"role":"reception","is_active":True})
            if not reception.password:
                reception.set_unusable_password();reception.save(update_fields=["password"])
            if council=="CRO":
                entry=MedicalRecordEntry.objects.filter(tenant=tenant,customer=customer,title="Evolução odontológica").first()
                if not entry:
                    entry=save_dental_encounter(tenant=tenant,customer=customer,professional=professional,user=doctor,
                        anamnesis="Anamnese fictícia",findings="Exame fictício",procedures="Procedimento fictício",plan="Retorno fictício",
                        odontogram={"11":[{"condition":"restauracao","surfaces":["mesial"],"note":"Registro de teste"}]})
                    # Titles/content are immutable; identify demo records by their responsible profile.
                if not MedicalRecordEntry.objects.filter(tenant=tenant,title="Periodontograma fictício").exists():
                    save_structured_record(tenant=tenant,customer=customer,professional=professional,user=doctor,kind="periodontal",title="Periodontograma fictício",data={"chart":{"11":{"mobility":0,"sites":{"MV":{"probing":2,"recession":0,"bleeding":False}}}}})
                if not MedicalRecordEntry.objects.filter(tenant=tenant,title="Orçamento fictício").exists():
                    save_structured_record(tenant=tenant,customer=customer,professional=professional,user=doctor,kind="treatment_plan",title="Orçamento fictício",data={"lines":[{"tooth":"11","procedure":"Procedimento fictício","quantity":1,"price":"50.00"}]})
            else:
                entry=MedicalRecordEntry.objects.filter(tenant=tenant,title="Avaliação fictícia").first()
                if not entry:
                    entry=create_record(tenant=tenant,customer=customer,professional=professional,user=doctor,title="Avaliação fictícia",record_type="physio_evaluation",content=json.dumps({"schema":"applanner.physiotherapy.v1","sections":{"registration":"999999","chief_complaint":"Queixa fictícia","pain_level":7,"body_findings":{"knee_left":{"pain":7,"condition":"pain","note":"Fictício"}}}}))
                    create_record(tenant=tenant,customer=customer,professional=professional,user=doctor,title="Evolução fictícia",record_type="physio_evolution",content=json.dumps({"schema":"applanner.physiotherapy.v1","sections":{"registration":"999999","pain_level":3,"response":"Resposta fictícia","body_findings":{"knee_left":{"pain":3,"condition":"treated","note":"Fictício"}}}}))
            if not entry.attachments.exists():
                image=BytesIO();Image.new('RGB',(80,80),(200,220,240)).save(image,'PNG')
                attach_document(entry=entry,user=doctor,upload=SimpleUploadedFile('imagem-ficticia.png',image.getvalue()),kind="image")
            datasets.append((tenant,doctor,customer,entry,reception))
        checks=[]
        for tenant,doctor,customer,entry,reception in datasets:
            def req(actor):
                request=RequestFactory().get('/app/clinica/');request.user=actor;request.session={};request._messages=FallbackStorage(request);return request
            for view,args in ((clinic_views.dashboard,()),(clinic_views.patient,(customer.pk,)),(clinic_views.record_detail,(entry.pk,))):
                result=view(req(doctor),*args)
                if result.status_code!=200:raise CommandError("Tela clínica não respondeu 200.")
                checks.append(view.__name__+":"+tenant.category+":200")
                try:view(req(reception),*args)
                except PermissionDenied:checks.append("reception-denied:"+view.__name__)
                else:raise CommandError("Recepção acessou conteúdo clínico.")
            export=clinic_views.export_patient(req(doctor),customer.pk,"pdf")
            if not b''.join(export.streaming_content).startswith(b'%PDF-'):raise CommandError("PDF clínico inválido.")
            checks.append("pdf:"+tenant.category+":ok")
        try:read_record(entry=datasets[0][3],user=datasets[1][1])
        except PermissionDenied:checks.append("cross-tenant-denied")
        else:raise CommandError("Isolamento entre clínicas falhou.")
        try:clinic_views.patient(req(datasets[0][1]),datasets[1][2].pk)
        except Http404:checks.append("patient-idor-denied")
        else:raise CommandError("IDOR de paciente não bloqueado.")
        self.stdout.write(json.dumps({"status":"passed","checks":checks,"public_slugs":[x[0].public_slug for x in datasets],"login_accounts":"unusable_passwords"},ensure_ascii=False))
