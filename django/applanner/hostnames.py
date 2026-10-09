"""Extract the explicitly configured public host for internal callbacks."""

from urllib.parse import urlsplit


def normalize_public_base_url(value):
    """Accept a URL value or a mistakenly pasted PUBLIC_BASE_URL=value assignment."""
    value=value.strip().strip('\"\'')
    if value.startswith('PUBLIC_BASE_URL='):
        value=value.removeprefix('PUBLIC_BASE_URL=').strip().strip('\"\'')
    return value.rstrip('/')


def public_allowed_host(base_url):
    try:
        url=urlsplit(base_url)
        if (url.scheme!="https" or not url.hostname or url.username or url.password
            or url.path not in ("","/") or url.query or url.fragment):
            return ""
        return url.hostname
    except ValueError:
        return ""
