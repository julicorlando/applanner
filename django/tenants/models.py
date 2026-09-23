from django.db import models
from core.models import TimeStampedModel


class Tenant(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL="trial","Teste"
        ACTIVE="active","Ativo"
        SUSPENDED="suspended","Suspenso"
        CANCELLED="cancelled","Cancelado"

    name=models.CharField(max_length=150)
    slug=models.SlugField(max_length=120,unique=True)
    public_slug=models.SlugField(max_length=120,unique=True,null=True,blank=True)
    public_short_code=models.CharField(max_length=16,unique=True,null=True,blank=True)
    public_booking_enabled=models.BooleanField(default=True)
    public_enabled=models.BooleanField(default=False)
    category=models.CharField(max_length=60,blank=True)
    description=models.TextField(blank=True)
    document=models.CharField(max_length=32,blank=True)
    email=models.EmailField(blank=True)
    phone=models.CharField(max_length=32,blank=True)
    logo=models.ImageField(upload_to="tenant/logo/",blank=True)
    cover=models.ImageField(upload_to="tenant/cover/",blank=True)
    primary_color=models.CharField(max_length=7,default="#2563eb")
    menu_color=models.CharField(max_length=7,default="#17213b")
    menu_text_color=models.CharField(max_length=7,default="#dce3f7")
    background_color=models.CharField(max_length=7,default="#f4f6fb")
    text_color=models.CharField(max_length=7,default="#17213b")
    font_family=models.CharField(max_length=40,default="Inter")
    font_size=models.PositiveSmallIntegerField(default=15)
    accepted_payment_methods=models.JSONField(default=list,blank=True)
    public_sections=models.JSONField(default=list,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.TRIAL,db_index=True)
    onboarding_step=models.PositiveSmallIntegerField(default=1)
    locale=models.CharField(max_length=10,default="pt-br")
    default_locale=models.CharField(max_length=10,default="pt-br")
    timezone=models.CharField(max_length=64,default="America/Recife")
    public_layout=models.CharField(max_length=24,default="editorial")
    public_headline=models.CharField(max_length=120,blank=True)
    public_subheadline=models.CharField(max_length=300,blank=True)
    public_cta_label=models.CharField(max_length=60,blank=True)
    public_announcement=models.CharField(max_length=160,blank=True)
    public_accent_color=models.CharField(max_length=7,blank=True)
    public_section_order=models.JSONField(default=list,blank=True)
    public_seo_title=models.CharField(max_length=70,blank=True)
    public_seo_description=models.CharField(max_length=180,blank=True)
    public_instagram=models.CharField(max_length=120,blank=True)
    metadata=models.JSONField(default=dict,blank=True)
    deleted_at=models.DateTimeField(null=True,blank=True)

    def __str__(self):
        return self.name


class Unit(TimeStampedModel):
    tenant=models.ForeignKey(Tenant,on_delete=models.CASCADE,related_name="units")
    name=models.CharField(max_length=150)
    address=models.CharField(max_length=255,blank=True)
    address_number=models.CharField(max_length=20,blank=True)
    address_complement=models.CharField(max_length=120,blank=True)
    district=models.CharField(max_length=100,blank=True)
    city=models.CharField(max_length=100,blank=True)
    state=models.CharField(max_length=2,blank=True)
    postal_code=models.CharField(max_length=10,blank=True)
    latitude=models.DecimalField(max_digits=10,decimal_places=7,null=True,blank=True)
    longitude=models.DecimalField(max_digits=10,decimal_places=7,null=True,blank=True)
    geocoded_at=models.DateTimeField(null=True,blank=True)
    phone=models.CharField(max_length=32,blank=True)
    whatsapp=models.CharField(max_length=30,blank=True)
    email=models.EmailField(blank=True)
    instagram=models.CharField(max_length=190,blank=True)
    facebook=models.URLField(max_length=255,blank=True)
    tiktok=models.CharField(max_length=190,blank=True)
    website=models.URLField(max_length=255,blank=True)
    map_url=models.URLField(max_length=500,blank=True)
    amenities=models.JSONField(default=list,blank=True)
    payment_methods=models.JSONField(default=list,blank=True)
    public_notes=models.CharField(max_length=500,blank=True)
    is_primary=models.BooleanField(default=False)
    active=models.BooleanField(default=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","active"]),
            models.Index(fields=["active","latitude","longitude"]),
        ]
        constraints=[
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(is_primary=True),
                name="uq_primary_unit_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.tenant} — {self.name}"


class TenantOnboarding(models.Model):
    tenant=models.OneToOneField(Tenant,primary_key=True,on_delete=models.CASCADE,related_name="onboarding")
    company_done=models.BooleanField(default=False)
    branding_done=models.BooleanField(default=False)
    unit_done=models.BooleanField(default=False)
    professional_done=models.BooleanField(default=False)
    service_done=models.BooleanField(default=False)
    schedule_done=models.BooleanField(default=False)
    payment_done=models.BooleanField(default=False)
    public_page_done=models.BooleanField(default=False)
    completed_at=models.DateTimeField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)


class TenantStatusHistory(models.Model):
    tenant=models.ForeignKey(Tenant,on_delete=models.CASCADE,related_name="status_history")
    from_status=models.CharField(max_length=40)
    to_status=models.CharField(max_length=40)
    reason=models.CharField(max_length=500)
    changed_by=models.ForeignKey("accounts.User",on_delete=models.PROTECT,related_name="tenant_status_changes")
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","created_at"],name="tenant_status_hist_idx")]
