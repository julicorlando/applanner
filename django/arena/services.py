import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ArenaSettings, Court, CourtBlock, CourtHours, PriceRule,
    Reservation, ReservationFinance, ReservationHistory, SportsSettings,
)


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)


class ArenaReservationService:
    def sports_settings(self,tenant):
        obj,_=SportsSettings.objects.get_or_create(tenant=tenant)
        return obj

    def arena_settings(self,tenant):
        obj,_=ArenaSettings.objects.get_or_create(tenant=tenant)
        return obj

    def is_available(self,tenant,court,start,end,exclude_reservation_id=None,public_rules=True):
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        start=start.astimezone(tz)
        end=end.astimezone(tz)
        if end<=start or start.date()!=end.date():
            return False

        minutes=int((end-start).total_seconds()//60)
        if minutes<court.minimum_minutes or minutes>court.maximum_minutes:
            return False

        settings_obj=self.sports_settings(tenant)
        now=timezone.now().astimezone(tz)
        if public_rules:
            if start < now+timedelta(minutes=settings_obj.minimum_notice_minutes):
                return False
            if start > now+timedelta(days=settings_obj.maximum_days_ahead):
                return False

        hours=CourtHours.objects.filter(
            tenant=tenant,court=court,weekday=start.isoweekday(),active=True
        )
        inside=False
        for row in hours:
            window_start=datetime.combine(start.date(),row.start_time,tzinfo=tz)
            window_end=datetime.combine(start.date(),row.end_time,tzinfo=tz)
            if start>=window_start and end<=window_end:
                inside=True
                break
        if not inside:
            return False

        if CourtBlock.objects.filter(
            tenant=tenant,court=court,status=CourtBlock.Status.ACTIVE,
            starts_at__lt=end,ends_at__gt=start,
        ).exists():
            return False

        conflicts=Reservation.objects.filter(
            tenant=tenant,court=court,
            status__in=[
                Reservation.Status.PENDING_PAYMENT,
                Reservation.Status.CONFIRMED,
                Reservation.Status.COMPLETED,
            ],
            starts_at__lt=end,ends_at__gt=start,
        )
        if exclude_reservation_id:
            conflicts=conflicts.exclude(pk=exclude_reservation_id)
        return not conflicts.exists()

    def _matching_price_rule(self,tenant,court,start,end,modality=None):
        duration=int((end-start).total_seconds()//60)
        day=start.date()
        rows=PriceRule.objects.filter(
            tenant=tenant,court=court,active=True
        ).order_by("-priority","id")
        best=None
        best_score=-1
        for row in rows:
            if row.modality_id and (not modality or row.modality_id!=modality.id):
                continue
            if row.weekday and row.weekday!=start.isoweekday():
                continue
            if row.specific_date and row.specific_date!=day:
                continue
            if row.valid_from and day<row.valid_from:
                continue
            if row.valid_to and day>row.valid_to:
                continue
            if row.start_time and start.timetz().replace(tzinfo=None)<row.start_time:
                continue
            if row.end_time and end.timetz().replace(tzinfo=None)>row.end_time:
                continue
            if row.minimum_duration_minutes and duration<row.minimum_duration_minutes:
                continue
            if row.maximum_duration_minutes and duration>row.maximum_duration_minutes:
                continue
            score=row.priority*100
            score+=40 if row.specific_date else 0
            score+=20 if row.rule_type!=PriceRule.RuleType.STANDARD else 0
            score+=10 if row.modality_id else 0
            score+=5 if row.weekday else 0
            score+=2 if row.start_time or row.end_time else 0
            if score>best_score:
                best=row
                best_score=score
        return best

    def _occupancy_percent(self,tenant,court,day):
        tz=ZoneInfo(tenant.timezone or "America/Recife")
        hours=CourtHours.objects.filter(
            tenant=tenant,court=court,weekday=day.isoweekday(),active=True
        )
        available=0
        for row in hours:
            a=datetime.combine(day,row.start_time,tzinfo=tz)
            b=datetime.combine(day,row.end_time,tzinfo=tz)
            available+=max(0,int((b-a).total_seconds()//60))
        if available<=0:
            return Decimal("0")
        start_day=datetime.combine(day,datetime.min.time(),tzinfo=tz)
        end_day=start_day+timedelta(days=1)
        occupied=0
        for row in Reservation.objects.filter(
            tenant=tenant,court=court,
            status__in=[Reservation.Status.PENDING_PAYMENT,Reservation.Status.CONFIRMED],
            starts_at__lt=end_day,ends_at__gt=start_day,
        ):
            occupied+=max(0,int((min(row.ends_at,end_day)-max(row.starts_at,start_day)).total_seconds()//60))
        return (Decimal(occupied)*Decimal("100")/Decimal(available)).quantize(Decimal("0.01"))

    def quote(self,tenant,court,start,end,modality=None):
        rule=self._matching_price_rule(tenant,court,start,end,modality)
        if not rule:
            raise ValidationError("Nenhuma regra de preço disponível para este horário.")
        duration=Decimal(str((end-start).total_seconds()/60))
        base=_money(rule.price_per_hour*duration/Decimal("60"))
        settings_obj=self.arena_settings(tenant)
        multiplier=Decimal("1")
        details={"rule_id":rule.pk,"base":str(base)}

        if settings_obj.dynamic_pricing_enabled:
            occupancy=self._occupancy_percent(tenant,court,start.date())
            details["occupancy_percent"]=str(occupancy)
            now=timezone.now().astimezone(start.tzinfo)

            if start-now<=timedelta(hours=settings_obj.dynamic_last_minute_hours):
                multiplier*=Decimal("1")-(settings_obj.dynamic_last_minute_discount_percent/Decimal("100"))
                details["last_minute"]=True

            if occupancy>=settings_obj.dynamic_high_occupancy_threshold:
                multiplier*=Decimal("1")+(settings_obj.dynamic_high_occupancy_surcharge_percent/Decimal("100"))
                details["high_occupancy"]=True
            elif occupancy<=settings_obj.dynamic_low_occupancy_threshold:
                multiplier*=Decimal("1")-(settings_obj.dynamic_low_occupancy_discount_percent/Decimal("100"))
                details["low_occupancy"]=True

            if start.isoweekday() in {6,7} and settings_obj.dynamic_weekend_surcharge_percent:
                multiplier*=Decimal("1")+(settings_obj.dynamic_weekend_surcharge_percent/Decimal("100"))
                details["weekend"]=True

            multiplier=max(settings_obj.dynamic_min_multiplier,min(settings_obj.dynamic_max_multiplier,multiplier))

        total=_money(base*multiplier)
        step=settings_obj.dynamic_rounding_step
        if step and step>0:
            total=(total/step).quantize(Decimal("1"),rounding=ROUND_HALF_UP)*step
            total=_money(total)
        details["multiplier"]=str(multiplier.quantize(Decimal("0.0001")))
        details["total"]=str(total)
        return {"rule":rule,"base_total":base,"multiplier":multiplier,"total":total,"details":details}

    @transaction.atomic
    def create_reservation(
        self,*,tenant,court,start,end,customer_name,customer_phone,
        customer_email="",customer=None,modality=None,payment_method="onsite",
        source=Reservation.Source.PUBLIC,created_by=None,notes="",accept_terms=False,
        public_rules=True
    ):
        court=Court.objects.select_for_update().get(pk=court.pk,tenant=tenant,active=True)
        if not self.is_available(tenant,court,start,end,public_rules=public_rules):
            raise ValidationError("Este horário não está mais disponível.")
        if modality and not court.modalities.filter(pk=modality.pk).exists():
            raise ValidationError("Modalidade não disponível nesta quadra.")

        quote=self.quote(tenant,court,start,end,modality)
        settings_obj=self.sports_settings(tenant)
        deposit=Decimal("0")
        if settings_obj.require_deposit:
            if settings_obj.deposit_type==SportsSettings.DepositType.FIXED:
                deposit=min(quote["total"],_money(settings_obj.deposit_value))
            else:
                deposit=_money(quote["total"]*settings_obj.deposit_value/Decimal("100"))

        pending=settings_obj.require_deposit and deposit>0
        token=secrets.token_urlsafe(32)
        public_id=secrets.token_hex(16)
        minutes=int((end-start).total_seconds()//60)
        reservation=Reservation.objects.create(
            public_id=public_id,
            tenant=tenant,
            court=court,
            modality=modality,
            customer=customer,
            customer_name=customer_name[:160],
            customer_phone=customer_phone[:30],
            customer_email=customer_email,
            starts_at=start,
            ends_at=end,
            duration_minutes=minutes,
            price_per_hour=quote["rule"].price_per_hour,
            total_amount=quote["total"],
            base_total_amount=quote["base_total"],
            pricing_multiplier=quote["multiplier"],
            pricing_details=quote["details"],
            deposit_amount=deposit,
            status=Reservation.Status.PENDING_PAYMENT if pending else Reservation.Status.CONFIRMED,
            payment_method=payment_method,
            payment_status=Reservation.PaymentStatus.PENDING if pending else Reservation.PaymentStatus.NOT_REQUIRED,
            manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            source=source,
            notes=notes[:1000],
            terms_accepted_at=timezone.now() if accept_terms else None,
            confirmed_at=None if pending else timezone.now(),
            created_by=created_by,
        )
        ReservationFinance.objects.create(
            reservation=reservation,
            tenant=tenant,
            payment_state=ReservationFinance.State.PENDING if pending else ReservationFinance.State.NOT_REQUIRED,
            gross_amount=quote["total"],
            deposit_due=deposit,
        )
        ReservationHistory.objects.create(
            reservation=reservation,
            action="created",
            new_status=reservation.status,
            actor_user=created_by,
        )
        return reservation,token
