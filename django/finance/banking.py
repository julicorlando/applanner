from django.db import transaction

from core.crypto import decrypt_text,encrypt_text

from .models import PlatformBankAccount


@transaction.atomic
def save_platform_bank_account(
    *,bank_name,bank_code,account_type,agency,account,holder_name,
    holder_document,person_type,user=None,ispb="",agency_digit="",account_digit="",
    pix_key="",pix_key_type="",notes="",is_default=False
):
    if is_default:
        PlatformBankAccount.objects.filter(
            is_default=True,
            status=PlatformBankAccount.Status.ACTIVE,
            deleted_at__isnull=True,
        ).update(is_default=False)
    return PlatformBankAccount.objects.create(
        bank_name=bank_name[:120],
        bank_code=bank_code[:10],
        ispb=ispb[:20],
        account_type=account_type,
        agency_encrypted=encrypt_text(agency),
        agency_digit=agency_digit[:3],
        account_encrypted=encrypt_text(account),
        account_digit=account_digit[:3],
        holder_name=holder_name[:150],
        holder_document_encrypted=encrypt_text(holder_document),
        person_type=person_type,
        pix_key_encrypted=encrypt_text(pix_key) if pix_key else "",
        pix_key_type=pix_key_type[:12],
        notes_encrypted=encrypt_text(notes) if notes else "",
        is_default=is_default,
        created_by=user,
    )


def reveal_platform_bank_account(account):
    return {
        "agency":decrypt_text(account.agency_encrypted),
        "account":decrypt_text(account.account_encrypted),
        "holder_document":decrypt_text(account.holder_document_encrypted),
        "pix_key":decrypt_text(account.pix_key_encrypted) if account.pix_key_encrypted else "",
        "notes":decrypt_text(account.notes_encrypted) if account.notes_encrypted else "",
    }
