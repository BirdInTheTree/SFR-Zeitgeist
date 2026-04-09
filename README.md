# SRF Zeitgeist

Proposal demo for SRF's AI and discovery teams: a topic-centric front page for the broadcast archive.

SRF's TV archive organizes content by show — Tagesschau, 10 vor 10, Schweiz aktuell. But viewers don't think in shows. They think in topics: "What happened with Artemis?" "Why is everyone talking about PFAS?" There is no way to navigate the archive by what Switzerland is actually talking about.

**SRF Zeitgeist** fills that gap. It analyzes subtitles from SRF news programs and surfaces the top trending topics as a visual 5×5 grid — one glance at what Switzerland discussed today.

The product thesis is simple: Play SRF should not only answer "which show should I watch?" It should also answer "what is Switzerland talking about right now?" This prototype demonstrates that the answer can be generated from SRF's own editorial output, without relying on click popularity.

## How it works

Every day, SRF broadcasts ~50 news programs (including re-broadcasts). Each has subtitles. Zeitgeist processes all of them:

1. **Segment** — an LLM splits each broadcast into editorial story segments, assigning a keyword and identifying the most important moment
2. **Merge** — segments from different programs are grouped into unified stories by keyword matching, with fingerprint validation to prevent false merges
3. **Score** — each story is ranked by five signals: `novelty × spread × persistence × prominence × primetime`
4. **Screenshot** — a video frame is extracted at the story's emotional peak (not the anchor intro)
5. **Display** — top 25 stories become a 5×5 grid with TV frames and source quotes

