#!/usr/bin/env python3
"""Build one day's newsletter issue.

Harvests the seeded content (GitHub Discussions), both sites, and the manual queue; assembles
them into the shape the day's calendar slot calls for; renders HTML, plain text and a markdown
archive page; and runs every compliance guard before anything is written.

The send policy is deliberate: a thin day gets the short edition and an empty day holds. See
strategy/cadence.md - a daily newsletter is only defensible if most days earn the send.

Usage:
  python3 marketing/scripts/build_newsletter.py                 # today
  python3 marketing/scripts/build_newsletter.py --date 2026-09-12
  python3 marketing/scripts/build_newsletter.py --offline       # skip network sources
  python3 marketing/scripts/build_newsletter.py --force         # build even if it would hold
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, copy as C, guards, planner, sources  # noqa: E402

BRAND = "print_my_design"          # the sending brand; AXIS content rides along
SECTION_TITLES = {
    "community": "From the community",
    "writing": "New on the sites",
    "proof": "Off the press",
    "product": "From the shop",
    "editorial": "Also this week",
}


# --------------------------------------------------------------------------- palette

def palette() -> dict:
    raw = json.loads((config.BRAND_DIR / "palette.json").read_text(encoding="utf-8"))
    return {
        "orange": raw["core"]["print-orange"]["hex"],
        "orange_deep": raw["core"]["print-orange-deep"]["hex"],
        "blue": raw["core"]["print-blue"]["hex"],
        "blue_bright": raw["core"]["print-blue-bright"]["hex"],
        "ink": raw["neutral"]["ink"]["hex"],
        "graphite": raw["neutral"]["graphite"]["hex"],
        "slate": raw["neutral"]["slate"]["hex"],
        "rule": raw["neutral"]["rule"]["hex"],
        "paper": raw["neutral"]["paper"]["hex"],
    }


# --------------------------------------------------------------------------- assembly

def issue_number(date: dt.date) -> int:
    """Sequential issue number from the published index, so it survives re-runs."""
    history = sources.load_history()
    dates = sorted({h["date"] for h in history if h.get("date") < date.isoformat()})
    return len(dates) + 1


def group_sections(items: list[sources.Item], plan: planner.DayPlan) -> list[dict]:
    lim = config.limits("newsletter")
    buckets: dict[str, list[sources.Item]] = {}
    for item in items:
        key = item.section or "editorial"
        buckets.setdefault(key, []).append(item)

    # Thursday leads with the community; every other day leads with our own writing.
    order = (["community", "writing", "proof", "product", "editorial"]
             if plan.slot.get("cross_brand")
             else ["proof", "writing", "community", "product", "editorial"])

    sections: list[dict] = []
    for key in order:
        pool = buckets.get(key) or []
        if not pool:
            continue
        pool.sort(key=lambda i: (-i.weight, i.published or "", i.title))
        sections.append({
            "key": key,
            "title": SECTION_TITLES.get(key, key.title()),
            "blurb": "",
            # NB: "entries", not "items" - `section.items` in Jinja resolves to the
            # dict method, not the key, and silently yields a bound method.
            "entries": [i.as_dict() for i in pool[: lim["max_items_per_section"]]],
        })
    return sections[: lim["max_sections"]]


def compose_headline(plan: planner.DayPlan, sections: list[dict]) -> tuple[str, str, dict | None]:
    """Headline and standfirst, taken from the day's lead item rather than invented.

    The lead item is *removed* from its section: an issue that opens with a story and then
    lists the same story three inches further down reads like a bug, because it is one.
    """
    slot_lead = plan.slot.get("lead", "")
    for section in sections:
        if section["entries"]:
            lead = section["entries"].pop(0)
            # A section emptied by promoting its only item is dropped by the caller.
            return lead["title"], (lead.get("summary") or slot_lead), lead
    return plan.slot.get("label", "Today"), slot_lead, None


def compose_subject(plan: planner.DayPlan, headline: str, offer: dict | None) -> str:
    """Subject line.

    compliance.md #2: a number only appears here alongside its qualifier, which is why the
    offer's `phrase` (not its raw percentage) is what gets used.
    """
    lim = config.limits("newsletter")
    if offer and plan.ladder == "scarcity":
        base = str(offer.get("phrase") or C.offer_phrase(offer))
    else:
        base = headline
    return C.truncate(base, lim["subject_max_chars"])


def build_offer_block(plan: planner.DayPlan, date: dt.date) -> dict | None:
    if not plan.offer:
        return None
    offer = dict(plan.offer)
    ends = offer.get("ends")
    ends_long = ""
    if ends:
        try:
            ends_long = dt.date.fromisoformat(str(ends)).strftime("%-d %B")
        except ValueError:
            ends_long = str(ends)
    brand = config.brand(BRAND)
    return {
        "key": plan.offer_key,
        "phrase": str(offer.get("phrase") or C.offer_phrase(offer)),
        "exclusions_line": C.exclusions_line(offer),
        "ends_long": ends_long,
        "stacking": offer.get("stacking", ""),
        "cta": brand["primary_cta"]["label"],
        "url": C.newsletter_url(BRAND, brand["primary_cta"]["path"],
                                date=date.isoformat(), section="offer",
                                slug=plan.offer_key or "offer"),
        "_raw": offer,
    }


def build_issue(date: dt.date, *, offline: bool = False, force: bool = False
                ) -> tuple[dict, guards.GuardReport]:
    plan = planner.plan_for(date)
    lim = config.limits("newsletter")
    policy = config.weekly_slots()["send_policy"]
    brand = config.brand(BRAND)

    if offline:
        harvest = sources.Harvest(statuses=[sources.SourceStatus("all", True, 0,
                                                                "offline mode")])
        _, statuses = sources.fetch_file_queue(
            "manual_queue", config.sources()["sources"]["manual_queue"])
        queued, _ = sources.fetch_file_queue(
            "manual_queue", config.sources()["sources"]["manual_queue"])
        harvest.items = queued
        harvest.statuses.append(statuses)
    else:
        harvest = sources.harvest()

    unique, collapsed = sources.dedupe_within(harvest.items)
    fresh, dropped = sources.drop_seen(unique)
    sections = group_sections(fresh, plan)
    item_count = sum(len(s["entries"]) for s in sections)

    # Send policy: thin day -> short edition; empty day -> hold.
    shape = plan.slot.get("newsletter_shape", "standard")
    decision = "send"
    if item_count < policy["min_items_for_short"]:
        decision = "hold"
    elif item_count < policy["min_items_to_send"]:
        shape, decision = "short", "send_short"
    if plan.window.get("send_policy") == "hold":
        decision = "hold"
    if force and decision == "hold":
        decision = "send_forced"

    headline, standfirst, lead_item = compose_headline(plan, sections)
    sections = [sec for sec in sections if sec["entries"]]
    offer = build_offer_block(plan, date) if shape != "short" else None
    if plan.is_meaning_window:
        offer = None
    subject = compose_subject(plan, headline, offer["_raw"] if offer else None)
    preheader = C.truncate(standfirst or plan.slot.get("lead", ""),
                           lim["preheader_max_chars"])

    # ---- guards -----------------------------------------------------------
    report = guards.GuardReport()
    offer_raw = offer["_raw"] if offer else None
    checked = [(subject, "subject"), (preheader, "preheader"),
               (headline, "headline"), (standfirst, "standfirst")]
    for section in sections:
        for item in section["entries"]:
            checked.append((item["title"], f"item:{item['url']}"))
            checked.append((item.get("summary", ""), f"summary:{item['url']}"))
    if offer:
        checked.append((offer["phrase"], "offer.phrase"))
    if lead_item:
        checked.append((lead_item["title"], f"lead:{lead_item['url']}"))
        report.extend(guards.check_attribution(lead_item.get("customer_id"), today=date,
                                               where=f"lead:{lead_item['url']}"))
    for text, where in checked:
        report.extend(guards.check_copy(text, offer=offer_raw, window=plan.window,
                                        today=date, where=where))
    for section in sections:
        for item in section["entries"]:
            report.extend(guards.check_attribution(item.get("customer_id"),
                                                   today=date,
                                                   where=f"item:{item['url']}"))
    report.extend(guards.check_length(subject, lim["subject_max_chars"], "subject"))
    report.extend(guards.check_length(preheader, lim["preheader_max_chars"], "preheader"))
    report.extend(guards.check_send_preconditions(BRAND))

    site_display = re.sub(r"^https?://", "", brand["site"]).rstrip("/")
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "shape": shape,
        "subject": subject,
        "preheader": preheader,
        "plan": plan.as_dict(),
        "issue": {
            "date": date.isoformat(),
            "date_long": date.strftime("%-d %B %Y"),
            "slot_label": plan.slot.get("label", ""),
            "number": issue_number(date),
            "headline": headline,
            "standfirst": standfirst,
        },
        "brand": {
            "name": brand["name"], "site": brand["site"], "site_display": site_display,
            "from_name": brand["from_name"], "from_email": brand["from_email"],
            "reply_to": brand["reply_to"],
        },
        "lead_item": lead_item,
        "sections": sections,
        "offer": offer,
        "ps": plan.notes[0] if plan.notes and shape != "short" else "",
        "item_count": item_count,
        "deduped": dropped,
        "collapsed": collapsed,
        "sources": [s.as_dict() for s in harvest.statuses],
        "guards": {
            "ok": report.ok,
            "failures": [str(v) for v in report.failures],
            "warnings": [str(v) for v in report.warnings],
        },
    }
    return payload, report


# --------------------------------------------------------------------------- render

def render(payload: dict) -> dict[str, str]:
    env = Environment(loader=FileSystemLoader(str(config.TEMPLATE_DIR / "newsletter")),
                      undefined=StrictUndefined, autoescape=True,
                      trim_blocks=False, lstrip_blocks=False)
    brand = config.brand(BRAND)
    date = payload["issue"]["date"]
    ctx = {
        "palette": palette(),
        "asset_base": config.env("ASSET_BASE_URL",
                                 default=f"{brand['site'].rstrip('/')}/email-assets"),
        "postal_address": config.env(brand["postal_address_env"],
                                     default="[POSTAL ADDRESS NOT SET]"),
        "unsubscribe_url": config.env("UNSUBSCRIBE_URL",
                                      default=f"{brand['site'].rstrip('/')}/unsubscribe"),
        "preferences_url": config.env("PREFERENCES_URL",
                                      default=f"{brand['site'].rstrip('/')}/email-preferences"),
        "web_url": f"{brand['site'].rstrip('/')}/newsletter/{date}",
        "consent_note": config.env("CONSENT_NOTE", default=""),
        **payload,
    }
    html = env.get_template("issue.html.j2").render(**ctx)
    text_env = Environment(loader=FileSystemLoader(str(config.TEMPLATE_DIR / "newsletter")),
                           undefined=StrictUndefined, autoescape=False,
                           trim_blocks=True, lstrip_blocks=True)
    text = text_env.get_template("issue.txt.j2").render(**ctx)
    return {"html": html, "text": re.sub(r"\n{3,}", "\n\n", text)}


def render_archive(payload: dict, rendered: dict[str, str]) -> str:
    issue = payload["issue"]
    lines = [
        "---",
        f'title: "{issue["headline"]}"',
        f'date: {issue["date"]}',
        f'issue: {issue["number"]}',
        f'slot: "{issue["slot_label"]}"',
        f'subject: "{payload["subject"]}"',
        "---",
        "",
        f"# {issue['headline']}",
        "",
        f"*{issue['date_long']} &middot; {issue['slot_label']} &middot; "
        f"Issue {issue['number']}*",
        "",
    ]
    if issue["standfirst"]:
        lines += [issue["standfirst"], ""]
    if payload.get("lead_item"):
        lines += [f"[Read the full piece]({payload['lead_item']['url']})", ""]
    for section in payload["sections"]:
        lines += [f"## {section['title']}", ""]
        for item in section["entries"]:
            lines.append(f"### [{item['title']}]({item['url']})")
            if item.get("summary"):
                lines += ["", item["summary"]]
            meta = " &middot; ".join(x for x in (item.get("category"), item.get("author"),
                                                item.get("published")) if x)
            if meta:
                lines += ["", f"*{meta}*"]
            lines.append("")
    if payload["offer"]:
        o = payload["offer"]
        lines += ["## This week", "", f"**{o['phrase']}**", "",
                  o["exclusions_line"] + (f" Ends {o['ends_long']}." if o["ends_long"] else ""),
                  "", f"[{o['cta']}]({o['url']})", ""]
    if payload["ps"]:
        lines += [f"**P.S.** {payload['ps']}", ""]
    return "\n".join(lines)


def write_outputs(payload: dict, rendered: dict[str, str]) -> list[Path]:
    date = payload["issue"]["date"]
    out = config.OUT_DIR / "newsletter" / date
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in (("issue.html", rendered["html"]),
                          ("issue.txt", rendered["text"]),
                          ("archive.md", render_archive(payload, rendered))):
        path = out / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    meta = out / "issue.json"
    meta.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    written.append(meta)
    return written


def retire_queue_items(payload: dict) -> int:
    """Move published manual-queue files into queue/published/ so they do not repeat."""
    moved = 0
    published_dir = config.QUEUE_DIR / "published"
    published_dir.mkdir(parents=True, exist_ok=True)
    urls = {i["url"] for s in payload["sections"] for i in s["entries"]}
    if payload.get("lead_item"):
        urls.add(payload["lead_item"]["url"])
    for path in config.QUEUE_DIR.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        if any(url in text for url in urls):
            shutil.move(str(path), str(published_dir /
                                       f"{payload['issue']['date']}-{path.name}"))
            moved += 1
    return moved


# --------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--offline", action="store_true", help="skip network sources")
    ap.add_argument("--force", action="store_true", help="build even if policy says hold")
    ap.add_argument("--no-write", action="store_true", help="build and report, write nothing")
    args = ap.parse_args(argv)

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    payload, report = build_issue(date, offline=args.offline, force=args.force)

    plan = payload["plan"]
    print(f"=== newsletter {date.isoformat()} ({plan['weekday']}) ===")
    print(f"  window   {plan['window']['label']}  |  slot {plan['slot']['label']}")
    print(f"  decision {payload['decision']}  shape {payload['shape']}  "
          f"items {payload['item_count']} "
          f"(collapsed {payload['collapsed']}, already sent {payload['deduped']})")
    print(f"  subject  {payload['subject']!r} ({len(payload['subject'])} chars)")
    for s in payload["sources"]:
        flag = "ok " if s["ok"] else "ERR"
        print(f"    [{flag}] {s['name']:<22} n={s['count']:<3} {s['detail'][:64]}")

    if payload["decision"] == "hold":
        print("  HOLD: nothing worth sending today. This is a clean exit, not a failure.")
        print("        strategy/cadence.md - a daily newsletter is only defensible if most "
              "days earn the send.")
        return 0

    rendered = render(payload)
    if not args.no_write:
        written = write_outputs(payload, rendered)
        moved = retire_queue_items(payload)
        # Record what went out so tomorrow's issue does not repeat it, and so issue
        # numbers advance. The workflow commits marketing/out, which is what carries this
        # state from one run to the next.
        published = [sources.Item(**{k: v for k, v in entry.items()
                                     if k in sources.Item.__annotations__})
                     for section in payload["sections"] for entry in section["entries"]]
        if payload.get("lead_item"):
            published.append(sources.Item(**{
                k: v for k, v in payload["lead_item"].items()
                if k in sources.Item.__annotations__}))
        sources.record_history(payload["issue"]["date"], published)
        print(f"  wrote {len(written)} files to "
              f"{written[0].parent.relative_to(config.REPO_ROOT)}"
              + (f"; retired {moved} queue item(s)" if moved else "")
              + f"; recorded {len(published)} item(s) against future dedupe")

    if report.failures:
        print("\n" + report.summary())
        return 1
    if report.warnings:
        print(f"  {len(report.warnings)} warning(s): "
              + "; ".join(w.message[:70] for w in report.warnings[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
