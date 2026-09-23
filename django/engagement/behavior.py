from datetime import timedelta
from decimal import Decimal
from statistics import mean, median, pstdev

from django.db import transaction

from scheduling.models import Appointment
from .models import BehaviorProfile, BehaviorServiceProfile


def _stats(rows):
    rows=list(rows)
    visits=len(rows)
    if not rows:
        return {
            "visits_count":0,"intervals":[],"avg":None,"median":None,
            "stddev":None,"last":None,"next":None,"confidence":0,
        }
    starts=[row.starts_at for row in rows]
    intervals=[
        max(0,(starts[i].date()-starts[i-1].date()).days)
        for i in range(1,len(starts))
    ]
    positive=[value for value in intervals if value>0]
    avg=Decimal(str(round(mean(positive),2))) if positive else None
    med=Decimal(str(round(median(positive),2))) if positive else None
    std=Decimal(str(round(pstdev(positive),2))) if len(positive)>1 else Decimal("0.00") if positive else None
    baseline=med or avg
    expected=starts[-1].date()+timedelta(days=max(1,int(round(float(baseline))))) if baseline else None
    stability=100
    if avg and std is not None and avg>0:
        stability=max(0,100-int(min(100,float(std/avg)*100)))
    confidence=min(100,int(min(visits,6)*12 + stability*0.28)) if visits>=2 else min(25,visits*15)
    return {
        "visits_count":visits,
        "intervals":intervals[-24:],
        "avg":avg,"median":med,"stddev":std,
        "last":starts[-1],"next":expected,"confidence":confidence,
    }


def _defaults(stats):
    return {
        "avg_interval_days":stats["avg"],
        "median_interval_days":stats["median"],
        "std_deviation_days":stats["stddev"],
        "last_visit_at":stats["last"],
        "next_expected_date":stats["next"],
        "confidence_score":stats["confidence"],
        "visits_count":stats["visits_count"],
        "intervals":stats["intervals"],
    }


@transaction.atomic
def refresh_behavior_for_tenant(tenant):
    completed=(
        Appointment.objects.filter(tenant=tenant,status=Appointment.Status.COMPLETED)
        .select_related("customer","service").order_by("customer_id","starts_at")
    )
    customer_ids=set(completed.values_list("customer_id",flat=True))
    service_pairs=set(completed.values_list("customer_id","service_id"))

    updated=0
    for customer_id in customer_ids:
        rows=completed.filter(customer_id=customer_id).order_by("starts_at")
        BehaviorProfile.objects.update_or_create(
            tenant=tenant,customer_id=customer_id,defaults=_defaults(_stats(rows))
        )
        updated+=1

    for customer_id,service_id in service_pairs:
        rows=completed.filter(customer_id=customer_id,service_id=service_id).order_by("starts_at")
        BehaviorServiceProfile.objects.update_or_create(
            tenant=tenant,customer_id=customer_id,service_id=service_id,
            defaults=_defaults(_stats(rows)),
        )
        updated+=1

    BehaviorProfile.objects.filter(tenant=tenant).exclude(customer_id__in=customer_ids).delete()
    BehaviorServiceProfile.objects.filter(tenant=tenant).exclude(
        customer_id__in=customer_ids
    ).delete()
    return updated
