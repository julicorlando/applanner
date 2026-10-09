import hashlib
import hmac
import re
import time
from decimal import Decimal, InvalidOperation

import requests
from core.redaction import redact_sensitive_text


def validate_charge_amount(value):
    try:
        amount=Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        amount=amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Valor da cobrança inválido. Revise o valor contratado.") from exc
    if amount<Decimal("0.50"):
        raise ValueError("O valor da cobrança deve ser de pelo menos R$ 0,50. Peça à gestão para revisar o valor contratado, a promoção ou os descontos; nenhuma cobrança foi iniciada.")
    return amount


class MercadoPagoError(RuntimeError):
    pass


class MercadoPagoProvider:
    BASE_URL="https://api.mercadopago.com"

    def __init__(self,access_token,transport=None,timeout=20):
        token=(access_token or "").strip()
        if not (token.startswith("APP_USR-") or token.startswith("TEST-")) or len(token)<16:
            raise ValueError("Credencial Mercado Pago inválida.")
        self.access_token=token
        self.transport=transport
        self.timeout=timeout

    def _request(self,method,path,payload=None,idempotency_key=""):
        if self.transport:
            return self.transport(method,path,payload or {},idempotency_key,self.access_token)

        headers={
            "Authorization":f"Bearer {self.access_token}",
            "Content-Type":"application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"]=idempotency_key

        response=requests.request(
            method,
            self.BASE_URL+path,
            json=payload if method!="GET" else None,
            headers=headers,
            timeout=self.timeout,
        )
        try:
            data=response.json()
        except ValueError as exc:
            raise MercadoPagoError("Resposta inválida do Mercado Pago.") from exc

        if not isinstance(data,dict):
            raise MercadoPagoError("Resposta inválida do Mercado Pago.")
        if not 200<=response.status_code<300:
            errors=data.get("errors") or data.get("cause") or []
            if not isinstance(errors,list):
                errors=[]
            reasons=[]
            for error in errors[:3]:
                if isinstance(error,dict):
                    code=str(error.get("code") or "")[:80]
                    detail=str(error.get("message") or error.get("description") or "")[:200]
                    if code=="invalid_email_for_sandbox":
                        detail="Em testes, informe o e-mail da conta compradora de teste do Mercado Pago (@testuser.com)."
                    if code or detail:
                        reasons.append(f"{code}: {detail}" if code and detail else code or detail)
            message=("; ".join(reasons) or str(data.get("message") or data.get("error") or "requisição recusada"))[:600]
            if "payer and collector cannot be the same user" in message.lower():
                raise MercadoPagoError(
                    "O pagador não pode ser a mesma conta Mercado Pago que recebe a cobrança. "
                    "Informe um e-mail de comprador diferente e, em testes, entre no Mercado Pago com a conta compradora."
                )
            message=redact_sensitive_text(message,secrets=(self.access_token,))
            raise MercadoPagoError(f"Mercado Pago HTTP {response.status_code}: {message}")
        return data

    def test_connection(self):
        return self._request("GET","/users/me")

    def create_subscription(self,*,reason,external_reference,payer_email,back_url,amount,frequency=1,trial_days=0,idempotency_key="",start_at=None):
        amount=validate_charge_amount(amount)
        if amount<=0:
            raise ValueError("Valor da assinatura inválido.")
        body={
            "reason":reason,
            "external_reference":external_reference,
            "payer_email":payer_email,
            "back_url":back_url,
            "status":"pending",
            "auto_recurring":{
                "frequency":max(1,int(frequency)),
                "frequency_type":"months",
                "transaction_amount":float(amount),
                "currency_id":"BRL",
            },
        }
        if start_at:
            body["auto_recurring"]["start_date"]=start_at.isoformat()
        elif trial_days:
            body["auto_recurring"]["free_trial"]={
                "frequency":max(1,int(trial_days)),
                "frequency_type":"days",
            }
        data=self._request("POST","/preapproval",body,idempotency_key)
        return {
            "reference":str(data.get("id") or ""),
            "status":str(data.get("status") or "pending"),
            "init_point":data.get("init_point"),
        }

    def get_subscription(self,reference):
        return self._request("GET",f"/preapproval/{reference}")

    def update_subscription_amount(self,reference,amount):
        amount=validate_charge_amount(amount)
        if amount<=0:
            raise ValueError("Valor inválido.")
        return self._request("PUT",f"/preapproval/{reference}",{
            "auto_recurring":{"transaction_amount":float(amount),"currency_id":"BRL"}
        })

    def cancel_subscription(self,reference):
        return self._request("PUT",f"/preapproval/{reference}",{"status":"canceled"})

    def get_payment(self,reference):
        return self._request("GET",f"/v1/payments/{reference}")

    def create_pix_order(self,*,amount,external_reference,payer_email,expiration_hours=24,idempotency_key=""):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",external_reference or ""):
            raise ValueError("Referência Pix inválida: use até 64 letras, números, hífens ou sublinhados.")
        if not 1<=len(idempotency_key)<=128:
            raise ValueError("Chave de idempotência Pix inválida.")
        amount=validate_charge_amount(amount)
        if amount<=0:
            raise ValueError("Valor Pix inválido.")
        hours=max(1,min(720,int(expiration_hours)))
        body={
            "type":"online",
            "total_amount":str(amount),
            "external_reference":external_reference,
            "processing_mode":"automatic",
            "transactions":{
                "payments":[{
                    "amount":str(amount),
                    "expiration_time":f"PT{hours}H",
                    "payment_method":{
                        "id":"pix",
                        "type":"bank_transfer",
                    },
                }]
            },
            "payer":{"email":payer_email},
        }
        data=self._request("POST","/v1/orders",body,idempotency_key)
        payment=((data.get("transactions") or {}).get("payments") or [{}])[0]
        method=payment.get("payment_method") or {}
        return {
            "order_id":str(data.get("id") or ""),
            "payment_id":str(payment.get("id") or ""),
            "status":str(payment.get("status") or data.get("status") or "action_required"),
            "ticket_url":method.get("ticket_url"),
            "qr_code":method.get("qr_code"),
            "qr_code_base64":method.get("qr_code_base64"),
        }

    def get_order(self,reference):
        return self._request("GET",f"/v1/orders/{reference}")

    def create_tokenized_card_payment(
        self,*,amount,token,payment_method_id,payer_email,external_reference,
        installments=1,issuer_id="",identification=None,notification_url="",
        description="ApPlanner",idempotency_key=""
    ):
        amount=validate_charge_amount(amount)
        if amount<=0 or not token or not payment_method_id or "@" not in payer_email:
            raise ValueError("Dados do pagamento por cartão inválidos.")
        body={
            "transaction_amount":float(amount),
            "token":token,
            "description":description,
            "installments":max(1,min(24,int(installments))),
            "payment_method_id":payment_method_id,
            "payer":{"email":payer_email},
            "external_reference":external_reference,
        }
        if issuer_id:
            body["issuer_id"]=issuer_id
        if notification_url:
            body["notification_url"]=notification_url
        if identification and identification.get("type") and identification.get("number"):
            body["payer"]["identification"]={
                "type":str(identification["type"]),
                "number":str(identification["number"]),
            }
        data=self._request("POST","/v1/payments",body,idempotency_key)
        fee=sum(
            Decimal(str(item.get("amount") or 0))
            for item in data.get("fee_details",[])
            if isinstance(item,dict)
        )
        net=Decimal(str((data.get("transaction_details") or {}).get("net_received_amount") or (amount-fee)))
        return {
            "id":str(data.get("id") or ""),
            "status":str(data.get("status") or "pending"),
            "status_detail":str(data.get("status_detail") or ""),
            "payment_method_id":str(data.get("payment_method_id") or payment_method_id),
            "payment_type_id":str(data.get("payment_type_id") or ""),
            "transaction_amount":Decimal(str(data.get("transaction_amount") or amount)),
            "fee_amount":fee,
            "net_received_amount":net,
        }

    @staticmethod
    def valid_webhook_signature(signature,request_id,data_id,secret,now=None,tolerance_seconds=300):
        parts={}
        for part in (signature or "").split(","):
            key,sep,value=part.strip().partition("=")
            if sep:
                parts[key]=value
        ts_raw=parts.get("ts","")
        provided=parts.get("v1","")
        if not (secret and request_id and data_id and ts_raw and provided):
            return False
        try:
            ts=int(ts_raw)
        except ValueError:
            return False
        ts_seconds=ts/1000 if ts>9_999_999_999 else ts
        now=time.time() if now is None else now
        if abs(now-ts_seconds)>tolerance_seconds:
            return False
        manifest=f"id:{str(data_id).lower()};request-id:{request_id};ts:{ts_raw};"
        expected=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,provided)
