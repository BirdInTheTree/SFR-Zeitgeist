"""Media fetching and screenshot helpers for the v3 pipeline."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path

from .subtitles import parse_vtt_blocks, timecode_to_seconds


IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"


def fetch_media_info(urn: str) -> dict:
    url = f"{IL_BASE}/{urn}?onlyChapters=true&vector=portalplay"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read())
    except Exception:
        return {}

    chapter = data.get("chapterList", [{}])[0]
    result = {}
    image_url = chapter.get("imageUrl", "")
    if image_url:
        result["imageUrl"] = image_url

    for subtitle in chapter.get("subtitleList", []):
        if subtitle.get("format") == "VTT":
            result["vttUrl"] = subtitle.get("url", "")
            break

    for resource in chapter.get("resourceList", []):
        if resource.get("streaming") == "HLS" and resource.get("quality") == "HD":
            result["hlsUrl"] = resource.get("url", "")
            break
    if "hlsUrl" not in result:
        for resource in chapter.get("resourceList", []):
            if resource.get("streaming") == "HLS":
                result["hlsUrl"] = resource.get("url", "")
                break
    return result


def load_vtt_text(urn: str, local_vtt_path: Path | None, cache_dir: Path) -> str:
    if local_vtt_path and local_vtt_path.exists():
        return local_vtt_path.read_text()

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{urn.replace(':', '_')}.vtt"
    if cache_path.exists():
        return cache_path.read_text()

    media_info = fetch_media_info(urn)
    vtt_url = media_info.get("vttUrl", "")
    if not vtt_url:
        return ""

    request = urllib.request.Request(vtt_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception:
        return ""

    cache_path.write_text(text)
    return text


def find_keyword_timecode(vtt_text: str, keyword: str, start_time: str, end_time: str) -> str:
    if not vtt_text:
        return start_time

    start_seconds = timecode_to_seconds(start_time)
    end_seconds = timecode_to_seconds(end_time)
    keyword_lower = keyword.lower()

    for block in parse_vtt_blocks(vtt_text):
        block_start = timecode_to_seconds(block["start_time"])
        if block_start < start_seconds or block_start > end_seconds:
            continue
        if keyword_lower in block["text"].lower():
            return block["start_time"]

    return start_time


def fetch_story_screenshot(
    entry: dict,
    output_dir: Path,
    local_vtt_path: Path | None = None,
    vtt_cache_dir: Path | None = None,
) -> str:
    from PIL import Image

    from backend.smart_crop import download_image, smart_crop

    output_dir.mkdir(parents=True, exist_ok=True)
    vtt_cache_dir = vtt_cache_dir or output_dir / "vtt"

    urn = entry.get("urn", "")
    if not urn:
        return ""

    media_info = fetch_media_info(urn)
    hls_url = media_info.get("hlsUrl", "")
    image_url = media_info.get("imageUrl", "")

    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", entry.get("canonical_keyword", "story"))[:60]
    raw_frame_path = output_dir / f"{stem}_raw.jpg"
    crop_path = output_dir / f"{stem}.jpg"

    vtt_text = load_vtt_text(urn, local_vtt_path=local_vtt_path, cache_dir=vtt_cache_dir)
    timecode = find_keyword_timecode(
        vtt_text,
        keyword=entry.get("canonical_keyword", ""),
        start_time=entry.get("start_time", "00:00:00.000"),
        end_time=entry.get("end_time", "00:00:00.000"),
    )

    got_frame = False
    if hls_url:
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", timecode, "-i", hls_url, "-frames:v", "1", "-q:v", "2", str(raw_frame_path)],
                capture_output=True,
                timeout=30,
            )
            got_frame = raw_frame_path.exists()
        except Exception:
            got_frame = False

    if not got_frame and image_url:
        try:
            image = download_image(image_url)
            image.save(str(raw_frame_path), quality=90)
            got_frame = True
        except Exception:
            got_frame = False

    if not got_frame:
        return ""

    try:
        image = Image.open(str(raw_frame_path))
        cropped = smart_crop(image)
        cropped.save(str(crop_path), quality=85)
    except Exception:
        return ""

    return str(crop_path)