The formula automatically suppresses evergreen topics (weather, ongoing background stories) — their novelty score is ~1.0 because they appear every day. A story like "Artemis-2 launch" that spikes from 0 to 20 segments scores orders of magnitude higher.

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
demo-data/week/*.json             ← daily program schedules with subtitles
        │
        ▼
backend/v2/pipeline.py            ← LLM segmentation → merge → scoring
        │
        ├── demo-data/v2/segment_cache/   cached LLM segmentations
        ├── demo-data/v2/merge_cache/     cached story merges
        ├── demo-data/v2/artifacts/       all intermediate results
        └── demo-data/v2/story_registry.json  cross-day keyword registry
        │
        ▼
demo-data/zeitgeist_YYYYMMDD.json ← 25 stories with scores, quotes, images
        │
        ▼
frontend/                         ← vanilla HTML/CSS/JS grid viewer
```

### Key files

| File | Purpose |
|------|---------|
| `backend/v2/pipeline.py` | Main pipeline: segment → merge → score → frames → output |
| `backend/v2/segmenter.py` | LLM segmentation, keyword chaining, fingerprinting, story merge |
| `backend/v2/scorer.py` | 5-signal scoring formula |
| `backend/v2/fetch_epg.py` | Daily EPG data fetcher (accumulates history beyond API's 2-week window) |
| `backend/smart_crop.py` | Face-aware image cropping with blank detection (4:3, 280×210) |
| `frontend/app.js` | Grid rendering, fish-eye word list, zoom overlays, day navigation |

### Scoring formula

$$score(s) = novelty \times spread \times persistence \times prominence \times primetime$$

| Signal | Formula | What it measures |
|--------|---------|-----------------|
| novelty | $(N_{today} + 1) / (\overline{N}_{prev7} + 1)$ | Spike vs 7-day baseline |
| spread | $1 + \log_2(1 + U_{today})$ | How many editorial desks covered it |
| persistence | $1 + \log_2(1 + N_{today})$ | How often the story returned today |
| prominence | $1 + \log_2(1 + M_{today}/60)$ | Total segment airtime in minutes |
| primetime | $1 + 0.25 \times tier$ | Evening prime time presence (0/1/2) |

Re-broadcasts contribute through log-dampened persistence and prominence — editorial decisions to keep airing a story are a signal, but logarithms prevent linear inflation.

See [backend/v2/README.md](backend/v2/README.md) for full formula rationale.

## Why it matters for SRF

- **Better archive discovery** — users can enter through the topic of the day, not only through a show brand they already know.
- **Editorially grounded ranking** — the homepage reflects what SRF journalists are covering across formats, not what already won the click race.
- **Low-friction extension** — the prototype uses SRF's existing schedule, subtitle, and media APIs; no new publishing workflow is required.
- **Strong demo signal** — it combines product thinking, applied NLP, and a distinct visual treatment into one concrete proposal.

## Current demo corpus

- **3 daily snapshots** with full v2 pipeline (`2026-03-30` to `2026-04-01`)
- **~50 news programs per day** from SRF's broadcast schedule
- **~35 stories per day** after LLM segmentation and merge
- **100% image coverage** — every story has a video frame
- **Cross-day story tracking** — 27 stories persist across multiple days
- **EPG data available** for `2026-03-05` to `2026-04-09` (28 days)

## Running

**Prerequisites:** Python 3.13, ffmpeg, Anthropic API key in `.env`

```bash
source ~/venvs/SFR_env/bin/activate

# Fetch latest EPG data (run weekly to accumulate history)
python -m backend.v2.fetch_epg --range 14

# Generate zeitgeist for a specific date (with images)
python -m backend.v2.pipeline 2026-04-01

# Generate all available days
python -m backend.v2.pipeline --all

# Serve frontend
python -m http.server 8080
# Open http://localhost:8080/frontend/
```

## What this demonstrates

This is a proposal demo for SRF's National AI Service Team. It shows:

1. **Topic-centric navigation** — an alternative to the current show-centric Play SRF archive
2. **SRF data literacy** — built on real EPG + Integration Layer APIs, not hypothetical
3. **Methodological rigor** — spike detection from corpus linguistics, not vibes
4. **Production-shaped judgment** — ranking, deduplication, quotes, and image retrieval are wired into a usable interface
5. **Visual impact** — one screen tells the story of the day

The underlying question: *what if Play SRF had a "trending" page — not based on clicks, but on what the journalists themselves are covering?*

## Current limitations

- The demo is based on pre-generated daily snapshots, not a live continuously updated service.
- Image coverage is incomplete for some topics, especially when no usable frame can be extracted.
- The ranking pipeline is tuned for German-language SRF news subtitles and has not yet been validated with user testing.
- This repository focuses on the proposal and the prototype, not on deployment infrastructure.

## Key design decisions

- **Story-level, not phrase-level** — LLM segments broadcasts into editorial stories. This solves the fundamental problem of phrase-based approaches: "Kanton Bern" vs "Berner Regierung" vs "Regierungsratswahlen Bern" are all the same story.
- **Keyword chaining** — broadcasts are processed chronologically. Each LLM call receives keywords from earlier broadcasts, so it reuses the same keyword for the same story across programs.
- **Repeats count, through logarithm** — re-broadcasts aren't excluded. An editor keeping a story in the 19:30 re-airing is a signal. But 5 re-airings don't count as 5× importance — logarithmic dampening handles this.
- **Peak-time screenshots** — the LLM identifies the most important moment in each segment. The screenshot is taken there, not at the start (which is typically the anchor in studio).
- **Canonical story registry** — cross-day keyword consistency via fingerprint matching. "Muriel Furrer Untersuchung" on day 1 keeps the same keyword on day 2.

## References

- Jonathan Harris, [10×10](https://jjh.org/10x10) (2004) — original inspiration
- Google, [Year in Search Data Methodology](https://trends.withgoogle.com/year-in-search/data-methodology/)
- GDELT, [Television News Ngram 2.0](https://blog.gdeltproject.org/announcing-the-television-news-ngram-2-0-dataset/)
- Scott (1997) — keyness in corpus linguistics
- Boutaleb et al. (2024), [BERTrend](https://arxiv.org/abs/2411.05930) — temporal trend detection
- Ben Mansour et al. (2025) — LLM vs traditional keyword extraction
