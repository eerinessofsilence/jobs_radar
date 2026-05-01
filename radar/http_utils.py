from __future__ import annotations

from collections.abc import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


def retry_session(
    total: int = 3,
    backoff_factor: float = 0.5,
    allowed_methods: Iterable[str] = ("GET",),
    read_retries: int | None = None,
) -> requests.Session:
    retry = Retry(
        total=total,
        connect=total,
        read=total if read_retries is None else read_retries,
        status=total,
        backoff_factor=backoff_factor,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=frozenset(method.upper() for method in allowed_methods),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
