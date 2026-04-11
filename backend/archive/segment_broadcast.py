import argparse
import json
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DAY_DIR = PROJECT_ROOT / "demo-data" / "week"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "demo-data" / "segmentation"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


PROMPT_TEMPLATE = """You are segmenting subtitles from a single SRF news broadcast into editorial story segments. Split the transcript into consecutive segments where each segment contains one main news story or one clear studio intro/outro block. For each segment, return: start_time, end_time, segment_type (story|intro|outro|teaser|transition), short_label, summary, key_entities, and confidence. Start a new segment only when the topic clearly changes, not at every subtitle block. Keep politically or semantically connected lines in the same segment even if wording varies. Use the provided timestamps to preserve exact order and coverage duration. Return valid JSON only in this format: {{"segments":[{{"start_time":"HH:MM:SS.mmm","end_time":"HH:MM:SS.mmm","segment_type":"story","short_label":"...","summary":"...","key_entities":["..."],"confidence":0.0}}]}}. Here is the subtitle transcript with timestamps:\n\n{transcript}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment one SRF broadcast from a VTT file.")
    parser.add_argument("--date", required=True, help="Broadcast date, e.g. 2026-04-01")
    parser.add_argument("--title", required=True, help="Program title as stored in demo-data/week/*.json")
    parser.add_argument("--vtt", required=True, help="Path to the raw VTT subtitle file")
    parser.add_argument("--day-json", help="Optional explicit path to the day JSON file")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for JSON and Markdown")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model name")
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_program_metadata(day_json_path: Path, title: str) -> dict:
    programs = json.loads(day_json_path.read_text())
    for program in programs:
        if program.get("title") == title:
            return program
    raise ValueError(f"Program '{title}' not found in {day_json_path}")


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt_blocks(vtt_path: Path) -> list[dict]:
    content = vtt_path.read_text()
    chunks = re.split(r"\n\n+", content)
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
        text = strip_tags(" ".join(lines[time_index + 1:]))
        if not text:
            continue

        blocks.append({
            "start_time": start_time,
            "end_time": end_time,
            "text": text,
        })

    if not blocks:
        raise ValueError(f"No subtitle blocks parsed from {vtt_path}")
    return blocks


def build_prompt(blocks: list[dict]) -> str:
    transcript_lines = []
    for block in blocks:
        transcript_lines.append(f"[{block['start_time']} --> {block['end_time']}] {block['text']}")
    return PROMPT_TEMPLATE.format(transcript="\n".join(transcript_lines))


def call_model(prompt: str, model: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package is not installed") from exc

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=3500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Model did not return JSON: {text[:500]}")
    return json.loads(match.group(0))


def format_airtime(start_time: str) -> str:
    match = re.search(r"T(\d{2}:\d{2})", start_time)
    return match.group(1) if match else start_time


def pick_key_characteristics(segments: list[dict]) -> list[str]:
    selected = []

    first_non_story = next((segment for segment in segments if segment.get("segment_type") != "story"), None)
    if first_non_story:
        selected.append(
            f"Открытие выпуска: {first_non_story.get('short_label', 'вступление')} — {first_non_story.get('summary', '').strip()}"
        )

    story_segments = [segment for segment in segments if segment.get("segment_type") == "story"]
    for segment in story_segments[:3]:
        selected.append(
            f"{segment.get('short_label', 'Сюжет')} — {segment.get('summary', '').strip()}"
        )

    return [item for item in selected if item][:4]


def build_markdown(program: dict, segments: list[dict]) -> str:
    airtime = format_airtime(program.get("startTime", ""))
    characteristics = pick_key_characteristics(segments)

    lines = [
        f"# {program['title']}",
        "",
        f"- Дата: {program['date']}",
        f"- Время выпуска: {airtime}",
        f"- Канал: {program.get('channel', '')}",
        "",
        "## Ключевые характеристики",
        "",
    ]

    for index, item in enumerate(characteristics, start=1):
        lines.append(f"{index}. {item}")

    lines.extend([
        "",
        "## Сегменты",
        "",
    ])

    for index, segment in enumerate(segments, start=1):
        entities = ", ".join(segment.get("key_entities", [])[:6])
        lines.extend([
            f"### {index}. {segment.get('short_label', 'Без названия')}",
            f"- Время: {segment.get('start_time', '')} - {segment.get('end_time', '')}",
            f"- Тип: {segment.get('segment_type', '')}",
            f"- Кратко: {segment.get('summary', '').strip()}",
            f"- Сущности: {entities}",
            f"- Уверенность: {segment.get('confidence', '')}",
            "",
        ])

    return "\n".join(lines).strip() + "\n"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def main() -> None:
    args = parse_args()
    load_env_file(PROJECT_ROOT / ".env")

    day_json_path = Path(args.day_json) if args.day_json else DEFAULT_DAY_DIR / f"{args.date}.json"
    program = load_program_metadata(day_json_path, args.title)
    blocks = parse_vtt_blocks(Path(args.vtt))
    prompt = build_prompt(blocks)
    result = call_model(prompt, args.model)

    segments = result.get("segments", [])
    if not segments:
        raise ValueError("Model returned no segments")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.date}_{slugify(args.title)}"

    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"

    json_payload = {
        "program": {
            "date": program.get("date"),
            "title": program.get("title"),
            "startTime": program.get("startTime"),
            "channel": program.get("channel"),
            "urn": program.get("urn"),
            "vtt": str(Path(args.vtt)),
        },
        "segments": segments,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2))
    md_path.write_text(build_markdown(program, segments))

    print(f"Wrote segmentation JSON: {json_path}")
    print(f"Wrote segmentation report: {md_path}")


if __name__ == "__main__":
    main()