"""
SRF Zeitgeist pipeline — weekly story-level segmentation.

Processes a week of SRF news broadcasts into a 7×7 grid of 49 keywords.
Each broadcast is segmented by LLM, segments are merged into stories,
scored by five signals, and displayed with video frames.

Usage:
    python -m backend.pipeline 2026-03-30          # one week (Monday date)
    python -m backend.pipeline --all               # all available weeks
    python -m backend.pipeline --all --no-images   # skip frame extraction
"""

import copy
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .scorer import score_story, novelty, spread, persistence, prominence, primetime, PRIMETIME_HOUR
from .segmenter import (
    fetch_vtt_url,
    download_vtt,
    parse_vtt,
    vtt_blocks_to_transcript,
    get_vtt_cached,
    save_vtt_cache,
    segment_broadcast,
    merge_segments_into_stories,
    compute_fingerprint,
    extract_segment_text,
    find_importance_peak,
    seconds_to_tc,
    tc_to_seconds,
)
from .frames import fetch_frames
from .baseline import load_baseline

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEK_DIR = PROJECT_ROOT / "demo-data" / "week"
OUTPUT_DIR = PROJECT_ROOT / "demo-data"
VTT_CACHE_DIR = OUTPUT_DIR / "cache" / "vtt"
SEGMENT_CACHE_DIR = OUTPUT_DIR / "cache" / "segments"

GRID_SIZE = 49
MIN_WORD_COUNT = 5


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_day(date_str: str) -> list[dict]:
    """Load programs for a single date from week/ folder."""
    path = WEEK_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()) or []


def filter_news(programs: list[dict]) -> list[dict]:
    """Keep only Nachrichten genre, skip near-empty subtitles."""
    return [
        p for p in programs
        if p.get("genre") == "Nachrichten"
        and p.get("word_count", 0) >= MIN_WORD_COUNT
    ]


def editorial_unit(title: str) -> str:
    """Collapse variant broadcasts into base editorial unit.

    'Tagesschau in Gebärdensprache' → 'Tagesschau'
    """
    for suffix in (" in Gebaerdensprache", " in Gebärdensprache", " kompakt", " extra"):
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


# ---------------------------------------------------------------------------
# Step 1: Fetch VTT subtitles
# ---------------------------------------------------------------------------

def fetch_program_vtt(program: dict) -> list[dict] | None:
    """Fetch and parse VTT for a program. Returns parsed blocks or None."""
    urn = program.get("urn", "")
    if not urn:
        return None

    cached = get_vtt_cached(urn, VTT_CACHE_DIR)
    if cached:
        blocks = parse_vtt(cached)
        return blocks if blocks else None

    media_info = fetch_vtt_url(urn)
    vtt_url = media_info.get("vttUrl", "")
    if not vtt_url:
        return None

    try:
        vtt_text = download_vtt(vtt_url)
    except Exception as e:
        logger.warning("VTT download failed for %s: %s", urn, e)
        return None

    save_vtt_cache(urn, vtt_text, VTT_CACHE_DIR)

    hls_url = media_info.get("hlsUrl", "")
    if hls_url:
        program["_hlsUrl"] = hls_url
    img_url = media_info.get("imageUrl", "")
    if img_url:
        program["_imageUrl"] = img_url

    blocks = parse_vtt(vtt_text)
    return blocks if blocks else None


# ---------------------------------------------------------------------------
# Step 2: Segment broadcasts
# ---------------------------------------------------------------------------

def _segment_cache_path(program: dict) -> Path:
    """Cache path for segmentation result."""
    urn = program.get("urn", "").replace(":", "_").replace("/", "_")
    return SEGMENT_CACHE_DIR / f"{urn}.json"


def _load_prev_week_keywords(week_start: str) -> list[str]:
    """Load top keywords from the previous week's zeitgeist output."""
    prev_monday = (date.fromisoformat(week_start) - timedelta(days=7)).isoformat()
    prev_compact = prev_monday.replace("-", "")
    prev_path = OUTPUT_DIR / f"zeitgeist_week_{prev_compact}.json"
    if not prev_path.exists():
        return []
    try:
        data = json.loads(prev_path.read_text())
        return [entry["keyword"] for entry in data if entry.get("keyword")]
    except Exception:
        return []


# Segment types that represent actual news content (not structural).
# Weather excluded from grid — it's evergreen and dominates scoring.
_CONTENT_TYPES = {"story", "sport"}


def _filter_story_segments(segments: list[dict]) -> list[dict]:
    """Remove intro/outro/teaser segments and empty micro-segments."""
    return [
        s for s in segments
        if s.get("segment_type", "story") in _CONTENT_TYPES
        and s.get("segment_text", "")
    ]


