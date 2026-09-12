"""Tests for content harvesting: deduplication, summarising, date parsing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import sources  # noqa: E402


def item(url, *, title="T", summary="", weight=1):
    return sources.Item(title=title, url=url, brand="b", source="s",
                        summary=summary, weight=weight)


def test_same_url_from_two_sources_collapses():
    kept, n = sources.dedupe_within([item("https://x.com/a"), item("https://x.com/a")])
    assert len(kept) == 1 and n == 1


def test_trailing_slash_and_scheme_collapse():
    kept, n = sources.dedupe_within([item("https://x.com/a/"), item("http://x.com/a")])
    assert len(kept) == 1 and n == 1


def test_www_prefix_collapses():
    kept, _ = sources.dedupe_within([item("https://www.x.com/a"), item("https://x.com/a")])
    assert len(kept) == 1


def test_utm_params_do_not_prevent_collapse():
    kept, _ = sources.dedupe_within(
        [item("https://x.com/a?utm_source=rss"), item("https://x.com/a")])
    assert len(kept) == 1


def test_meaningful_query_params_stay_distinct():
    kept, _ = sources.dedupe_within(
        [item("https://x.com/a?page=2"), item("https://x.com/a")])
    assert len(kept) == 2


def test_richest_copy_wins():
    kept, _ = sources.dedupe_within([
        item("https://x.com/a", summary=""),
        item("https://x.com/a", summary="a real summary", weight=3),
    ])
    assert kept[0].summary == "a real summary"


def test_distinct_urls_are_kept():
    kept, n = sources.dedupe_within([item("https://x.com/a"), item("https://x.com/b")])
    assert len(kept) == 2 and n == 0


def test_summarise_skips_a_heading():
    assert sources.summarise("# Title\n\nThe actual body.") == "The actual body."


def test_summarise_trims_on_a_word_boundary():
    out = sources.summarise("word " * 200, limit=50)
    assert len(out) <= 53 and not out.rstrip(".").endswith("wor")


def test_summarise_handles_empty():
    assert sources.summarise("") == ""


def test_rfc822_dates_parse():
    assert sources._parse_dt("Fri, 11 Sep 2026 18:00:00 +0000") is not None


def test_iso_dates_parse():
    assert sources._parse_dt("2026-09-11T18:00:00Z") is not None


def test_garbage_dates_return_none():
    assert sources._parse_dt("not a date") is None


def test_harvest_never_raises_when_everything_is_down():
    """The whole point of the contract: one dead feed must not take down the send."""
    h = sources.harvest()
    assert isinstance(h.items, list)
    assert all(isinstance(s.ok, bool) for s in h.statuses)


# --- cross-issue dedupe must actually persist (regression) -------------------

def test_history_round_trip_suppresses_a_repeat(tmp_path=None):
    """record_history was defined but never called, so every issue re-sent the same
    items and the issue number never advanced. This holds that fix in place."""
    import json, tempfile
    from pathlib import Path as P
    original = sources._history_path
    with tempfile.TemporaryDirectory() as tmp:
        fake = P(tmp) / "index.json"
        sources._history_path = lambda: fake
        try:
            assert sources.load_history() == []
            first = [item("https://x.com/a"), item("https://x.com/b")]
            kept, dropped = sources.drop_seen(first)
            assert len(kept) == 2 and dropped == 0

            sources.record_history("2026-09-11", first)
            assert len(sources.load_history()) == 1

            # Same items tomorrow: both suppressed.
            kept, dropped = sources.drop_seen(first)
            assert kept == [] and dropped == 2

            # A new item still gets through.
            kept, _ = sources.drop_seen(first + [item("https://x.com/c")])
            assert [i.url for i in kept] == ["https://x.com/c"]
        finally:
            sources._history_path = original


def test_history_matches_across_url_variants():
    import tempfile
    from pathlib import Path as P
    original = sources._history_path
    with tempfile.TemporaryDirectory() as tmp:
        sources._history_path = lambda: P(tmp) / "index.json"
        try:
            sources.record_history("2026-09-11", [item("https://x.com/a")])
            kept, dropped = sources.drop_seen([item("http://www.x.com/a/?utm_source=rss")])
            assert kept == [] and dropped == 1
        finally:
            sources._history_path = original


def test_history_is_trimmed_to_the_lookback_window():
    import tempfile
    from pathlib import Path as P
    from lib import config
    original = sources._history_path
    limit = config.sources()["dedupe"]["lookback_issues"]
    with tempfile.TemporaryDirectory() as tmp:
        sources._history_path = lambda: P(tmp) / "index.json"
        try:
            for day in range(limit + 10):
                sources.record_history(f"2026-01-{day + 1:02d}", [item(f"https://x.com/{day}")])
            assert len(sources.load_history()) == limit
        finally:
            sources._history_path = original


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn(); passed += 1
        except Exception:
            failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)
