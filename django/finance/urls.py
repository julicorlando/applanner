from django.urls import path
from . import portal

urlpatterns=[
    path("pdv/",portal.pos,name="finance-pos"),
    path("pdv/<int:pk>/cancelar/",portal.sale_cancel,name="finance-sale-cancel"),
    path("caixa/",portal.cash,name="finance-cash"),
    path("comissoes/",portal.commissions,name="finance-commissions"),
]
