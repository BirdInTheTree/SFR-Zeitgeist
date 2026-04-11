"""
Fetch daily program data from SRF EPG API and save to demo-data/week/.

The EPG API only keeps ~2 weeks of data. Run this daily (cron or manual)
to accumulate history beyond the API window. Saved data never expires —
the pipeline uses it for baseline computation.

For each program with subtitles, fetches and cleans the VTT text
so the week JSON is self-contained for pipeline processing.

Usage:
    python -m backend.fetch_epg                  # today
    python -m backend.fetch_epg 2026-04-01        # specific date
    python -m backend.fetch_epg --range 7         # today + 6 days back
"""

import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEK_DIR = PROJECT_ROOT / "demo-data" / "week"
VTT_CACHE_DIR = PROJECT_ROOT / "demo-data" / "cache" / "vtt"

EPG_URL = "https://www.srf.ch/play/v3/api/srf/production/tv-program-guide"
IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"


def fetch_epg_schedule(date_str: str) -> list[dict]:
    """Fetch program schedule for a date from SRF EPG API.

    Returns list of raw program entries.
    """
    url = f"{EPG_URL}?date={date_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    programs = []
    for channel_data in data.get("data", []):
        channel = channel_data.get("channel", {}).get("title", "")
        for prog in channel_data.get("programList", []):
            programs.append({
                "date": date_str,
                "channel": channel,
                "title": prog.get("title", ""),
                "startTime": prog.get("startTime", ""),
                "genre": prog.get("genre", ""),
                "urn": prog.get("urn", ""),
            })
    return programs


def fetch_subtitle_text(urn: str) -> tuple[str, int]:
    """Fetch and clean VTT subtitle text for a program.

    Returns (cleaned_text, word_count). Caches VTT to disk.
    """
    from .segmenter import get_vtt_cached, save_vtt_cache

    # Check VTT cache first
    cached = get_vtt_cached(urn, VTT_CACHE_DIR)
    if cached:
        clean = _clean_vtt_text(cached)
        return clean, len(clean.split())

    # Fetch media info from Integration Layer
    url = f"{IL_BASE}/{urn}?onlyChapters=true&vector=portalplay"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return "", 0

    chapter = data.get("chapterList", [{}])[0]
    vtt_url = ""
    for sub in chapter.get("subtitleList", []):
        if sub.get("format") == "VTT":
            vtt_url = sub.get("url", "")
            break
    if not vtt_url:
        return "", 0

    # Download VTT
    req = urllib.request.Request(vtt_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            vtt_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return "", 0

    # Cache raw VTT
    save_vtt_cache(urn, vtt_text, VTT_CACHE_DIR)

    clean = _clean_vtt_text(vtt_text)
    return clean, len(clean.split())


def _clean_vtt_text(vtt_text: str) -> str:
    """Extract plain text from VTT, strip tags and timestamps."""
    lines = []
    for line in vtt_text.splitlines():
        # Skip timestamp lines and headers
        if "-->" in line or line.startswith("WEBVTT") or line.strip().isdigit():
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            lines.append(clean)
    return " ".join(lines)


def fetch_and_save_day(date_str: str) -> Path:
    """Fetch all programs for a date, enrich with subtitles, save to disk.

    Skips dates that already have a saved file (idempotent).
    """
    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WEEK_DIR / f"{date_str}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text())
        print(f"  {date_str}: already saved ({len(existing)} programs)")
        return out_path

    print(f"  {date_str}: fetching EPG schedule...", end=" ", flush=True)
    programs = fetch_epg_schedule(date_str)
    print(f"{len(programs)} programs")

    # Enrich with subtitle text
    for i, prog in enumerate(programs):
        urn = prog.get("urn", "")
        if not urn:
            prog["subtitle_text_clean"] = ""
            prog["word_count"] = 0
            continue

        text, wc = fetch_subtitle_text(urn)
        prog["subtitle_text_clean"] = text
        prog["word_count"] = wc

        if (i + 1) % 20 == 0:
            print(f"    subtitles: {i+1}/{len(programs)}", flush=True)

    # Save incrementally — write after all subtitles fetched for this day
    out_path.write_text(
        json.dumps(programs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    news_count = sum(1 for p in programs if p.get("genre") == "Nachrichten")
    print(f"  {date_str}: saved {len(programs)} programs ({news_count} news) → {out_path.name}")
    return out_path


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--range":
        n_days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        today = date.today()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(n_days)]
        dates.reverse()
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        dates = [sys.argv[1]]
    else:
        dates = [date.today().isoformat()]

    print(f"=== SRF EPG Fetcher ===")
    print(f"Fetching {len(dates)} day(s): {dates[0]} → {dates[-1]}\n")

    for d in dates:
        try:
            fetch_and_save_day(d)
        except Exception as e:
            print(f"  {d}: ERROR — {e}")


if __name__ == "__main__":
    main()
