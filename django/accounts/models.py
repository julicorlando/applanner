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

    USERNAME_FIELD="email"
    REQUIRED_FIELDS=[]

    objects=UserManager()

    def __str__(self):
        return self.email
