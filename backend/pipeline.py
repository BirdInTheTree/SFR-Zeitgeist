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

import spacy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEK_DIR = PROJECT_ROOT / "demo-data" / "week"
OUTPUT_DIR = PROJECT_ROOT / "demo-data"

GRID_SIZE = 36
MIN_PROGRAMS = 2          # phrase must appear in ≥2 distinct programs
REFERENCE_DAYS = 14
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
# We collapse them into editorial units for the "≥2 programs" filter.
_GEBAERDEN_SUFFIX = " in Gebärdensprache"


def editorial_unit(title: str) -> str:
    """Collapse 'Tagesschau in Gebärdensprache' → 'Tagesschau'."""
    if title.endswith(_GEBAERDEN_SUFFIX):
        return title[: -len(_GEBAERDEN_SUFFIX)]
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


def extract_phrases(nlp, text: str) -> list[str]:
    """Extract noun phrases + named entities from German subtitle text."""
    doc = nlp(text)

    phrases = set()

    # Noun chunks
    for chunk in doc.noun_chunks:
        has_noun = any(t.pos_ in ("NOUN", "PROPN") for t in chunk)
        if has_noun:
            lemma = " ".join(
                t.lemma_ for t in chunk
                if t.pos_ in ("NOUN", "PROPN", "ADJ")
                and not t.is_stop
            ).strip()
            if len(lemma) >= MIN_PHRASE_LEN and len(lemma.split()) <= MAX_PHRASE_WORDS:
                phrases.add(lemma)

    # Named entities
    for ent in doc.ents:
        if ent.label_ in ("PER", "ORG", "LOC", "GPE"):
            cleaned = ent.text.strip()
            if len(cleaned) >= MIN_PHRASE_LEN and len(cleaned.split()) <= MAX_PHRASE_WORDS:
                phrases.add(cleaned)

    # Remove subtitle metadata junk
    phrases = {
        p for p in phrases
        if not any(junk.lower() in p.lower() for junk in _JUNK_PATTERNS)
    }

    return list(phrases)


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


