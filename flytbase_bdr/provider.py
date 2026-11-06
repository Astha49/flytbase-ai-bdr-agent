"""Shared bounded HTTP retries/pacing. No paid-provider fallback exists."""
import hashlib
import math
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx


class ProviderError(RuntimeError):
    pass


class QuotaExhausted(ProviderError):
    pass


class RequestTooLarge(ProviderError):
    pass


class ProjectWindowWait(ProviderError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("Shared project rolling window is full; wait before dispatch.")


def estimate_tokens(text):
    """Conservative English/JSON estimate; never presented as measured token usage."""
    return math.ceil(len(text.encode("utf-8")) / 3) + 128


def wait_seconds(seconds):
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        time.sleep(min(5, deadline - time.monotonic()))


def retry_delay(value, default=60):
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    return default


class WindowPacer:
    def __init__(self):
        self.events, self.lock = [], threading.Lock()
        self.token_limit, self.remote_tokens, self.remote_reset = None, None, 0
        self.daily_requests, self.cooldown_until = None, 0

    def capacity(self, configured, margin=1.0):
        return min(configured, configured if self.token_limit is None else int(self.token_limit * margin))

    def observe(self, headers, status=200):
        """Groq documents request headers as RPD and token headers as TPM."""
        def seconds(value):
            if not value:
                return 0
            try:
                return max(0, float(value))
            except ValueError:
                return sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u]
                           for n, u in re.findall(r"(\d+(?:\.\d+)?)([hms])", str(value)))
        with self.lock:
            current = time.monotonic()
            for field, attr in [("x-ratelimit-limit-tokens", "token_limit"),
                                ("x-ratelimit-remaining-tokens", "remote_tokens"),
                                ("x-ratelimit-remaining-requests", "daily_requests")]:
                try:
                    if field in headers:
                        setattr(self, attr, max(0, int(headers[field])))
                except (ValueError, TypeError):
                    pass
            if "x-ratelimit-reset-tokens" in headers:
                self.remote_reset = current + seconds(headers["x-ratelimit-reset-tokens"]) + .5
            elif "x-ratelimit-remaining-tokens" in headers:
                self.remote_reset = current + 61
            if status == 429 and "retry-after" in headers:
                self.cooldown_until = max(self.cooldown_until, current + retry_delay(headers["retry-after"]))

    def reserve(self, tokens, tpm, rpm, notify=lambda n: None, *, input_tokens=None, output_tokens=None,
                input_tpm=None, output_tpm=None):
        tpm = self.capacity(tpm)
        input_tokens, output_tokens = input_tokens or 0, output_tokens or 0
        if tokens > tpm:
            raise RequestTooLarge("Single request exceeds configured free-tier token window; no request sent.")
        if (input_tpm and input_tokens > input_tpm) or (output_tpm and output_tokens > output_tpm):
            raise RequestTooLarge("Single request exceeds the configured separate input/output window; no request sent.")
        began = time.monotonic()
        with self.lock:
            while True:
                now = time.monotonic()
                if self.daily_requests is not None and self.daily_requests <= 0:
                    raise QuotaExhausted("Provider RPD exhausted; wait for account reset. No automatic daily retry.")
                self.events = [e for e in self.events if now - e[0] < 61]
                remote_wait = max(0, self.cooldown_until - now)
                if self.remote_tokens is not None and now < self.remote_reset and tokens > self.remote_tokens:
                    remote_wait = max(remote_wait, self.remote_reset - now)
                separate_ok = ((not input_tpm or sum(e[2] for e in self.events if len(e) > 2) + input_tokens <= input_tpm)
                               and (not output_tpm or sum(e[3] for e in self.events if len(e) > 3) + output_tokens <= output_tpm))
                if not remote_wait and separate_ok and len(self.events) < rpm and sum(e[1] for e in self.events) + tokens <= tpm:
                    ticket = [time.monotonic(), tokens, input_tokens, output_tokens]
                    self.events.append(ticket)
                    if self.daily_requests is not None:
                        self.daily_requests -= 1
                    if self.remote_tokens is not None and now < self.remote_reset:
                        self.remote_tokens = max(0, self.remote_tokens - tokens)
                    return ticket
                delay = max(remote_wait, max(0.1, 61 - (now - self.events[0][0])) if self.events else .1)
                if now - began + delay > 180:
                    raise QuotaExhausted("Provider window cannot clear within bounded scheduler wait; checkpoint retained.")
                notify(delay)
                wait_seconds(delay)

    def settle(self, ticket, tokens, input_tokens=None, output_tokens=None):
        with self.lock:
            ticket[1] = tokens
            if len(ticket) > 3:
                if input_tokens is not None: ticket[2] = input_tokens
                if output_tokens is not None: ticket[3] = output_tokens


