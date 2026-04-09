"""Standalone story-first v3 pipeline for SRF Zeitgeist."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .llm import cluster_day_segments, get_anthropic_client, load_env_file, segment_broadcast
from .media import fetch_story_screenshot, load_vtt_text
from .scoring import score_story
from .subtitles import (
    filter_news_programs,
    find_previous_dates,
    load_day_programs,
    parse_vtt_blocks,
    segment_duration_seconds,
    slugify,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAY_DIR = PROJECT_ROOT / "demo-data" / "week"
OUTPUT_ROOT = PROJECT_ROOT / "demo-data" / "v3"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the story-first SRF Zeitgeist v3 pipeline.")
    parser.add_argument("date", help="Target date, e.g. 2026-04-01")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model name")
    parser.add_argument("--baseline-days", type=int, default=7, help="Baseline window length")
    parser.add_argument("--top-k", type=int, default=49, help="Number of ranked stories to keep")
    parser.add_argument("--no-images", action="store_true", help="Skip screenshot extraction")
    return parser.parse_args()


def cache_dirs() -> dict[str, Path]:
    root = OUTPUT_ROOT / "cache"
    paths = {
        "root": OUTPUT_ROOT,
        "segments": root / "segments",
        "stories": root / "stories",
        "vtt": root / "vtt",
        "images": OUTPUT_ROOT / "images",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def segment_cache_path(cache_path: Path, day: str, title: str) -> Path:
    return cache_path / f"{day}_{slugify(title)}.json"


def story_cache_path(cache_path: Path, day: str) -> Path:
    return cache_path / f"{day}.json"


def local_vtt_candidate(program: dict) -> Path | None:
    root = PROJECT_ROOT / "demo-data"
    explicit = root / f"{program.get('title', '').replace('/', '_')}.vtt"
    if explicit.exists():
        return explicit
    normalized = root / f"{program.get('title', '').replace(' ', '_').replace('/', '_')}.vtt"
    if normalized.exists():
        return normalized
    return None


def enrich_segments(day: str, program: dict, segments: list[dict]) -> list[dict]:
    enriched = []
    for index, segment in enumerate(segments, start=1):
        item = dict(segment)
        item["segment_id"] = item.get("segment_id") or f"{day}:{slugify(program['title'])}:{index:03d}"
        item["date"] = day
        item["program_title"] = program.get("title", "")
        item["program_start_time"] = program.get("startTime", "")
        item["urn"] = program.get("urn", "")
        item["duration_seconds"] = segment_duration_seconds(item)
        enriched.append(item)
    return enriched


def segment_program_cached(
    client,
    cache_path: Path,
    day: str,
    program: dict,
    previous_segments: list[dict],
    model: str,
    vtt_cache_dir: Path,
) -> list[dict]:
    path = segment_cache_path(cache_path, day, program["title"])
    if path.exists():
        return read_json(path)["segments"]

    local_vtt_path = local_vtt_candidate(program)
    vtt_text = load_vtt_text(program.get("urn", ""), local_vtt_path=local_vtt_path, cache_dir=vtt_cache_dir)
    if not vtt_text:
        write_json(path, {"program": program, "segments": []})
        return []

    blocks = parse_vtt_blocks(vtt_text)
    if not blocks:
        write_json(path, {"program": program, "segments": []})
        return []

    segments = segment_broadcast(
        client,
        program_title=program["title"],
        blocks=blocks,
        previous_segments=previous_segments,
        model=model,
    )
    enriched = enrich_segments(day, program, segments)
    write_json(path, {"program": program, "segments": enriched})
    return enriched


def cluster_day_cached(client, cache_path: Path, day: str, segments: list[dict], model: str) -> list[dict]:
    path = story_cache_path(cache_path, day)
    if path.exists():
        return read_json(path).get("stories", [])

    stories = cluster_day_segments(client, segments, model=model)
    write_json(path, {"date": day, "stories": stories})
    return stories


def build_segment_lookup(all_segments: list[dict]) -> dict[str, dict]:
    return {segment["segment_id"]: segment for segment in all_segments}


def build_story_metrics(story: dict, segment_lookup: dict[str, dict], baseline_story_segments: dict[str, list[int]]) -> dict:
    segments = [segment_lookup[segment_id] for segment_id in story.get("segment_ids", []) if segment_id in segment_lookup]
    if not segments:
        return {}

    segments.sort(key=lambda item: (item.get("program_start_time", ""), item["start_time"]))

    canonical_keyword = story.get("canonical_keyword", "")
    baseline_counts = baseline_story_segments.get(canonical_keyword, [])
    baseline_avg = sum(baseline_counts) / len(baseline_counts) if baseline_counts else 0.0

    total_segments = len(segments)
    distinct_programs = len({segment["program_title"] for segment in segments})
    total_story_seconds = sum(segment.get("duration_seconds", 0.0) for segment in segments)
    score = score_story(
        today_segments=total_segments,
        baseline_avg_segments=baseline_avg,
        distinct_programs=distinct_programs,
        total_segments=total_segments,
        total_story_seconds=total_story_seconds,
    )

    first_segment = segments[0]
    return {
        "story_id": story.get("story_id", ""),
        "canonical_keyword": canonical_keyword,
        "short_label": story.get("short_label", canonical_keyword),
        "summary": story.get("summary", ""),
        "segment_ids": story.get("segment_ids", []),
        "programs": sorted({segment["program_title"] for segment in segments}),
        "segment_count": total_segments,
        "distinct_program_count": distinct_programs,
        "total_story_seconds": round(total_story_seconds, 1),
        "baseline_avg_segments": round(baseline_avg, 3),
        "score": round(score, 4),
        "urn": first_segment.get("urn", ""),
        "program_title": first_segment.get("program_title", ""),
        "program_start_time": first_segment.get("program_start_time", ""),
        "start_time": first_segment.get("start_time", ""),
        "end_time": first_segment.get("end_time", ""),
    }


def baseline_segment_counts(stories_by_day: dict[str, list[dict]], segment_lookup_by_day: dict[str, dict[str, dict]]) -> dict[str, list[int]]:
    counts = defaultdict(list)
    for day, stories in stories_by_day.items():
        lookup = segment_lookup_by_day[day]
        for story in stories:
            canonical_keyword = story.get("canonical_keyword", "")
            if not canonical_keyword:
                continue
            segment_count = sum(1 for segment_id in story.get("segment_ids", []) if segment_id in lookup)
            counts[canonical_keyword].append(segment_count)
    return counts


def run_pipeline(target_date: str, model: str, baseline_days: int, top_k: int, skip_images: bool) -> Path:
    load_env_file(PROJECT_ROOT / ".env")
    client = get_anthropic_client()
    caches = cache_dirs()

    all_days = find_previous_dates(target_date, baseline_days) + [target_date]
    previous_segments_by_title: dict[str, list[dict]] = {}
    day_stories: dict[str, list[dict]] = {}
    segment_lookup_by_day: dict[str, dict[str, dict]] = {}

    for day in all_days:
        programs = filter_news_programs(load_day_programs(DAY_DIR / f"{day}.json"))
        day_segments = []
        for program in programs:
            previous_segments = previous_segments_by_title.get(program["title"], [])
            segments = segment_program_cached(
                client,
                cache_path=caches["segments"],
                day=day,
                program=program,
                previous_segments=previous_segments,
                model=model,
                vtt_cache_dir=caches["vtt"],
            )
            if segments:
                day_segments.extend(segments)
                previous_segments_by_title[program["title"]] = segments

        stories = cluster_day_cached(client, caches["stories"], day, day_segments, model=model) if day_segments else []
        day_stories[day] = stories
        segment_lookup_by_day[day] = build_segment_lookup(day_segments)

    baseline_days_only = {day: stories for day, stories in day_stories.items() if day != target_date}
    baseline_counts = baseline_segment_counts(baseline_days_only, segment_lookup_by_day)

    target_lookup = segment_lookup_by_day[target_date]
    ranked = []
    for story in day_stories[target_date]:
        metrics = build_story_metrics(story, target_lookup, baseline_counts)
        if metrics:
            ranked.append(metrics)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    ranked = ranked[:top_k]

    if not skip_images:
        for entry in ranked:
            program_stub = {
                "title": entry["program_title"],
                "urn": entry["urn"],
            }
            image_path = fetch_story_screenshot(
                entry,
                output_dir=caches["images"] / target_date,
                local_vtt_path=local_vtt_candidate(program_stub),
                vtt_cache_dir=caches["vtt"],
            )
            if image_path:
                entry["imagePath"] = image_path

    output_path = OUTPUT_ROOT / f"zeitgeist_{target_date.replace('-', '')}.json"
    write_json(
        output_path,
        {
            "date": target_date,
            "formula": "score = novelty * spread * persistence * prominence",
            "stories": ranked,
        },
    )
    return output_path


def main() -> None:
    args = parse_args()
    output_path = run_pipeline(
        target_date=args.date,
        model=args.model,
        baseline_days=args.baseline_days,
        top_k=args.top_k,
        skip_images=args.no_images,
    )
    print(f"Saved v3 output to {output_path}")


if __name__ == "__main__":
    main()