"""
Replace anchor/studio shots with next scene from the same story.

Logic:
1. Load all cropped images for a zeitgeist day
2. Find clusters of similar images (cosine > 0.92 on thumbnails)
3. For each cluster (=same anchor shot): keep 1, replace rest
4. For each image to replace:
   a. Get the HLS video URL + VTT timecode
   b. Starting from the original timecode, scan forward for next scene change
   c. Extract frame from next scene
   d. But stay within the same subtitle block (don't jump to next story)
   e. Smart crop the new frame
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from smart_crop import smart_crop

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "demo-data"
FRAMES_DIR = DATA_DIR / "frames"
CROPPED_DIR = DATA_DIR / "cropped"

SIMILARITY_THRESHOLD = 0.92  # images more similar than this = same anchor shot
MAX_SCENE_SEARCH_SEC = 30    # don't search more than 30s forward for next scene


def load_image_vector(path: str, size=(64, 48)) -> np.ndarray:
    """Load image, resize to thumbnail, return normalized flat vector."""
    img = Image.open(path).resize(size).convert("RGB")
    arr = np.array(img).flatten().astype(float)
    return arr / (np.linalg.norm(arr) + 1e-8)


def find_anchor_clusters(entries: list[dict]) -> list[list[int]]:
    """Find groups of entries with very similar images (anchor shots)."""
    vectors = []
    valid_indices = []

    for i, entry in enumerate(entries):
        img_path = entry.get("imageUrl", "")
        if not img_path:
            continue
        full = PROJECT_ROOT / img_path.lstrip("../")
        if not full.exists():
            continue
        vectors.append(load_image_vector(str(full)))
        valid_indices.append(i)

    if len(vectors) < 2:
        return []

    # Build similarity matrix
    vecs = np.array(vectors)
    sim_matrix = vecs @ vecs.T

    # Find clusters via greedy grouping
    used = set()
    clusters = []
    for i in range(len(vectors)):
        if i in used:
            continue
        cluster = [valid_indices[i]]
        used.add(i)
        for j in range(i + 1, len(vectors)):
            if j in used:
                continue
            if sim_matrix[i, j] >= SIMILARITY_THRESHOLD:
                cluster.append(valid_indices[j])
                used.add(j)
        if len(cluster) >= 2:
            clusters.append(cluster)

    return clusters


def extract_next_scene_frame(hls_url: str, start_tc: str, output_path: str) -> bool:
    """Extract a frame from the next scene after start_tc.

    Uses ffmpeg to grab frames every 2 seconds for 30 seconds,
    then picks the one most different from the first (=anchor) frame.
    """
    # Parse start timecode to seconds
    parts = start_tc.replace(",", ".").split(":")
    start_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    # Extract candidate frames every 2 seconds for the next 30 seconds
    tmp_dir = Path(output_path).parent / "_tmp_scenes"
    tmp_dir.mkdir(exist_ok=True)

    candidates = []
    for offset in range(2, MAX_SCENE_SEARCH_SEC + 1, 2):
        tc_sec = start_sec + offset
        tc_h = int(tc_sec // 3600)
        tc_m = int((tc_sec % 3600) // 60)
        tc_s = tc_sec % 60
        tc_str = f"{tc_h:02d}:{tc_m:02d}:{tc_s:06.3f}"

        tmp_path = tmp_dir / f"probe_{offset:02d}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", tc_str, "-i", hls_url,
                 "-frames:v", "1", "-q:v", "2", str(tmp_path)],
                capture_output=True, timeout=20,
            )
            if tmp_path.exists():
                candidates.append((offset, str(tmp_path)))
        except Exception:
            continue

    if not candidates:
        # Cleanup
        for f in tmp_dir.glob("probe_*.jpg"):
            f.unlink()
        return False

    # Load anchor frame (the one at start_tc)
    anchor_path = tmp_dir / "probe_anchor.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", start_tc, "-i", hls_url,
             "-frames:v", "1", "-q:v", "2", str(anchor_path)],
            capture_output=True, timeout=20,
        )
    except Exception:
        pass

    if anchor_path.exists():
        anchor_vec = load_image_vector(str(anchor_path))
    else:
        # Can't compare, just take frame at +6 seconds
        best_path = candidates[min(2, len(candidates) - 1)][1]
        img = Image.open(best_path)
        cropped = smart_crop(img)
        cropped.save(output_path, quality=85)
        for f in tmp_dir.glob("probe_*.jpg"):
            f.unlink()
        return True

    # Find most different frame from anchor
    best_diff = -1
    best_path = None
    for offset, path in candidates:
        vec = load_image_vector(path)
        sim = float(np.dot(anchor_vec, vec))
        diff = 1 - sim
        if diff > best_diff:
            best_diff = diff
            best_path = path

    if best_path and best_diff > 0.05:  # at least 5% different
        img = Image.open(best_path)
        cropped = smart_crop(img)
        cropped.save(output_path, quality=85)
        print(f"scene@+{best_diff:.2f} ", end="", flush=True)
        result = True
    else:
        result = False

    # Cleanup
    for f in tmp_dir.glob("probe_*.jpg"):
        f.unlink()
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    return result


def fix_day(date_str: str):
    """Fix anchor shots for one day."""
    path = DATA_DIR / f"zeitgeist_{date_str}.json"
    if not path.exists():
        print(f"No file for {date_str}")
        return

    data = json.loads(path.read_text())
    clusters = find_anchor_clusters(data)

    if not clusters:
        print(f"  No anchor clusters found")
        return

    total_to_fix = sum(len(c) - 1 for c in clusters)
    print(f"  {len(clusters)} clusters, {total_to_fix} images to replace")

    # Import fetch_media_info from pipeline
    from pipeline import _fetch_media_info, _find_timecode
    import urllib.request

    vtt_cache = {}
    updated = False

    for cluster in clusters:
        # Keep first image in cluster (highest ranked), replace rest
        for idx in cluster[1:]:
            entry = data[idx]
            quotes = entry.get("quotes", [])
            if not quotes:
                continue

            urn = quotes[0].get("urn", "")
            if not urn:
                continue

            tc = entry.get("timecode", "")
            if not tc:
                continue

            phrase = entry["phrase"]
            safe = re.sub(r"[^\w-]", "_", phrase)[:40]
            new_crop = CROPPED_DIR / f"{date_str}_{idx+1:02d}_{safe}_scene.jpg"

            print(f"  [{idx+1}] {phrase[:30]:<30s} ", end="", flush=True)

            # Get HLS URL
            info = _fetch_media_info(urn)
            hls_url = info.get("hlsUrl", "")
            if not hls_url:
                print("no HLS")
                continue

            if extract_next_scene_frame(hls_url, tc, str(new_crop)):
                entry["imageUrl"] = f"../demo-data/cropped/{new_crop.name}"
                updated = True
                print("OK")
            else:
                print("no scene change found")

    if updated:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  Updated {path.name}")


def main():
    days = json.loads((DATA_DIR / "days.json").read_text())

    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        days = [sys.argv[1].replace("-", "")]

    for day in days:
        print(f"\n=== {day} ===")
        fix_day(day)


if __name__ == "__main__":
    main()
