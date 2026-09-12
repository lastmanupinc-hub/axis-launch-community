"""Run health: notice when the system has stopped being able to do its job.

Every refusal in this system is a clean exit by design. A day with nothing to say holds, a
blocked send exits 0, an unpublishable ad set is not an error. That is correct behaviour
and it creates one specific danger: the system can run degraded for weeks and every day
still looks like a successful workflow run. Nobody finds out until somebody thinks to look.

So each run records what it managed to do, and this module decides whether the pattern
across recent runs is normal or wrong.

THE DISTINCTION THAT MATTERS

  waiting  - a known blocker recorded in launch-readiness.yml. Checkout takes no money, so
             the ads do not publish. That is not a fault, it is the system correctly
             declining. Never alarms.
  broken   - something that was working has stopped, or something that should be reachable
             is not. Credentials, connectivity, a capability regression, a content pipeline
             that has gone dry. Always alarms, after a grace period.

Alarming on `waiting` would train everyone to ignore the alarm, which is the only outcome
worse than not having one.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import config

HEALTH_FILE = "marketing/out/.health.json"
KEEP_RUNS = 30

# Consecutive degraded runs before a condition escalates from noted to failing.
THRESHOLDS = {
    "product_unreachable": 3,      # cannot see the product at all
    "api_unauthenticated": 5,      # token missing or rejected
    "catalogue_not_live": 10,      # never refreshed from the running shop
    "newsletter_dry": 7,           # nothing worth sending, that many days running
    "capability_regression": 1,    # something that worked stopped working. Immediate.
}


@dataclass
class RunRecord:
    date: str
    kind: str                       # "ads" | "newsletter"
    product_reachable: bool = False
    api_authenticated: bool = False
    catalogue_live: bool = False
    capabilities: dict = field(default_factory=dict)
    produced: bool = False          # an issue was built, or an ad set was built
    dispatched: bool = False        # it actually went out
    blocked_by: list = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Finding:
    condition: str
    severity: str                   # "note" | "fail"
    streak: int
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper()}: {self.condition} ({self.streak} runs): {self.message}"


def _path() -> Path:
    return config.REPO_ROOT / HEALTH_FILE


def load() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:                                    # noqa: BLE001
        return []


def record(run: RunRecord) -> list[dict]:
    """Append a run, replacing any earlier record for the same date and kind."""
    history = [r for r in load()
               if not (r.get("date") == run.date and r.get("kind") == run.kind)]
    history.append(run.as_dict())
    history.sort(key=lambda r: (r.get("date", ""), r.get("kind", "")))
    history = history[-KEEP_RUNS * 2:]
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return history


def _streak(runs: list[dict], predicate) -> int:
    """How many of the most recent runs, consecutively, satisfy the predicate."""
    count = 0
    for run in reversed(runs):
        if predicate(run):
            count += 1
        else:
            break
    return count


def _finding(condition: str, streak: int, message: str) -> Finding | None:
    if streak <= 0:
        return None
    limit = THRESHOLDS[condition]
    severity = "fail" if streak >= limit else "note"
    return Finding(condition, severity, streak,
                   f"{message} ({streak}/{limit} before this fails the run)"
                   if severity == "note" else message)


def assess(kind: str | None = None, history: list[dict] | None = None) -> list[Finding]:
    """Decide whether the recent pattern is waiting or broken."""
    runs = history if history is not None else load()
    if kind:
        runs = [r for r in runs if r.get("kind") == kind]
    if not runs:
        return []

    out: list[Finding] = []

    f = _finding("product_unreachable",
                 _streak(runs, lambda r: not r.get("product_reachable")),
                 "cannot reach the product. Every capability has fallen back to the "
                 "conservative baseline, so nothing will spend or send until it is visible "
                 "again. Check the site is up and PMD_API_BASE is right.")
    if f:
        out.append(f)

    f = _finding("api_unauthenticated",
                 _streak(runs, lambda r: not r.get("api_authenticated")),
                 "the API is not authenticating. No catalogue refresh, no live prices, no "
                 "capability probe. Check PMD_API_TOKEN has not expired.")
    if f:
        out.append(f)

    f = _finding("catalogue_not_live",
                 _streak(runs, lambda r: not r.get("catalogue_live")),
                 "the catalogue has not been refreshed from the running shop. Ads are "
                 "being built against whatever was last imported, which may no longer "
                 "match what a visitor sees.")
    if f:
        out.append(f)

    if kind in (None, "newsletter"):
        news = [r for r in runs if r.get("kind") == "newsletter"]
        if news:
            f = _finding("newsletter_dry",
                         _streak(news, lambda r: not r.get("produced")),
                         "no issue has been worth sending. Holding is correct for a quiet "
                         "day, but this many in a row means the content sources have gone "
                         "dry, not that there is briefly nothing to say.")
            if f:
                out.append(f)

    regression = _capability_regression(runs)
    if regression:
        out.append(regression)
    return out


def _capability_regression(runs: list[dict]) -> Finding | None:
    """Something that was working has stopped. Alarms immediately, with no grace period.

    Only counts when both readings were taken while the product was reachable - a
    capability "disappearing" because we went blind is the blindness, not a regression, and
    it is already reported as `product_unreachable`.
    """
    seen = [r for r in runs if r.get("product_reachable")]
    if len(seen) < 2:
        return None
    latest, previous = seen[-1], seen[-2]
    lost = [cap for cap, was in (previous.get("capabilities") or {}).items()
            if was and not (latest.get("capabilities") or {}).get(cap)]
    if not lost:
        return None
    return Finding(
        "capability_regression", "fail", 1,
        f"the product could do {', '.join(sorted(lost))} on {previous.get('date')} and "
        f"cannot on {latest.get('date')}. Something regressed, or a route moved. This is "
        "the one condition with no grace period.")


def summarise(findings: list[Finding]) -> str:
    if not findings:
        return "health: nothing wrong. Any refusals today were the system declining on purpose."
    lines = ["health:"]
    lines += [f"  {f}" for f in findings]
    failing = [f for f in findings if f.severity == "fail"]
    if failing:
        lines.append("")
        lines.append("  These are 'broken', not 'waiting'. A known blocker recorded in")
        lines.append("  launch-readiness.yml never appears here - it is the system declining")
        lines.append("  on purpose, and alarming on it would train everyone to ignore the alarm.")
    return "\n".join(lines)


def ok(findings: list[Finding]) -> bool:
    return not any(f.severity == "fail" for f in findings)


def today() -> str:
    return dt.date.today().isoformat()
