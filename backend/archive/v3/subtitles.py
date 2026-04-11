"""Subtitle and schedule helpers for the v3 pipeline."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from collections import Counter


NEWS_GENRES = {"Nachrichten"}
NEWS_TITLES = {
    "10 vor 10",
    "Club",
    "Eco Talk",
    "Gredig direkt",
    "Meteo",
    "Rundschau",
    "SRF Börse",
    "Schweiz aktuell",
    "Tagesschau",
    "Tagesschau kompakt",
    "Telesguard",
}


def load_day_programs(day_json_path: Path) -> list[dict]:
    if not day_json_path.exists():
        return []
    return json.loads(day_json_path.read_text())


def is_news_program(program: dict) -> bool:
    title = program.get("title", "")
    genre = program.get("genre", "")
    return genre in NEWS_GENRES or title in NEWS_TITLES


def filter_news_programs(programs: list[dict]) -> list[dict]:
    return [program for program in programs if is_news_program(program)]


def editorial_unit(title: str) -> str:
    for suffix in (" in Gebaerdensprache", " in Gebärdensprache", " kompakt", " extra"):
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt_blocks(vtt_text: str) -> list[dict]:
    chunks = re.split(r"\n\n+", vtt_text)
    blocks = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        time_line = None
        time_index = -1
        for index, line in enumerate(lines):
            if "-->" in line:
                time_line = line
                time_index = index
                break

        if time_line is None:
            continue

        start_time, end_time = [part.strip() for part in time_line.split("-->", 1)]
        text = strip_tags(" ".join(lines[time_index + 1 :]))
        if not text:
            continue

        blocks.append({
            "start_time": start_time,
            "end_time": end_time,
            "text": text,
        })
    return blocks


def timecode_to_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    raise ValueError(f"Unsupported timecode format: {value}")


def seconds_to_timecode(value: float) -> str:
    total_ms = int(round(value * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) / 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def segment_duration_seconds(segment: dict) -> float:
    return max(0.0, timecode_to_seconds(segment["end_time"]) - timecode_to_seconds(segment["start_time"]))


def extract_segment_text(blocks: list[dict], start_time: str, end_time: str) -> str:
    start_seconds = timecode_to_seconds(start_time)
    end_seconds = timecode_to_seconds(end_time)

    texts = []
    for block in blocks:
        block_start = timecode_to_seconds(block["start_time"])
        block_end = timecode_to_seconds(block["end_time"])
        if block_end > start_seconds and block_start < end_seconds:
            texts.append(block["text"])

    return " ".join(texts)


_STOPWORDS = frozenset(
    "der die das ein eine einer eines einem einen den dem des und oder aber "
    "ist sind war waren wird werden hat haben hatte hatten kann können konnte "
    "soll sollen sollte mit von für auf aus bei nach über vor durch zwischen "
    "sich ich wir sie er es ihr sein seine seiner seinem seinen ihre ihrem "
    "nicht auch noch schon sehr mehr als wie wenn dann da so nur doch weil "
    "dass ob zum zur bis um an in im am vom was wer wo alle allem allen aller "
    "alles andere anderem anderen anderer anderes hier dort nun jetzt heute "
    "diese diesem diesen dieser dieses jede jedem jeden jeder jedes man muss "
    "müssen gegen unter bereits also etwa rund neue neuen neuer neues neuem "
    "keine keinem keinen keiner".split()
)


def compute_fingerprint(text: str) -> dict:
    words = text.split()

    entities = set()
    for index, word in enumerate(words):
        clean = re.sub(r"[^\wäöüÄÖÜß]", "", word)
        if len(clean) < 2:
            continue
        if clean[0].isupper() and clean.lower() not in _STOPWORDS:
            is_sentence_start = index == 0 or (index > 0 and words[index - 1][-1] in ".!?")
            if not is_sentence_start:
                entities.add(clean)

    word_freq = Counter()
    for word in words:
        clean = re.sub(r"[^\wäöüÄÖÜß]", "", word).lower()
        if len(clean) > 4 and clean not in _STOPWORDS:
            word_freq[clean] += 1

    top_words = sorted([word for word, _ in word_freq.most_common(5)])

    return {
        "entities": sorted(entities),
        "top_words": top_words,
        "word_count": len(words),
    }


def fingerprint_match(first: dict, second: dict) -> bool:
    entity_overlap = len(set(first.get("entities", [])) & set(second.get("entities", [])))
    if entity_overlap >= 2:
        return True

    word_overlap = len(set(first.get("top_words", [])) & set(second.get("top_words", [])))
    return word_overlap >= 3


def is_near_duplicate(first: dict, second: dict) -> bool:
    if not first or not second:
        return False

    first_entities = set(first.get("entities", []))
    second_entities = set(second.get("entities", []))
    if first_entities and second_entities:
        overlap = len(first_entities & second_entities)
        min_size = min(len(first_entities), len(second_entities))
        if min_size and overlap / min_size >= 0.7:
            return True

    first_words = set(first.get("top_words", []))
    second_words = set(second.get("top_words", []))
    return len(first_words & second_words) >= 4


def find_previous_dates(target_date: str, count: int) -> list[str]:
    target_dt = date.fromisoformat(target_date)
    return [
        (target_dt - timedelta(days=offset)).isoformat()
        for offset in range(count, 0, -1)
    ]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def title_to_filename(title: str) -> str:
    return slugify(title).replace("_", " ")
