# SRF Zeitgeist

Proposal demo for SRF's AI and discovery teams: a topic-centric front page for the broadcast archive.

SRF's TV archive organizes content by show — Tagesschau, 10 vor 10, Schweiz aktuell. But viewers don't think in shows. They think in topics: "What happened with Artemis?" "Why is everyone talking about PFAS?" There is no way to navigate the archive by what Switzerland is actually talking about.

**SRF Zeitgeist** fills that gap. It analyzes subtitles from SRF news programs and surfaces the top trending topics as a visual 7×7 grid — one glance at what Switzerland discussed today.

The product thesis is simple: Play SRF should not only answer "which show should I watch?" It should also answer "what is Switzerland talking about right now?" This prototype demonstrates that the answer can be generated from SRF's own editorial output, without relying on click popularity.

## How it works

Every day, SRF broadcasts ~50 news programs (including re-broadcasts). Each has subtitles. Zeitgeist processes all of them:

1. **Extract** — spaCy pulls noun phrases and named entities from German subtitle text
2. **Compare** — each phrase's frequency today is compared to a 7-day baseline (the "spike")
3. **Filter** — phrases are ranked by spike and then cleaned up with deduplication plus an LLM quality gate
4. **Rank** — `score = spike × log₂(program_count)` balances novelty with breadth
5. **Display** — top 49 phrases become a 7×7 grid with TV frames and source quotes

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
spike = frequency_today / average_frequency_7_days
score = spike × log₂(program_count)
```

**Editorial signal and cleanup**:
- variant broadcasts collapse into one editorial unit: "Tagesschau" and "Tagesschau in Gebärdensprache" count as the same desk
- near-duplicate phrases are removed with substring, semantic, and story-level deduplication
- an LLM quality gate removes generic or non-topical leftovers before the final grid is rendered

**NLP**: spaCy `de_core_news_md` — noun chunks + named entities (PER, ORG, LOC, GPE). Lemmatized. Junk from subtitle metadata (SWISS TXT headers) is filtered.

## Why it matters for SRF

- **Better archive discovery** — users can enter through the topic of the day, not only through a show brand they already know.
- **Editorially grounded ranking** — the homepage reflects what SRF journalists are covering across formats, not what already won the click race.
- **Low-friction extension** — the prototype uses SRF's existing schedule, subtitle, and media APIs; no new publishing workflow is required.
- **Strong demo signal** — it combines product thinking, applied NLP, and a distinct visual treatment into one concrete proposal.

## Current demo corpus

- **12 daily snapshots** in the current demo build (`2026-03-19` to `2026-04-01`)
- **1,172 programs** ingested from the saved archive window, including **541 news programs**
- **3.55M subtitle words** processed across the available dataset
- **255 surfaced topics**, with **206 topics carrying imagery** (80.8% coverage)
- **848 linked source quotes**, or **3.33 quotes per topic** on average
- **LLM quality gate pass rate: 35.7%** (`940 / 2632` candidates kept)

See [EVALUATION.md](EVALUATION.md) for the measurement notes and caveats.

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
4. **Production-shaped judgment** — ranking, deduplication, quotes, and image retrieval are wired into a usable interface
5. **Visual impact** — one screen tells the story of the day

The underlying question: *what if Play SRF had a "trending" page — not based on clicks, but on what the journalists themselves are covering?*

## Current limitations

- The demo is based on pre-generated daily snapshots, not a live continuously updated service.
- Image coverage is incomplete for some topics, especially when no usable frame can be extracted.
- The ranking pipeline is tuned for German-language SRF news subtitles and has not yet been validated with user testing.
- This repository focuses on the proposal and the prototype, not on deployment infrastructure.

## V3 Direction

The next pipeline version moves from phrase ranking to story ranking.

Instead of extracting keywords first and deduplicating later, `backend/v3/` will:

1. load raw VTT subtitles for news programs only
2. ask an LLM to segment each broadcast into editorial story segments
3. assign one keyword per segment and mark exact carry-over segments from the previous episode
4. merge matching stories across programs
5. rank stories, not phrases
6. find the first mention of the winning keyword in the earliest segment and extract the frame there

The story-level score is:

$$
score(s) = novelty(s) \times spread(s) \times persistence(s) \times prominence(s)
$$

with:

$$
novelty(s)=\frac{N_{today}(s)+\alpha}{\overline{N}_{prev7}(s)+\alpha}
$$

$$
spread(s)=1+\log_2(1+U_{today}(s))
$$

$$
persistence(s)=1+\log_2(1+N_{today}(s))
$$

$$
prominence(s)=1+\log_2\left(1+\frac{M_{today}(s)}{60}\right)
$$

where:

- $N_{today}(s)$ = number of segments assigned to story $s$ today
- $\overline{N}_{prev7}(s)$ = average number of segments assigned to story $s$ over the previous 7 days
- $U_{today}(s)$ = number of distinct programs that carry story $s$ today
- $M_{today}(s)$ = total duration in seconds of story segments assigned to $s$ today
- $\alpha$ = smoothing constant, typically 1

This design keeps repeated coverage as an editorial signal, but prevents repeated broadcasts from dominating linearly: repetition increases the score through persistence and screen time, while cross-program presence increases spread.

## References

- Jonathan Harris, [10×10](https://jjh.org/10x10) (2004) — original inspiration
- Google, [Year in Search Data Methodology](https://trends.withgoogle.com/year-in-search/data-methodology/)
- GDELT, [Television News Ngram 2.0](https://blog.gdeltproject.org/announcing-the-television-news-ngram-2-0-dataset/)
- Scott (1997) — keyness in corpus linguistics
- Boutaleb et al. (2024), [BERTrend](https://arxiv.org/abs/2411.05930) — temporal trend detection
- Ben Mansour et al. (2025) — LLM vs traditional keyword extraction
