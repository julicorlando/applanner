from decimal import Decimal


CYCLE_MONTHS={"monthly":1,"quarterly":3,"semiannual":6,"annual":12}


def cycle_months(subscription):
    return CYCLE_MONTHS.get(subscription.billing_cycle,1)


def subscription_charge_breakdown(subscription):
    months=cycle_months(subscription)
    plan=subscription.plan
    base=subscription.base_contracted_price
    if base is None:
        prices={
            "monthly":plan.monthly_price,
            "quarterly":plan.quarterly_price,
            "semiannual":plan.semiannual_price,
            "annual":plan.annual_price,
        }
        configured=prices.get(subscription.billing_cycle)
        base=Decimal(configured if configured is not None else plan.monthly_price*months)
    base=Decimal(base or 0).quantize(Decimal("0.01"))

    addons=[]
    for addon in subscription.tenant.module_addons.select_related("module").filter(
        status="active",billing_mode="merged_subscription"
    ).order_by("module__sort_order","module__name"):
        monthly=Decimal(addon.monthly_price or 0).quantize(Decimal("0.01"))
        addons.append({
            "slug":addon.module.slug,
            "name":addon.module.name,
            "quantity":int(addon.quantity or 1),
            "monthly":str(monthly),
            "cycle_total":str((monthly*months).quantize(Decimal("0.01"))),
            "per_unit":bool(addon.module.per_unit_billing),
            "unit_price":str(Decimal(addon.module.addon_monthly_price or 0).quantize(Decimal("0.01"))),
        })

    addon_total=sum((Decimal(item["cycle_total"]) for item in addons),Decimal("0.00"))
    contracted=Decimal(subscription.contracted_price or (base+addon_total)).quantize(Decimal("0.01"))
    adjustment=(contracted-base-addon_total).quantize(Decimal("0.01"))
    active_units=subscription.tenant.units.filter(active=True).count()
    return {
        "cycle":subscription.billing_cycle,
        "cycle_label":subscription.get_billing_cycle_display(),
        "months":months,
        "plan":{"name":plan.name,"amount":str(base)},
        "addons":addons,
        "active_units":active_units,
        "adjustment":str(adjustment),
        "total":str(contracted),
    }