def _clone_segments_for_rebroadcast(
    original_segments: list[dict], prog: dict,
) -> list[dict]:
    """Create copies of segments with a re-broadcast's metadata."""
    cloned = []
    for seg in original_segments:
        new_seg = copy.deepcopy(seg)
        new_seg["startTime"] = prog.get("startTime", "")
        new_seg["program"] = prog["title"]
        new_seg["editorial_unit"] = editorial_unit(prog["title"])
        new_seg["is_rebroadcast"] = True
        cloned.append(new_seg)
    return cloned


def segment_all_broadcasts(programs: list[dict], target_date: str = "") -> list[dict]:
    """Segment all news programs into stories via LLM.

    Processes broadcasts chronologically with keyword chaining.
    Re-broadcasts (same URN) reuse first airing's segments.
    """
    SEGMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    sorted_programs = sorted(programs, key=lambda p: p.get("startTime", ""))
    prev_kw = _load_prev_week_keywords(target_date) if target_date else []

    all_segments = []
    known_keywords = list(prev_kw)
    seen_urns: dict[str, list[dict]] = {}

    for i, prog in enumerate(sorted_programs):
        title = prog["title"]
        urn = prog.get("urn", "")
        cache_path = _segment_cache_path(prog)

        if urn and urn in seen_urns:
            reused = _clone_segments_for_rebroadcast(seen_urns[urn], prog)
            all_segments.extend(reused)
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} rebroadcast ({len(reused)} segments)")
            continue

        if cache_path.exists():
            segments = json.loads(cache_path.read_text())
            segments = _filter_story_segments(segments)
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} cached ({len(segments)} segments)")
            for seg in segments:
                kw = seg.get("keyword", "")
                if kw and kw not in known_keywords:
                    known_keywords.append(kw)
            if urn:
                seen_urns[urn] = segments
            all_segments.extend(segments)
            continue

        blocks = fetch_program_vtt(prog)
        if not blocks:
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} no VTT")
            continue

        transcript = vtt_blocks_to_transcript(blocks)
        try:
            segments = segment_broadcast(
                transcript, title,
                existing_keywords=known_keywords if known_keywords else None,
            )
        except Exception as e:
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} LLM error: {e}")
            continue

        for seg in segments:
            seg["urn"] = urn
            seg["channel"] = prog.get("channel", "")
            seg["editorial_unit"] = editorial_unit(title)
            seg["startTime"] = prog.get("startTime", "")

            seg_text = extract_segment_text(
                blocks, seg.get("start_time", ""), seg.get("end_time", ""),
            )
            seg["segment_text"] = seg_text
            seg["fingerprint"] = compute_fingerprint(seg_text)

            if not seg.get("peak_time") and blocks:
                try:
                    start_sec = tc_to_seconds(seg.get("start_time", "0:0:0"))
                    end_sec = tc_to_seconds(seg.get("end_time", "0:0:0"))
                    peak_sec = find_importance_peak(blocks, start_sec, end_sec)
                    if peak_sec is not None:
                        seg["peak_time"] = seconds_to_tc(peak_sec)
                except (ValueError, IndexError):
                    pass

            kw = seg.get("keyword", "")
            if kw and kw not in known_keywords:
                known_keywords.append(kw)

        cache_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
        segments = _filter_story_segments(segments)

        if urn:
            seen_urns[urn] = segments
        print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} {len(segments)} segments")
        all_segments.extend(segments)

    return all_segments


# ---------------------------------------------------------------------------
# Step 3: Score stories
# ---------------------------------------------------------------------------

def _extract_hour(start_time_iso: str) -> int | None:
    """Extract hour from ISO start time like '2026-04-01T19:30:00+02:00'."""
    if not start_time_iso or "T" not in start_time_iso:
        return None
    try:
        return int(start_time_iso.split("T")[1][:2])
    except (IndexError, ValueError):
        return None


def _segment_duration(seg: dict) -> float:
    """Compute segment duration in seconds from start_time/end_time."""
    try:
        start = tc_to_seconds(seg.get("start_time", ""))
        end = tc_to_seconds(seg.get("end_time", ""))
        return max(end - start, 0)
    except (ValueError, IndexError):
        return 0


def _real_air_sort_key(seg: dict) -> float:
    """Sort key for finding first mention: program start + segment offset."""
    iso = seg.get("startTime", "")
    try:
        time_part = iso.split("T")[1][:8]
        h, m, s = int(time_part[:2]), int(time_part[3:5]), int(time_part[6:8])
        prog_seconds = h * 3600 + m * 60 + s
    except (IndexError, ValueError):
        return 99 * 3600

    try:
        offset = tc_to_seconds(seg.get("start_time", "00:00:00"))
    except (ValueError, IndexError):
        offset = 0

    return prog_seconds + offset


