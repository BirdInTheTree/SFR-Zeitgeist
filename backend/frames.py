"""Frame extraction for SRF Zeitgeist.

Extracts video frames from HLS streams at the story's peak moment.
Fallback chain: peak timecode → keyword in VTT → program thumbnail.
"""

import logging
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .segmenter import (
    fetch_vtt_url,
    download_vtt,
    parse_vtt,
    get_vtt_cached,
    save_vtt_cache,
    seconds_to_tc,
    tc_to_seconds,
)

logger = logging.getLogger(__name__)

# smart_crop import — optional
try:
    from .smart_crop import smart_crop as _smart_crop, is_blank as _is_blank
    from PIL import Image as _Image
    _HAS_SMART_CROP = True
except ImportError:
    _HAS_SMART_CROP = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "demo-data"
VTT_CACHE_DIR = OUTPUT_DIR / "cache" / "vtt"


def _extract_frame(hls_url: str, timecode: str, out_path: Path) -> bool:
    """Extract a single video frame via ffmpeg. Returns True if file was created."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", timecode, "-i", hls_url,
             "-frames:v", "1", "-q:v", "2", str(out_path)],
            capture_output=True, timeout=30,
        )
        return out_path.exists()
    except Exception as e:
        logger.warning("ffmpeg failed at %s: %s", timecode, e)
        return False


def _try_peak_frame(hls_url: str, tc: str, frame_path: Path) -> bool:
    """Try frame at peak timecode. Retries 5s later if frame is blank."""
    if not hls_url or not tc:
        return False

    if not _extract_frame(hls_url, tc, frame_path):
        return False

    # Check if frame is blank — if so, try 5 seconds later
    if _HAS_SMART_CROP:
        test_img = _Image.open(str(frame_path))
        if _is_blank(test_img):
            offset = tc_to_seconds(tc) + 5.0
            retry_tc = seconds_to_tc(offset)
            _extract_frame(hls_url, retry_tc, frame_path)
            print(f"retry@{retry_tc} ", end="", flush=True)
            return frame_path.exists()

    print(f"frame@{tc} ", end="", flush=True)
    return True


def _try_keyword_frame(hls_url: str, vtt_url: str, urn: str,
                       keyword: str, frame_path: Path) -> bool:
    """Fallback: find keyword mention in VTT subtitles, extract frame there."""
    if not hls_url or not vtt_url:
        return False

    cached_vtt = get_vtt_cached(urn, VTT_CACHE_DIR)
    if not cached_vtt:
        try:
            cached_vtt = download_vtt(vtt_url)
            save_vtt_cache(urn, cached_vtt, VTT_CACHE_DIR)
        except Exception:
            return False

    blocks = parse_vtt(cached_vtt)
    keyword_tc = _find_keyword_in_blocks(blocks, keyword)
    if not keyword_tc:
        return False

    tc_str = seconds_to_tc(keyword_tc)
    if _extract_frame(hls_url, tc_str, frame_path):
        print("frame@keyword ", end="", flush=True)
        return True
    return False


def _try_thumbnail(fallback_img: str, frame_path: Path) -> bool:
    """Fallback: download the program's thumbnail image."""
    if not fallback_img:
        return False
    try:
        req = urllib.request.Request(
            fallback_img + "/scale/width/640",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            frame_path.write_bytes(resp.read())
        print("thumbnail ", end="", flush=True)
        return True
    except Exception as e:
        logger.warning("Thumbnail download failed: %s", e)
        return False


def _crop_and_save(frame_path: Path, crop_path: Path) -> None:
    """Smart-crop the frame (if available) and save final image."""
    if _HAS_SMART_CROP:
        img = _Image.open(str(frame_path))
        cropped = _smart_crop(img)
        cropped.save(str(crop_path), quality=85)
        print("OK")
    else:
        shutil.copy2(frame_path, crop_path)
        print("OK (no crop)")
    frame_path.unlink(missing_ok=True)


def fetch_frames(entries: list[dict], date_str: str) -> None:
    """Extract video frames for top stories. Updates imageUrl in-place.

    Tries three strategies in order: peak timecode → keyword in VTT → thumbnail.
    """
    images_dir = OUTPUT_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for i, entry in enumerate(entries):
        urn = entry.get("first_mention_urn", "")
        if not urn:
            continue

        keyword = entry["keyword"]
        safe = re.sub(r"[^\w-]", "_", keyword)[:40]
        crop_path = images_dir / f"{date_str}_{i+1:02d}_{safe}.jpg"

        if crop_path.exists():
            entry["imageUrl"] = str(crop_path.relative_to(PROJECT_ROOT))
            continue

        print(f"  [{i+1:2d}/{len(entries)}] {keyword[:35]:<35s} ", end="", flush=True)

        media_info = fetch_vtt_url(urn)
        if not media_info:
            print("no media")
            continue

        hls_url = media_info.get("hlsUrl", "")
        vtt_url = media_info.get("vttUrl", "")
        fallback_img = media_info.get("imageUrl", "")
        frame_path = images_dir / f".tmp_{date_str}_{i+1:02d}_{safe}.jpg"
        tc = entry.get("first_mention_time", "")

        got_frame = (
            _try_peak_frame(hls_url, tc, frame_path)
            or _try_keyword_frame(hls_url, vtt_url, urn, keyword, frame_path)
            or _try_thumbnail(fallback_img, frame_path)
        )

        if not got_frame:
            print("no image")
            continue

        _crop_and_save(frame_path, crop_path)
        entry["imageUrl"] = str(crop_path.relative_to(PROJECT_ROOT))


def _find_keyword_in_blocks(blocks: list[dict], keyword: str) -> float | None:
    """Find the first VTT block that mentions the keyword. Returns seconds or None."""
    kw_lower = keyword.lower()
    words = kw_lower.split()

    # Try exact match
    for block in blocks:
        if kw_lower in block["text"].lower():
            return block["start"]

    # Try longest word
    for word in sorted(words, key=len, reverse=True):
        if len(word) < 3:
            continue
        for block in blocks:
            if word in block["text"].lower():
                return block["start"]

    return None
