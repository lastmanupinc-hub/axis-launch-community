"""Client for the Print My Design API.

Everything the marketing system needs to know about the product it advertises comes from
here at generation time, rather than from a file somebody remembered to update:

  - the catalogue                 GET  /v4/catalog/products
  - a price                       POST /v4/pricing/quote
  - what the product can do       probed, see probe_capabilities()

Design rules, all of them chosen so the system can run unattended:

  FAIL CLOSED. Every failure path returns "unknown" or None, never an optimistic default.
  A probe that cannot reach the API reports the capability as absent, which stops the spend.
  The dangerous failure is a system that keeps advertising while blind, so blindness has to
  read as "stop", not as "carry on".

  A 422 no_cost_basis IS NOT AN ERROR. It is the pricing service correctly refusing to
  invent a price for a variant with no cost samples. It means "no price today", and the ad
  generator simply builds without one.

  NOTHING IS WRITTEN BY THIS MODULE. It reads. Callers decide what to record.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

import requests

from . import config

DEFAULT_TIMEOUT = 20
RETRIES = 3
BACKOFF = (2, 4, 8)


@dataclass
class ApiResult:
    ok: bool
    status: int | None = None
    data: Any = None
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quote:
    variant_key: str
    quantity: int
    price_cents: int
    currency: str = "USD"
    floor_applied: bool = False
    source: str = "pricing_api"

    @property
    def price(self) -> float:
        return self.price_cents / 100.0


class PmdApi:
    """Thin, patient client. One instance per run; it caches within the run."""

    def __init__(self, base: str | None = None, token: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT):
        site = config.brand("print_my_design")["site"].rstrip("/")
        self.base = (base or config.env("PMD_API_BASE", default=f"{site}/api/v4")).rstrip("/")
        self.token = token if token is not None else config.env("PMD_API_TOKEN")
        self.timeout = timeout
        self._cache: dict[str, ApiResult] = {}
        self.calls: list[dict] = []          # a record of every call, for the run report

    # ---------------------------------------------------------------- transport

    @property
    def configured(self) -> bool:
        """Without a token every catalogue and pricing route answers 401."""
        return bool(self.token)

    def _headers(self) -> dict:
        h = {"Accept": "application/json",
             "User-Agent": "print-my-design-marketing/1.0"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 cache_key: str | None = None, retries: int = RETRIES) -> ApiResult:
        if cache_key and cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.base}/{path.lstrip('/')}"
        result = ApiResult(ok=False, detail="not attempted")
        for attempt in range(retries):
            try:
                resp = requests.request(method, url, headers=self._headers(),
                                        json=json_body, timeout=self.timeout)
                body: Any = None
                if resp.content:
                    try:
                        body = resp.json()
                    except ValueError:
                        body = resp.text[:400]
                result = ApiResult(ok=resp.status_code < 300, status=resp.status_code,
                                   data=body,
                                   detail="" if resp.status_code < 300
                                   else f"HTTP {resp.status_code}")
                break
            except Exception as exc:                     # noqa: BLE001 - fail closed
                result = ApiResult(ok=False, status=None, detail=f"{type(exc).__name__}: {exc}")
                if attempt < retries - 1:
                    time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])

        self.calls.append({"method": method, "path": path, "status": result.status,
                           "ok": result.ok, "detail": result.detail[:120]})
        if cache_key:
            self._cache[cache_key] = result
        return result

    # ---------------------------------------------------------------- catalogue

    def catalogue(self) -> tuple[list[dict], ApiResult]:
        """The products the product actually has. Empty list is a legitimate answer."""
        if not self.configured:
            return [], ApiResult(False, None, None, "PMD_API_TOKEN not set")
        res = self._request("GET", "/catalog/products", cache_key="catalogue")
        if not res.ok:
            return [], res
        data = res.data
        rows = data.get("products") if isinstance(data, dict) else data
        if isinstance(data, dict) and rows is None:
            rows = data.get("data") or data.get("items") or []
        return list(rows or []), res

    # ---------------------------------------------------------------- pricing

    def quote(self, variant_key: str, quantity: int,
              vendor_cost_cents: int | None = None) -> tuple[Quote | None, ApiResult]:
        """A price for one variant at one quantity, or None.

        None is the normal answer today: with no cost samples recorded the service returns
        422 no_cost_basis, which is it refusing to guess. That refusal is the behaviour we
        want and it propagates straight through to "this ad carries no price".
        """
        if not self.configured:
            return None, ApiResult(False, None, None, "PMD_API_TOKEN not set")
        body: dict = {"variant_key": variant_key, "quantity": int(quantity)}
        if vendor_cost_cents is not None:
            body["vendor_cost_cents"] = int(vendor_cost_cents)
        res = self._request("POST", "/pricing/quote", json_body=body,
                            cache_key=f"quote:{variant_key}:{quantity}")
        if res.status == 422:
            return None, ApiResult(True, 422, res.data, "no_cost_basis: no price today")
        if not res.ok or not isinstance(res.data, dict):
            return None, res

        d = res.data
        cents = (d.get("price_cents") or d.get("final_price_cents")
                 or d.get("finalPriceCents"))
        if cents is None:
            return None, ApiResult(False, res.status, d, "quote carried no price field")
        return Quote(
            variant_key=variant_key, quantity=int(quantity), price_cents=int(cents),
            currency=d.get("currency", "USD"),
            floor_applied=bool(d.get("floor_applied") or d.get("floorApplied")),
        ), res

    # ---------------------------------------------------------------- probes

    def probe(self, method: str, path: str, *, json_body: dict | None = None) -> ApiResult:
        """A single capability probe. Never retried - a probe is a question, not a job."""
        return self._request(method, path, json_body=json_body, retries=1)


# --------------------------------------------------------------------------- capabilities

@dataclass
class CapabilityReport:
    """What the product can do, as measured rather than as declared."""
    detected: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    reachable: bool = False
    checked_at: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# Probes are ordered so the cheapest and most decisive run first.
# Each returns (capability_name, is_true, evidence).
def probe_capabilities(api: PmdApi, *, sample_variant: str | None = None,
                       sample_quantity: int = 1) -> CapabilityReport:
    """Measure what the product can do. Fail closed on everything.

    A capability is true ONLY when a probe positively demonstrates it. Unreachable,
    unauthenticated, ambiguous and errored all mean false, because the cost of a false
    negative is a quiet day and the cost of a false positive is money spent advertising
    something that does not work.
    """
    import datetime as dt

    report = CapabilityReport(
        checked_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    site = config.brand("print_my_design")["site"].rstrip("/")

    # --- can_browse: is the storefront actually up? -------------------------
    try:
        resp = requests.get(site, timeout=DEFAULT_TIMEOUT,
                            headers={"User-Agent": "print-my-design-marketing/1.0"})
        browse = resp.status_code < 400
        report.detected["can_browse"] = browse
        report.evidence["can_browse"] = f"GET {site} -> {resp.status_code}"
        report.reachable = True
    except Exception as exc:                              # noqa: BLE001
        report.detected["can_browse"] = False
        report.evidence["can_browse"] = f"GET {site} failed: {type(exc).__name__}"

    if not api.configured:
        for cap in ("can_transact", "can_fulfil", "has_price_confidence",
                    "has_subscriber_capture"):
            report.detected[cap] = False
            report.evidence[cap] = "PMD_API_TOKEN not set; cannot probe. Treated as absent."
        return report

    # --- can_transact: does a payment route exist on the order path? --------
    # A 404 means the route is not there. Anything else - 400, 401, 422 - means something
    # is listening, which is the only thing this probe claims to establish.
    pay = api.probe("POST", "/checkout/pay", json_body={})
    intent = api.probe("POST", "/checkout/payment-intent", json_body={})
    exists = [p for p in (pay, intent) if p.status not in (404, None)]
    report.detected["can_transact"] = bool(exists)
    report.evidence["can_transact"] = (
        f"POST /checkout/pay -> {pay.status}, /checkout/payment-intent -> {intent.status}. "
        + ("a payment route answers" if exists else "no payment route: 404 on both")
    )

    # --- has_subscriber_capture: is there anywhere to subscribe? ------------
    sub = api.probe("POST", "/newsletter/subscribe", json_body={})
    sub2 = api.probe("POST", "/subscribers", json_body={})
    sub_exists = [p for p in (sub, sub2) if p.status not in (404, None)]
    report.detected["has_subscriber_capture"] = bool(sub_exists)
    report.evidence["has_subscriber_capture"] = (
        f"POST /newsletter/subscribe -> {sub.status}, /subscribers -> {sub2.status}. "
        + ("a capture route answers" if sub_exists else "no capture route: 404 on both")
    )

    # --- can_fulfil: is a renderer configured? ------------------------------
    # The renderer is the last blocker before an order can become a file a vendor accepts.
    health = api.probe("GET", "/print/renderer/status")
    configured = False
    if health.ok and isinstance(health.data, dict):
        configured = bool(health.data.get("configured") or health.data.get("renderer"))
    report.detected["can_fulfil"] = configured
    report.evidence["can_fulfil"] = (
        f"GET /print/renderer/status -> {health.status}. "
        + ("renderer reports configured" if configured
           else "no configured renderer reported")
    )

    # --- has_price_confidence: does a real quote come back? -----------------
    if sample_variant:
        quote, res = api.quote(sample_variant, sample_quantity)
        report.detected["has_price_confidence"] = quote is not None
        report.evidence["has_price_confidence"] = (
            f"POST /pricing/quote {sample_variant} x{sample_quantity} -> {res.status}. "
            + (f"priced at {quote.price:.2f} {quote.currency}" if quote
               else res.detail or "no price")
        )
    else:
        report.detected["has_price_confidence"] = False
        report.evidence["has_price_confidence"] = (
            "no sample variant to quote; cannot demonstrate a price. Treated as absent.")

    return report
