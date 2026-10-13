"""Financial snapshots from authenticated payment responses; never estimate fees."""
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from .models import Payment, PaymentGateway


def money(value):
    try: amount=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError): raise ValueError('Valor financeiro inválido.')
    if not amount.is_finite() or amount<0 or amount.quantize(Decimal('.01'))!=amount:
        raise ValueError('Valor financeiro inválido.')
    return amount


def capture_accounting(payment,remote):
    """Caller supplies only a response retrieved using the platform credential."""
    if (str(remote.get('id',''))!=payment.provider_payment_id
        or remote.get('currency_id')!='BRL'
        or money(remote.get('transaction_amount'))!=payment.amount
        or remote.get('external_reference')!=payment.provider_reference
        or not isinstance(remote.get('live_mode'),bool)
        or remote['live_mode']!=(payment.environment=='production')):
        raise ValueError('Dados financeiros não correspondem à cobrança.')
    status=remote.get('status')
    if status not in {'approved','refunded','charged_back','partially_refunded'}: return False
    refunded=money(remote.get('transaction_amount_refunded',remote.get('amount_refunded',0)))
    if status in {'refunded','charged_back'}: refunded=payment.amount
    if status=='partially_refunded' and not any(k in remote for k in ('transaction_amount_refunded','amount_refunded')):
        raise ValueError('Valor do estorno parcial não informado pelo provedor.')
    prior=(payment.metadata or {}).get('accounting') or {}
    if (payment.status=='refunded' and status not in {'refunded','charged_back'}) or refunded<money(prior.get('refunded',0)):
        raise ValueError('A consulta não pode desfazer um estorno confirmado.')
    if status=='partially_refunded' and refunded==0: raise ValueError('Estorno parcial sem valor confirmado.')
    if refunded>payment.amount: raise ValueError('Estorno superior à cobrança.')
    details=remote.get('transaction_details') or {}
    net_raw=details.get('net_received_amount')
    fees_raw=remote.get('fee_details')
    fee=None
    if isinstance(fees_raw,list): fee=sum((money(item['amount']) for item in fees_raw),Decimal('0'))
    net=money(net_raw) if net_raw is not None else None
    # Net is retained separately; no assumptions about fee refunds or wallet availability.
    if net is not None and net>payment.amount: raise ValueError('Líquido superior ao valor bruto.')
    if net is not None and refunded==0: fee=payment.amount-net
    if fee is not None and fee>payment.amount: raise ValueError('Taxa superior à cobrança.')
    snapshot={'fee':str(fee) if fee is not None else None,'net_received':str(net) if net is not None else None,
              'refunded':str(refunded),'status':status,'checked_at':timezone.now().isoformat()}
    payment.metadata={**(payment.metadata or {}),'accounting':snapshot}
    return True


def reconcile_financial_payment(pk):
    from .payment_services import platform_provider
    row=Payment.objects.get(pk=pk)
    gateway=PaymentGateway.objects.filter(provider=row.provider,environment=row.environment,active=True,last_test_status='validated').first()
    if not gateway or not row.provider_payment_id: raise ValueError('Conexão ou pagamento indisponível.')
    snapshot=(row.provider_payment_id,row.provider_reference,row.environment,row.amount)
    remote=platform_provider(gateway).get_payment(row.provider_payment_id)
    with transaction.atomic():
        row=Payment.objects.select_for_update().get(pk=pk)
        if snapshot!=(row.provider_payment_id,row.provider_reference,row.environment,row.amount):
            raise ValueError('Cobrança alterada durante a consulta.')
        changed=capture_accounting(row,remote)
        if changed:
            status=remote.get('status')
            if status in {'refunded','charged_back'}: row.status='refunded'
            elif status=='partially_refunded' or money(row.metadata['accounting']['refunded'])>0: row.status='partially_refunded'
            row.save(update_fields=['metadata','status'])
        return changed


def accounting_totals(rows):
    fees=refunded=net=Decimal('0')
    missing=0
    for row in rows:
        data=(row.metadata or {}).get('accounting') or {}
        if data.get('fee') is None: missing+=1
        else: fees+=money(data['fee'])
        if row.status=='refunded': refunded+=row.amount
        else: refunded+=money(data.get('refunded',0))
        if data.get('net_received') is not None: net+=money(data['net_received'])
    return {'provider_fees':fees,'refunds':refunded,'provider_net_received':net,'unreconciled_count':missing}
