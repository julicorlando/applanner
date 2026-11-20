"""Redact credentials before provider diagnostics reach UI, logs or persisted errors."""

import re

from django.conf import settings


def redact_sensitive_text(value, *, secrets=()):
    text = str(value)
    known = list(secrets)
    for name in (
        "SECRET_KEY",
        "FIELD_ENCRYPTION_KEY",
        "EMAIL_HOST_PASSWORD",
        "MASTER_WHATSAPP_GATEWAY_TOKEN",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
        "META_CONVERSION_ACCESS_TOKEN",
    ):
        known.append(getattr(settings, name, ""))
    known.append(settings.DATABASES.get("default", {}).get("PASSWORD", ""))
    for secret in sorted(
        {str(x) for x in known if x and len(str(x)) >= 6}, key=len, reverse=True
    ):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"'<>;,]+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)(https?://|postgres(?:ql)?://|redis://)([^\s/@]+@)",
        r"\1[REDACTED]@",
        text,
    )
    text = re.sub(
        r"(?i)([\"']?(?:access_token|api_key|password|secret|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&;,}\]]+",
        r"\1[REDACTED]",
        text,
    )
    return text
