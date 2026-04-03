"""
Extract video frames for zeitgeist phrases.

For each phrase:
1. Get VTT subtitle URL from Integration Layer (by URN)
2. Find timecode where the phrase is spoken
3. Get HLS video stream URL
4. Extract frame with ffmpeg at that timecode
5. Smart crop to 4:3 (280x210)
"""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from smart_crop import smart_crop, download_image
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "demo-data"
CROPPED_DIR = OUTPUT_DIR / "cropped"
FRAMES_DIR = OUTPUT_DIR / "frames"

IL_BASE = "https://il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn"


def fetch_media_info(urn: str) -> dict:
    """Get VTT subtitle URL + HLS stream URL from Integration Layer."""
    url = f"{IL_BASE}/{urn}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"    IL error: {e}")
        return {}

    chapter = data.get("chapterList", [{}])[0]
    result = {"imageUrl": ""}

    # Image URL (fallback)
    img = chapter.get("imageUrl", "")
    if img:
        result["imageUrl"] = img + "/scale/width/640"

    # Subtitle URL (VTT)
    for sub in chapter.get("subtitleList", []):
        if sub.get("format") == "VTT":
            result["vttUrl"] = sub.get("url", "")
            break

    # HLS stream URL
    for res in chapter.get("resourceList", []):
        if res.get("streaming") == "HLS" and res.get("quality") == "HD":
            result["hlsUrl"] = res.get("url", "")
            break
    # Fallback to any HLS
    if "hlsUrl" not in result:
        for res in chapter.get("resourceList", []):
            if res.get("streaming") == "HLS":
                result["hlsUrl"] = res.get("url", "")
                break

    return result


def fetch_vtt(url: str) -> str:
    """Download VTT subtitle text."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    VTT download error: {e}")
        return ""


def find_timecode(vtt_text: str, phrase: str) -> str:
    """Find the timecode where phrase appears in VTT subtitles.

    Returns timecode string like '00:01:23.456' or empty string.
    """
    # VTT format: "00:01:23.456 --> 00:01:25.789\nsubtitle text"
    blocks = re.split(r"\n\n+", vtt_text)
    phrase_lower = phrase.lower()
    # Try exact match first
    for block in blocks:
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                text = " ".join(lines[i + 1:]).lower()
                # Strip HTML tags
                text = re.sub(r"<[^>]+>", "", text)
                if phrase_lower in text:
                    # Return start timecode
                    return line.split("-->")[0].strip()

    # Try individual words from phrase (longest first)
    words = sorted(phrase.split(), key=len, reverse=True)
    for word in words:
        if len(word) < 3:
            continue
        word_lower = word.lower()
        for block in blocks:
            lines = block.strip().split("\n")
            for i, line in enumerate(lines):
                if "-->" in line:
                    text = " ".join(lines[i + 1:]).lower()
                    text = re.sub(r"<[^>]+>", "", text)
                    if word_lower in text:
                        return line.split("-->")[0].strip()

    return ""


def extract_frame(hls_url: str, timecode: str, output_path: str) -> bool:
    """Extract a single frame from HLS stream at timecode using ffmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", timecode,
                "-i", hls_url,
                "-frames:v", "1",
                "-q:v", "2",
                output_path,
            ],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0 and Path(output_path).exists()
    except Exception as e:
        print(f"    ffmpeg error: {e}")
        return False


def process_day(date_str: str):
    """Fetch frames for all phrases in a zeitgeist file."""
    path = OUTPUT_DIR / f"zeitgeist_{date_str}.json"
    if not path.exists():
        print(f"No zeitgeist file for {date_str}")
        return

    data = json.loads(path.read_text())
    CROPPED_DIR.mkdir(exist_ok=True)
    FRAMES_DIR.mkdir(exist_ok=True)
    updated = False

    for i, entry in enumerate(data):
        # Skip if cropped image already exists
        existing = entry.get("imageUrl", "")
        if existing and Path(PROJECT_ROOT / existing.lstrip("../")).exists():
            continue

        quotes = entry.get("quotes", [])
        if not quotes:
            continue

        urn = quotes[0].get("urn", "")
        if not urn:
            continue

        phrase = entry["phrase"]
        safe_name = re.sub(r"[^\w-]", "_", phrase)[:40]
        print(f"  [{i+1:2d}/{len(data)}] {phrase[:35]:<35s} ", end="", flush=True)

        # Step 1: get media info
        info = fetch_media_info(urn)
        if not info:
            print("no media info")
            continue

        hls_url = info.get("hlsUrl", "")
        vtt_url = info.get("vttUrl", "")
        fallback_img = info.get("imageUrl", "")

        frame_path = FRAMES_DIR / f"{date_str}_{i+1:02d}_{safe_name}.jpg"
        crop_path = CROPPED_DIR / f"{date_str}_{i+1:02d}_{safe_name}.jpg"

        got_frame = False

        # Step 2: try to extract frame at phrase timecode
        if hls_url and vtt_url:
            vtt_text = fetch_vtt(vtt_url)
            if vtt_text:
                tc = find_timecode(vtt_text, phrase)
                if tc:
                    got_frame = extract_frame(hls_url, tc, str(frame_path))
                    if got_frame:
                        print(f"frame@{tc} ", end="", flush=True)

        # Step 3: fallback to program thumbnail
        if not got_frame and fallback_img:
            try:
                img = download_image(fallback_img)
                img.save(str(frame_path), quality=90)
                got_frame = True
                print("thumbnail ", end="", flush=True)
            except Exception as e:
                print(f"img error: {e}")

        if not got_frame:
            print("no image")
            continue

        # Step 4: smart crop
        try:
            img = Image.open(str(frame_path))
            cropped = smart_crop(img)
            cropped.save(str(crop_path), quality=85)
            entry["imageUrl"] = f"../demo-data/cropped/{crop_path.name}"
            entry["frameImage"] = f"../demo-data/frames/{frame_path.name}"
            updated = True
            print("OK")
        except Exception as e:
            print(f"crop error: {e}")

    if updated:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  Updated {path.name}")


def main():
    days_file = OUTPUT_DIR / "days.json"
    days = json.loads(days_file.read_text())

    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        days = [sys.argv[1].replace("-", "")]

    for day in days:
        print(f"\n=== {day} ===")
        process_day(day)


if __name__ == "__main__":
    main()
