"""Fetch newsletter material from every configured source.

Contract: every fetcher returns a list of Item and never raises. A source that is down,
misconfigured, or empty produces zero items and one SourceStatus record explaining why. The
issue is then built from whatever did arrive. One dead feed must never take down the send.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests

from . import config


@dataclass
class Item:
    title: str
    url: str
    brand: str
    source: str
    published: str = ""              # ISO date
    summary: str = ""
    section: str = ""
    ladder: str = ""
    author: str = ""
    category: str = ""
    weight: int = 1
    customer_id: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceStatus:
    name: str
    ok: bool
    count: int = 0
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Harvest:
    items: list[Item] = field(default_factory=list)
    statuses: list[SourceStatus] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"items": [i.as_dict() for i in self.items],
                "statuses": [s.as_dict() for s in self.statuses]}


# --------------------------------------------------------------------------- http

def _http_get(url: str, *, headers: dict | None = None) -> requests.Response:
    cfg = config.sources()["http"]
    last: Exception | None = None
    backoff = cfg.get("backoff_seconds", [2, 4, 8])
    hdrs = {"User-Agent": cfg["user_agent"], **(headers or {})}
    for attempt in range(cfg.get("retries", 3)):
        try:
            resp = requests.get(url, headers=hdrs, timeout=cfg["timeout_seconds"])
            resp.raise_for_status()
            return resp
        except Exception as exc:                       # noqa: BLE001 - reported, not raised
            last = exc
            if attempt < cfg.get("retries", 3) - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise last if last else RuntimeError("request failed")


def _cutoff(hours: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


def _parse_dt(value: str) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip()
    for parser in (
        lambda v: dt.datetime.fromisoformat(v.replace("Z", "+00:00")),
        lambda v: dt.datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %z"),
        lambda v: dt.datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=dt.timezone.utc),
        lambda v: dt.datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc),
    ):
        try:
            parsed = parser(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


_TAG = re.compile(r"<[^>]+>")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def summarise(text: str, limit: int = 240) -> str:
    """First meaningful paragraph, stripped of markup, trimmed on a word boundary."""
    if not text:
        return ""
    text = _MD_LINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = re.sub(r"[*_`>|]", "", text)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        # A heading is a label, not a summary. Skip it and take the prose that follows.
        if re.match(r"^#{1,6}\s", block) and len(block.splitlines()) == 1:
            continue
        block = re.sub(r"^#{1,6}\s*", "", block, flags=re.M)
        # Discussion-form answers arrive as "### Label\nvalue"; keep the value.
        paragraphs.append(block.strip())
    body = paragraphs[0] if paragraphs else re.sub(r"^#{1,6}\s*", "", text.strip(), flags=re.M)
    body = re.sub(r"\s+", " ", body)
    if len(body) <= limit:
        return body
    return body[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "..."


# --------------------------------------------------------------------------- GitHub Discussions

_DISCUSSIONS_QUERY = """
query($owner:String!, $repo:String!, $first:Int!) {
  repository(owner:$owner, name:$repo) {
    discussions(first:$first, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        title url body createdAt updatedAt
        author { login }
        category { name slug }
        comments { totalCount }
        upvoteCount
      }
    }
  }
}
"""


def fetch_github_discussions(name: str, cfg: dict) -> tuple[list[Item], SourceStatus]:
    token = config.env(cfg.get("auth_env", "GITHUB_TOKEN"))
    if not token:
        return [], SourceStatus(name, False, 0,
                                f"{cfg.get('auth_env','GITHUB_TOKEN')} not set; skipped")
    weights = {c["slug"]: c.get("weight", 1) for c in cfg.get("categories", [])}
    labels = {c["slug"]: c.get("label", c["slug"]) for c in cfg.get("categories", [])}
    try:
        resp = requests.post(
            "https://api.github.com/graphql",
            json={"query": _DISCUSSIONS_QUERY,
                  "variables": {"owner": cfg["owner"], "repo": cfg["repo"],
                                "first": min(50, cfg.get("max_items", 8) * 5)}},
            headers={"Authorization": f"Bearer {token}",
                     "User-Agent": config.sources()["http"]["user_agent"]},
            timeout=config.sources()["http"]["timeout_seconds"],
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:                            # noqa: BLE001
        return [], SourceStatus(name, False, 0, f"request failed: {exc}")

    if payload.get("errors"):
        return [], SourceStatus(name, False, 0,
                                f"GraphQL errors: {payload['errors'][0].get('message')}")

    nodes = (((payload.get("data") or {}).get("repository") or {})
             .get("discussions") or {}).get("nodes") or []
    cutoff = _cutoff(cfg.get("lookback_hours", 48))
    min_chars = cfg.get("min_body_chars", 0)
    items: list[Item] = []
    for node in nodes:
        updated = _parse_dt(node.get("updatedAt", ""))
        if updated and updated < cutoff:
            continue
        body = node.get("body") or ""
        if len(body) < min_chars:
            continue
        slug = ((node.get("category") or {}).get("slug") or "")
        if weights and slug not in weights:
            continue
        items.append(Item(
            title=node.get("title", "").strip(),
            url=node.get("url", ""),
            brand=cfg.get("brand", "axis_launch"),
            source=name,
            published=(updated.date().isoformat() if updated else ""),
            summary=summarise(body),
            category=labels.get(slug, slug),
            author=((node.get("author") or {}).get("login") or ""),
            weight=weights.get(slug, 1),
            section="community",
            ladder="story",
        ))
    items.sort(key=lambda i: (-i.weight, i.published), reverse=False)
    items = items[: cfg.get("max_items", 8)]
    return items, SourceStatus(name, True, len(items),
                               f"{len(nodes)} discussions scanned")


# --------------------------------------------------------------------------- RSS

def fetch_rss(name: str, cfg: dict) -> tuple[list[Item], SourceStatus]:
    try:
        resp = _http_get(cfg["url"])
        root = ET.fromstring(resp.content)
    except Exception as exc:                            # noqa: BLE001
        return [], SourceStatus(name, False, 0, f"unreachable or unparseable: {exc}")

    cutoff = _cutoff(cfg.get("lookback_hours", 168))
    items: list[Item] = []
    # RSS 2.0 and Atom in one pass.
    entries = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")
    for entry in entries:
        def text(*names: str) -> str:
            for n in names:
                el = entry.find(n)
                if el is not None:
                    if el.text:
                        return el.text.strip()
                    if el.get("href"):
                        return el.get("href", "").strip()
            return ""

        title = text("title", "{http://www.w3.org/2005/Atom}title")
        link = text("link", "{http://www.w3.org/2005/Atom}link")
        when = _parse_dt(text("pubDate", "{http://www.w3.org/2005/Atom}updated",
                              "{http://www.w3.org/2005/Atom}published"))
        if when and when < cutoff:
            continue
        body = text("description", "{http://www.w3.org/2005/Atom}summary",
                    "{http://purl.org/rss/1.0/modules/content/}encoded")
        if not title or not link:
            continue
        items.append(Item(title=title, url=link, brand=cfg.get("brand", ""), source=name,
                          published=(when.date().isoformat() if when else ""),
                          summary=summarise(body), section="writing", ladder="purpose"))
    items = items[: cfg.get("max_items", 4)]
    return items, SourceStatus(name, True, len(items), f"{len(entries)} entries scanned")


# --------------------------------------------------------------------------- sitemap

def fetch_sitemap(name: str, cfg: dict) -> tuple[list[Item], SourceStatus]:
    try:
        resp = _http_get(cfg["url"])
        root = ET.fromstring(resp.content)
    except Exception as exc:                            # noqa: BLE001
        return [], SourceStatus(name, False, 0, f"unreachable or unparseable: {exc}")

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    cutoff = _cutoff(cfg.get("lookback_hours", 168))
    include = cfg.get("include_paths") or []
    items: list[Item] = []
    urls = root.findall(".//sm:url", ns) or root.findall(".//url")
    for url_el in urls:
        loc_el = url_el.find("sm:loc", ns)
        if loc_el is None:
            loc_el = url_el.find("loc")
        if loc_el is None or not loc_el.text:
            continue
        loc = loc_el.text.strip()
        if include and not any(seg in loc for seg in include):
            continue
        mod_el = url_el.find("sm:lastmod", ns)
        if mod_el is None:
            mod_el = url_el.find("lastmod")
        when = _parse_dt(mod_el.text if mod_el is not None and mod_el.text else "")
        if when and when < cutoff:
            continue
        slug = loc.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
        items.append(Item(title=slug.title() or loc, url=loc, brand=cfg.get("brand", ""),
                          source=name,
                          published=(when.date().isoformat() if when else ""),
                          summary="", section="writing", ladder="purpose"))
    items.sort(key=lambda i: i.published, reverse=True)
    items = items[: cfg.get("max_items", 6)]
    return items, SourceStatus(name, True, len(items), f"{len(urls)} urls scanned")


# --------------------------------------------------------------------------- manual queue

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def fetch_file_queue(name: str, cfg: dict) -> tuple[list[Item], SourceStatus]:
    import yaml
    directory = config.REPO_ROOT / cfg.get("path", "marketing/queue")
    if not directory.exists():
        return [], SourceStatus(name, True, 0, "queue directory absent")
    items: list[Item] = []
    skipped: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        raw = path.read_text(encoding="utf-8")
        match = _FRONT_MATTER.match(raw)
        if not match:
            skipped.append(f"{path.name}: no front matter")
            continue
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except Exception as exc:                        # noqa: BLE001
            skipped.append(f"{path.name}: bad front matter ({exc})")
            continue
        missing = [k for k in ("title", "brand", "url") if not meta.get(k)]
        if missing:
            skipped.append(f"{path.name}: missing {', '.join(missing)}")
            continue
        items.append(Item(
            title=str(meta["title"]), url=str(meta["url"]), brand=str(meta["brand"]),
            source=name, published=str(meta.get("date", "")),
            summary=summarise(match.group(2)), section=str(meta.get("section", "")),
            ladder=str(meta.get("ladder", "")), weight=int(meta.get("weight", 3)),
            customer_id=meta.get("customer_id") or None,
        ))
        items[-1].__dict__["_path"] = str(path)          # for the post-publish move
    detail = f"{len(items)} queued"
    if skipped:
        detail += f"; skipped {len(skipped)}: " + "; ".join(skipped[:3])
    return items, SourceStatus(name, True, len(items), detail)


FETCHERS = {
    "github_discussions": fetch_github_discussions,
    "rss": fetch_rss,
    "sitemap": fetch_sitemap,
    "file_queue": fetch_file_queue,
}


# --------------------------------------------------------------------------- dedupe

def _history_path() -> Path:
    return config.REPO_ROOT / config.sources()["dedupe"]["history_file"]


def load_history() -> list[dict]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return []


def record_history(issue_date: str, items: list[Item]) -> None:
    cfg = config.sources()["dedupe"]
    history = load_history()
    history.append({"date": issue_date, "keys": [getattr(i, cfg["key"]) for i in items]})
    history = history[-cfg["lookback_issues"]:]
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def dedupe_within(items: list[Item]) -> tuple[list[Item], int]:
    """Collapse duplicates inside one harvest.

    A sitemap and an RSS feed over the same blog return the same URLs; so do two sources
    pointed at the same site. Keep the richest copy of each: heavier weight first, then the
    one that actually has a summary.
    """
    cfg = config.sources()["dedupe"]
    best: dict[str, Item] = {}
    for item in items:
        key = _dedupe_key(getattr(item, cfg["key"]))
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        score = (item.weight, len(item.summary or ""), len(item.title or ""))
        current_score = (current.weight, len(current.summary or ""),
                         len(current.title or ""))
        if score > current_score:
            best[key] = item
    kept = list(best.values())
    return kept, len(items) - len(kept)


def _dedupe_key(url: str) -> str:
    """Normalise a URL so http/https, trailing slashes and tracking params collapse."""
    from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
    parts = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if not k.lower().startswith(("utm_", "ref", "fbclid", "gclid"))]
    return urlunsplit((
        "", parts.netloc.lower().removeprefix("www."),
        parts.path.rstrip("/") or "/", urlencode(sorted(query)), "",
    ))


def drop_seen(items: list[Item]) -> tuple[list[Item], int]:
    cfg = config.sources()["dedupe"]
    seen = {_dedupe_key(k) for entry in load_history() for k in entry.get("keys", [])}
    kept = [i for i in items if _dedupe_key(getattr(i, cfg["key"])) not in seen]
    return kept, len(items) - len(kept)


# --------------------------------------------------------------------------- harvest

def harvest(*, only_brand: str | None = None) -> Harvest:
    result = Harvest()
    for name, cfg in config.sources()["sources"].items():
        if not cfg.get("enabled", True):
            result.statuses.append(SourceStatus(name, True, 0, "disabled"))
            continue
        if only_brand and cfg.get("brand") not in (only_brand, "both"):
            continue
        fetcher = FETCHERS.get(cfg.get("type", ""))
        if not fetcher:
            result.statuses.append(SourceStatus(name, False, 0,
                                                f"unknown source type {cfg.get('type')!r}"))
            continue
        try:
            items, status = fetcher(name, cfg)
        except Exception as exc:                         # noqa: BLE001 - never break the send
            items, status = [], SourceStatus(name, False, 0, f"unhandled error: {exc}")
        result.items.extend(items)
        result.statuses.append(status)
    return result
