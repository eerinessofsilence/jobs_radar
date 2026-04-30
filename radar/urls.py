from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parts.path.rstrip("/") if parts.path != "/" else parts.path
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ""))
