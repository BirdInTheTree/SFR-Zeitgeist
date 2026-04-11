"""Smart crop for SRF Zeitgeist grid images.

Rules:
1. Remove pillarbox/letterbox (black bars)
2. Find faces → center crop on largest face, keep full head
3. No face → center on lower 60% (TV action area)
4. Target ratio: 4:3
5. Never cut heads, never cut text
6. Resize to 280x210
"""

import io
import urllib.request
import numpy as np
from PIL import Image

try:
    import face_recognition
    HAS_FACE = True
except ImportError:
    HAS_FACE = False


def download_image(url):
    """Download image from URL, return PIL Image."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


def remove_black_bars(img):
    """Remove pillarbox (vertical) and letterbox (horizontal) black bars."""
    arr = np.array(img)
    brightness = arr.mean(axis=2)  # average of RGB per pixel
    h, w = brightness.shape

    # Find left/right bars (columns where >90% pixels are dark)
    col_brightness = brightness.mean(axis=0)
    left = 0
    right = w
    for i in range(w // 4):  # check up to 25% from each side
        if col_brightness[i] < 20:
            left = i + 1
        else:
            break
    for i in range(w - 1, w - w // 4, -1):
        if col_brightness[i] < 20:
            right = i
        else:
            break

    # Find top/bottom bars
    row_brightness = brightness.mean(axis=1)
    top = 0
    bottom = h
    for i in range(h // 4):
        if row_brightness[i] < 20:
            top = i + 1
        else:
            break
    for i in range(h - 1, h - h // 4, -1):
        if row_brightness[i] < 20:
            bottom = i
        else:
            break

    if left > 0 or right < w or top > 0 or bottom < h:
        img = img.crop((left, top, right, bottom))

    return img


def find_focal_point(img):
    """Find the best focal point: face center or lower-center fallback."""
    w, h = img.size

    if HAS_FACE:
        # Downscale for speed
        scale = 1.0
        if max(w, h) > 800:
            scale = 800 / max(w, h)
            small = img.resize((int(w * scale), int(h * scale)))
        else:
            small = img

        faces = face_recognition.face_locations(np.array(small))

        if faces:
            # Pick the largest face (by area)
            largest = max(faces, key=lambda f: (f[2] - f[0]) * (f[1] - f[3]))
            top, right, bottom, left = largest

            # Scale back to original coordinates
            cx = int((left + right) / 2 / scale)
            cy = int((top + bottom) / 2 / scale)
            face_h = int((bottom - top) / scale)

            return cx, cy, face_h

    # Fallback: lower 45% center (TV action area)
    return w // 2, int(h * 0.45), 0


def is_blank(img, threshold=500) -> bool:
    """Check if image is mostly uniform (blank, black, or solid color)."""
    arr = np.array(img)
    # Sample 1000 pixels for speed
    flat = arr.reshape(-1, 3)
    sample = flat[::max(1, len(flat) // 1000)]
    avg = sample.mean(axis=0)
    var = ((sample - avg) ** 2).sum(axis=1).mean()
    return var < threshold


def smart_crop(img, target_ratio=4/3, target_w=280, target_h=210):
    """Crop image to target ratio, centered on focal point.

    Args:
        img: PIL Image to crop.
        target_ratio: width/height ratio for the crop (default 4:3).
        target_w: output width in pixels (default 280, matches frontend grid cell).
        target_h: output height in pixels (default 210, matches frontend grid cell).

    When no face is found, zooms in to ~70% of the frame to make
    details more prominent (inspired by Jonathan Harris's 10x10 aesthetic).
    """
    # Step 1: remove black bars
    img = remove_black_bars(img)
    w, h = img.size

    # Step 2: find focal point
    cx, cy, face_h = find_focal_point(img)

    # Step 3: if face found, ensure head + context visible
    # Crop should include at least 2x face height for context (shoulders, gestures)
    # If no face, zoom in to 70% of frame for visual interest
    if face_h > 0:
        min_crop_h = max(face_h * 2.5, h * 0.4)
    else:
        # No face → zoom into center 70% for tighter, more interesting crop
        min_crop_h = h * 0.7

    # Step 4: compute crop box for target ratio
    current_ratio = w / h

    if current_ratio > target_ratio:
        # Too wide → crop width, keep full height (or min_crop_h)
        crop_h = max(int(min_crop_h), h)
        crop_h = min(crop_h, h)
        crop_w = int(crop_h * target_ratio)
        crop_w = min(crop_w, w)

        # Center horizontally on focal point
        left = max(0, min(cx - crop_w // 2, w - crop_w))
        # Center vertically on focal point
        top = max(0, min(cy - crop_h // 2, h - crop_h))
    else:
        # Too tall → crop height, keep full width
        crop_w = w
        crop_h = int(crop_w / target_ratio)
        crop_h = min(crop_h, h)

        # Center vertically on focal point
        top = max(0, min(cy - crop_h // 2, h - crop_h))
        left = 0

    # If face found, ensure full head visible with generous margin
    if face_h > 0:
        face_top_orig = cy - face_h // 2
        # Head with hair ≈ 1.3x face_h. Add 1x face_h above for safety.
        head_margin = int(face_h * 1.2)
        desired_top = face_top_orig - head_margin
        if top > desired_top:
            top = max(0, desired_top)
        # Also ensure bottom of crop captures at least shoulders
        # Face should be in upper 40% of crop, not dead center
        face_in_crop = cy - top
        ideal_face_pos = crop_h * 0.35  # face at 35% from top
        if face_in_crop > ideal_face_pos + face_h:
            # Face too low in crop — shift crop down
            shift = int(face_in_crop - ideal_face_pos)
            top = min(top + shift, h - crop_h)
            top = max(0, top)

    crop_box = (left, top, left + crop_w, top + crop_h)
    cropped = img.crop(crop_box)

    # Step 5: resize
    thumb = cropped.resize((target_w, target_h), Image.LANCZOS)
    return thumb


def process_image(url, output_path):
    """Download, smart crop, save."""
    img = download_image(url)
    thumb = smart_crop(img)
    thumb.save(output_path, quality=85)
    return thumb.size


if __name__ == "__main__":
    # Test
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://download-media.srf.ch/world/image/default/2026/03/imported-image-4603249219222345772.jpg"
    process_image(url, "test_crop.jpg")
    print("Done")
