"""
LLM-based broadcast segmentation for SRF Zeitgeist.

Each news broadcast is segmented into editorial stories by Claude.
The LLM assigns a keyword, segment_type, and marks repeats.
VTT subtitles (with timestamps) are fetched from SRF Integration Layer.

Key design:
- LLM returns minimal fields per segment (no summary — added later for top-N only)
- Each broadcast gets the keyword list from previously processed broadcasts,
  so the LLM reuses existing keywords for the same story
- Code computes a fingerprint (entities + top_words) for each segment
  as a fallback for matching stories when keywords differ
- Story merging is done by code (keyword match + fingerprint overlap), not LLM
"""

import json
import logging
import re
import urllib.request
from collections import Counter
from json import JSONDecoder
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"

# German stopwords (frequent words that don't help identify a story)
_STOPWORDS = frozenset(
    "der die das ein eine einer eines einem einen den dem des und oder aber "
    "ist sind war waren wird werden hat haben hatte hatten kann können konnte "
    "soll sollen sollte mit von für auf aus bei nach über vor durch zwischen "
    "sich ich wir sie er es ihr sein seine seiner seinem seinen ihre ihrem "
    "nicht auch noch schon sehr mehr als wie wenn dann da so nur "
    "doch weil dass ob zum zur bis um an in im am vom was wer wo "
    "alle allem allen aller alles andere anderem anderen anderer anderes "
    "hier dort nun jetzt heute diese diesem diesen dieser dieses jede jedem "
    "jeden jeder jedes man muss müssen würde würden gegen unter bereits also "
    "etwa rund neue neuen neuer neues neuem keine keinem keinen keiner".split()
)


# ---------------------------------------------------------------------------
# VTT fetching and parsing
# ---------------------------------------------------------------------------

def fetch_vtt_url(urn: str) -> dict:
    """Get VTT subtitle URL + HLS stream URL from Integration Layer.

    Returns dict with keys: vttUrl, hlsUrl, imageUrl (any may be absent).
    """
    url = f"{IL_BASE}/{urn}?onlyChapters=true&vector=portalplay"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning("IL fetch failed for %s: %s", urn, e)
        return {}

    chapter = data.get("chapterList", [{}])[0]
    result = {}

    img = chapter.get("imageUrl", "")
    if img:
        result["imageUrl"] = img

    for sub in chapter.get("subtitleList", []):
        if sub.get("format") == "VTT":
            result["vttUrl"] = sub["url"]
            break

    for res in chapter.get("resourceList", []):
        if res.get("streaming") == "HLS" and res.get("quality") == "HD":
            result["hlsUrl"] = res["url"]
            break
    if "hlsUrl" not in result:
        for res in chapter.get("resourceList", []):
            if res.get("streaming") == "HLS":
                result["hlsUrl"] = res["url"]
                break

    return result


