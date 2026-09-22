import hashlib
import secrets
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from finance.models import FinancialTransaction,Product,ProductStockMovement
from .models import (
    ArenaCommand,ArenaCommandItem,ArenaCommandStockMovement,
    ClassAttendance,ClassMakeup,ClassStudent,Game,GamePlayer,
    Reservation,SportsClass,Tournament,TournamentMatch,
)


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


@transaction.atomic
def create_game(*,tenant,court,name,starts_at,ends_at,max_players,minimum_players=1,
                modality=None,total_amount=0,split_payment=True,reservation=None,rules="",user=None):
    if ends_at<=starts_at:
        raise ValidationError("O término deve ser posterior ao início.")
    if int(max_players)<1 or int(minimum_players)<1 or int(minimum_players)>int(max_players):
        raise ValidationError("Quantidade de jogadores inválida.")
    return Game.objects.create(
        public_token=secrets.token_hex(16),tenant=tenant,reservation=reservation,court=court,
        modality=modality,name=name,starts_at=starts_at,ends_at=ends_at,
        total_amount=_money(total_amount),max_players=max_players,minimum_players=minimum_players,
        split_payment=split_payment,status=Game.Status.OPEN,rules=rules[:1000],created_by=user,
    )


def _rebalance_game(game):
    active=list(game.players.exclude(participation_status=GamePlayer.ParticipationStatus.CANCELLED))
    if not game.split_payment or not active:
        return
    share=_money(game.total_amount/Decimal(len(active)))
    for player in active:
        if player.payment_status!=GamePlayer.PaymentStatus.PAID:
            GamePlayer.objects.filter(pk=player.pk).update(share_amount=share)


@transaction.atomic
def add_game_player(*,game,name,phone,email="",customer=None):
    game=Game.objects.select_for_update().get(pk=game.pk)
    active=game.players.exclude(participation_status=GamePlayer.ParticipationStatus.CANCELLED).count()
    if active>=game.max_players:
        raise ValidationError("O racha atingiu o limite de jogadores.")
    token=secrets.token_urlsafe(32)
    player=GamePlayer.objects.create(
        game=game,tenant=game.tenant,customer=customer,name=name[:160],phone=phone[:30],email=email,
        share_amount=0,participation_status=GamePlayer.ParticipationStatus.CONFIRMED,
        payment_status=GamePlayer.PaymentStatus.PENDING,
        manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        confirmed_at=timezone.now(),
    )
    _rebalance_game(game)
    player.refresh_from_db()
    return player,token


@transaction.atomic
def record_attendance(*,sports_class,student,class_date,status,notes="",user=None):
    if student.sports_class_id!=sports_class.id or student.tenant_id!=sports_class.tenant_id:
        raise ValidationError("Aluno não pertence a esta turma.")
    valid={value for value,_ in ClassAttendance.Status.choices}
    if status not in valid:
        raise ValidationError("Status de presença inválido.")
    attendance,_=ClassAttendance.objects.update_or_create(
        student=student,class_date=class_date,
        defaults={
            "tenant":sports_class.tenant,"sports_class":sports_class,
            "status":status,"notes":notes[:300],
        },
    )
    if status==ClassAttendance.Status.EXCUSED:
        ClassMakeup.objects.get_or_create(
            tenant=sports_class.tenant,student=student,original_class=sports_class,
            original_date=class_date,
            defaults={"status":ClassMakeup.Status.CREDIT,"notes":"Crédito gerado por falta justificada","created_by":user},
        )
    return attendance


@transaction.atomic
def schedule_makeup(*,makeup,replacement_class,replacement_date):
    makeup=ClassMakeup.objects.select_for_update().get(pk=makeup.pk)
    if makeup.status not in {ClassMakeup.Status.CREDIT,ClassMakeup.Status.SCHEDULED}:
        raise ValidationError("Reposição não está disponível.")
    if replacement_class.tenant_id!=makeup.tenant_id:
        raise ValidationError("Turma de reposição pertence a outra empresa.")
    if replacement_class.students.filter(status=ClassStudent.Status.ACTIVE).count()>=replacement_class.capacity:
        raise ValidationError("Turma de reposição sem vagas.")
    makeup.replacement_class=replacement_class
    makeup.replacement_date=replacement_date
    makeup.status=ClassMakeup.Status.SCHEDULED
    makeup.save(update_fields=["replacement_class","replacement_date","status","updated_at"])
    return makeup


@transaction.atomic
def generate_knockout_bracket(*,tournament):
    tournament=Tournament.objects.select_for_update().get(pk=tournament.pk)
    teams=list(tournament.teams.order_by("id"))
    if len(teams)<2:
        raise ValidationError("Cadastre pelo menos duas equipes.")
    tournament.matches.all().delete()
    size=1
    while size<len(teams):
        size*=2
    padded=teams+[None]*(size-len(teams))
    matches=[]
    first_count=size//2
    for idx in range(first_count):
        home=padded[idx*2]
        away=padded[idx*2+1]
        match=TournamentMatch.objects.create(
            tournament=tournament,tenant=tournament.tenant,
            home_team=home,away_team=away,phase="Rodada 1",round_number=1,
            status=TournamentMatch.Status.SCHEDULED,
        )
        matches.append(match)
    rounds=1
    count=first_count
    while count>1:
        rounds+=1
        count//=2
        for _ in range(count):
            TournamentMatch.objects.create(
                tournament=tournament,tenant=tournament.tenant,
                phase=f"Rodada {rounds}",round_number=rounds,
                status=TournamentMatch.Status.SCHEDULED,
            )
    # Propaga BYEs automaticamente.
    for match in list(tournament.matches.filter(round_number=1).order_by("id")):
        if bool(match.home_team_id)^bool(match.away_team_id):
            winner=match.home_team or match.away_team
            match.status=TournamentMatch.Status.COMPLETED
            match.home_score=1 if match.home_team_id else 0
            match.away_score=1 if match.away_team_id else 0
            match.save(update_fields=["status","home_score","away_score","updated_at"])
            _advance_winner(match,winner)
    tournament.status=Tournament.Status.RUNNING
    tournament.save(update_fields=["status","updated_at"])
    return tournament.matches.count()


