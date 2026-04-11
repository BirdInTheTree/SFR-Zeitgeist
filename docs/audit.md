# SFR Zeitgeist — Audit

Date: 2026-04-11

## What works well

- **Scoring formula** (`scorer.py`) — clean pure functions, well-documented theory
- **Pipeline resumability** — caching at every stage (VTT, segmentation, merge)
- **Separation of concerns** — each module does one thing: `fetch_epg` (data), `segmenter` (LLM + text), `scorer` (math), `pipeline` (orchestration), `smart_crop` (images)
- **Keyword chaining** — broadcasts processed chronologically, LLM reuses keywords
- **Code-based merging** — deterministic text fingerprints, no LLM needed
- **Documentation** — four docs in `docs/` explaining design decisions with rationale

## Critical

### C1. No dependency management

No `requirements.txt`. Project imports `anthropic`, `python-dotenv`, `Pillow`, `numpy`, `face_recognition` and uses `ffmpeg` — none declared.

**Fix:** Add `requirements.txt`.

### C2. No tests

Zero test files. Scoring formula, fingerprint matching, VTT parsing are all testable pure functions.

**Fix:** Add tests for `scorer.py`, `compute_fingerprint`, `parse_vtt`, `merge_segments_into_stories`.

### C3. No Anthropic API retry logic

`segmenter.py` — new `anthropic.Anthropic()` client per call, zero retry. A single API hiccup silently skips the broadcast.

**Fix:** Create client once, use `max_retries` parameter.

### C4. XSS via innerHTML

`app.js` — `kw.phrase` from LLM output injected as raw HTML.

**Fix:** Use `textContent` on child spans.

### C5. No keyboard accessibility

Grid cells are `<div>` with click handlers but no `role`, `tabindex`, or `aria-label`.

**Fix:** Add `role="button"`, `tabindex="0"`, keydown handler.

### C6. No mobile support

Zero `@media` queries. `overflow: hidden` on body. Acceptable for desktop demo but should degrade gracefully.

## Important

### I1. Silent exception swallowing

`fetch_epg.py` — bare `except Exception` blocks return empty results with no logging.

**Fix:** Add `logger.warning`.

### I2. `fetch_frames()` too long

~130 lines handling media URLs, ffmpeg, blank detection, VTT fallback, thumbnail fallback, smart crop.

**Fix:** Extract each fallback into a function.

### I3. `import anthropic` inside function bodies

Core dependency hidden as lazy import. If not installed, error appears at runtime.

**Fix:** Import at module top.

### I4. `dates[0]` crashes on empty list

`pipeline.py` batch mode — `IndexError` if no processable days.

**Fix:** Guard with `if not dates: return`.

### I5. Story registry grows without bounds

No pruning. Old entries may cause false matches.

**Fix:** Add TTL (decide what to do with entries older than 14 days).

### I6. `fetch_epg.py` not incremental

Downloads subtitles for ALL programs before saving. Kill at program 150/200 = no data saved.

**Fix:** Write after each program.

### I7. No focus trap on overlays

Zoom/fullscreen/about overlays don't trap focus. Tab navigates behind them.

### I8. No loading/error state for day navigation

If fetch fails, grid shows empty cells. No feedback.

**Fix:** Show loading indicator or error message.

### I9. Doc threshold mismatch

`keywords.md` says merge needs "2 shared top-words or 2 shared entities." Code uses different thresholds.

**Fix:** Update docs to match code.

## Minor

| # | Issue |
|---|-------|
| M1 | Duplicate words in stopwords list |
| M2 | No docstrings on `smart_crop()` parameters |
| M3 | `import copy` and `import re` inside function bodies |
| M4 | No rate limiting on EPG API calls |
| M5 | Unused CSS classes (`.cell.empty`, `.load-error`) |
| M6 | `formatDay()` defined but never called in `app.js` |
| M7 | ArrowLeft/Right `preventDefault()` breaks text selection |
| M8 | Spread signal has low variance (most stories score 2.0 or 2.58) |
| M9 | Registry entity/word lists capped alphabetically, not by frequency |
| M10 | Summary generation not cached |

## Action plan

### Before demo

1. Add `requirements.txt`
2. Fix XSS in `app.js` (use `textContent`)
3. Fix docs threshold mismatch

### Before sharing

4. Add unit tests for `scorer.py` and fingerprint logic
5. Add API retry logic
6. Add loading/error states in frontend
7. Prune story registry (TTL)

### Nice to have

8. Keyboard accessibility
9. Mobile responsiveness
10. Refactor `fetch_frames()` into smaller functions
11. Cache summaries
