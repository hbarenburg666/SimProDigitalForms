"""
Simpro Digital Forms (white-labeled GoCanvas) REST API v3 client.

Auth: OAuth 2.0 client credentials. Token is cached on disk and refreshed on expiry.
Secrets come from .env only and are never logged.

Safety posture for this project:
  - No DELETE verb is implemented anywhere in this module.
  - Writes (POST) are limited to forms; submissions are read-only.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
TOKEN_CACHE = PROJECT_ROOT / ".token_cache.json"

DEFAULT_BASE = "https://digitalforms.simprogroup.com/api/v3"
FALLBACK_BASE = "https://api.gocanvas.com/v3"

# Seconds of headroom before expiry at which we proactively refresh.
TOKEN_SKEW = 120
# Polite delay between calls in loops (no concurrent requests allowed).
LOOP_DELAY = 0.35


class SimproError(RuntimeError):
    pass


def _redact(text: str) -> str:
    """Strip anything secret-looking out of text before it can reach a log."""
    for key in ("SIMPRO_CLIENT_SECRET", "SIMPRO_CLIENT_ID"):
        val = os.getenv(key)
        if val and val in text:
            text = text.replace(val, f"<{key}>")
    return text


class SimproClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.client_id = os.getenv("SIMPRO_CLIENT_ID")
        self.client_secret = os.getenv("SIMPRO_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise SimproError(
                "SIMPRO_CLIENT_ID / SIMPRO_CLIENT_SECRET not set. "
                "Copy .env.example to .env and fill them in."
            )
        self.base_url = (base_url or os.getenv("SIMPRO_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.session = requests.Session()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self.last_rate_limit: dict[str, str] = {}

    # ---------- auth ----------

    def _load_cached_token(self) -> bool:
        if not TOKEN_CACHE.exists():
            return False
        try:
            data = json.loads(TOKEN_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if data.get("base_url") != self.base_url:
            return False
        if data.get("expires_at", 0) - TOKEN_SKEW <= time.time():
            return False
        self._token = data.get("access_token")
        self._expires_at = data["expires_at"]
        return bool(self._token)

    def _save_cached_token(self) -> None:
        TOKEN_CACHE.write_text(
            json.dumps(
                {
                    "access_token": self._token,
                    "expires_at": self._expires_at,
                    "base_url": self.base_url,
                }
            )
        )
        try:  # best effort: restrict to current user on Windows
            os.chmod(TOKEN_CACHE, 0o600)
        except OSError:
            pass

    def _fetch_token(self) -> None:
        url = f"{self.base_url}/oauth/token"
        resp = self.session.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "api",
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise SimproError(
                f"Token request failed: HTTP {resp.status_code} at {url}\n"
                f"{_redact(resp.text[:500])}"
            )
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise SimproError(f"No access_token in token response: {list(payload)}")
        self._token = token
        self._expires_at = time.time() + float(payload.get("expires_in", 7200))
        self._save_cached_token()

    def token(self) -> str:
        if self._token and self._expires_at - TOKEN_SKEW > time.time():
            return self._token
        if self._load_cached_token():
            return self._token  # type: ignore[return-value]
        self._fetch_token()
        return self._token  # type: ignore[return-value]

    # ---------- transport ----------

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        if method.upper() not in ("GET", "POST"):
            raise SimproError(f"Refusing {method}: this client is GET/POST only by design.")

        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")

        for attempt in range(5):
            headers["Authorization"] = f"Bearer {self.token()}"
            resp = self.session.request(method, url, headers=headers, timeout=60, **kwargs)

            self.last_rate_limit = {
                k: v for k, v in resp.headers.items() if k.lower().startswith("ratelimit")
            }

            if resp.status_code == 401 and attempt == 0:
                # Token may have been revoked early — force a fresh one once.
                self._token = None
                TOKEN_CACHE.unlink(missing_ok=True)
                continue

            if resp.status_code == 429:
                reset = resp.headers.get("RateLimit-Reset") or resp.headers.get("Retry-After")
                wait = min(float(reset), 120) if reset and reset.isdigit() else 5 * (attempt + 1)
                print(f"  [rate limited] sleeping {wait:.0f}s…")
                time.sleep(wait)
                continue

            if resp.status_code >= 500 and attempt < 4:
                time.sleep(2 ** attempt)
                continue

            if not resp.ok:
                raise SimproError(
                    f"{method} {url} -> HTTP {resp.status_code}\n{_redact(resp.text[:1000])}"
                )
            return resp

        raise SimproError(f"{method} {url} failed after retries.")

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs).json()

    def get_raw(self, path: str, **kwargs: Any) -> bytes:
        return self._request("GET", path, **kwargs).content

    def post(self, path: str, payload: Any, **kwargs: Any) -> Any:
        resp = self._request(
            "POST",
            path,
            json=payload,
            headers={"Content-Type": "application/json"},
            **kwargs,
        )
        return resp.json() if resp.content else {}

    def paginate(self, path: str, **kwargs: Any) -> Iterator[dict]:
        """Follow RFC 5988 `Link: <...>; rel="next"` headers."""
        url = path
        while url:
            resp = self._request("GET", url, **kwargs)
            body = resp.json()
            items = body if isinstance(body, list) else body.get("data", body.get("forms", []))
            yield from items

            url = None
            for part in resp.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break
            if url:
                time.sleep(LOOP_DELAY)
            kwargs.pop("params", None)  # next link already carries the query string

    # ---------- endpoints ----------

    def me(self) -> dict:
        return self.get("/me")

    def list_forms(self) -> list[dict]:
        return list(self.paginate("/forms", params={"per_page": 100}))

    def get_form(self, form_id: str | int, fmt: str = "nested") -> dict:
        return self.get(f"/forms/{form_id}", params={"format": fmt})

    def update_form(self, form_id: str | int, nested_json: dict) -> dict:
        return self.post(f"/forms/{form_id}", nested_json)

    def create_form(self, nested_json: dict) -> dict:
        return self.post("/forms", nested_json)

    def list_submissions(self, form_id: str | int, **filters: Any) -> list[dict]:
        return list(self.paginate("/submissions", params={"form_id": form_id, **filters}))

    def get_submission(self, submission_id: str | int) -> dict:
        return self.get(f"/submissions/{submission_id}")

    def submission_pdf(self, submission_id: str | int) -> bytes:
        return self.get_raw(f"/submissions/{submission_id}/pdf", headers={"Accept": "application/pdf"})


def connect(verbose: bool = True) -> SimproClient:
    """Build a client, trying the Simpro host first and GoCanvas as a fallback."""
    tried: list[str] = []
    for base in (os.getenv("SIMPRO_BASE_URL") or DEFAULT_BASE, FALLBACK_BASE):
        if base in tried:
            continue
        tried.append(base)
        client = SimproClient(base_url=base)
        try:
            client.me()
        except (SimproError, requests.RequestException) as exc:
            if verbose:
                print(f"[!] Base {base} did not work: {str(exc).splitlines()[0]}")
            continue
        if verbose:
            print(f"[ok] Authenticated against {base}")
        return client
    raise SimproError(f"Could not authenticate against any base URL: {tried}")