def _advance_winner(match,winner):
    current=list(match.tournament.matches.filter(round_number=match.round_number).order_by("id"))
    try:
        index=[m.pk for m in current].index(match.pk)
    except ValueError:
        return
    next_matches=list(match.tournament.matches.filter(round_number=match.round_number+1).order_by("id"))
    if not next_matches:
        match.tournament.champion_team=winner
        match.tournament.status=Tournament.Status.COMPLETED
        match.tournament.save(update_fields=["champion_team","status","updated_at"])
        return
    target=next_matches[index//2]
    if index%2==0:
        target.home_team=winner
        target.save(update_fields=["home_team","updated_at"])
    else:
        target.away_team=winner
        target.save(update_fields=["away_team","updated_at"])


@transaction.atomic
def record_match_result(*,match,home_score,away_score):
    match=TournamentMatch.objects.select_for_update().select_related("home_team","away_team","tournament").get(pk=match.pk)
    if not match.home_team_id or not match.away_team_id:
        raise ValidationError("Partida ainda não possui as duas equipes.")
    home_score=int(home_score); away_score=int(away_score)
    if home_score<0 or away_score<0 or home_score==away_score:
        raise ValidationError("Informe um placar sem empate para mata-mata.")
    match.home_score=home_score
    match.away_score=away_score
    match.status=TournamentMatch.Status.COMPLETED
    match.save(update_fields=["home_score","away_score","status","updated_at"])
    winner=match.home_team if home_score>away_score else match.away_team
    _advance_winner(match,winner)
    return winner


@transaction.atomic
def open_arena_command(*,tenant,user,reservation=None,customer=None,notes=""):
    if reservation and reservation.tenant_id!=tenant.id:
        raise ValidationError("Reserva pertence a outra empresa.")
    customer=customer or (reservation.customer if reservation else None)
    return ArenaCommand.objects.create(
        public_id=secrets.token_hex(16),tenant=tenant,reservation=reservation,customer=customer,
        opened_by=user,opened_at=timezone.now(),notes=notes[:500],
    )


@transaction.atomic
def add_command_product(*,command,product,quantity=1,unit_price=None):
    command=ArenaCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=ArenaCommand.Status.OPEN:
        raise ValidationError("Comanda não está aberta.")
    product=Product.objects.get(pk=product.pk,tenant=command.tenant)
    quantity=Decimal(str(quantity))
    price=_money(product.sale_price if unit_price in (None,"") else unit_price)
    total=_money(quantity*price)
    if quantity<=0:
        raise ValidationError("Quantidade inválida.")
    item=ArenaCommandItem.objects.create(
        command=command,tenant=command.tenant,product=product,description=product.name,
        quantity=quantity,unit_price=price,cost_snapshot=product.cost_price,total=total,
    )
    recalculate_arena_command(command)
    return item


def recalculate_arena_command(command):
    subtotal=sum((row.total for row in command.items.all()),Decimal("0"))
    total=_money(subtotal-command.discount+command.surcharge)
    if total<0:
        raise ValidationError("Total não pode ser negativo.")
    ArenaCommand.objects.filter(pk=command.pk).update(subtotal=_money(subtotal),total=total,updated_at=timezone.now())
    command.subtotal=_money(subtotal); command.total=total
    return command


@transaction.atomic
def close_arena_command(*,command,user,payment_method):
    command=ArenaCommand.objects.select_for_update().get(pk=command.pk)
    if command.status==ArenaCommand.Status.CLOSED:
        return command
    recalculate_arena_command(command)
    if command.total>0 and not payment_method:
        raise ValidationError("Informe a forma de pagamento.")
    for item in command.items.select_related("product"):
        if not item.product_id:
            continue
        product=Product.objects.select_for_update().get(pk=item.product_id)
        if product.stock<item.quantity:
            raise ValidationError(f"Estoque insuficiente para {product.name}.")
        product.stock-=item.quantity
        product.save(update_fields=["stock","updated_at"])
        ProductStockMovement.objects.create(
            tenant=command.tenant,product=product,type=ProductStockMovement.Type.COMMAND,
            quantity=-item.quantity,balance_after=product.stock,user=user,
            reason=f"Comanda Arena #{command.pk}",
        )
        ArenaCommandStockMovement.objects.get_or_create(
            tenant=command.tenant,command=command,product=product,
            movement_type=ArenaCommandStockMovement.Type.COMMAND_CLOSE,
            defaults={"quantity":-item.quantity,"balance_after":product.stock},
        )
    FinancialTransaction.objects.get_or_create(
        tenant=command.tenant,idempotency_key=f"arena-command:{command.pk}",
        defaults={
            "source_type":"arena_command","source_id":command.pk,
            "type":FinancialTransaction.Type.INCOME,
            "description":f"Comanda Arena #{command.pk}","amount":command.total,
            "payment_method":payment_method or "other","competence_at":timezone.localdate(),
            "status":FinancialTransaction.Status.PAID,"paid_at":timezone.now(),
        },
    )
    command.payment_method=payment_method[:40]
    command.payment_status=ArenaCommand.PaymentStatus.PAID
    command.status=ArenaCommand.Status.CLOSED
    command.closed_by=user; command.closed_at=timezone.now()
    command.save(update_fields=["payment_method","payment_status","status","closed_by","closed_at","updated_at"])
    return command
