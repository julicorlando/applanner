from datetime import time
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from arena.models import ArenaSettings, Court, CourtHours, CourtModality, Modality, PriceRule, SportsSettings
from auto.models import ServiceBay
from billing.models import Module, TenantModule
from engagement.models import PackageItem, ServicePackage, TenantLoyaltySettings
from finance.models import Product
from scheduling.models import Customer, Professional, ProfessionalAvailability, ProfessionalService, Service
from tenants.models import Tenant, Unit


class Command(BaseCommand):
    help="Cria um tenant de homologação com dados suficientes para testar o portal Django."

    def add_arguments(self, parser):
        parser.add_argument("--slug",default="demo")
        parser.add_argument("--name",default="ApPlanner Demo")
        parser.add_argument("--user-email",default="")
        parser.add_argument("--user-password",default="")

    @transaction.atomic
    def handle(self,*args,**options):
        call_command("seed_modules",verbosity=0)

        tenant,_=Tenant.objects.update_or_create(
            slug=options["slug"],
            defaults={
                "name":options["name"],
                "public_slug":options["slug"],
                "public_enabled":True,
                "public_booking_enabled":True,
                "status":Tenant.Status.ACTIVE,
                "category":"homologacao",
                "description":"Ambiente de homologação criado pelo Django.",
            },
        )
        unit,_=Unit.objects.update_or_create(
            tenant=tenant,name="Unidade Principal",
            defaults={"is_primary":True,"active":True,"city":"Carpina","state":"PE"},
        )

        for module in Module.objects.filter(active=True):
            TenantModule.objects.update_or_create(
                tenant=tenant,module=module,defaults={"enabled":True}
            )

        customer,_=Customer.objects.update_or_create(
            tenant=tenant,email="cliente.demo@example.test",
            defaults={"name":"Cliente Demo","phone":"81999990000","active":True},
        )
        customer2,_=Customer.objects.update_or_create(
            tenant=tenant,email="cliente2.demo@example.test",
            defaults={"name":"Segundo Cliente","phone":"81999990001","active":True},
        )

        service,_=Service.objects.update_or_create(
            tenant=tenant,name="Atendimento Demo",
            defaults={"description":"Serviço de homologação","duration_minutes":60,"price":Decimal("80.00"),"active":True},
        )
        service2,_=Service.objects.update_or_create(
            tenant=tenant,name="Atendimento Rápido",
            defaults={"description":"Serviço de 30 minutos","duration_minutes":30,"price":Decimal("45.00"),"active":True},
        )
        professional,_=Professional.objects.update_or_create(
            tenant=tenant,name="Profissional Demo",
            defaults={"unit":unit,"email":"profissional.demo@example.test","specialty":"Atendimento","active":True},
        )
        ProfessionalService.objects.get_or_create(professional=professional,service=service)
        ProfessionalService.objects.get_or_create(professional=professional,service=service2)
        for weekday in range(1,7):
            ProfessionalAvailability.objects.update_or_create(
                tenant=tenant,professional=professional,weekday=weekday,
                defaults={"start_time":time(9,0),"end_time":time(18,0),"active":True},
            )

        Product.objects.update_or_create(
            tenant=tenant,sku="DEMO-001",
            defaults={
                "unit":unit,"name":"Produto Demo","category":"Homologação",
                "cost_price":Decimal("10.00"),"sale_price":Decimal("25.00"),
                "stock":Decimal("20.000"),"minimum_stock":Decimal("5.000"),"active":True,
            },
        )

        package,_=ServicePackage.objects.update_or_create(
            tenant=tenant,name="Pacote Demo",
            defaults={"description":"4 créditos para homologação","price":Decimal("250.00"),"validity_days":30,"active":True},
        )
        PackageItem.objects.update_or_create(package=package,service=service,defaults={"credits":4})
        TenantLoyaltySettings.objects.update_or_create(
            tenant=tenant,
            defaults={
                "enabled":True,"points_per_currency":Decimal("1.00"),
                "reward_points":100,"reward_value":Decimal("10.00"),"referral_points":50,
            },
        )

        SportsSettings.objects.get_or_create(tenant=tenant)
        ArenaSettings.objects.get_or_create(tenant=tenant)
        modality,_=Modality.objects.update_or_create(
            tenant=tenant,name="Futebol",
            defaults={"description":"Modalidade de homologação","active":True,"sort_order":1},
        )
        court,_=Court.objects.update_or_create(
            tenant=tenant,slug="quadra-demo",
            defaults={
                "unit":unit,"name":"Quadra Demo","surface":"Sintético","lighting":True,
                "minimum_minutes":60,"maximum_minutes":180,"interval_minutes":0,"active":True,
            },
        )
        CourtModality.objects.get_or_create(court=court,modality=modality)
        for weekday in range(1,8):
            CourtHours.objects.update_or_create(
                tenant=tenant,court=court,weekday=weekday,
                defaults={"start_time":time(8,0),"end_time":time(23,0),"active":True},
            )
        PriceRule.objects.update_or_create(
            tenant=tenant,court=court,modality=modality,weekday=None,start_time=None,end_time=None,
            specific_date=None,valid_from=None,valid_to=None,label="Preço padrão demo",
            defaults={
                "price_per_hour":Decimal("100.00"),"priority":0,"active":True,
                "rule_type":PriceRule.RuleType.STANDARD,
            },
        )

        ServiceBay.objects.update_or_create(
            tenant=tenant,name="Box 01",
            defaults={"bay_type":ServiceBay.Type.BOX,"capacity":1,"active":True,"sort_order":1},
        )

        email=(options["user_email"] or "").strip().lower()
        password=options["user_password"]
        if email:
            user,_=User.objects.get_or_create(email=email,defaults={"tenant":tenant,"is_active":True})
            user.tenant=tenant
            user.is_active=True
            if password:
                user.set_password(password)
            elif not user.has_usable_password():
                user.set_unusable_password()
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Usuário tenant configurado: {email}"))

        self.stdout.write(self.style.SUCCESS(
            f"Demo pronta: tenant={tenant.slug} | clientes={Customer.objects.filter(tenant=tenant).count()} | "
            f"serviços={Service.objects.filter(tenant=tenant).count()} | quadras={Court.objects.filter(tenant=tenant).count()}"
        ))
        self.stdout.write("Superusuários podem acessar /app/ e selecionar este tenant para homologação.")
