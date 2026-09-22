from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from finance.models import Product
from scheduling.models import Customer
from tenants.models import Tenant
from .models import (
    ArenaCommand,ClassAttendance,ClassStudent,Court,Game,Modality,
    Reservation,SportsClass,Tournament,TournamentMatch,
)
from .operations import (
    add_command_product,add_game_player,close_arena_command,create_game,
    generate_knockout_bracket,open_arena_command,record_attendance,record_match_result,
)


def _tenant(request):
    if request.user.tenant_id:
        return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:
            return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


class GameForm(forms.Form):
    court=forms.ModelChoiceField(queryset=Court.objects.none())
    modality=forms.ModelChoiceField(queryset=Modality.objects.none(),required=False)
    name=forms.CharField(max_length=160)
    starts_at=forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"),input_formats=["%Y-%m-%dT%H:%M"])
    ends_at=forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"),input_formats=["%Y-%m-%dT%H:%M"])
    total_amount=forms.DecimalField(min_value=0,decimal_places=2,max_digits=12)
    max_players=forms.IntegerField(min_value=1,initial=10)
    minimum_players=forms.IntegerField(min_value=1,initial=2)
    split_payment=forms.BooleanField(required=False,initial=True)
    rules=forms.CharField(required=False,widget=forms.Textarea(attrs={"rows":3}))
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["court"].queryset=Court.objects.filter(tenant=tenant,active=True)
        self.fields["modality"].queryset=Modality.objects.filter(tenant=tenant,active=True)


class PlayerForm(forms.Form):
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),required=False)
    name=forms.CharField(max_length=160)
    phone=forms.CharField(max_length=30)
    email=forms.EmailField(required=False)
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")


class CommandForm(forms.Form):
    reservation=forms.ModelChoiceField(queryset=Reservation.objects.none(),required=False)
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),required=False)
    notes=forms.CharField(required=False,widget=forms.Textarea(attrs={"rows":3}))
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["reservation"].queryset=Reservation.objects.filter(tenant=tenant).order_by("-starts_at")[:500]
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")


class ProductForm(forms.Form):
    product=forms.ModelChoiceField(queryset=Product.objects.none())
    quantity=forms.DecimalField(min_value=0.001,decimal_places=3,max_digits=12,initial=1)
    unit_price=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12)
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True).order_by("name")


@login_required
def games(request):
    tenant=_tenant(request)
    form=GameForm(request.POST or None,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        try:
            game=create_game(tenant=tenant,user=request.user,**form.cleaned_data)
            messages.success(request,"Racha criado.")
            return redirect("arena-game-detail",pk=game.pk)
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,"arena/games.html",{"tenant":tenant,"games":Game.objects.filter(tenant=tenant).order_by("-starts_at")[:100],"form":form})


@login_required
def game_detail(request,pk):
    tenant=_tenant(request)
    game=get_object_or_404(Game.objects.prefetch_related("players"),pk=pk,tenant=tenant)
    form=PlayerForm(request.POST or None,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        try:
            add_game_player(game=game,**form.cleaned_data)
            messages.success(request,"Jogador adicionado e rateio recalculado.")
            return redirect("arena-game-detail",pk=game.pk)
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,"arena/game_detail.html",{"game":game,"form":form})


@login_required
def class_detail(request,pk):
    tenant=_tenant(request)
    sports_class=get_object_or_404(SportsClass.objects.prefetch_related("students__customer"),pk=pk,tenant=tenant)
    if request.method=="POST":
        student=get_object_or_404(ClassStudent,pk=request.POST.get("student"),sports_class=sports_class,tenant=tenant)
        try:
            record_attendance(
                sports_class=sports_class,student=student,class_date=request.POST.get("class_date"),
                status=request.POST.get("status"),notes=request.POST.get("notes",""),user=request.user,
            )
            messages.success(request,"Presença registrada.")
        except ValidationError as exc: messages.error(request,str(exc))
        return redirect("arena-class-detail",pk=pk)
    return render(request,"arena/class_detail.html",{"sports_class":sports_class,"attendance_choices":ClassAttendance.Status.choices})


@login_required
def tournament_detail(request,pk):
    tenant=_tenant(request)
    tournament=get_object_or_404(Tournament.objects.prefetch_related("teams","matches__home_team","matches__away_team"),pk=pk,tenant=tenant)
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="generate":
                total=generate_knockout_bracket(tournament=tournament)
                messages.success(request,f"Chave gerada com {total} partidas.")
            elif action=="result":
                match=get_object_or_404(TournamentMatch,pk=request.POST.get("match"),tournament=tournament,tenant=tenant)
                winner=record_match_result(match=match,home_score=request.POST.get("home_score"),away_score=request.POST.get("away_score"))
                messages.success(request,f"Resultado salvo. Vencedor: {winner.name}.")
        except (ValidationError,ValueError) as exc: messages.error(request,str(exc))
        return redirect("arena-tournament-detail",pk=pk)
    return render(request,"arena/tournament_detail.html",{"tournament":tournament})


@login_required
def commands(request):
    tenant=_tenant(request)
    form=CommandForm(request.POST or None,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        try:
            command=open_arena_command(tenant=tenant,user=request.user,**form.cleaned_data)
            messages.success(request,"Comanda Arena aberta.")
            return redirect("arena-command-detail",pk=command.pk)
        except ValidationError as exc: form.add_error(None,exc)
    return render(request,"arena/commands.html",{"commands":ArenaCommand.objects.filter(tenant=tenant).order_by("-opened_at")[:100],"form":form})


@login_required
def command_detail(request,pk):
    tenant=_tenant(request)
    command=get_object_or_404(ArenaCommand.objects.prefetch_related("items"),pk=pk,tenant=tenant)
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="product":
                form=ProductForm(request.POST,tenant=tenant)
                if not form.is_valid(): raise ValidationError("; ".join(sum(form.errors.values(),[])))
                add_command_product(command=command,**form.cleaned_data)
                messages.success(request,"Produto adicionado.")
            elif action=="close":
                close_arena_command(command=command,user=request.user,payment_method=request.POST.get("payment_method",""))
                messages.success(request,"Comanda fechada com estoque e financeiro atualizados.")
        except (ValidationError,ValueError) as exc: messages.error(request,str(exc))
        return redirect("arena-command-detail",pk=pk)
    return render(request,"arena/command_detail.html",{"command":command,"product_form":ProductForm(tenant=tenant)})
