"""Extract the explicitly configured public host for internal callbacks."""

from urllib.parse import urlsplit


def public_allowed_host(base_url):
    try:
        url=urlsplit(base_url)
        if (url.scheme!="https" or not url.hostname or url.username or url.password
            or url.path not in ("","/") or url.query or url.fragment):
            return ""
        return url.hostname
    except ValueError:
        return ""
