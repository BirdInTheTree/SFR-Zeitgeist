# Screenshots

Each grid cell shows a video frame from the story. The goal: show the *story*, not the studio.

## Peak moment

The LLM marks the most important moment of each segment — the key fact, the decisive quote, the dramatic turn. The video frame is extracted there, not at the segment start (which is typically the anchor reading the intro).

If the LLM doesn't return a peak time, a fallback computes it from the text: scanning for importance markers (names, numbers, action verbs) and picking the densest block.

## Blank detection

After extraction, the frame is checked for variance. If it's mostly uniform (black transition, solid color), we retry 5 seconds later.

## Smart crop

Frames are cropped to 4:3 (280x210) with face awareness:

1. Remove black bars (pillarbox/letterbox)
2. If a face is found: center on the largest face, keep full head with shoulders
3. If no face: zoom to 70% of the frame center for a tighter, more interesting crop
4. Resize to 280x210

The zoom for no-face images makes landscapes and b-roll shots more visually engaging — closer to the aesthetic of Jonathan Harris's 10x10 where every cell is cropped tight on the action.

## Fallback chain

1. Frame at peak_time via ffmpeg from HLS stream
2. If blank: retry at peak_time + 5 seconds
3. If no HLS: search for keyword in VTT, extract frame at that timecode
4. If nothing works: program thumbnail from Integration Layer
