from django.db import migrations


def backfill_account_deletion_requests(apps,schema_editor):
    SupportTicket=apps.get_model("operations","SupportTicket")
    BillingSupportRequest=apps.get_model("operations","BillingSupportRequest")

    for ticket in SupportTicket.objects.filter(category="account_deletion").iterator():
        status="completed" if ticket.status in {"resolved","closed"} else "pending"
        BillingSupportRequest.objects.get_or_create(
            ticket_id=ticket.pk,
            defaults={
                "tenant_id":ticket.tenant_id,
                "user_id":ticket.user_id,
                "request_type":"account_deletion",
                "status":status,
            },
        )


class Migration(migrations.Migration):
    dependencies=[
        ("operations","0007_platformemailtemplate"),
    ]

    operations=[
        migrations.RunPython(backfill_account_deletion_requests,migrations.RunPython.noop),
    ]
