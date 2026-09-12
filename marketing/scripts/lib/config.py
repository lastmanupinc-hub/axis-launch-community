"""Config loading and path resolution.

Everything the build needs lives in marketing/config and marketing/calendar. Nothing is
hardcoded in a script; if a value matters, it is in YAML and it is loaded here.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import yaml

# marketing/scripts/lib/config.py -> marketing/
MARKETING_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = MARKETING_ROOT.parent

CONFIG_DIR = MARKETING_ROOT / "config"
CALENDAR_DIR = MARKETING_ROOT / "calendar"
TEMPLATE_DIR = MARKETING_ROOT / "templates"
BRAND_DIR = MARKETING_ROOT / "brand"
OUT_DIR = MARKETING_ROOT / "out"
QUEUE_DIR = MARKETING_ROOT / "queue"


class ConfigError(RuntimeError):
    """Raised when a config file is missing, malformed, or internally inconsistent."""


def _load(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"missing config file: {path.relative_to(REPO_ROOT)}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.relative_to(REPO_ROOT)} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.relative_to(REPO_ROOT)} must be a mapping at the top level")
    return data


@functools.lru_cache(maxsize=None)
def brands() -> dict:
    return _load(CONFIG_DIR / "brands.yml")


@functools.lru_cache(maxsize=None)
def hooks() -> dict:
    return _load(CONFIG_DIR / "hooks.yml")


@functools.lru_cache(maxsize=None)
def products() -> dict:
    return _load(CONFIG_DIR / "products.yml")


@functools.lru_cache(maxsize=None)
def sources() -> dict:
    return _load(CONFIG_DIR / "sources.yml")


@functools.lru_cache(maxsize=None)
def blocklist() -> dict:
    return _load(CONFIG_DIR / "blocklist.yml")


@functools.lru_cache(maxsize=None)
def permissions() -> dict:
    path = CONFIG_DIR / "permissions.yml"
    if not path.exists():
        return {"version": 1, "customers": {}}
    return _load(path)


@functools.lru_cache(maxsize=None)
def launch_readiness() -> dict:
    return _load(CONFIG_DIR / "launch-readiness.yml")


@functools.lru_cache(maxsize=None)
def detected_readiness() -> dict:
    path = CONFIG_DIR / "launch-readiness.detected.yml"
    if not path.exists():
        return {}
    try:
        return _load(path)
    except ConfigError:
        return {}


# A probe older than this is not evidence about the product as it is now.
DETECTION_MAX_AGE_HOURS = 36


def capabilities(brand_key: str, *, refresh: bool = False) -> dict:
    """What the product can do: the declared baseline, overridden by a fresh probe.

    See scripts/probe_capabilities.py for the merge rule. The short version: a capability is
    true only when something positively says so, and blindness reads as "stop".
    """
    if refresh:
        detected_readiness.cache_clear()
    declared = dict((launch_readiness().get(brand_key) or {}).get("capabilities", {}))

    probe = detected_readiness()
    if not probe or probe.get("brand") != brand_key:
        return declared
    if not probe.get("reachable"):
        return declared                      # blind: the conservative baseline stands
    if _probe_is_stale(probe.get("checked_at")):
        return declared

    for cap, value in (probe.get("capabilities") or {}).items():
        declared[cap] = bool(value)
    return declared


def _probe_is_stale(checked_at: str | None) -> bool:
    if not checked_at:
        return True
    import datetime as dt
    try:
        when = dt.datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    age = dt.datetime.now(dt.timezone.utc) - when
    return age > dt.timedelta(hours=DETECTION_MAX_AGE_HOURS)


@functools.lru_cache(maxsize=None)
def annual_calendar() -> dict:
    return _load(CALENDAR_DIR / "annual.yml")


@functools.lru_cache(maxsize=None)
def weekly_slots() -> dict:
    return _load(CALENDAR_DIR / "weekly-slots.yml")


def brand(key: str) -> dict:
    data = brands()["brands"]
    if key not in data:
        raise ConfigError(f"unknown brand '{key}'. Known: {sorted(data)}")
    return data[key]


def limits(section: str) -> dict:
    return brands()["limits"][section]


def env(name: str, *, required: bool = False, default: str = "") -> str:
    """Read an environment variable.

    Secrets and anything environment-specific (postal addresses, API keys, list IDs) come
    from here and are never committed.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            raise ConfigError(
                f"environment variable {name} is required and is empty. "
                "Set it as a repository secret or in the local shell; the build will not "
                "substitute a placeholder."
            )
        return default
    return value


def absolute_url(brand_key: str, path: str) -> str:
    """Join a brand's site to a path, tolerating slashes on either side."""
    if path.startswith(("http://", "https://")):
        return path
    site = brand(brand_key)["site"].rstrip("/")
    return f"{site}/{path.lstrip('/')}"
