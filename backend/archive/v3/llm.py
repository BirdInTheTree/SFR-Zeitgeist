"""LLM prompts and Anthropic helpers for the v3 pipeline."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


SEGMENT_PROMPT = """You are segmenting subtitles from one SRF news or current-affairs broadcast into editorial story segments.

Your task:
1. Split the transcript into consecutive segments.
2. Each segment should contain one main story, or one clear intro, teaser, transition, or outro block.
3. For each segment return:
   - segment_id
   - start_time
   - end_time
   - segment_type (story|intro|outro|teaser|transition)
   - keyword
   - short_label
   - summary
   - key_entities
   - confidence
   - is_repeat_previous_episode (true|false)

Rules:
- Keep politically or semantically connected lines in one segment even if the wording changes.
- Use one specific keyword or short phrase that could be reused across programs for the same story.
- Mark is_repeat_previous_episode=true only if this segment is essentially the same editorial package as a segment from the previous episode of the same program.
- Return valid JSON only.

Return this exact shape:
{{"segments":[{{"segment_id":"...","start_time":"HH:MM:SS.mmm","end_time":"HH:MM:SS.mmm","segment_type":"story","keyword":"...","short_label":"...","summary":"...","key_entities":["..."],"confidence":0.0,"is_repeat_previous_episode":false}}]}}

Program: {program_title}

Previous episode context:
{previous_context}

Current transcript:
{transcript}
"""


CLUSTER_PROMPT = """You are merging editorial story segments from one SRF day across multiple programs.

Your task:
1. Group segments that describe the same story into one merged story.
2. Repeated carry-over segments from the same program should stay inside the same story and must not create a separate story.
3. Choose one canonical_keyword per merged story.
4. Return a concise short_label and summary for the merged story.

Return valid JSON only in this shape:
{{"stories":[{{"story_id":"story_1","canonical_keyword":"...","short_label":"...","summary":"...","segment_ids":["...","..."]}}]}}

Segments:
{segments}
"""


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package is not installed") from exc
    return anthropic.Anthropic(api_key=api_key)


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        candidate = cleaned[index:]
        try:
            obj, _ = decoder.raw_decode(candidate)
            return obj
        except json.JSONDecodeError:
            continue

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        candidate = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        return json.loads(candidate)

    raise ValueError(f"LLM did not return parseable JSON: {cleaned[:1000]}")


def call_json(client, prompt: str, model: str, max_tokens: int = 4000) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()
    return extract_json(text)


def format_previous_context(previous_segments: list[dict]) -> str:
    if not previous_segments:
        return "No previous episode context available."
    lines = []
    for segment in previous_segments:
        lines.append(
            f"- {segment.get('keyword','')} | {segment.get('short_label','')} | {segment.get('summary','')}"
        )
    return "\n".join(lines)


def format_transcript(blocks: list[dict]) -> str:
    return "\n".join(
        f"[{block['start_time']} --> {block['end_time']}] {block['text']}"
        for block in blocks
    )


def segment_broadcast(client, program_title: str, blocks: list[dict], previous_segments: list[dict], model: str) -> list[dict]:
    prompt = SEGMENT_PROMPT.format(
        program_title=program_title,
        previous_context=format_previous_context(previous_segments),
        transcript=format_transcript(blocks),
    )
    result = call_json(client, prompt, model=model, max_tokens=12000)
    return result.get("segments", [])


def cluster_day_segments(client, segments: list[dict], model: str) -> list[dict]:
    prompt_segments = json.dumps(segments, ensure_ascii=False, indent=2)
    result = call_json(client, CLUSTER_PROMPT.format(segments=prompt_segments), model=model, max_tokens=8000)
    return result.get("stories", [])
