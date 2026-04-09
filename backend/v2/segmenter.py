"""
LLM-based broadcast segmentation for SRF Zeitgeist v2.

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
from pathlib import Path

logger = logging.getLogger(__name__)

IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"

# German stopwords (frequent words that don't help identify a story)
_STOPWORDS = frozenset(
    "der die das ein eine einer eines einem einen den dem des und oder aber "
    "ist sind war waren wird werden hat haben hatte hatten kann können konnte "
    "soll sollen sollte mit von für auf aus bei nach über vor durch zwischen "
    "sich ich wir sie er es ihr sein seine seiner seinem seinen ihre ihrem "
    "nicht auch noch schon sehr mehr als wie wenn dann da so nur auch noch "
    "doch aber weil dass ob zum zur bis um an in im am vom was wer wo wie "
    "alle allem allen aller alles andere anderem anderen anderer anderes "
    "hier dort nun jetzt heute diese diesem diesen dieser dieses jede jedem "
    "jeden jeder jedes man muss müssen würde würden gegen unter bereits also "
    "etwa rund dort neue neuen neuer neues neuem keine keinem keinen keiner".split()
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

    Returns True if entity overlap >= 2 OR top_words overlap >= 3.
    """
    entity_overlap = len(set(fp1["entities"]) & set(fp2["entities"]))
    if entity_overlap >= 2:
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
# LLM segmentation — minimal output + keyword chaining
# ---------------------------------------------------------------------------

_SEGMENT_PROMPT = """\
Segment this SRF news broadcast into editorial stories.

For each segment return ONLY:
- start_time, end_time (from the timestamps in the transcript)
- keyword (1-3 words, German, specific to the event — not generic like "Politik")
- segment_type: "story", "weather", "sport", "intro", "outro", "teaser"

{keyword_instruction}

Return ONLY valid JSON array:
[
  {{"start_time": "HH:MM:SS.mmm", "end_time": "HH:MM:SS.mmm", "keyword": "...", "segment_type": "story"}}
]

Transcript:
{transcript}"""

_KEYWORD_REUSE = """IMPORTANT: These keywords already exist from earlier broadcasts today:
{keywords}
If a segment covers the same story, reuse the EXACT keyword. Only create a new keyword if it's a genuinely new topic."""

_NO_KEYWORDS_YET = "This is the first broadcast of the day. Choose specific keywords."


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
        existing_keywords: keywords from previously processed broadcasts today.
            LLM will reuse these for the same stories.

    Returns list of segment dicts with start_time, end_time, keyword, segment_type.
    No summary — added later only for top-N stories.
    """
    import anthropic

    if existing_keywords:
        kw_instruction = _KEYWORD_REUSE.format(keywords=", ".join(existing_keywords))
    else:
        kw_instruction = _NO_KEYWORDS_YET

    client = anthropic.Anthropic()
    prompt = _SEGMENT_PROMPT.format(
        keyword_instruction=kw_instruction,
        transcript=transcript,
    )

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Try to parse as JSON array or object with "segments" key
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        match = re.search(r"[\[\{].*[\]\}]", text, re.DOTALL)
        if not match:
            raise ValueError(f"LLM did not return JSON: {text[:300]}")
        data = json.loads(match.group(0))

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

def merge_segments_into_stories(all_segments: list[dict]) -> list[dict]:
    """Group segments into stories by keyword match + fingerprint fallback.

    Returns list of story dicts:
        story_id, keyword, segment_indices, repeat_indices

    Algorithm:
    1. Exact keyword match → same story
    2. Different keyword but fingerprint_match() → same story (merge into first-seen keyword)
    3. No match → new story
    """
    # story_keyword → {story_id, keyword, segment_indices, fingerprints}
    stories: dict[str, dict] = {}
    # Map from segment index to story keyword
    seg_to_story: dict[int, str] = {}

    for i, seg in enumerate(all_segments):
        keyword = seg.get("keyword", "").strip()
        fp = seg.get("fingerprint", {})

        # 1. Exact keyword match
        if keyword and keyword in stories:
            stories[keyword]["segment_indices"].append(i)
            stories[keyword]["fingerprints"].append(fp)
            seg_to_story[i] = keyword
            continue

        # 2. Fingerprint fallback — check against all existing stories
        matched_key = None
        if fp and fp.get("entities"):
            for story_key, story_data in stories.items():
                for existing_fp in story_data["fingerprints"]:
                    if fingerprint_match(fp, existing_fp):
                        matched_key = story_key
                        break
                if matched_key:
                    break

        if matched_key:
            stories[matched_key]["segment_indices"].append(i)
            stories[matched_key]["fingerprints"].append(fp)
            seg_to_story[i] = matched_key
            # If this segment had a different keyword, the LLM might have
            # a better name. Keep the first one for consistency.
            continue

        # 3. New story
        story_id = re.sub(r"[^a-z0-9]+", "_", keyword.lower()).strip("_") or f"story_{i}"
        stories[keyword] = {
            "story_id": story_id,
            "keyword": keyword,
            "segment_indices": [i],
            "fingerprints": [fp],
        }
        seg_to_story[i] = keyword

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

_SUMMARY_PROMPT = """\
Write a one-sentence German summary for each of these news story segments.
Return ONLY a JSON array of strings, one summary per segment, in the same order.

Segments:
{segments_json}"""


def generate_summaries(
    segments: list[dict],
    model: str = "claude-haiku-4-5-20251001",
) -> list[str]:
    """Generate one-sentence summaries for a batch of segments.

    Called only for top-N stories after ranking, not for all segments.
    """
    if not segments:
        return []

    import anthropic
    client = anthropic.Anthropic()

    compact = []
    for seg in segments:
        compact.append({
            "keyword": seg.get("keyword", ""),
            "program": seg.get("program", ""),
            "text_preview": seg.get("segment_text", "")[:300],
        })

    prompt = _SUMMARY_PROMPT.format(
        segments_json=json.dumps(compact, ensure_ascii=False, indent=1)
    )

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    try:
        summaries = json.loads(text)
        if isinstance(summaries, list):
            return summaries
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))

    logger.warning("Could not parse summaries response")
    return [""] * len(segments)
