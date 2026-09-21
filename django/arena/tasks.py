from celery import shared_task

from .membership import generate_membership
from .models import Membership


@shared_task
def generate_due_memberships(limit=250):
    memberships=(
        Membership.objects
        .filter(status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .order_by("next_generation_date","id")[:max(1,min(500,int(limit)))]
    )
    result={"memberships":0,"generated":0,"conflicts":0}
    for membership in memberships:
        try:
            one=generate_membership(membership)
        except Exception:
            continue
        result["memberships"]+=1
        result["generated"]+=one["generated"]
        result["conflicts"]+=one["conflicts"]
    return result
