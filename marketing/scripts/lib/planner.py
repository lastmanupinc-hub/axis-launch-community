"""Resolve a date into a plan: which annual window, which weekday slot, which offer.

This is the only place that answers "what is today supposed to be?". Both the newsletter
builder and the ad builder start here so they cannot disagree about the day.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import config


@dataclass
class DayPlan:
    date: dt.date
    weekday: str                 # "monday" ...
    window: dict                 # record from calendar/annual.yml
    slot: dict                   # record from calendar/weekly-slots.yml
    offer: dict | None           # record from config/products.yml, or None
    offer_key: str | None
    lead_products: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_meaning_window(self) -> bool:
        return bool(self.window.get("meaning_window"))

    @property
    def discount_weight(self) -> float:
        return float(self.window.get("discount_weight", 0.0))

    @property
    def ladder(self) -> str:
        return self.slot.get("ladder", "purpose")

    @property
    def families(self) -> list[str]:
        return list(self.slot.get("families", []))

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "weekday": self.weekday,
            "window": {"id": self.window.get("id"), "label": self.window.get("label"),
                       "posture": self.window.get("posture"),
                       "discount_weight": self.discount_weight,
                       "meaning_window": self.is_meaning_window},
            "slot": {"label": self.slot.get("label"), "ladder": self.ladder,
                     "families": self.families,
                     "newsletter_shape": self.slot.get("newsletter_shape"),
                     "cross_brand": bool(self.slot.get("cross_brand"))},
            "offer": ({"key": self.offer_key, **{k: v for k, v in (self.offer or {}).items()}}
                      if self.offer else None),
            "lead_products": self.lead_products,
            "notes": self.notes,
        }


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _md(value: str) -> tuple[int, int]:
    month, day = value.split("-")
    return int(month), int(day)


def _in_window(date: dt.date, window: dict) -> bool:
    """Month-day comparison so windows roll over year to year, including across New Year."""
    start, end = _md(window["from"]), _md(window["to"])
    today = (date.month, date.day)
    if start <= end:
        return start <= today <= end
    return today >= start or today <= end      # wraps the year boundary (the dark window)


def resolve_window(date: dt.date) -> dict:
    for window in config.annual_calendar()["windows"]:
        if _in_window(date, window):
            return window
    # Every day should match something; if the calendar has a hole, fail loudly rather than
    # silently inventing a posture.
    raise config.ConfigError(
        f"no annual window covers {date.isoformat()}. calendar/annual.yml has a gap."
    )


def resolve_slot(date: dt.date) -> tuple[str, dict]:
    weekday = WEEKDAYS[date.weekday()]
    slots = config.weekly_slots()["days"]
    if weekday not in slots:
        raise config.ConfigError(f"calendar/weekly-slots.yml has no entry for {weekday}")
    return weekday, slots[weekday]


def _offer_is_live(offer: dict, date: dt.date) -> bool:
    starts = offer.get("starts")
    ends = offer.get("ends")
    if starts and dt.date.fromisoformat(str(starts)) > date:
        return False
    if ends and dt.date.fromisoformat(str(ends)) < date:
        return False
    return True


def resolve_offer(date: dt.date, window: dict, slot: dict) -> tuple[str | None, dict | None]:
    """Pick the day's offer.

    Rules, in order:
      1. The meaning window carries no offer, ever.
      2. A window with discount_weight 0 carries no offer.
      3. Prefer a live seasonal offer whose products overlap the window's lead products -
         seasonal offers are the ones with real end dates, so they are the only ones that
         can carry urgency.
      4. Otherwise fall back to the always-on offer, which can be stated but never rushed.
      5. On a low-discount day (weight < 0.35) that is not the scarcity slot, prefer no offer
         at all over a weak one. A quiet day is better than a limp sale.
    """
    if window.get("meaning_window"):
        return None, None
    weight = float(window.get("discount_weight", 0.0))
    if weight <= 0.0:
        return None, None

    catalogue = config.products()
    lead = set(window.get("lead_products") or [])

    seasonal = catalogue.get("seasonal_offers") or {}
    candidates = [
        (key, offer) for key, offer in seasonal.items()
        if _offer_is_live(offer, date)
        and (not lead or lead.intersection(offer.get("applies_to") or []))
    ]
    if candidates:
        # Prefer the one ending soonest: it is the most honestly urgent.
        candidates.sort(key=lambda kv: str(kv[1].get("ends") or "9999-12-31"))
        return candidates[0]

    if weight < 0.35 and slot.get("ladder") != "scarcity":
        return None, None

    always = catalogue.get("offers") or {}
    for key in ("first_order", "spend_ladder", "free_shipping", "email_signup"):
        offer = always.get(key)
        if offer and _offer_is_live(offer, date):
            return key, offer
    return None, None


def plan_for(date: dt.date) -> DayPlan:
    window = resolve_window(date)
    weekday, slot = resolve_slot(date)
    offer_key, offer = resolve_offer(date, window, slot)

    lead = list(window.get("lead_products") or [])
    if not lead:
        lead = [k for k, v in config.products()["products"].items()
                if v.get("role") in ("acquisition", "lead_magnet")]

    notes: list[str] = []
    for source in (window, slot):
        if source.get("note"):
            notes.append(source["note"].strip())
    if window.get("rotating_daily"):
        notes.append("Peak week: today's deal must be materially different from yesterday's.")
    if offer is None and not window.get("meaning_window"):
        notes.append("No offer today by design. Lead with the content.")

    return DayPlan(date=date, weekday=weekday, window=window, slot=slot,
                   offer=offer, offer_key=offer_key, lead_products=lead, notes=notes)


def plan_range(start: dt.date, days: int) -> list[DayPlan]:
    return [plan_for(start + dt.timedelta(days=i)) for i in range(days)]
