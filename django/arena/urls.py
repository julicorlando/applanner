from django.urls import path
from . import portal

urlpatterns=[
    path("jogos/",portal.games,name="arena-games"),
    path("jogos/<int:pk>/",portal.game_detail,name="arena-game-detail"),
    path("turmas/<int:pk>/",portal.class_detail,name="arena-class-detail"),
    path("torneios/<int:pk>/",portal.tournament_detail,name="arena-tournament-detail"),
    path("comandas/",portal.commands,name="arena-commands"),
    path("comandas/<int:pk>/",portal.command_detail,name="arena-command-detail"),
]