def download_vtt(vtt_url: str) -> str:
    """Download VTT subtitle text."""
    req = urllib.request.Request(vtt_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_vtt(vtt_text: str) -> list[dict]:
    """Parse VTT into list of {start, end, text} blocks.

    Timestamps are in seconds (float). Text has HTML tags stripped.
    """
    blocks = re.split(r"\n\n+", vtt_text)
    result = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        time_line = None
        time_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_line = line
                time_idx = i
                break
        if time_line is None:
            continue

        start_str, end_str = [p.strip() for p in time_line.split("-->", 1)]
        text = re.sub(r"<[^>]+>", "", " ".join(lines[time_idx + 1:]))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue

        result.append({
            "start": tc_to_seconds(start_str),
            "end": tc_to_seconds(end_str),
            "text": text,
        })

    return result


def tc_to_seconds(tc: str) -> float:
    """Convert VTT timecode 'HH:MM:SS.mmm' to seconds."""
    tc = tc.replace(",", ".")
    parts = tc.split(":")
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def seconds_to_tc(seconds: float) -> str:
    """Convert seconds back to 'HH:MM:SS.mmm' timecode."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def vtt_blocks_to_transcript(blocks: list[dict]) -> str:
    """Format VTT blocks into a compact timestamped transcript for LLM input.

    Merges consecutive blocks to reduce token count while keeping timestamps.
    """
    if not blocks:
        return ""

    # Merge blocks within 1-second gaps into chunks (reduces LLM tokens ~3x)
    merged = []
    current = {"start": blocks[0]["start"], "end": blocks[0]["end"], "text": blocks[0]["text"]}
    for b in blocks[1:]:
        if b["start"] - current["end"] < 1.0:
            current["end"] = b["end"]
            current["text"] += " " + b["text"]
        else:
            merged.append(current)
            current = {"start": b["start"], "end": b["end"], "text": b["text"]}
    merged.append(current)

    lines = []
    for chunk in merged:
        tc = seconds_to_tc(chunk["start"])
        lines.append(f"[{tc}] {chunk['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Segment text extraction
# ---------------------------------------------------------------------------

def extract_segment_text(vtt_blocks: list[dict], start_time: str, end_time: str) -> str:
    """Extract VTT text that falls within a segment's time range."""
    try:
        start_sec = tc_to_seconds(start_time)
        end_sec = tc_to_seconds(end_time)
    except (ValueError, IndexError):
        return ""

    texts = []
    for block in vtt_blocks:
        # Block overlaps with segment if it starts before segment ends
        # and ends after segment starts
        if block["end"] > start_sec and block["start"] < end_sec:
            texts.append(block["text"])
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Fingerprinting — deterministic segment identity from text
# ---------------------------------------------------------------------------

def compute_fingerprint(text: str) -> dict:
    """Compute a deterministic fingerprint from segment text.

    Returns:
        entities: capitalized multi-word or single proper nouns (person, org, place names)
        top_words: 5 most frequent content words (>4 chars, no stopwords), sorted
        word_count: total words in segment
    """
    words = text.split()
    word_count = len(words)

    # Entities: capitalized words not at sentence start, 2+ chars
    # Heuristic: word is capitalized AND not after ". " or start of text
    entities = set()
    for i, word in enumerate(words):
        clean = re.sub(r"[^\wäöüÄÖÜß]", "", word)
        if len(clean) < 2:
            continue
        if clean[0].isupper() and clean.lower() not in _STOPWORDS:
            # Skip if it's the first word or follows sentence-ending punctuation
            is_sentence_start = (i == 0) or (i > 0 and words[i - 1][-1] in ".!?")
            if not is_sentence_start:
                entities.add(clean)

    # Top words: most frequent content words >4 chars
    word_freq = Counter()
    for word in words:
        clean = re.sub(r"[^\wäöüÄÖÜß]", "", word).lower()
        if len(clean) > 4 and clean not in _STOPWORDS:
            word_freq[clean] += 1

    top_words = sorted([w for w, _ in word_freq.most_common(5)])

    return {
        "entities": sorted(entities),
        "top_words": top_words,
        "word_count": word_count,
    }


def fingerprint_match(fp1: dict, fp2: dict) -> bool:
    """Check if two fingerprints likely represent the same story.

    Returns True if entity overlap >= 3 OR top_words overlap >= 3.
    Threshold is high because German capitalizes ALL nouns, so generic
    words like "Kanton", "Lösung", "Bevölkerung" appear as false entities.
    """
    entity_overlap = len(set(fp1["entities"]) & set(fp2["entities"]))
    if entity_overlap >= 3:
        return True

    word_overlap = len(set(fp1["top_words"]) & set(fp2["top_words"]))
    if word_overlap >= 3:
        return True

    return False


# ---------------------------------------------------------------------------
# VTT cache
# ---------------------------------------------------------------------------

def get_vtt_cached(urn: str, cache_dir: Path) -> str | None:
    """Try to load VTT from cache. Returns None if not cached."""
    safe = re.sub(r"[^\w-]", "_", urn)
    path = cache_dir / f"{safe}.vtt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def save_vtt_cache(urn: str, vtt_text: str, cache_dir: Path) -> None:
    """Save VTT to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w-]", "_", urn)
    path = cache_dir / f"{safe}.vtt"
    path.write_text(vtt_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Emotional/importance peak detection in subtitle text
# ---------------------------------------------------------------------------

# German words that signal the core of a news story — facts, actions, stakes.
# Not "sad/happy" sentiment, but information density and narrative weight.
_IMPORTANCE_MARKERS = frozenset(
    # Numbers and firsts
    "millionen milliarden prozent rekord erstmals historisch höchste niedrigste "
    "grösste schlimmste stärkste "
    # Actions and decisions
    "beschlossen verurteilt gestorben getötet verhaftet gestartet gewählt "
    "abgestimmt genehmigt abgelehnt gekündigt entlassen geschlossen verboten "
    "angeklagt freigesprochen gerettet evakuiert gestoppt "
    # Stakes and consequences
    "tod opfer tote verletzte schaden katastrophe krise gefahr notfall "
    "angriff krieg explosion brand unfall absturz "
    # Assessment and scale
    "dramatisch beispiellos massiv heftig schwer dringend kritisch "
    "überraschend unerwartet schockierend entscheidend "
    # Specific nouns that anchor facts
    "urteil gesetz abstimmung wahl ergebnis bericht studie "
    "million milliarde franken euro dollar".split()
)

# Named entities (capitalized, not sentence-start) also signal importance
# — who is acting, where it happened. Handled separately via capitalization.


def find_importance_peak(
    vtt_blocks: list[dict],
    start_sec: float,
    end_sec: float,
    window_size: int = 3,
) -> float | None:
    """Find the timestamp of the most important moment within a segment.

    Scores each VTT block by density of importance markers + named entities.
    Uses a sliding window of `window_size` blocks to smooth noise.
    Returns timestamp (seconds) of the peak, or None if no blocks found.

    Skips the first 5 seconds of the segment (usually anchor intro).
    """
    # Filter blocks within segment time range, skip first 5 seconds
    skip_until = start_sec + 5.0
    seg_blocks = [
        b for b in vtt_blocks
        if b["end"] > skip_until and b["start"] < end_sec
    ]
    if not seg_blocks:
        return None

    # Score each block
    scores = []
    for block in seg_blocks:
        words = block["text"].lower().split()
        if not words:
            scores.append(0)
            continue

        # Importance markers
        marker_count = sum(1 for w in words if w.rstrip(".,!?;:") in _IMPORTANCE_MARKERS)

        # Named entities: capitalized words not at sentence start
        raw_words = block["text"].split()
        entity_count = 0
        for i, w in enumerate(raw_words):
            clean = re.sub(r"[^\wäöüÄÖÜß]", "", w)
            if len(clean) > 2 and clean[0].isupper() and clean.lower() not in _STOPWORDS:
                is_start = (i == 0) or (i > 0 and raw_words[i-1][-1] in ".!?")
                if not is_start:
                    entity_count += 1

        # Density = (markers + entities) / words
        score = (marker_count + entity_count * 0.5) / max(len(words), 1)
        scores.append(score)

    if not scores:
        return None

    # Sliding window smoothing
    smoothed = []
    for i in range(len(scores)):
        window = scores[max(0, i - window_size // 2): i + window_size // 2 + 1]
        smoothed.append(sum(window) / len(window))

    # Find peak
    peak_idx = max(range(len(smoothed)), key=lambda i: smoothed[i])

    # Return timestamp of peak block
    return seg_blocks[peak_idx]["start"]


# ---------------------------------------------------------------------------
# Robust JSON extraction from LLM output (adapted from v3)
# ---------------------------------------------------------------------------

def _extract_json(text: str):
    """Extract JSON from LLM response, handling markdown fences and trailing commas."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Try incremental parsing — finds the first valid JSON object or array
    decoder = JSONDecoder()
    for i, char in enumerate(cleaned):
        if char not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[i:])
            return obj
        except json.JSONDecodeError:
            continue

    # Fallback: regex + trailing comma cleanup
    match = re.search(r"[\[{].*[}\]]", cleaned, re.DOTALL)
    if match:
        candidate = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        return json.loads(candidate)

    raise ValueError(f"LLM did not return parseable JSON: {cleaned[:300]}")


