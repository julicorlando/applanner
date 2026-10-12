from django.urls import path
from . import portal
from .material_portal import materials
from .statement import statement

urlpatterns=[
    path("competencia/",statement,name="finance-statement"),
    path("insumos/",materials,name="finance-materials"),
    path("resumo/",portal.summary,name="finance-summary"),
    path("pdv/",portal.pos,name="finance-pos"),
    path("pdv/<int:pk>/cancelar/",portal.sale_cancel,name="finance-sale-cancel"),
    path("caixa/",portal.cash,name="finance-cash"),
    path("comissoes/",portal.commissions,name="finance-commissions"),
]
