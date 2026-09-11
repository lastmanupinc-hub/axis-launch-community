#!/usr/bin/env python3
"""Dispatch a built newsletter issue to the email service provider.

DRY RUN IS THE DEFAULT. Nothing leaves this machine unless --live is passed AND the
provider credentials are present AND every compliance guard passes. There is no flag that
skips the guards.

Providers: buttondown, resend, mailchimp. Selected with NEWSLETTER_PROVIDER.
Credentials come from the environment only; nothing is read from a file in the repo.

Usage:
  python3 marketing/scripts/send_newsletter.py --date 2026-09-11             # dry run
  python3 marketing/scripts/send_newsletter.py --date 2026-09-11 --live      # sends
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, guards  # noqa: E402

BRAND = "print_my_design"


class SendError(RuntimeError):
    pass


# --------------------------------------------------------------------------- providers

def send_buttondown(payload: dict, html: str, text: str, *, live: bool) -> dict:
    key = config.env("BUTTONDOWN_API_KEY", required=True)
    body = {
        "subject": payload["subject"],
        "body": html,
        "email_type": "public",
    }
    if not live:
        return {"provider": "buttondown", "would_post": "/v1/emails", "body_keys": list(body)}
    resp = requests.post(
        "https://api.buttondown.email/v1/emails",
        headers={"Authorization": f"Token {key}"}, json=body, timeout=30,
    )
    if resp.status_code >= 300:
        raise SendError(f"buttondown {resp.status_code}: {resp.text[:300]}")
    return {"provider": "buttondown", "status": resp.status_code, "id": resp.json().get("id")}


def send_resend(payload: dict, html: str, text: str, *, live: bool) -> dict:
    key = config.env("RESEND_API_KEY", required=True)
    audience = config.env("RESEND_AUDIENCE_ID", required=True)
    brand = config.brand(BRAND)
    body = {
        "from": f"{brand['from_name']} <{brand['from_email']}>",
        "reply_to": brand["reply_to"],
        "subject": payload["subject"],
        "html": html,
        "text": text,
        "audience_id": audience,
    }
    if not live:
        return {"provider": "resend", "would_post": "/broadcasts",
                "from": body["from"], "audience_id": audience}
    resp = requests.post(
        "https://api.resend.com/broadcasts",
        headers={"Authorization": f"Bearer {key}"}, json=body, timeout=30,
    )
    if resp.status_code >= 300:
        raise SendError(f"resend {resp.status_code}: {resp.text[:300]}")
    return {"provider": "resend", "status": resp.status_code, "id": resp.json().get("id")}


def send_mailchimp(payload: dict, html: str, text: str, *, live: bool) -> dict:
    key = config.env("MAILCHIMP_API_KEY", required=True)
    list_id = config.env("MAILCHIMP_LIST_ID", required=True)
    server = key.rsplit("-", 1)[-1] if "-" in key else config.env("MAILCHIMP_SERVER",
                                                                 required=True)
    brand = config.brand(BRAND)
    base = f"https://{server}.api.mailchimp.com/3.0"
    settings = {
        "subject_line": payload["subject"],
        "preview_text": payload["preheader"],
        "title": f"Daily {payload['issue']['date']}",
        "from_name": brand["from_name"],
        "reply_to": brand["reply_to"],
    }
    if not live:
        return {"provider": "mailchimp", "would_post": f"{base}/campaigns",
                "list_id": list_id, "settings": settings}
    created = requests.post(f"{base}/campaigns", auth=("key", key), timeout=30, json={
        "type": "regular", "recipients": {"list_id": list_id}, "settings": settings})
    if created.status_code >= 300:
        raise SendError(f"mailchimp create {created.status_code}: {created.text[:300]}")
    cid = created.json()["id"]
    content = requests.put(f"{base}/campaigns/{cid}/content", auth=("key", key), timeout=30,
                           json={"html": html, "plain_text": text})
    if content.status_code >= 300:
        raise SendError(f"mailchimp content {content.status_code}: {content.text[:300]}")
    sent = requests.post(f"{base}/campaigns/{cid}/actions/send", auth=("key", key),
                         timeout=30)
    if sent.status_code >= 300:
        raise SendError(f"mailchimp send {sent.status_code}: {sent.text[:300]}")
    return {"provider": "mailchimp", "campaign_id": cid, "status": sent.status_code}


PROVIDERS = {
    "buttondown": send_buttondown,
    "resend": send_resend,
    "mailchimp": send_mailchimp,
}


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--live", action="store_true",
                    help="actually send. Without this nothing leaves the machine.")
    args = ap.parse_args(argv)

    date = args.date or dt.date.today().isoformat()
    issue_dir = config.OUT_DIR / "newsletter" / date
    meta_path = issue_dir / "issue.json"
    if not meta_path.exists():
        print(f"no built issue at {issue_dir.relative_to(config.REPO_ROOT)}.")
        print(f"  Nothing to send. Run build_newsletter.py --date {date} first, or the day "
              "held by policy.")
        return 0

    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    html = (issue_dir / "issue.html").read_text(encoding="utf-8")
    text = (issue_dir / "issue.txt").read_text(encoding="utf-8")

    if payload["decision"] == "hold":
        print("issue is marked hold; not sending.")
        return 0

    # Guards run again at send time. A build that passed yesterday can fail today - an
    # offer's end date may have gone by in between.
    report = guards.GuardReport()
    report.extend(guards.check_send_preconditions(BRAND))
    offer = (payload.get("offer") or {}).get("_raw")
    today = dt.date.fromisoformat(date)
    for field in ("subject", "preheader"):
        report.extend(guards.check_copy(payload[field], offer=offer,
                                        window=payload["plan"]["window"], today=today,
                                        where=field))
    if payload["guards"]["failures"]:
        for failure in payload["guards"]["failures"]:
            report.add(guards.Violation("build-time-failure", "fail", where="build",
                                        message=failure))
    if not report.ok:
        print(report.summary())
        print("\nREFUSING TO SEND. Fix the failures above; there is no override flag.")
        return 1

    provider_name = config.env("NEWSLETTER_PROVIDER", default="buttondown").lower()
    provider = PROVIDERS.get(provider_name)
    if not provider:
        print(f"unknown NEWSLETTER_PROVIDER {provider_name!r}. "
              f"Known: {', '.join(sorted(PROVIDERS))}")
        return 1

    mode = "LIVE SEND" if args.live else "dry run"
    print(f"=== {mode}: {provider_name} ===")
    print(f"  date      {date}")
    print(f"  subject   {payload['subject']!r}")
    print(f"  preheader {payload['preheader'][:70]!r}")
    print(f"  html      {len(html):,} bytes    text {len(text):,} bytes")
    print(f"  guards    clean ({len(report.warnings)} warning(s))")

    try:
        result = provider(payload, html, text, live=args.live)
    except config.ConfigError as exc:
        print(f"\n  missing credentials: {exc}")
        return 0 if not args.live else 1
    except SendError as exc:
        print(f"\n  SEND FAILED: {exc}")
        return 1

    print("  result    " + json.dumps(result))
    if not args.live:
        print("\n  Dry run only. Nothing was sent. Re-run with --live to dispatch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
