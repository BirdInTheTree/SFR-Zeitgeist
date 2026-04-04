"""
SRF Zeitgeist pipeline — news-only edition.

Reads pre-fetched program data from demo-data/week/*.json,
filters to Nachrichten genre only (including re-broadcasts),
extracts noun phrases + named entities via spaCy,
computes keyness (spike vs 14-day baseline),
and outputs a zeitgeist JSON for the frontend 6×6 grid.
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import hashlib
import subprocess
import urllib.request

from dotenv import load_dotenv
import numpy as np
import spacy
from nltk.tokenize import TextTilingTokenizer

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from PIL import Image
from sentence_transformers import SentenceTransformer

from smart_crop import smart_crop, download_image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEK_DIR = PROJECT_ROOT / "demo-data" / "week"
OUTPUT_DIR = PROJECT_ROOT / "demo-data"

GRID_SIZE = 49
MIN_EDITORIAL_UNITS = 1   # no EU filter — spike + LLM gate handle quality
REFERENCE_DAYS = 7         # previous week as baseline
MIN_PHRASE_LEN = 2        # skip single-char phrases
MIN_WORD_COUNT = 5        # skip programs with near-empty subtitles
MAX_PHRASE_WORDS = 4      # skip overly long noun chunks (usually parsing noise)

# Junk phrases that leak from subtitle metadata, not news content
_JUNK_PATTERNS = [
    "SWISS TXT",
    "Accessibility Services",
    "Live-Untertitel",
    "Untertitelung",
]

# Gebärdensprache versions share content with their base show.
# We collapse variant broadcasts into editorial units.
# Tagesschau in Gebärdensprache and Tagesschau kompakt are the same editorial desk.
_EDITORIAL_SUFFIXES = [
    " in Gebärdensprache",
    " kompakt",
    " extra",
]


def editorial_unit(title: str) -> str:
    """Collapse variant broadcasts into base editorial unit.

    'Tagesschau in Gebärdensprache' → 'Tagesschau'
    'Tagesschau kompakt' → 'Tagesschau'
    """
    for suffix in _EDITORIAL_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


def load_day(date_str: str) -> list[dict]:
    """Load programs for a single date from week/ folder."""
    path = WEEK_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not data:
        return []
    return data


def filter_news(programs: list[dict]) -> list[dict]:
    """Keep only Nachrichten genre, skip near-empty subtitles."""
    return [
        p for p in programs
        if p.get("genre") == "Nachrichten"
        and p.get("word_count", 0) >= MIN_WORD_COUNT
    ]


def extract_phrases(nlp, text: str) -> list[dict]:
    """Extract noun phrases + named entities from German subtitle text.

    Returns list of {lemma, surface, char_idx} dicts.
    lemma: for counting/dedup. surface: for display. char_idx: position in text.
    """
    doc = nlp(text)
    # Track best (most frequent) surface form per lemma
    seen: dict[str, dict] = {}  # lemma → {surface, char_idx, count}

    # Noun chunks
    for chunk in doc.noun_chunks:
        has_noun = any(t.pos_ in ("NOUN", "PROPN") for t in chunk)
        if not has_noun:
            continue

        content_tokens = [
            t for t in chunk
            if t.pos_ in ("NOUN", "PROPN", "ADJ")
            and not t.is_stop
        ]
        if not content_tokens:
            continue

        lemma = " ".join(t.lemma_ for t in content_tokens).strip()
        surface = " ".join(t.text for t in content_tokens).strip()

        if len(lemma) < MIN_PHRASE_LEN or len(lemma.split()) > MAX_PHRASE_WORDS:
            continue

        if lemma not in seen:
            seen[lemma] = {"surface": surface, "char_idx": chunk.start_char, "count": 1}
        else:
            seen[lemma]["count"] += 1
            # Keep the most frequent surface form
            if surface != seen[lemma]["surface"]:
                seen[lemma]["surface"] = surface  # last seen wins; could track Counter

    # Named entities — surface form = entity text as-is
    for ent in doc.ents:
        if ent.label_ not in ("PER", "ORG", "LOC", "GPE"):
            continue
        cleaned = ent.text.strip()
        if len(cleaned) < MIN_PHRASE_LEN or len(cleaned.split()) > MAX_PHRASE_WORDS:
            continue
        # For NER, lemma = surface (names don't get lemmatized)
        if cleaned not in seen:
            seen[cleaned] = {"surface": cleaned, "char_idx": ent.start_char, "count": 1}
        else:
            seen[cleaned]["count"] += 1

    # Remove subtitle metadata junk
    results = []
    for lemma, info in seen.items():
        if any(junk.lower() in lemma.lower() for junk in _JUNK_PATTERNS):
            continue
        results.append({
            "lemma": lemma,
            "surface": info["surface"],
            "char_idx": info["char_idx"],
        })

    return results


# TextTiling requires paragraphs separated by blank lines.
# Subtitle text is continuous, so we split into pseudo-paragraphs by sentence.
_tiler = TextTilingTokenizer(w=20, k=10)


def segment_into_stories(text: str) -> list[str]:
    """Split a news program transcript into story segments via TextTiling.

    Returns a list of text segments, each roughly one news story.
    Falls back to the full text as a single segment if TextTiling fails
    (e.g. text too short or too uniform).
    """
    # TextTiling needs paragraph breaks (blank lines) between text blocks.
    # We treat each sentence as a "paragraph" so the tiler can find topic shifts.
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) < 3:
        return [text]

    # Join sentences with blank lines to form pseudo-paragraphs
    prepared = "\n\n".join(sentences)
    try:
        segments = _tiler.tokenize(prepared)
    except ValueError:
        # TextTiling raises ValueError when text is too short or uniform
        return [text]

    # Filter out empty segments
    segments = [s.strip() for s in segments if s.strip()]
    return segments if segments else [text]


def extract_quote(text: str, phrase: str, context_chars: int = 80) -> str:
    """Find phrase in subtitle text and return surrounding context."""
    idx = text.lower().find(phrase.lower())
    if idx == -1:
        # Try individual words from the phrase
        words = phrase.split()
        for word in words:
            idx = text.lower().find(word.lower())
            if idx != -1:
                break
    if idx == -1:
        return ""

    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(phrase) + context_chars)
    snippet = text[start:end].strip()

    # Clean up boundaries to whole words
    if start > 0:
        snippet = "..." + snippet[snippet.find(" ") + 1:]
    if end < len(text):
        last_space = snippet.rfind(" ")
        if last_space > 0:
            snippet = snippet[:last_space] + "..."

    return snippet


_EMBED_MODEL = None

def _get_embedder():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        print("Loading embedding model for dedup...")
        _EMBED_MODEL = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _EMBED_MODEL


def _story_dedup(entries: list[dict], segment_phrases: list[set[str]],
                 overlap_threshold: float = 0.5) -> list[dict]:
    """Dedup phrases that belong to the same news story.

    Two phrases are considered part of the same story if they co-occur
    in a high fraction of their segments. We keep the higher-scoring one.
    """
    if not entries or not segment_phrases:
        return entries

    # Build segment sets for each lemma: which segments mention it
    lemma_segments: dict[str, set[int]] = defaultdict(set)
    for seg_idx, seg_lemmas in enumerate(segment_phrases):
        for lemma in seg_lemmas:
            lemma_segments[lemma].add(seg_idx)

    # Greedy dedup: iterate top-down (already sorted by score),
    # skip if phrase co-occurs with an already-selected phrase in most of its segments
    selected = []
    for entry in entries:
        lemma = entry["lemma"]
        my_segs = lemma_segments.get(lemma, set())
        if not my_segs:
            selected.append(entry)
            continue

        is_dup = False
        for sel in selected:
            sel_segs = lemma_segments.get(sel["lemma"], set())
            if not sel_segs:
                continue
            overlap = len(my_segs & sel_segs)
            # Fraction of the smaller set that overlaps
            min_size = min(len(my_segs), len(sel_segs))
            if overlap / min_size >= overlap_threshold:
                is_dup = True
                break
        if not is_dup:
            selected.append(entry)

    n_removed = len(entries) - len(selected)
    if n_removed > 0:
        print(f"  Story dedup removed {n_removed} phrases (co-occurrence threshold={overlap_threshold})")
    return selected


def _cosine_dedup(entries: list[dict], threshold: float = 0.6) -> list[dict]:
    """Greedy dedup: iterate top-down, skip if cosine ≥ threshold to any selected."""
    if not entries:
        return entries

    model = _get_embedder()
    phrases = [e["phrase"] for e in entries]
    embeddings = model.encode(phrases, normalize_embeddings=True)

    selected_indices = []
    for i in range(len(entries)):
        is_dup = False
        for j in selected_indices:
            sim = float(np.dot(embeddings[i], embeddings[j]))
            if sim >= threshold:
                is_dup = True
                break
        if not is_dup:
            selected_indices.append(i)

    deduped = [entries[i] for i in selected_indices]
    n_removed = len(entries) - len(deduped)
    if n_removed > 0:
        print(f"  Cosine dedup removed {n_removed} phrases (threshold={threshold})")
    return deduped


def load_nlp():
    """Load spaCy model once."""
    print("Loading spaCy model...")
    nlp = spacy.load("de_core_news_md")
    nlp.max_length = 2_000_000
    return nlp


def build_zeitgeist(target_date: str, nlp=None) -> list[dict]:
    """
    Main pipeline: compute weekly zeitgeist ending on target_date.

    1. Load 7 days of news programs (target week)
    2. Load 14-day reference period before the week
    3. Extract phrases with spaCy, segment programs into stories
    4. Compute spike = target_freq / reference_avg_freq
    5. Filter: ≥2 distinct editorial units
    6. Score = spike × log₂(unit_count)
    7. Dedup: substring → cosine → story co-occurrence
    8. Return top GRID_SIZE entries
    """
    from datetime import date, timedelta

    if nlp is None:
        nlp = load_nlp()

    target_dt = date.fromisoformat(target_date)

    # --- Load target week (7 days ending on target_date) ---
    target_programs = []
    target_days = 7
    for i in range(target_days):
        day_date = (target_dt - timedelta(days=i)).isoformat()
        day_news = filter_news(load_day(day_date))
        target_programs.extend(day_news)
    if not target_programs:
        print(f"No news programs found for week ending {target_date}")
        return []
    week_start = (target_dt - timedelta(days=target_days - 1)).isoformat()
    print(f"Target week {week_start} → {target_date}: {len(target_programs)} news programs")

    # --- Load reference period (previous week) ---
    ref_programs = []
    ref_end = target_dt - timedelta(days=target_days)
    for i in range(REFERENCE_DAYS):
        ref_date = (ref_end - timedelta(days=i)).isoformat()
        day_news = filter_news(load_day(ref_date))
        ref_programs.extend(day_news)
    print(f"Reference ({REFERENCE_DAYS} days): {len(ref_programs)} news programs")

    # --- Extract phrases from target ---
    print("Extracting phrases from target day...")
    # lemma → {programs, editorial_units, count, quotes, surface_forms}
    target_data = defaultdict(lambda: {
        "programs": set(),
        "editorial_units": set(),
        "count": 0,
        "quotes": [],
        "surface_forms": Counter(),  # surface → count
    })

    # segment_id → set of lemmas (for co-occurrence dedup later)
    segment_phrases: list[set[str]] = []

    for prog in target_programs:
        text = prog.get("subtitle_text_clean", "")
        if not text:
            continue
        title = prog["title"]
        eu = editorial_unit(title)
        segments = segment_into_stories(text)

        for segment in segments:
            phrase_dicts = extract_phrases(nlp, segment)
            seg_lemmas = {pd["lemma"] for pd in phrase_dicts}
            segment_phrases.append(seg_lemmas)

        # Count per-program (not per-segment) — extract_phrases dedupes within text
        phrase_dicts = extract_phrases(nlp, text)
        for pd in phrase_dicts:
            lemma = pd["lemma"]
            entry = target_data[lemma]
            entry["programs"].add(title)
            entry["editorial_units"].add(eu)
            entry["count"] += 1
            entry["surface_forms"][pd["surface"]] += 1

            # Collect a quote if we don't have one from this program yet
            prog_titles_with_quotes = {q["title"] for q in entry["quotes"]}
            if title not in prog_titles_with_quotes:
                quote = extract_quote(text, lemma)
                if not quote:
                    quote = extract_quote(text, pd["surface"])
                if quote:
                    entry["quotes"].append({
                        "title": title,
                        "channel": prog.get("channel", ""),
                        "quote": quote,
                        "urn": prog.get("urn", ""),
                        "startTime": prog.get("startTime", ""),
                    })

    print(f"  {len(target_data)} unique phrases, {len(segment_phrases)} story segments")

    # --- Extract phrases from reference ---
    print("Extracting phrases from reference period...")
    ref_freq = Counter()
    for prog in ref_programs:
        text = prog.get("subtitle_text_clean", "")
        if not text:
            continue
        phrase_dicts = extract_phrases(nlp, text)
        for pd in phrase_dicts:
            ref_freq[pd["lemma"]] += 1

    print(f"  {len(ref_freq)} unique phrases in reference")

    # --- Compute keyness ---
    print("Computing keyness scores...")
    results = []

    for phrase, data in target_data.items():
        n_editorial_units = len(data["editorial_units"])
        if n_editorial_units < MIN_EDITORIAL_UNITS:
            continue

        target_count = data["count"]
        ref_count = ref_freq.get(phrase, 0)

        # Spike: ratio of target week frequency to reference week frequency.
        # Both periods are 7 days, so no per-day normalization needed.
        # Smoothing: assume at least 1 occurrence in reference week.
        ref_smoothed = max(ref_count, 1)
        spike = target_count / ref_smoothed

        score = spike * math.log2(n_editorial_units)

        # Best surface form: most frequent original spelling
        best_surface = data["surface_forms"].most_common(1)[0][0] if data["surface_forms"] else phrase

        results.append({
            "phrase": best_surface,   # display form (correct German)
            "lemma": phrase,          # normalized form (for dedup/counting)
            "spike": round(spike, 1),
            "target_count": target_count,
            "unit_count": n_editorial_units,
            "editorial_units": sorted(data["editorial_units"]),
            "programs": sorted(data["programs"]),
            "quotes": data["quotes"][:5],  # max 5 quotes
            "score": round(score, 1),
        })

    # --- Rank (tiebreaker: target_count) ---
    results.sort(key=lambda x: (x["score"], x["target_count"]), reverse=True)

    # --- Dedup: substring + cosine similarity ---
    # Step 1: substring on lemma — "Bosnien" inside "Bosnien-Herzegowina" → keep longer.
    # Step 2: cosine on phrase — "Mond" / "Mondlandung" → same story.
    deduped = []
    for entry in results:
        lemma_low = entry["lemma"].lower()
        is_dup = False
        for selected in deduped:
            sel_low = selected["lemma"].lower()
            if lemma_low in sel_low or sel_low in lemma_low:
                is_dup = True
                break
        if not is_dup:
            deduped.append(entry)

    # Cosine dedup on the substring-deduped list
    deduped = _cosine_dedup(deduped, threshold=0.6)

    # Story dedup: phrases co-occurring in the same segments are from the same story
    deduped = _story_dedup(deduped, segment_phrases)

    # --- LLM Quality Gate (optional) ---
    candidates = deduped[:GRID_SIZE * 3]  # send up to 3x grid size
    filtered = llm_quality_gate(candidates)
    top = filtered[:GRID_SIZE]

    # Add rank field
    for i, entry in enumerate(top):
        entry["rank"] = i + 1
        entry["imageUrl"] = ""

    print(f"\nTop {len(top)} phrases for {target_date}:")
    for entry in top[:10]:
        print(f"  {entry['rank']:2d}. {entry['phrase']:<30s} "
              f"spike={entry['spike']:>8.1f}  "
              f"units={entry['unit_count']}  "
              f"score={entry['score']:>8.1f}")

    return top


# ---------------------------------------------------------------------------
# LLM Quality Gate
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
Ты фильтр для дашборда "О чём говорит Швейцария на этой неделе".
Для каждой фразы ответь: 1 (zeitgeist) или 0 (шум).

Zeitgeist (1): КОНКРЕТНЫЕ имена собственные, названия, специфические термины
привязанные к конкретному событию или теме недели.
Примеры: "Bosnien-Herzegowina", "Kunsthaus Zürich", "NASA", "TikTok",
"Cyberangriff", "Solaranlage", "Netanjahu", "Todesstrafe".

Шум (0): общие/абстрактные существительные, которые могут появиться
в любых новостях любой недели. Даже если слово "звучит серьёзно",
если оно не привязано к конкретной теме — это шум.
Примеры: "Studium", "Protest", "Mannschaften", "Kontinent",
"Grenzwerte", "Rat", "Stimmen", "Versicherung", "Umwelt",
"Auseinandersetzungen", "Verbündeten", "Wechsel", "Trend".

Правило: если фразу нельзя загуглить и найти ОДНУ конкретную новость — это 0.

Ответь ТОЛЬКО цифрами через запятую, без пробелов. Пример: 1,0,1,1,0

Фразы:
{phrases}"""


