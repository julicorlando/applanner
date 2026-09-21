from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations=True

    def create_user(self,email,password=None,**extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        email=self.normalize_email(email).lower()
        user=self.model(email=email,**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self,email,password=None,**extra_fields):
        extra_fields.setdefault("is_staff",True)
        extra_fields.setdefault("is_superuser",True)
        extra_fields.setdefault("is_active",True)
        return self.create_user(email,password,**extra_fields)


class User(AbstractUser):
    username=None
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.CASCADE,related_name="users")
    email=models.EmailField(unique=True)
    role=models.CharField(max_length=60,default="user",db_index=True)
    must_change_password=models.BooleanField(default=False)
    locale=models.CharField(max_length=10,default="pt-br")
    session_version=models.PositiveIntegerField(default=1)
    two_factor_secret_encrypted=models.TextField(blank=True)
    two_factor_enabled_at=models.DateTimeField(null=True,blank=True)
    two_factor_last_step=models.BigIntegerField(default=0)

    USERNAME_FIELD="email"
    REQUIRED_FIELDS=[]

    objects=UserManager()

    @property
    def two_factor_enabled(self):
        return bool(self.two_factor_secret_encrypted and self.two_factor_enabled_at)

    def __str__(self):
        return self.email


class RecoveryCode(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name="recovery_codes")
    code_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    used_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["user","used_at"])]


class TrustedDevice(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name="trusted_devices")
    selector=models.CharField(max_length=64,unique=True)
    verifier_hash=models.CharField(max_length=64)
    label=models.CharField(max_length=180,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    session_version=models.PositiveIntegerField()
    expires_at=models.DateTimeField(db_index=True)
    last_used_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["user","expires_at"])]


class Capability(models.Model):
    slug=models.CharField(max_length=120,unique=True)
    name=models.CharField(max_length=150)

    def __str__(self):
        return self.name


class PlatformRole(models.Model):
    slug=models.CharField(max_length=60,unique=True)
    name=models.CharField(max_length=100)
    capabilities=models.ManyToManyField(Capability,through="RoleCapability",related_name="roles",blank=True)

    def __str__(self):
        return self.name


class RoleCapability(models.Model):
    role=models.ForeignKey(PlatformRole,on_delete=models.CASCADE,related_name="capability_links")
    capability=models.ForeignKey(Capability,on_delete=models.CASCADE,related_name="role_links")

    class Meta:
        constraints=[models.UniqueConstraint(fields=["role","capability"],name="uq_role_capability")]


class UserRole(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name="role_links")
    role=models.ForeignKey(PlatformRole,on_delete=models.CASCADE,related_name="user_links")

    class Meta:
        constraints=[models.UniqueConstraint(fields=["user","role"],name="uq_user_platform_role")]


class LoginHistory(models.Model):
    user=models.ForeignKey(User,null=True,blank=True,on_delete=models.SET_NULL,related_name="login_history")
    email=models.EmailField()
    successful=models.BooleanField()
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    user_agent=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[
            models.Index(fields=["user","created_at"]),
            models.Index(fields=["email","created_at"]),
        ]