_PACERS, _PACERS_LOCK = {}, threading.Lock()


def shared_pacer(provider, key, model=""):
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12]
    with _PACERS_LOCK:
        return _PACERS.setdefault((provider, fingerprint, model), WindowPacer())


class HTTPProvider:
    name, base_url, key_name = "provider", "", ""

    def __init__(self, settings, run, client=None):
        import os
        from .config import credential_status
        credential_status()
        key = os.environ.get(self.key_name, "").strip()
        if not key:
            raise ProviderError(f"{self.key_name} is missing. Configure it in the local .env; never paste secrets into chat.")
        self.settings, self.run, self.key = settings, run, key
        self.client = client or httpx.Client(timeout=settings.timeout_seconds, follow_redirects=False)
        self.exhausted = False

    def request(self, method, path, purpose, payload=None, before_attempt=lambda: None):
        from .execution import require_live_execution
        require_live_execution(self.client)
        if self.exhausted:
            raise QuotaExhausted(f"{self.name}: quota/access stopped this provider for this run. No provider switch attempted.")
        for attempt in range(self.settings.max_retries + 1):
            if self.name == "tavily" and method == "GET" and path == "usage":
                from .budget import ProjectBudget
                ProjectBudget(self.settings).demo_control_request(self.run.run_id)
            before_attempt()
            self.run.logs.append({"event": "api_attempt", "provider": self.name, "purpose": purpose, "attempt": attempt + 1})
            try:
                response = self.client.request(method, self.base_url + path, json=payload,
                                               headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < self.settings.max_retries:
                    wait_seconds(2 ** attempt)
                    continue
                raise ProviderError(f"{self.name}: network/timeout failure; usage may be unreported. No fallback used.") from None
            code = response.status_code
            if self.name == "groq" and hasattr(getattr(self, "pacer", None), "observe"):
                self.pacer.observe(response.headers, code)
            if code == 200:
                try:
                    return response.json(), response.headers
                except ValueError:
                    raise ProviderError(f"{self.name}: invalid JSON response; no output accepted.") from None
            # Preserve actionable diagnostics, never the full server body (which
            # can echo prompts, generated JSON, headers or credentials).
            from .reporting import sanitise
            details = {}
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict):
                    for field in ("type", "code", "param", "message"):
                        value = error.get(field)
                        if isinstance(value, (str, int)):
                            clean = str(value).replace(self.key, "[REDACTED]")
                            details[field] = sanitise(" ".join(clean.split()))[:500 if field == "message" else 120]
            except (ValueError, AttributeError, TypeError):
                pass
            self.run.logs.append({"event": "api_error", "provider": self.name, "purpose": purpose,
                                  "status_code": code, "error_details": details,
                                  "request_id": sanitise(str(response.headers.get("x-request-id", "")).replace(self.key, "[REDACTED]"))[:120]})
            if code in {402, 432, 433} or (code == 429 and response.headers.get("x-ratelimit-remaining-requests") == "0"):
                self.exhausted = True
                raise QuotaExhausted(f"{self.name}: free quota exhausted (HTTP {code}); wait for reset. No paid fallback.")
            if code in {401, 403}:
                self.exhausted = True
                raise ProviderError(f"{self.name}: credentials/model/account access rejected (HTTP {code}); no upgrade or fallback attempted.")
            if code == 429 or code == 434 or code >= 500:
                delay = retry_delay(response.headers.get("retry-after"), 60 if code == 429 else 2 ** attempt)
                if delay > self.settings.max_retry_after_seconds or attempt == self.settings.max_retries:
                    self.exhausted = code == 429
                    raise QuotaExhausted(f"{self.name}: rate/free-capacity limit (HTTP {code}); retry after {delay:.0f}s or account reset. Run remains incomplete.")
                self.run.logs.append({"event": "retry_wait", "provider": self.name, "purpose": purpose, "seconds": delay})
                wait_seconds(delay)
                continue
            diagnostic = "; ".join(f"{k}={v}" for k, v in details.items())
            raise ProviderError(f"{self.name}: HTTP {code}; request/schema/model not accepted. "
                                + (diagnostic + ". " if diagnostic else "Server supplied no usable error detail. ")
                                + "No automatic retry, model or provider switch.")
        raise ProviderError(f"{self.name}: retry limit reached.")

    def close(self):
        self.client.close()
