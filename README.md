# SRF Zeitgeist

SRF's TV archive organizes content by show — Tagesschau, 10 vor 10, Schweiz aktuell. But viewers don't think in shows. They think in topics: "What happened with Artemis?" "Why is everyone talking about PFAS?" There is no way to navigate the archive by what Switzerland is actually talking about.

**SRF Zeitgeist** fills that gap. It analyzes subtitles from SRF news programs and surfaces the top trending topics as a visual 6×6 grid — one glance at what Switzerland discussed today.

## How it works

Every day, SRF broadcasts ~50 news programs (including re-broadcasts). Each has subtitles. Zeitgeist processes all of them:

1. **Extract** — spaCy pulls noun phrases and named entities from German subtitle text
2. **Compare** — each phrase's frequency today is compared to a 14-day baseline (the "spike")
3. **Filter** — only phrases appearing in ≥2 different programs survive (agenda-setting: if multiple shows cover it, it matters)
4. **Rank** — `score = spike × log₂(program_count)` balances novelty with breadth
5. **Display** — top 36 phrases become a 6×6 grid with TV frames and source quotes

The spike mechanism automatically suppresses evergreen words ("Schweiz", "heute") without a manual stoplist — they appear every day, so their spike is ~1.0. A phrase like "Artemis-2-Mission" that jumps from 0 to 20 mentions scores orders of magnitude higher.

## The grid

Inspired by Jonathan Harris's [10×10](https://web.archive.org/web/20050227035405/http://www.tenbyten.org/info.html) (2004), which captured "the world right now" from news photos and headlines.

- **Hover** a cell → the phrase appears, the matching word highlights in the sidebar
- **Hover** a word → the matching cell highlights in the grid
- **Click** → zoom view with quotes from each program + links to Play SRF
- **Arrow keys** → navigate between days

The word list uses a fish-eye effect: the active word is large and red, neighbors shrink progressively into dust-grey.

## Data source

All data comes from SRF's public APIs:

| API | What it provides | Auth |
|-----|-----------------|------|
| EPG (`/tv-program-guide`) | Daily program schedule (~158 programs) | None |
| Integration Layer 2.1 (`/mediaComposition/byUrn`) | Subtitles (VTT), video streams, images | API key |

Subtitles are available for ~75% of programs. The pipeline processes only the **Nachrichten** (news) genre — including re-broadcasts, which amplify the signal of important topics.

## Architecture

```
demo-data/week/*.json          ← pre-fetched programs with cleaned subtitles
        │
        ▼
backend/pipeline.py            ← spaCy extraction → keyness → ranking
        │
        ▼
demo-data/zeitgeist_YYYYMMDD.json  ← 36 phrases with scores, quotes, images
        │
        ▼
frontend/                      ← vanilla HTML/CSS/JS grid viewer
```

### Key files

| File | Purpose |
|------|---------|
| `backend/pipeline.py` | Main pipeline: extract phrases, compute spike, rank, output JSON |
| `backend/fetch_images.py` | Extract video frames at phrase timecodes via ffmpeg + smart crop |
| `backend/smart_crop.py` | Face-aware image cropping (4:3, 280×210) |
| `frontend/app.js` | Grid rendering, hover/click interactions, day navigation |
| `frontend/style.css` | Layout, fish-eye typography, zoom overlays |

### Algorithm detail

**Spike detection** (based on [Google Trends methodology](https://trends.withgoogle.com/year-in-search/data-methodology/)):

```
spike = frequency_today / average_frequency_14_days
score = spike × log₂(program_count)
```

**Multi-source filter** (based on [agenda-setting theory](https://en.wikipedia.org/wiki/Agenda-setting_theory)):
a phrase must appear in ≥2 distinct editorial units. "Tagesschau" and "Tagesschau in Gebärdensprache" count as one unit (same content).

**NLP**: spaCy `de_core_news_md` — noun chunks + named entities (PER, ORG, LOC, GPE). Lemmatized. Junk from subtitle metadata (SWISS TXT headers) is filtered.

## Running

**Prerequisites:** Python 3.13, spaCy with `de_core_news_md`, ffmpeg

```bash
# Activate virtual environment
source ~/venvs/SFR_env/bin/activate

# Generate zeitgeist for a specific date
python backend/pipeline.py 2026-04-01

# Generate all available days
python backend/pipeline.py --all

# Fetch video frame images
python backend/fetch_images.py --all

# Serve frontend
python -m http.server 8080
# Open http://localhost:8080/frontend/
```

## What this demonstrates

This is a proposal demo for SRF's National AI Service Team. It shows:

1. **Topic-centric navigation** — an alternative to the current show-centric Play SRF archive
2. **SRF data literacy** — built on real EPG + Integration Layer APIs, not hypothetical
3. **Methodological rigor** — spike detection from corpus linguistics, not vibes
4. **Visual impact** — one image tells the story of the day

The underlying question: *what if Play SRF had a "trending" page — not based on clicks, but on what the journalists themselves are covering?*

## References

- Jonathan Harris, [10×10](https://jjh.org/10x10) (2004) — original inspiration
- Google, [Year in Search Data Methodology](https://trends.withgoogle.com/year-in-search/data-methodology/)
- GDELT, [Television News Ngram 2.0](https://blog.gdeltproject.org/announcing-the-television-news-ngram-2-0-dataset/)
- Scott (1997) — keyness in corpus linguistics
- Boutaleb et al. (2024), [BERTrend](https://arxiv.org/abs/2411.05930) — temporal trend detection
- Ben Mansour et al. (2025) — LLM vs traditional keyword extraction