def build_zeitgeist(target_date: str) -> list[dict]:
    """
    Main pipeline: compute zeitgeist for a target date.

    1. Load target day news programs (including re-broadcasts)
    2. Load 14-day reference period news programs
    3. Extract phrases with spaCy
    4. Compute spike = target_freq / reference_avg_freq
    5. Filter: ≥2 distinct programs
    6. Score = spike × log₂(program_count)
    7. Return top GRID_SIZE entries
    """
    print(f"Loading spaCy model...")
    nlp = spacy.load("de_core_news_md")
    # Increase max length for concatenated subtitle text
    nlp.max_length = 2_000_000

    # --- Load target day ---
    target_programs = filter_news(load_day(target_date))
    if not target_programs:
        print(f"No news programs found for {target_date}")
        return []
    print(f"Target {target_date}: {len(target_programs)} news programs")

    # --- Load reference period ---
    from datetime import date, timedelta
    target_dt = date.fromisoformat(target_date)
    ref_programs = []
    for i in range(1, REFERENCE_DAYS + 1):
        ref_date = (target_dt - timedelta(days=i)).isoformat()
        day_news = filter_news(load_day(ref_date))
        ref_programs.extend(day_news)
    print(f"Reference ({REFERENCE_DAYS} days): {len(ref_programs)} news programs")

    # --- Extract phrases from target ---
    print("Extracting phrases from target day...")
    # phrase → {programs: set, count: int, quotes: list}
    target_data = defaultdict(lambda: {
        "programs": set(),
        "editorial_units": set(),
        "count": 0,
        "quotes": [],
    })

    for prog in target_programs:
        text = prog.get("subtitle_text_clean", "")
        if not text:
            continue
        phrases = extract_phrases(nlp, text)
        title = prog["title"]
        eu = editorial_unit(title)

        for phrase in phrases:
            entry = target_data[phrase]
            entry["programs"].add(title)
            entry["editorial_units"].add(eu)
            entry["count"] += 1

            # Collect a quote if we don't have one from this program yet
            prog_titles_with_quotes = {q["title"] for q in entry["quotes"]}
            if title not in prog_titles_with_quotes:
                quote = extract_quote(text, phrase)
                if quote:
                    entry["quotes"].append({
                        "title": title,
                        "channel": prog.get("channel", ""),
                        "quote": quote,
                        "urn": prog.get("urn", ""),
                    })

    print(f"  {len(target_data)} unique phrases extracted")

    # --- Extract phrases from reference ---
    print("Extracting phrases from reference period...")
    ref_freq = Counter()
    for prog in ref_programs:
        text = prog.get("subtitle_text_clean", "")
        if not text:
            continue
        phrases = extract_phrases(nlp, text)
        for phrase in phrases:
            ref_freq[phrase] += 1

    print(f"  {len(ref_freq)} unique phrases in reference")

    # --- Compute keyness ---
    print("Computing keyness scores...")
    results = []

    for phrase, data in target_data.items():
        n_editorial_units = len(data["editorial_units"])
        if n_editorial_units < MIN_PROGRAMS:
            continue

        target_count = data["count"]
        ref_count = ref_freq.get(phrase, 0)
        ref_avg = ref_count / REFERENCE_DAYS if REFERENCE_DAYS > 0 else 0

        # Spike: how much more frequent today vs baseline.
        # Smoothing: assume at least 1 occurrence over the entire reference period
        # so ref_avg_smoothed >= 1/REFERENCE_DAYS ≈ 0.071.
        # This keeps new phrases high but differentiates them by target_count.
        ref_avg_smoothed = max(ref_avg, 1 / REFERENCE_DAYS)
        spike = target_count / ref_avg_smoothed

        score = spike * math.log2(n_editorial_units)

        results.append({
            "phrase": phrase,
            "spike": round(spike, 1),
            "target_count": target_count,
            "unit_count": n_editorial_units,
            "editorial_units": sorted(data["editorial_units"]),
            "programs": sorted(data["programs"]),
            "quotes": data["quotes"][:5],  # max 5 quotes
            "score": round(score, 1),
        })

    # --- Rank ---
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:GRID_SIZE]

    # Add rank field, remove internal score
    for i, entry in enumerate(top):
        entry["rank"] = i + 1
        entry["imageUrl"] = ""  # placeholder — no frame extraction yet

    print(f"\nTop {len(top)} phrases for {target_date}:")
    for entry in top[:10]:
        print(f"  {entry['rank']:2d}. {entry['phrase']:<30s} "
              f"spike={entry['spike']:>8.1f}  "
              f"units={entry['unit_count']}  "
              f"score={entry['score']:>8.1f}")

    return top


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

    if batch:
        dates = find_processable_days()
        print(f"=== SRF Zeitgeist Pipeline (News Only) — Batch ===")
        print(f"Processing {len(dates)} days: {dates[0]} → {dates[-1]}\n")
        generated = []
        for d in dates:
            results = build_zeitgeist(d)
            if results:
                out = save_zeitgeist(results, d)
                generated.append(d.replace("-", ""))
                print(f"  Saved → {out}\n")
        # Write manifest for frontend
        manifest = OUTPUT_DIR / "days.json"
        manifest.write_text(json.dumps(sorted(generated)))
        print(f"\nManifest with {len(generated)} days → {manifest}")
    else:
        if len(sys.argv) > 1:
            target_date = sys.argv[1]
        else:
            files = sorted(WEEK_DIR.glob("*.json"))
            target_date = files[-1].stem if files else "2026-04-01"

        print(f"=== SRF Zeitgeist Pipeline (News Only) ===")
        print(f"Target date: {target_date}\n")

        results = build_zeitgeist(target_date)
        if results:
            out = save_zeitgeist(results, target_date)
            print(f"\nSaved {len(results)} entries to {out}")


if __name__ == "__main__":
    main()
