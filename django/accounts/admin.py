from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class ApPlannerUserAdmin(UserAdmin):
    ordering=("email",)
    list_display=("email","first_name","last_name","role","tenant","is_active","is_staff")
    search_fields=("email","first_name","last_name")
    fieldsets=(
        (None,{"fields":("email","password")}),
        ("Perfil",{"fields":("first_name","last_name","tenant","role","locale","must_change_password")}),
        ("Permissões",{"fields":("is_active","is_staff","is_superuser","groups","user_permissions")}),
        ("Datas",{"fields":("last_login","date_joined")}),
    )
    add_fieldsets=(
        (None,{"classes":("wide",),"fields":("email","password1","password2","tenant","role","is_staff","is_superuser")}),
    )