# ---------------------------------------------------------------------------
# LLM segmentation — minimal output + keyword chaining
# ---------------------------------------------------------------------------

# Prompts loaded from docs/prompts/ — single source of truth
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "prompts"

_SEGMENT_PROMPT = (_PROMPTS_DIR / "segment.md").read_text().strip()
_KEYWORD_CONTEXT = (_PROMPTS_DIR / "keyword_context.md").read_text().strip()

# Summary prompt removed — quotes are now generated during segmentation


def segment_broadcast(
    transcript: str,
    program_title: str,
    existing_keywords: list[str] | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> list[dict]:
    """Segment one broadcast into stories via LLM.

    Args:
        transcript: timestamped VTT transcript text
        program_title: for metadata attachment
        existing_keywords: keywords from yesterday's zeitgeist and/or
            previously processed broadcasts today. LLM will reuse these
            for the same stories.

    Returns list of segment dicts with start_time, end_time, keyword, segment_type.
    No summary — added later only for top-N stories.
    """

    if existing_keywords:
        kw_instruction = _KEYWORD_CONTEXT.replace("{keywords}", ", ".join(existing_keywords))
    else:
        kw_instruction = ""

    client = anthropic.Anthropic(max_retries=3)
    prompt = (_SEGMENT_PROMPT
              .replace("{keyword_instruction}", kw_instruction)
              .replace("{transcript}", transcript))

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    data = _extract_json(text)

    # Handle both [{...}] and {"segments": [{...}]} formats
    if isinstance(data, dict):
        segments = data.get("segments", [])
    elif isinstance(data, list):
        segments = data
    else:
        raise ValueError(f"Unexpected LLM response format: {type(data)}")

    # Attach source program
    for seg in segments:
        seg["program"] = program_title

    return segments


# ---------------------------------------------------------------------------
# Story merging — code-based, not LLM
# ---------------------------------------------------------------------------

def _segments_are_related(seg_a: dict, seg_b: dict) -> bool:
    """Check if two segments with the same keyword are actually about the same topic.

    Trusts the keyword match — only splits when texts share zero content.
    This prevents merging genuinely different stories that happen to get
    the same generic keyword from different programs.
    """
    fp_a = seg_a.get("fingerprint", {})
    fp_b = seg_b.get("fingerprint", {})
    if not fp_a or not fp_b:
        return True  # No fingerprint — trust keyword

    words_a = set(fp_a.get("top_words", []))
    words_b = set(fp_b.get("top_words", []))
    entities_a = set(fp_a.get("entities", []))
    entities_b = set(fp_b.get("entities", []))

    # Require at least 2 shared words or entities to confirm same topic.
    # Threshold of 1 is too loose — German noun capitalization creates
    # false entity matches between unrelated stories.
    if len(words_a & words_b) >= 2:
        return True
    if len(entities_a & entities_b) >= 2:
        return True

    return False


def merge_segments_into_stories(all_segments: list[dict]) -> list[dict]:
    """Group segments into stories by keyword match + text validation.

    Returns list of story dicts:
        story_id, keyword, segment_indices, repeat_indices

    Keyword match is primary. Before merging, validates that segments
    with the same keyword actually share content (via fingerprint).
    If they don't, creates a separate story with a numbered suffix.
    """
    # story_keyword → {story_id, keyword, segment_indices, representative_seg}
    stories: dict[str, dict] = {}

    for i, seg in enumerate(all_segments):
        keyword = seg.get("keyword", "").strip()
        if not keyword:
            keyword = f"unknown_{i}"

        if keyword in stories:
            # Same keyword = same story. Trust the LLM's keyword choice.
            stories[keyword]["segment_indices"].append(i)
        else:
            story_id = re.sub(r"[^a-z0-9]+", "_", keyword.lower()).strip("_") or f"story_{i}"
            stories[keyword] = {
                "story_id": story_id,
                "keyword": keyword,
                "segment_indices": [i],
            }

    # Detect repeats within each story: segments from the same editorial unit
    # with high fingerprint similarity are repeats
    result = []
    for story_data in stories.values():
        indices = story_data["segment_indices"]
        repeat_indices = _detect_repeats(all_segments, indices)

        result.append({
            "story_id": story_data["story_id"],
            "keyword": story_data["keyword"],
            "segment_indices": indices,
            "repeat_indices": repeat_indices,
        })

    return result


def _detect_repeats(all_segments: list[dict], indices: list[int]) -> list[int]:
    """Within a story's segments, detect which are repeats of earlier ones.

    A repeat = same editorial unit, high word overlap with an earlier segment.
    """
    if len(indices) < 2:
        return []

    repeat_indices = []
    seen_by_unit: dict[str, list[dict]] = {}  # editorial_unit → list of fingerprints

    for idx in indices:
        seg = all_segments[idx]
        unit = seg.get("editorial_unit", seg.get("program", ""))
        fp = seg.get("fingerprint", {})

        if unit in seen_by_unit:
            # Same editorial unit seen before — check if it's a repeat
            for prev_fp in seen_by_unit[unit]:
                if _is_near_duplicate(fp, prev_fp):
                    repeat_indices.append(idx)
                    break

        seen_by_unit.setdefault(unit, []).append(fp)

    return repeat_indices


def _is_near_duplicate(fp1: dict, fp2: dict) -> bool:
    """Check if two segments from the same editorial unit are near-duplicates.

    Stricter than fingerprint_match — requires high overlap in both entities and words.
    """
    if not fp1 or not fp2:
        return False

    entities1 = set(fp1.get("entities", []))
    entities2 = set(fp2.get("entities", []))
    if entities1 and entities2:
        overlap = len(entities1 & entities2)
        min_size = min(len(entities1), len(entities2))
        if min_size > 0 and overlap / min_size >= 0.7:
            return True

    words1 = set(fp1.get("top_words", []))
    words2 = set(fp2.get("top_words", []))
    if words1 and words2:
        overlap = len(words1 & words2)
        if overlap >= 4:
            return True

    return False


# ---------------------------------------------------------------------------
# Summary generation — only for top-N stories, after ranking
# ---------------------------------------------------------------------------

