"""
SRF Zeitgeist v2 pipeline — story-level segmentation.

New approach vs v1:
- LLM segments each broadcast into stories (not spaCy phrase extraction)
- Stories merged across broadcasts (not phrase-level dedup)
- Scoring: novelty × spread × persistence × prominence
- Repeats counted through log-dampened persistence/prominence (not excluded)

Usage:
    python -m backend.v2.pipeline 2026-04-01
    python -m backend.v2.pipeline --all
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

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
    generate_summaries,
    compute_fingerprint,
    extract_segment_text,
    seconds_to_tc,
    tc_to_seconds,
)

logger = logging.getLogger(__name__)

# smart_crop import — optional, loaded once
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from smart_crop import smart_crop as _smart_crop
    from PIL import Image as _Image
    _HAS_SMART_CROP = True
except ImportError:
    _HAS_SMART_CROP = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEEK_DIR = PROJECT_ROOT / "demo-data" / "week"
OUTPUT_DIR = PROJECT_ROOT / "demo-data"
VTT_CACHE_DIR = OUTPUT_DIR / "v2" / "vtt_cache"
SEGMENT_CACHE_DIR = OUTPUT_DIR / "v2" / "segment_cache"
MERGE_CACHE_DIR = OUTPUT_DIR / "v2" / "merge_cache"

GRID_SIZE = 49
MIN_WORD_COUNT = 5
BASELINE_DAYS = 7


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
    for suffix in (" in Gebärdensprache", " kompakt", " extra"):
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

    # Check cache
    cached = get_vtt_cached(urn, VTT_CACHE_DIR)
    if cached:
        blocks = parse_vtt(cached)
        return blocks if blocks else None

    # Fetch from Integration Layer
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

    # Store HLS URL for later frame extraction
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


def segment_all_broadcasts(programs: list[dict]) -> list[dict]:
    """Segment all news programs into stories via LLM.

    Processes broadcasts chronologically. Each broadcast receives the keyword
    list from previously processed broadcasts so the LLM reuses keywords
    for the same stories. After LLM segmentation, code computes a fingerprint
    for each segment from the VTT text.

    Returns flat list of segments, each with program metadata and fingerprint.
    Results are cached per-program to avoid re-processing.
    """
    SEGMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Sort by start time so keyword chaining works chronologically
    sorted_programs = sorted(programs, key=lambda p: p.get("startTime", ""))

    all_segments = []
    known_keywords = []  # Accumulated from all processed broadcasts

    for i, prog in enumerate(sorted_programs):
        title = prog["title"]
        cache_path = _segment_cache_path(prog)

        # Check cache — still collect keywords from cached segments
        if cache_path.exists():
            segments = json.loads(cache_path.read_text())
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} cached ({len(segments)} segments)")
            for seg in segments:
                kw = seg.get("keyword", "")
                if kw and kw not in known_keywords:
                    known_keywords.append(kw)
            all_segments.extend(segments)
            continue

        # Fetch VTT
        blocks = fetch_program_vtt(prog)
        if not blocks:
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} no VTT")
            continue

        # Build transcript and segment with keyword chaining
        transcript = vtt_blocks_to_transcript(blocks)
        try:
            segments = segment_broadcast(
                transcript, title,
                existing_keywords=known_keywords if known_keywords else None,
            )
        except Exception as e:
            print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} LLM error: {e}")
            continue

        # Attach metadata and compute fingerprints
        for seg in segments:
            seg["urn"] = prog.get("urn", "")
            seg["channel"] = prog.get("channel", "")
            seg["editorial_unit"] = editorial_unit(title)
            seg["startTime"] = prog.get("startTime", "")

            # Extract segment text from VTT and compute fingerprint
            seg_text = extract_segment_text(
                blocks, seg.get("start_time", ""), seg.get("end_time", ""),
            )
            seg["segment_text"] = seg_text
            seg["fingerprint"] = compute_fingerprint(seg_text)

            # Accumulate keyword for next broadcasts
            kw = seg.get("keyword", "")
            if kw and kw not in known_keywords:
                known_keywords.append(kw)

        # Cache result (incremental saving)
        cache_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
        print(f"  [{i+1}/{len(sorted_programs)}] {title[:40]:<40s} {len(segments)} segments")
        all_segments.extend(segments)

    return all_segments


# ---------------------------------------------------------------------------
# Step 3: Merge into stories and score
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


def build_stories(
    all_segments: list[dict],
    stories_meta: list[dict],
    baseline_segment_counts: dict[str, float],
) -> list[dict]:
    """Build scored story entries from merged story metadata.

    Args:
        all_segments: flat list of all segments from today's broadcasts
        stories_meta: LLM merge output — story_id, keyword, segment_indices, repeat_indices
        baseline_segment_counts: story_id → average daily segments in baseline period
    """
    results = []

    for story in stories_meta:
        story_id = story["story_id"]
        keyword = story["keyword"]
        indices = story.get("segment_indices", [])
        repeat_indices = set(story.get("repeat_indices", []))

        if not indices:
            continue

        # Collect segments for this story, keyed by global index
        idx_to_seg = {}
        for idx in indices:
            if 0 <= idx < len(all_segments):
                idx_to_seg[idx] = all_segments[idx]

        if not idx_to_seg:
            continue

        story_segments = list(idx_to_seg.values())

        # Count metrics
        n_today = len(story_segments)  # N_today: all segments including repeats
        programs = set()
        editorial_units = set()
        total_seconds = 0
        has_pre18 = False
        has_post18 = False

        for seg in story_segments:
            programs.add(seg.get("program", ""))
            editorial_units.add(seg.get("editorial_unit", ""))
            total_seconds += _segment_duration(seg)
            # Primetime tier from program start time (e.g. "2026-04-01T19:30:00+02:00")
            prog_start = seg.get("startTime", "")
            hour = _extract_hour(prog_start)
            if hour is not None:
                if hour < PRIMETIME_HOUR:
                    has_pre18 = True
                else:
                    has_post18 = True

        distinct_programs = len(editorial_units)  # U_today: distinct editorial units
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

        # Find first mention (earliest start_time among non-repeat segments)
        original_segments = [
            idx_to_seg[idx] for idx in indices
            if idx in idx_to_seg and idx not in repeat_indices
        ]
        if not original_segments:
            original_segments = story_segments

        first_seg = min(original_segments, key=lambda s: s.get("start_time", "99:99:99"))

        # Collect quotes (summaries from different editorial units)
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
                "quote": seg.get("summary", ""),
                "urn": seg.get("urn", ""),
                "startTime": seg.get("startTime", ""),
            })

        results.append({
            "story_id": story_id,
            "keyword": keyword,
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
            "first_mention_time": first_seg.get("start_time", ""),
            "first_mention_program": first_seg.get("program", ""),
            "imageUrl": "",
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    for i, entry in enumerate(results):
        entry["rank"] = i + 1

    return results


# ---------------------------------------------------------------------------
# Step 4: Frame extraction
# ---------------------------------------------------------------------------

def fetch_frames(entries: list[dict], date_str: str) -> None:
    """Extract video frames for top stories. Updates imageUrl in-place.

    Reuses the Integration Layer + ffmpeg approach from v1.
    """
    import re  # noqa: used for safe filename
    import subprocess

    frames_dir = OUTPUT_DIR / "v2" / "frames"
    cropped_dir = OUTPUT_DIR / "v2" / "cropped"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cropped_dir.mkdir(parents=True, exist_ok=True)

    for i, entry in enumerate(entries):
        urn = entry.get("first_mention_urn", "")
        if not urn:
            continue

        keyword = entry["keyword"]
        safe = re.sub(r"[^\w-]", "_", keyword)[:40]
        crop_path = cropped_dir / f"{date_str}_{i+1:02d}_{safe}.jpg"

        if crop_path.exists():
            entry["imageUrl"] = str(crop_path.relative_to(PROJECT_ROOT))
            continue

        print(f"  [{i+1:2d}/{len(entries)}] {keyword[:35]:<35s} ", end="", flush=True)

        # Get media URLs
        media_info = fetch_vtt_url(urn)
        if not media_info:
            print("no media")
            continue

        hls_url = media_info.get("hlsUrl", "")
        vtt_url = media_info.get("vttUrl", "")
        fallback_img = media_info.get("imageUrl", "")

        frame_path = frames_dir / f"{date_str}_{i+1:02d}_{safe}.jpg"
        got_frame = False

        # Try frame at first mention timecode
        tc = entry.get("first_mention_time", "")
        if hls_url and tc:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", tc, "-i", hls_url,
                     "-frames:v", "1", "-q:v", "2", str(frame_path)],
                    capture_output=True, timeout=30,
                )
                got_frame = frame_path.exists()
                if got_frame:
                    print(f"frame@{tc} ", end="", flush=True)
            except Exception:
                pass

        # Fallback: find keyword in VTT to get a better timecode
        if not got_frame and hls_url and vtt_url:
            cached_vtt = get_vtt_cached(urn, VTT_CACHE_DIR)
            if not cached_vtt:
                try:
                    cached_vtt = download_vtt(vtt_url)
                    save_vtt_cache(urn, cached_vtt, VTT_CACHE_DIR)
                except Exception:
                    cached_vtt = ""

            if cached_vtt:
                blocks = parse_vtt(cached_vtt)
                keyword_tc = _find_keyword_in_blocks(blocks, keyword)
                if keyword_tc and hls_url:
                    tc_str = seconds_to_tc(keyword_tc)
                    try:
                        subprocess.run(
                            ["ffmpeg", "-y", "-ss", tc_str, "-i", hls_url,
                             "-frames:v", "1", "-q:v", "2", str(frame_path)],
                            capture_output=True, timeout=30,
                        )
                        got_frame = frame_path.exists()
                        if got_frame:
                            print(f"frame@keyword ", end="", flush=True)
                    except Exception:
                        pass

        # Fallback: thumbnail
        if not got_frame and fallback_img:
            try:
                import urllib.request
                req = urllib.request.Request(
                    fallback_img + "/scale/width/640",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    frame_path.write_bytes(resp.read())
                got_frame = True
                print("thumbnail ", end="", flush=True)
            except Exception:
                pass

        if not got_frame:
            print("no image")
            continue

        # Smart crop
        if _HAS_SMART_CROP:
            img = _Image.open(str(frame_path))
            cropped = _smart_crop(img)
            cropped.save(str(crop_path), quality=85)
            entry["imageUrl"] = str(crop_path.relative_to(PROJECT_ROOT))
            print("OK")
        else:
            import shutil
            shutil.copy2(frame_path, crop_path)
            entry["imageUrl"] = str(crop_path.relative_to(PROJECT_ROOT))
            print("OK (no crop)")


def _find_keyword_in_blocks(blocks: list[dict], keyword: str) -> float | None:
    """Find the first VTT block that mentions the keyword. Returns seconds or None."""
    kw_lower = keyword.lower()
    words = kw_lower.split()

    # Try exact match
    for block in blocks:
        if kw_lower in block["text"].lower():
            return block["start"]

    # Try longest word
    for word in sorted(words, key=len, reverse=True):
        if len(word) < 3:
            continue
        for block in blocks:
            if word in block["text"].lower():
                return block["start"]

    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _add_summaries(all_segments: list[dict], top_stories: list[dict]) -> None:
    """Generate summaries for top stories' quotes.

    For each story, picks one representative segment per editorial unit
    and generates a one-sentence summary via LLM. Updates quotes in-place.
    """
    # Collect segments that need summaries
    segments_to_summarize = []
    story_quote_map = []  # (story_idx, quote_idx) for each segment

    for si, story in enumerate(top_stories):
        for qi, quote in enumerate(story.get("quotes", [])):
            if quote.get("quote") and len(quote["quote"]) > 10:
                continue  # Already has a good summary
            # Find the segment for this quote
            urn = quote.get("urn", "")
            for seg in all_segments:
                if seg.get("urn") == urn and seg.get("keyword") == story.get("keyword"):
                    segments_to_summarize.append(seg)
                    story_quote_map.append((si, qi))
                    break

    if not segments_to_summarize:
        return

    try:
        summaries = generate_summaries(segments_to_summarize)
        for (si, qi), summary in zip(story_quote_map, summaries):
            if summary:
                top_stories[si]["quotes"][qi]["quote"] = summary
    except Exception as e:
        logger.warning("Summary generation failed: %s", e)


def _load_merge_cache(target_date: str) -> list[dict] | None:
    """Load cached merge result for a date. Returns None if not cached."""
    path = MERGE_CACHE_DIR / f"merged_{target_date}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _save_merge_cache(target_date: str, stories_meta: list[dict]) -> None:
    """Cache merge result for a date."""
    MERGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = MERGE_CACHE_DIR / f"merged_{target_date}.json"
    path.write_text(json.dumps(stories_meta, ensure_ascii=False, indent=2))


def load_baseline(target_date: str) -> dict[str, float]:
    """Load baseline segment counts from previous BASELINE_DAYS days.

    Reads cached merge results for each prior day, counts segments
    per story_id, returns average daily count per story_id.
    """
    target_dt = date.fromisoformat(target_date)
    story_counts: dict[str, list[int]] = defaultdict(list)
    days_found = 0

    for i in range(1, BASELINE_DAYS + 1):
        prev_date = (target_dt - timedelta(days=i)).isoformat()
        cached = _load_merge_cache(prev_date)
        if cached is None:
            continue
        days_found += 1
        # Count segments per story for this day
        day_stories = set()
        for story in cached:
            sid = story.get("story_id", "")
            n_segs = len(story.get("segment_indices", []))
            story_counts[sid].append(n_segs)
            day_stories.add(sid)

        # Stories not present on this day get 0
        for sid in story_counts:
            if sid not in day_stories:
                story_counts[sid].append(0)

    if days_found == 0:
        logger.info("No baseline data found for %d days before %s", BASELINE_DAYS, target_date)
        return {}

    # Average across days found
    baseline = {}
    for sid, counts in story_counts.items():
        # Pad with zeros for days with no merge cache
        while len(counts) < days_found:
            counts.append(0)
        baseline[sid] = sum(counts) / days_found

    logger.info("Baseline loaded: %d stories from %d days", len(baseline), days_found)
    return baseline


def build_zeitgeist(target_date: str) -> list[dict]:
    """Main pipeline: build zeitgeist for target_date.

    1. Load today's news programs
    2. Fetch VTT, segment each broadcast via LLM
    3. Merge segments into stories via LLM (cached)
    4. Load baseline from previous days
    5. Score stories
    6. Return top GRID_SIZE
    """
    target_dt = date.fromisoformat(target_date)

    # Load today's news
    day_programs = filter_news(load_day(target_date))
    if not day_programs:
        print(f"No news programs for {target_date}")
        return []
    print(f"Target date {target_date}: {len(day_programs)} news programs")

    # Step 1-2: Segment all broadcasts
    print("\nSegmenting broadcasts...")
    all_segments = segment_all_broadcasts(day_programs)
    if not all_segments:
        print("No segments extracted")
        return []
    print(f"\nTotal segments: {len(all_segments)}")

    # Step 3: Merge segments into stories (code-based, not LLM)
    stories_meta = _load_merge_cache(target_date)
    if stories_meta is not None:
        print(f"\nMerge cache hit: {len(stories_meta)} stories")
    else:
        print("\nMerging segments into stories (keyword + fingerprint)...")
        stories_meta = merge_segments_into_stories(all_segments)
        if not stories_meta:
            print("No stories found after merge")
            return []
        _save_merge_cache(target_date, stories_meta)
        print(f"Found {len(stories_meta)} stories (cached)")

    # Step 4: Load baseline from previous days
    baseline = load_baseline(target_date)

    # Step 5: Score
    print("\nScoring stories...")
    results = build_stories(all_segments, stories_meta, baseline)

    top = results[:GRID_SIZE]

    # Step 6: Generate summaries only for top stories (cheap, targeted)
    print(f"\nGenerating summaries for top {len(top)} stories...")
    _add_summaries(all_segments, top)

    print(f"\nTop stories for {target_date}:")
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


def save_zeitgeist(results: list[dict], target_date: str) -> Path:
    """Write zeitgeist JSON."""
    day_compact = target_date.replace("-", "")
    out_dir = OUTPUT_DIR / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"zeitgeist_{day_compact}.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def find_processable_days(min_news: int = 5) -> list[str]:
    """Find all days in week/ with enough news programs."""
    days = []
    for f in sorted(WEEK_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        news = [
            p for p in data
            if p.get("genre") == "Nachrichten"
            and p.get("word_count", 0) >= MIN_WORD_COUNT
        ]
        if len(news) >= min_news:
            days.append(f.stem)
    return days


def main():
    skip_images = "--no-images" in sys.argv
    batch = "--all" in sys.argv

    if batch:
        dates = find_processable_days()
        print(f"=== SRF Zeitgeist v2 Pipeline — Batch ===")
        print(f"Processing {len(dates)} days: {dates[0]} → {dates[-1]}\n")
        generated = []
        for d in dates:
            print(f"\n{'='*60}")
            results = build_zeitgeist(d)
            if results:
                if not skip_images:
                    print("\nFetching frames...")
                    fetch_frames(results, d.replace("-", ""))
                out = save_zeitgeist(results, d)
                generated.append(d.replace("-", ""))
                print(f"Saved → {out}")

        # Write manifest
        manifest_path = OUTPUT_DIR / "v2" / "days.json"
        manifest_path.write_text(json.dumps(sorted(generated)))
        print(f"\nManifest with {len(generated)} days → {manifest_path}")
    else:
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            target_date = sys.argv[1]
        else:
            files = sorted(WEEK_DIR.glob("*.json"))
            target_date = files[-1].stem if files else "2026-04-01"

        print(f"=== SRF Zeitgeist v2 Pipeline ===")
        print(f"Target date: {target_date}\n")

        results = build_zeitgeist(target_date)
        if results:
            if not skip_images:
                print("\nFetching frames...")
                fetch_frames(results, target_date.replace("-", ""))
            out = save_zeitgeist(results, target_date)
            print(f"\nSaved {len(results)} stories to {out}")


if __name__ == "__main__":
    main()
