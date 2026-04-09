"""Subtitle and schedule helpers for the v3 pipeline."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path


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