def llm_quality_gate(entries: list[dict]) -> list[dict]:
    """Filter entries through Claude Haiku in batches. Returns only zeitgeist=1 entries.

    Requires ANTHROPIC_API_KEY env var. Skips silently if not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  LLM gate: skipped (no ANTHROPIC_API_KEY)")
        return entries

    try:
        import anthropic
    except ImportError:
        print("  LLM gate: skipped (anthropic package not installed)")
        return entries

    client = anthropic.Anthropic(api_key=api_key)
    log_path = OUTPUT_DIR / "llm_gate_log.txt"

    # Process in batches of 40 so Haiku can reliably return all verdicts
    BATCH_SIZE = 40
    all_filtered = []
    total_passed = 0

    print(f"  LLM gate: sending {len(entries)} candidates to Claude Haiku...")
    for batch_start in range(0, len(entries), BATCH_SIZE):
        batch = entries[batch_start:batch_start + BATCH_SIZE]

        phrase_lines = []
        for i, e in enumerate(batch):
            programs = ", ".join(e.get("editorial_units", [])[:3])
            phrase_lines.append(f"{i+1}. {e['phrase']} (spike={e['spike']}, programs: {programs})")

        prompt = _LLM_PROMPT.format(phrases="\n".join(phrase_lines))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        with open(log_path, "a") as f:
            f.write(f"\n--- batch {batch_start//BATCH_SIZE + 1}, {len(batch)} candidates ---\n{text}\n")

        try:
            verdicts = [int(v.strip()) for v in text.split(",")]
        except ValueError:
            print(f"  LLM gate: parse error in batch, keeping all. Response: {text[:100]}")
            all_filtered.extend(batch)
            continue

        if len(verdicts) != len(batch):
            print(f"  LLM gate: count mismatch ({len(verdicts)} vs {len(batch)}) in batch, keeping all")
            all_filtered.extend(batch)
            continue

        passed = [e for e, v in zip(batch, verdicts) if v == 1]
        total_passed += len(passed)
        all_filtered.extend(passed)

    print(f"  LLM gate: {total_passed}/{len(entries)} passed")
    return all_filtered


# ---------------------------------------------------------------------------
# Frame Extraction
# ---------------------------------------------------------------------------

IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"
FRAMES_DIR = OUTPUT_DIR / "frames"
CROPPED_DIR = OUTPUT_DIR / "cropped"


def _fetch_media_info(urn: str) -> dict:
    """Get VTT subtitle URL + HLS stream URL from Integration Layer."""
    url = f"{IL_BASE}/{urn}?onlyChapters=true&vector=portalplay"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return {}

    chapter = data.get("chapterList", [{}])[0]
    result = {}
    # Image URL (fallback)
    img = chapter.get("imageUrl", "")
    if img:
        result["imageUrl"] = img
    # VTT subtitle
    for sub in chapter.get("subtitleList", []):
        if sub.get("format") == "VTT":
            result["vttUrl"] = sub["url"]
            break
    # HLS stream
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


def _find_timecode(vtt_text: str, phrase: str) -> str:
    """Find timecode where phrase appears in VTT."""
    blocks = re.split(r"\n\n+", vtt_text)
    phrase_lower = phrase.lower()

    for block in blocks:
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                text = re.sub(r"<[^>]+>", "", " ".join(lines[i+1:])).lower()
                if phrase_lower in text:
                    return line.split("-->")[0].strip()

    # Fallback: try longest word from phrase
    words = sorted(phrase.split(), key=len, reverse=True)
    for word in words:
        if len(word) < 3:
            continue
        for block in blocks:
            lines = block.strip().split("\n")
            for i, line in enumerate(lines):
                if "-->" in line:
                    text = re.sub(r"<[^>]+>", "", " ".join(lines[i+1:])).lower()
                    if word.lower() in text:
                        return line.split("-->")[0].strip()
    return ""


def _compute_air_time(start_time_iso: str, vtt_timecode: str) -> str:
    """Compute real air time from program start + VTT offset.

    start_time_iso: '2026-04-01T19:30:00+02:00'
    vtt_timecode: '00:05:23.456'
    Returns: '19:35' (HH:MM in local time)
    """
    if not start_time_iso or not vtt_timecode:
        return ""
    try:
        from datetime import datetime, timedelta
        # Parse start time (take just HH:MM:SS, ignore timezone for display)
        time_part = start_time_iso[11:19]  # 'HH:MM:SS'
        h, m, s = int(time_part[:2]), int(time_part[3:5]), int(time_part[6:8])
        start_seconds = h * 3600 + m * 60 + s

        # Parse VTT timecode 'HH:MM:SS.mmm'
        tc_parts = vtt_timecode.replace(",", ".").split(":")
        tc_h = int(tc_parts[0])
        tc_m = int(tc_parts[1])
        tc_s = float(tc_parts[2])
        offset_seconds = tc_h * 3600 + tc_m * 60 + tc_s

        total = start_seconds + int(offset_seconds)
        air_h = (total // 3600) % 24
        air_m = (total % 3600) // 60
        return f"{air_h:02d}:{air_m:02d}"
    except Exception:
        return ""


def fetch_frames(entries: list[dict], date_str: str) -> list[dict]:
    """Fetch video frames for each entry. Updates imageUrl in-place."""
    FRAMES_DIR.mkdir(exist_ok=True)
    CROPPED_DIR.mkdir(exist_ok=True)

    vtt_cache: dict[str, str] = {}

    for i, entry in enumerate(entries):
        quotes = entry.get("quotes", [])
        if not quotes:
            continue
        urn = quotes[0].get("urn", "")
        if not urn:
            continue

        phrase = entry["phrase"]
        safe = re.sub(r"[^\w-]", "_", phrase)[:40]
        crop_path = CROPPED_DIR / f"{date_str}_{i+1:02d}_{safe}.jpg"

        # Skip if already exists
        if crop_path.exists():
            entry["imageUrl"] = f"../demo-data/cropped/{crop_path.name}"
            continue

        print(f"  [{i+1:2d}/{len(entries)}] {phrase[:35]:<35s} ", end="", flush=True)

        info = _fetch_media_info(urn)
        if not info:
            print("no media")
            continue

        hls_url = info.get("hlsUrl", "")
        vtt_url = info.get("vttUrl", "")
        fallback_img = info.get("imageUrl", "")

        frame_path = FRAMES_DIR / f"{date_str}_{i+1:02d}_{safe}.jpg"
        got_frame = False

        # Try frame at timecode
        if hls_url and vtt_url:
            if vtt_url not in vtt_cache:
                req = urllib.request.Request(vtt_url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        vtt_cache[vtt_url] = resp.read().decode("utf-8", errors="replace")
                except Exception:
                    vtt_cache[vtt_url] = ""

            tc = _find_timecode(vtt_cache[vtt_url], phrase)
            if not tc:
                tc = _find_timecode(vtt_cache[vtt_url], entry.get("lemma", phrase))
            if tc:
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", tc, "-i", hls_url,
                         "-frames:v", "1", "-q:v", "2", str(frame_path)],
                        capture_output=True, timeout=30,
                    )
                    got_frame = frame_path.exists()
                    if got_frame:
                        print(f"frame@{tc} ", end="", flush=True)
                        # Compute air time = program startTime + subtitle offset
                        entry["timecode"] = tc
                        start_time = quotes[0].get("startTime", "")
                        air_time = _compute_air_time(start_time, tc)
                        if air_time:
                            entry["airTime"] = air_time
                except Exception:
                    pass

        # Fallback: thumbnail
        if not got_frame and fallback_img:
            try:
                img = download_image(fallback_img)
                img.save(str(frame_path), quality=90)
                got_frame = True
                print("thumbnail ", end="", flush=True)
            except Exception:
                pass

        if not got_frame:
            print("no image")
            continue

        # Smart crop
        try:
            img = Image.open(str(frame_path))
            cropped = smart_crop(img)
            cropped.save(str(crop_path), quality=85)
            entry["imageUrl"] = f"../demo-data/cropped/{crop_path.name}"
            print("OK")
        except Exception as e:
            print(f"crop err: {e}")

    return entries


def save_zeitgeist(results: list[dict], target_date: str) -> Path:
    """Write zeitgeist JSON and return path."""
    day_compact = target_date.replace("-", "")
    out_path = OUTPUT_DIR / f"zeitgeist_{day_compact}.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def find_processable_days(min_news: int = 10) -> list[str]:
    """Find all days with enough news programs."""
    days = []
    for f in sorted(WEEK_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        news = [p for p in data
                if p.get("genre") == "Nachrichten"
                and p.get("word_count", 0) >= MIN_WORD_COUNT]
        if len(news) >= min_news:
            days.append(f.stem)
    return days


def main():
    batch = "--all" in sys.argv

    skip_images = "--no-images" in sys.argv

    if batch:
        dates = find_processable_days()
        print(f"=== SRF Zeitgeist Pipeline (News Only) — Batch ===")
        print(f"Processing {len(dates)} days: {dates[0]} → {dates[-1]}\n")
        nlp = load_nlp()
        generated = []
        for d in dates:
            results = build_zeitgeist(d, nlp=nlp)
            if results:
                if not skip_images:
                    print(f"  Fetching frames...")
                    fetch_frames(results, d.replace("-", ""))
                out = save_zeitgeist(results, d)
                generated.append(d.replace("-", ""))
                print(f"  Saved → {out}\n")
        # Write manifest for frontend
        manifest = OUTPUT_DIR / "days.json"
        manifest.write_text(json.dumps(sorted(generated)))
        print(f"\nManifest with {len(generated)} days → {manifest}")
    else:
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            target_date = sys.argv[1]
        else:
            files = sorted(WEEK_DIR.glob("*.json"))
            target_date = files[-1].stem if files else "2026-04-01"

        print(f"=== SRF Zeitgeist Pipeline (News Only) ===")
        print(f"Target date: {target_date}\n")

        results = build_zeitgeist(target_date)
        if results:
            if not skip_images:
                print(f"\nFetching frames...")
                fetch_frames(results, target_date.replace("-", ""))
            out = save_zeitgeist(results, target_date)
            print(f"\nSaved {len(results)} entries to {out}")


if __name__ == "__main__":
    main()