def build_stories(
    all_segments: list[dict],
    stories_meta: list[dict],
    baseline_segment_counts: dict[str, float],
) -> list[dict]:
    """Build scored story entries from merged story metadata."""
    results = []

    for story in stories_meta:
        story_id = story["story_id"]
        keyword = story["keyword"]
        indices = story.get("segment_indices", [])
        repeat_indices = set(story.get("repeat_indices", []))

        if not indices:
            continue

        idx_to_seg = {}
        for idx in indices:
            if 0 <= idx < len(all_segments):
                idx_to_seg[idx] = all_segments[idx]

        if not idx_to_seg:
            continue

        story_segments = list(idx_to_seg.values())

        n_today = len(story_segments)
        programs = set()
        editorial_units = set()
        total_seconds = 0
        has_pre18 = False
        has_post18 = False

        for seg in story_segments:
            programs.add(seg.get("program", ""))
            editorial_units.add(seg.get("editorial_unit", ""))
            total_seconds += _segment_duration(seg)
            hour = _extract_hour(seg.get("startTime", ""))
            if hour is not None:
                if hour < PRIMETIME_HOUR:
                    has_pre18 = True
                else:
                    has_post18 = True

        distinct_programs = len(editorial_units)
        baseline_avg = baseline_segment_counts.get(story_id, 0)

        final_score = score_story(
            today_segments=n_today,
            baseline_avg_segments=baseline_avg,
            distinct_programs=distinct_programs,
            total_segments=n_today,
            total_story_seconds=total_seconds,
            has_pre18=has_pre18,
            has_post18=has_post18,
        )

        original_segments = [
            idx_to_seg[idx] for idx in indices
            if idx in idx_to_seg and idx not in repeat_indices
        ]
        if not original_segments:
            original_segments = story_segments

        first_seg = min(original_segments, key=_real_air_sort_key)

        seen_units = set()
        quotes = []
        for seg in story_segments:
            eu = seg.get("editorial_unit", "")
            if eu in seen_units:
                continue
            seen_units.add(eu)
            quotes.append({
                "title": seg.get("program", ""),
                "channel": seg.get("channel", ""),
                "quote": seg.get("quote", ""),
                "urn": seg.get("urn", ""),
                "startTime": seg.get("startTime", ""),
            })

        results.append({
            "story_id": story_id,
            "keyword": keyword,
            "phrase": keyword,
            "score": round(final_score, 2),
            "novelty": round(novelty(n_today, baseline_avg), 2),
            "spread": round(spread(distinct_programs), 2),
            "persistence": round(persistence(n_today), 2),
            "prominence": round(prominence(total_seconds), 2),
            "primetime": round(primetime(has_pre18, has_post18), 2),
            "n_segments": n_today,
            "n_repeats": len(repeat_indices & set(indices)),
            "distinct_programs": distinct_programs,
            "total_seconds": round(total_seconds, 1),
            "editorial_units": sorted(editorial_units),
            "programs": sorted(programs),
            "quotes": quotes[:5],
            "first_mention_urn": first_seg.get("urn", ""),
            "first_mention_time": first_seg.get("peak_time", "") or first_seg.get("start_time", ""),
            "first_mention_program": first_seg.get("program", ""),
            "imageUrl": "",
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, entry in enumerate(results):
        entry["rank"] = i + 1
    return results


# ---------------------------------------------------------------------------
# Weekly pipeline orchestration
# ---------------------------------------------------------------------------

def _week_dates(week_start: str) -> list[str]:
    """Return list of 7 date strings Mon-Sun for a week starting at week_start."""
    start = date.fromisoformat(week_start)
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def build_zeitgeist(week_start: str) -> list[dict]:
    """Main pipeline: build weekly zeitgeist for Mon-Sun.

    1. Load all 7 days' news programs
    2. Segment each day's broadcasts via LLM (cached per URN)
    3. Merge all segments into stories across the whole week
    4. Load baseline from previous 4 weeks
    5. Score stories
    6. Return top GRID_SIZE unique keywords
    """
    dates = _week_dates(week_start)
    week_end = dates[-1]

    all_programs = []
    for d in dates:
        day_programs = filter_news(load_day(d))
        if day_programs:
            print(f"  {d}: {len(day_programs)} news programs")
            all_programs.extend(day_programs)

    if not all_programs:
        print(f"No news programs for week {week_start}")
        return []
    print(f"Week {week_start} → {week_end}: {len(all_programs)} total news programs")

    print("\nSegmenting broadcasts...")
    all_segments = segment_all_broadcasts(all_programs, week_start)
    if not all_segments:
        print("No segments extracted")
        return []
    print(f"\nTotal segments: {len(all_segments)}")

    print("\nMerging segments into stories (keyword + fingerprint)...")
    stories_meta = merge_segments_into_stories(all_segments)
    if not stories_meta:
        print("No stories found after merge")
        return []
    print(f"Found {len(stories_meta)} stories")

    baseline = load_baseline(week_start)

    print("\nScoring stories...")
    results = build_stories(all_segments, stories_meta, baseline)

    # Cluster related keywords: "Iran Waffenruhe" and "Iran Krieg" both
    # contain "Iran" → keep only the highest-scoring variant per cluster.
    top = []
    seen_keywords: set[str] = set()
    seen_words: set[str] = set()

    for entry in results:
        kw = entry["keyword"]
        if kw in seen_keywords:
            continue
        kw_words = {w.lower() for w in kw.split() if len(w) >= 4}
        if kw_words & seen_words:
            continue
        seen_keywords.add(kw)
        seen_words.update(kw_words)
        top.append(entry)
        if len(top) >= GRID_SIZE:
            break

    print(f"\nTop stories for week {week_start}:")
    for entry in top[:10]:
        print(
            f"  {entry['rank']:2d}. {entry['keyword']:<30s} "
            f"score={entry['score']:>6.2f}  "
            f"n={entry['novelty']:.1f} s={entry['spread']:.1f} "
            f"p={entry['persistence']:.1f} pr={entry['prominence']:.1f} "
            f"pt={entry['primetime']:.1f}  "
            f"units={entry['distinct_programs']}  "
            f"segs={entry['n_segments']} ({entry['n_repeats']} rpt)  "
            f"{entry['total_seconds']:.0f}s"
        )

    return top


def save_zeitgeist(results: list[dict], week_start: str) -> Path:
    """Write weekly zeitgeist JSON for frontend."""
    compact = week_start.replace("-", "")

    for entry in results:
        img = entry.get("imageUrl", "")
        if img and not img.startswith("../"):
            entry["imageUrl"] = f"../{img}"

    out_path = OUTPUT_DIR / f"zeitgeist_week_{compact}.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def find_processable_weeks() -> list[str]:
    """Find weeks (Mon-Sun) with at least 3 days of news data."""
    available = set()
    for f in sorted(WEEK_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        news = [
            p for p in data
            if p.get("genre") == "Nachrichten"
            and p.get("word_count", 0) >= MIN_WORD_COUNT
        ]
        if news:
            available.add(f.stem)

    if not available:
        return []

    all_dates = sorted(available)
    first = date.fromisoformat(all_dates[0])
    last = date.fromisoformat(all_dates[-1])
    first_monday = first - timedelta(days=first.weekday())

    weeks = []
    current = first_monday
    while current <= last:
        week_dates = [(current + timedelta(days=i)).isoformat() for i in range(7)]
        days_with_data = sum(1 for d in week_dates if d in available)
        if days_with_data >= 3:
            weeks.append(current.isoformat())
        current += timedelta(weeks=1)

    return weeks


def main():
    skip_images = "--no-images" in sys.argv
    batch = "--all" in sys.argv

    if batch:
        weeks = find_processable_weeks()
        if not weeks:
            print("No processable weeks found.")
            return
        print(f"=== SRF Zeitgeist Pipeline — Weekly Batch ===")
        print(f"Processing {len(weeks)} weeks: {weeks[0]} → {weeks[-1]}\n")
        generated = []
        for w in weeks:
            week_end = (date.fromisoformat(w) + timedelta(days=6)).isoformat()
            print(f"\n{'='*60}")
            print(f"Week: {w} → {week_end}")
            results = build_zeitgeist(w)
            if results:
                if not skip_images:
                    print("\nFetching frames...")
                    fetch_frames(results, w.replace("-", ""))
                out = save_zeitgeist(results, w)
                generated.append(w.replace("-", ""))
                print(f"Saved → {out}")

        sorted_weeks = sorted(generated)
        (OUTPUT_DIR / "weeks.json").write_text(json.dumps(sorted_weeks))
        print(f"\nManifest with {len(sorted_weeks)} weeks")
    else:
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            week_start = sys.argv[1]
        else:
            weeks = find_processable_weeks()
            week_start = weeks[-1] if weeks else "2026-04-07"

        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        print(f"=== SRF Zeitgeist Pipeline ===")
        print(f"Week: {week_start} → {week_end}\n")

        results = build_zeitgeist(week_start)
        if results:
            if not skip_images:
                print("\nFetching frames...")
                fetch_frames(results, week_start.replace("-", ""))
            out = save_zeitgeist(results, week_start)
            print(f"\nSaved {len(results)} stories to {out}")


if __name__ == "__main__":
    main()
