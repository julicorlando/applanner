"""Platform SMTP credentials configured by Master, with environment fallback."""

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend

from core.crypto import decrypt_text


def active_smtp_settings():
    from operations.models import PlatformSMTPSettings
    return PlatformSMTPSettings.objects.filter(pk=1,enabled=True).first()


class PlatformEmailBackend(DjangoSMTPBackend):
    def __init__(self,**kwargs):
        config=active_smtp_settings()
        if config:
            kwargs.update({
                "host":config.host,"port":config.port,"username":config.username,
                "password":decrypt_text(config.password_encrypted) if config.password_encrypted else "",
                "use_tls":config.use_tls,"use_ssl":config.use_ssl,
                "timeout":settings.EMAIL_TIMEOUT,
            })
        super().__init__(**kwargs)
        self.platform_sender=config.from_email if config else None

    def send_messages(self,email_messages):
        if self.platform_sender:
            for message in email_messages:
                if not message.from_email or message.from_email==settings.DEFAULT_FROM_EMAIL:
                    message.from_email=self.platform_sender
        return super().send_messages(email_messages)
