import math
import json
import hashlib
import httpx
import requests
from tavily import TavilyClient
from ..provider import HTTPProvider, ProviderError, QuotaExhausted, shared_pacer
from ..evidence import canonical_url
from ..budget import ProjectBudget


class ControlledSession(requests.Session):
    """Official SDK session hook; every actual attempt passes through our budget/retry controller."""
    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def request(self, method, url, **kwargs):
        if url not in {"https://api.tavily.com/search", "https://api.tavily.com/extract"}:
            raise ProviderError("Unexpected Tavily SDK endpoint blocked.")
        operation = url.rsplit("/", 1)[1]
        payload = json.loads(kwargs.get("data") or "{}")
        reservation = ((2 if payload.get("search_depth") == "advanced" else 1) if operation == "search" else
                       math.ceil(len(payload.get("urls", [])) / 5) * (2 if payload.get("extract_depth") == "advanced" else 1))
        raw, headers = self.provider.request(method, operation, self.provider.current_purpose, payload,
                                             lambda: self.provider.before(operation, reservation))
        return httpx.Response(200, json=raw, headers=headers)


class TavilyProvider(HTTPProvider):
    name, key_name, base_url = "tavily", "TAVILY_API_KEY", "https://api.tavily.com/"

    def __init__(self, settings, run, client=None):
        from ..execution import current_execution_phase
        if current_execution_phase() == "new_run":
            from ..execution import current_allowance_id
            approved = next((a for a in ProjectBudget(settings).read().get("execution_allowances", [])
                             if a.get("id") == current_allowance_id()), {})
            if approved.get("kind") != "fresh_enquiry" or approved.get("tavily_credits", 0) <= 0:
                raise QuotaExhausted("This allowance permits zero Tavily calls; fresh research unavailable.")
        super().__init__(settings, run, client)
        self.search_requests = self.extract_requests = self.reserved_credits = 0
        self.free_checked, self.available = False, 0
        self.pacer = shared_pacer(self.name, self.key)
        self.budget = ProjectBudget(settings)
        self.budget_ticket = None
        self.current_purpose = ""
        self.sdk = TavilyClient(api_key=self.key, session=ControlledSession(self))

    def check_free_plan(self):
        if self.free_checked:
            return self.plan_record
        raw, _ = self.request("GET", "usage", "probe:free plan")
        account, key = raw.get("account") or {}, raw.get("key") or {}
        plan = str(account.get("current_plan", "")).casefold()
        if (plan not in {"researcher", "free"} or "paygo_limit" not in account
                or account["paygo_limit"] not in {None, 0} or account.get("paygo_usage") != 0):
            raise ProviderError("Tavily Free/Researcher plan with zero PAYGO usage could not be verified; search/extract stopped to protect zero spending.")
        try:
            remaining = float(account["plan_limit"]) - float(account["plan_usage"])
            if key.get("limit") is not None:
                remaining = min(remaining, float(key["limit"]) - float(key["usage"]))
        except (KeyError, ValueError, TypeError):
            raise ProviderError("Tavily remaining free allowance not reported; search/extract stopped.") from None
        if remaining <= 0:
            self.exhausted = True
            raise QuotaExhausted("Tavily free credits exhausted. Wait for reset; no paid fallback.")
        self.available = remaining
        self.plan_record = {"provider": "tavily", "event": "free_plan_verified", "plan": account["current_plan"],
                            "free_credits_remaining_at_check": remaining, "paygo_limit": account["paygo_limit"],
                            "billing_protection": "Requests capped below reported free-plan allowance; null PAYGO cap is unspecified, not interpreted as disabled or unlimited."}
        self.run.logs.append(self.plan_record)
        self.free_checked = True
        return self.plan_record

    def before(self, operation, reserved):
        self.check_free_plan()
        if self.reserved_credits + reserved > min(self.available, self.settings.max_tavily_credits):
            raise QuotaExhausted("Tavily free-credit reservation budget exhausted; no request or upgrade.")
        if operation == "search":
            if self.search_requests >= self.settings.max_search_requests:
                raise QuotaExhausted("Tavily search-attempt budget exhausted (retries included).")
            self.search_requests += 1
        else:
            if self.extract_requests >= self.settings.max_extract_requests:
                raise QuotaExhausted("Tavily extract-attempt budget exhausted (retries included).")
            self.extract_requests += 1
        self.reserved_credits += reserved
        self.budget_ticket = self.budget.reserve("tavily", reserved, operation, run_id=self.run.run_id)
        self.pacer.reserve(1, self.settings.tavily_rpm, self.settings.tavily_rpm,
                           lambda delay: self.run.logs.append({"event": "rate_wait", "provider": "tavily", "seconds": round(delay, 1)}))

    def record_usage(self, raw, purpose):
        usage = raw.get("usage") or {}
        self.budget.settle(self.budget_ticket, usage.get("credits"))
        self.run.usage.append({"provider": "tavily", "purpose": purpose, "request_id": raw.get("request_id"),
                               "credits": usage.get("credits"), "details": usage,
                               "search_requests": 1 if purpose.startswith("search:") else 0,
                               "extract_requests": 1 if purpose.startswith("extract:") else 0})

    def search(self, queries, purpose, as_of_date, domains=None):
        results, errors = [], []
        for query in queries:
            depth = self.settings.tavily_search_depth
            if self.settings.selective_search_depth:
                depth = "advanced" if purpose.rsplit(":", 1)[-1] in {"organisation", "finance", "current"} else "basic"
            payload = {"query": query[:1000], "search_depth": depth, "auto_parameters": False,
                       "max_results": self.settings.max_results_per_query, "include_answer": False,
                       "include_raw_content": False, "include_usage": True, "topic": "general",
                       "end_date": as_of_date}
            # Do not force Tavily to refresh each result within 24 hours. On Free plans,
            # live-fetch requests may fail with HTTP 434; cached search results are
            # acceptable candidates, while claims still require inspected originals.
            if domains:
                payload["include_domains"] = domains
            try:
                cache = self.run.retrieval_cache.setdefault("_tavily_search", {})
                key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                if key in cache:
                    results += [{**item, "retrieval_query": query} for item in cache[key].get("results", [])]
                    self.run.logs.append({"event": "search_request_reused", "purpose": purpose,
                                          "note": "same-run successful response cache; no new search"})
                    continue
                self.current_purpose = purpose
                raw = self.sdk.search(**payload, timeout=self.settings.timeout_seconds)
                self.record_usage(raw, purpose)
                cache[key] = {"results": raw.get("results", [])}
                results += [{**item, "retrieval_query": query} for item in raw.get("results") or []]
            except ProviderError as exc:
                errors.append(str(exc))
                if isinstance(exc, QuotaExhausted) or self.exhausted:
                    break
        if not results:
            raise ProviderError("Tavily search returned no evidence. " + " ".join(errors))
        return {"results": results, "errors": errors, "provider": "tavily"}

    def extract(self, urls, purpose="extract:sources"):
        urls = list(dict.fromkeys(canonical_url(u) for u in urls))[:5]
        if not urls:
            return {"results": [], "failed_results": []}
        from ..evidence import source_family_key
        cache = self.run.retrieval_cache.setdefault("_tavily_extract", {})
        reused = [cache[source_family_key(url)] for url in urls if source_family_key(url) in cache]
        missing = [url for url in urls if source_family_key(url) not in cache]
        if not missing:
            self.run.logs.append({"event": "extract_request_reused", "purpose": purpose, "count": len(reused)})
            return {"results": reused, "failed_results": []}
        payload = {"urls": missing, "extract_depth": self.settings.tavily_extract_depth, "format": "text", "include_usage": True,
                   "include_images": False, "timeout": min(30, self.settings.timeout_seconds)}
        self.current_purpose = purpose
        raw = self.sdk.extract(**payload)
        self.record_usage(raw, purpose)
        for row in raw.get("results", []):
            if row.get("url") and row.get("raw_content"):
                cache[source_family_key(row["url"])] = row
        return {**raw, "results": [*reused, *raw.get("results", [])]}

    def refresh_usage(self):
        raw, _ = self.request("GET", "usage", "usage:after")
        account, key = raw.get("account") or {}, raw.get("key") or {}
        safe = {"provider": "tavily", "event": "usage_after", "plan": account.get("current_plan"),
                "plan_usage": account.get("plan_usage"), "plan_limit": account.get("plan_limit"),
                "key_usage": key.get("usage"), "key_limit": key.get("limit"),
                "paygo_usage": account.get("paygo_usage"), "paygo_limit": account.get("paygo_limit")}
        self.run.logs.append(safe)
        return safe
