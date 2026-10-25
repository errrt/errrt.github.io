import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url, *, headers=None, method="GET", body=None, timeout=30):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=payload,
        method=method,
        headers={"Accept": "application/json", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Network error for {url}: {error.reason}") from error


def request_text(url, *, headers=None, timeout=30):
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "errrt-growth-agent/1.0",
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Network error for {url}: {error.reason}") from error
