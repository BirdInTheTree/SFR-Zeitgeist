# SRF Zeitgeist

"What happened with Artemis?"
"Why is everyone talking about PFAS?"
"Has Italy qualified?"

Viewers think in topics. 
TV content is organized by programs.

Zeitgeist shows 49 words that capture what Switzerland's news talked about this week. 
Each word is a story. 
Each story has a video frame from its most important moment. 
Click — and you see what's been reported.

## How it works

Every day, SRF broadcasts ~50 news programs (including repeats). We process the subtitles of each broadcast:

1. **Segment** — an LLM reads each program's VTT subtitles and splits them into *segments* — individual news topics within a broadcast. Each segment gets a keyword and a peak moment timestamp. (see [prompts](docs/prompts/segment.md))
2. **Merge** — segments about the same topic from different programs are grouped into *stories*. One story = one topic, even if covered by Tagesschau, 10 vor 10, and Schweiz aktuell. Matching uses keywords + text fingerprints to prevent false merges.
3. **Score** — each story is ranked by five signals: `novelty × spread × persistence × prominence × primetime` (see [scoring](docs/scoring.md))
4. **Screenshot** — a video frame is extracted at the segment's peak moment (see [screenshots](docs/screenshots.md))
5. **Display** — top 49 stories become a 7×7 grid with TV frames and source quotes

## The grid

Each cell gives the user two cues — a video frame and a keyword. Together they work as [*information scent*](https://global.oup.com/academic/product/9780195173321) (Pirolli, 2007) — the viewer answers "is this story for me?" in a fraction of a second.

- **Hover** a cell → keyword appears, matching word lights up in the sidebar
- **Hover** a word → matching cell highlights
- **Click** → quotes from each program + "Watch on Play SRF" links
- **Arrow keys** → navigate between weeks

The word list uses a fish-eye effect: the active word is large and red, neighbors shrink into dust-grey.

Each keyword appears only once — 49 different stories per week.

Inspired by Jonathan Harris's [10×10](https://web.archive.org/web/20050227035405/http://www.tenbyten.org/info.html) (2004) — "100 words and pictures that capture the world right now."
## Scoring

$$score = novelty \times spread \times persistence \times prominence \times primetime$$

Five signals multiplied. A story needs all five to rank high. Evergreen topics suppress themselves — weather appears every day, so novelty stays at ~1.0. A spike like "Artemis launch" scores orders of magnitude higher.

Details and references: [docs/scoring.md](docs/scoring.md)

## Keywords

The keyword must work as a trigger word ([Pirolli, 2007](#references)) — one glance and you know the story. Proper nouns preferred. Max 2 words.

Broadcasts are processed chronologically. Each LLM call receives yesterday's top keywords and all keywords from earlier broadcasts today — so the same story keeps the same keyword across programs and days. A story registry with text fingerprints keeps keywords stable over time.

Details: [docs/keywords.md](docs/keywords.md)

## Screenshots

The LLM marks the *peak moment* of each segment — the most specific or climactic point in the story. The video frame is grabbed there, not at the beginning. Blank frames are retried 5 seconds later. No-face frames are zoomed tighter.

Details: [docs/screenshots.md](docs/screenshots.md)

## Data sources

| API | What it gives us | Auth |
|-----|-----------------|------|
| EPG (`/tv-program-guide`) | Daily program schedule (~150 programs) | None |
| Integration Layer 2.1 (`/mediaComposition/byUrn`) | Subtitles (VTT), video streams (HLS), images | API key |

Subtitles exist for ~70% of news programs. We process only the **Nachrichten** (news) genre. The EPG API keeps only ~2 weeks of data — we fetch daily to accumulate history.

## Architecture

```
demo-data/week/*.json             ← daily schedules with subtitles
        │
backend/pipeline.py            ← segment → merge → score → frames
        │
        ├── demo-data/cache/segments/      LLM segmentation results
        ├── demo-data/cache/merge/         story merge results
        └── demo-data/story_registry.json  cross-day story tracking
        │
demo-data/zeitgeist_YYYYMMDD.json ← output for frontend
        │
frontend/                         ← vanilla HTML/CSS/JS
```

| File | What it does |
|------|-------------|
| `backend/pipeline.py` | Orchestrates: segment → merge → score → frames → output |
| `backend/segmenter.py` | LLM calls, keyword chaining, fingerprinting, story merge |
| `backend/scorer.py` | Five-signal scoring formula |
| `backend/fetch_epg.py` | Fetches daily program data from EPG API |
| `backend/smart_crop.py` | Face-aware image cropping, blank detection |
| `frontend/app.js` | Grid, fish-eye word list, zoom overlay, week navigation |
| `docs/prompts/` | LLM prompts (source of truth — code loads from these files) |

## Running

```bash
pip install -r requirements.txt

# Fetch EPG data (run regularly to accumulate history)
python -m backend.fetch_epg --range 14

# Generate one day (with images)
python -m backend.pipeline 2026-04-01

# Generate all available days
python -m backend.pipeline --all

# Serve
python -m http.server 8080
# Open http://localhost:8080/frontend/
```

## What's next

- **Story lifecycle view** — how stories live and die across days. Timeline bars or metro map ([Shahaf et al., 2012](#references)). Data already exists in story registry.
- **Editorial override** — let a human pin, boost, or hide stories. The grid is algorithmic; the judgment should be editorial.

## References

- Pirolli, P., [*Information Foraging Theory*](https://global.oup.com/academic/product/9780195173321), Oxford, 2007
- McCombs, M. E. & Shaw, D. L., ["The Agenda-Setting Function of Mass Media"](https://doi.org/10.1086/267990), *Public Opinion Quarterly*, 1972
- Boutaleb, A. et al., [BERTrend: Neural Topic Modeling for Emerging Trends Detection](https://arxiv.org/abs/2411.05930), 2024
- Harris, J., [10×10](https://jjh.org/10x10), 2004
- Shahaf, D., Guestrin, C. & Horvitz, E., ["Metro Maps of Science"](https://doi.org/10.1145/2339530.2339705), *KDD*, 2012
- Thomas, J. J. & Cook, K. A. (Eds.), [*Illuminating the Path*](https://ils.unc.edu/courses/2017_fall/inls641_001/books/RD_Agenda_VisualAnalytics.pdf), IEEE, 2005
- Keith, B., ["Interactive Narrative Analytics"](https://doi.org/10.1109/ACCESS.2025.3630352), *IEEE Access*, 2026
