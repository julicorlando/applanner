from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from arena.models import Court,Game,Modality,Tournament,TournamentTeam
from arena.operations import add_game_player,create_game,generate_knockout_bracket,record_match_result
from tenants.models import Tenant


class ArenaOperationsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Arena",slug="arena-ops")
        self.user=User.objects.create_user(email="arena@example.com",password="StrongPassword123!",tenant=self.tenant)
        self.court=Court.objects.create(tenant=self.tenant,name="Quadra 1",slug="q1",minimum_minutes=30,maximum_minutes=180,interval_minutes=0)
        self.modality=Modality.objects.create(tenant=self.tenant,name="Futebol",slug="futebol")

    def test_game_split_rebalances(self):
        start=timezone.now()+timedelta(days=1)
        game=create_game(tenant=self.tenant,court=self.court,name="Racha",starts_at=start,ends_at=start+timedelta(hours=1),max_players=10,total_amount="100",user=self.user)
        p1,_=add_game_player(game=game,name="A",phone="1")
        p2,_=add_game_player(game=game,name="B",phone="2")
        p1.refresh_from_db();p2.refresh_from_db()
        self.assertEqual(str(p1.share_amount),"50.00")
        self.assertEqual(str(p2.share_amount),"50.00")

    def test_knockout_advances_winner(self):
        tournament=Tournament.objects.create(tenant=self.tenant,name="Copa",format=Tournament.Format.KNOCKOUT,starts_on=timezone.localdate())
        TournamentTeam.objects.create(tournament=tournament,tenant=self.tenant,name="A")
        TournamentTeam.objects.create(tournament=tournament,tenant=self.tenant,name="B")
        self.assertEqual(generate_knockout_bracket(tournament=tournament),1)
        match=tournament.matches.get()
        winner=record_match_result(match=match,home_score=2,away_score=1)
        tournament.refresh_from_db()
        self.assertEqual(tournament.champion_team,winner)
        self.assertEqual(tournament.status,Tournament.Status.COMPLETED)
