# SRF Zeitgeist

A topic-centric page for the broadcast archive.

Viewers think in topics.
TV content is organized by program.
Telesguard. Schweiz aktuell. 10 vor 10.
"What happened with Artemis?"
"Why is everyone talking about PFAS?"
"Has Italy qualified?"

5×5 is a way to navigate SRF's recent news archive by topics.

## How it works

Every day, SRF broadcasts ~50 news programs (including repeated broadcasts). We process the subtitles of each broadcast:

1. **Segment** — an LLM splits each broadcast into editorial story segments, assigning a keyword and identifying the most important moment (see [prompt](backend/segmenter.py), [output format](demo-data/artifacts/))
2. **Merge** — same segments from different broadcasts are grouped into unified stories by keyword matching, with fingerprint validation to prevent false merges
3. **Score** — each story is ranked by five signals: `novelty × spread × persistence × prominence × primetime` (see [formula](#scoring))
4. **Screenshot** — a video frame is extracted at the story's emotional peak (see [screenshots](#screenshots))
5. **Display** — top 25 stories become a 5×5 grid with TV frames and source quotes

## Product decisions

### The grid

Inspired by Jonathan Harris's [10×10](https://web.archive.org/web/20050227035405/http://www.tenbyten.org/info.html) (2004) — "100 words and pictures that capture the world right now."

The grid works because of *information scent* ([Pirolli, 2007](#references)): each cell gives the user two cues — a video frame (visual trigger) and a keyword (textual trigger). Together they answer "is this story for me?" in a fraction of a second.

- **Hover** a cell → keyword appears, matching word lights up in the sidebar
- **Hover** a word → matching cell highlights
- **Click** → quotes from each program + "Watch on Play SRF" links
- **Arrow keys** → navigate between days

The word list uses a fish-eye effect: the active word is large and red, neighbors shrink into dust-grey.

### [Scoring](docs/scoring.md)

$$score = novelty \times spread \times persistence \times prominence \times primetime$$

Five signals multiplied. A story needs all five to rank high. Evergreen topics suppress themselves — weather appears every day, so novelty stays at ~1.0. A spike like "Artemis launch" scores orders of magnitude higher.

### [Screenshots](docs/screenshots.md)

The LLM marks the *peak moment* of each segment — the key fact, the decisive quote. The video frame is grabbed there, not at the anchor intro. Blank frames are retried. No-face frames are zoomed tighter.

### [Keywords](docs/keywords.md)

The keyword must work as a trigger word ([Pirolli, 2007](#references)) — one glance and you know the story. Use proper nouns. Max 2 words. No nicknames. Broadcasts are processed chronologically with keyword chaining so the LLM reuses keywords across programs. A canonical registry keeps keywords stable across days.

## Data and architecture

### Data sources

| API | What it gives us | Auth |
|-----|-----------------|------|
| EPG (`/tv-program-guide`) | Daily program schedule (~158 programs) | None |
| Integration Layer 2.1 (`/mediaComposition/byUrn`) | Subtitles (VTT), video streams, images | API key |

Subtitles exist for ~75% of programs. We process only the **Nachrichten** (news) genre.

The EPG API keeps only ~2 weeks of data. We fetch and save it to build history beyond that window.

### Pipeline

```
demo-data/week/*.json             ← daily schedules with subtitles
        │
backend/pipeline.py            ← segment → merge → score → frames
        │
        ├── demo-data/cache/segments/      LLM segmentation results
        ├── demo-data/cache/merge/         story merge results
        ├── demo-data/artifacts/           all intermediate results
        └── demo-data/story_registry.json
        │
demo-data/zeitgeist_YYYYMMDD.json ← output for frontend
        │
frontend/                         ← vanilla HTML/CSS/JS
```

### Key files

| File | What it does |
|------|-------------|
| `backend/pipeline.py` | Orchestrates everything: segment → merge → score → frames → output |
| `backend/segmenter.py` | LLM prompts, keyword chaining, fingerprinting, story merge |
| `backend/scorer.py` | The five-signal scoring formula |
| `backend/fetch_epg.py` | Fetches daily program data from EPG API |
| `backend/smart_crop.py` | Face-aware image cropping, blank detection, zoom |
| `frontend/app.js` | Grid, fish-eye word list, zoom overlay, day navigation |

### Running

```bash
source ~/venvs/SFR_env/bin/activate

# Fetch EPG data (run weekly to accumulate history)
python -m backend.fetch_epg --range 14

# Generate one day (with images)
python -m backend.pipeline 2026-04-01

# Generate all available days
python -m backend.pipeline --all

# Serve
python -m http.server 8080
# Open http://localhost:8080/frontend/
```

### Current demo

- 3 daily snapshots (`2026-03-30` to `2026-04-01`)
- ~50 news programs per day, ~35 stories after merge
- 100% image coverage
- 27 stories persist across multiple days
- EPG data for 28 days (`2026-03-05` to `2026-04-09`)

## What's next

- **Story lifecycle view** — how stories live and die across days. Timeline bars or metro map ([Shahaf et al., 2012](#references)). Data already exists in story registry.
- **Baseline** — run more days so novelty can distinguish breaking news from ongoing background.
- **Editorial override** — let a human pin, boost, or hide stories. The grid is algorithmic; the judgment should be editorial.
- **Better screenshots** — avoid duplicate anchor shots across different stories. Try alternate programs when the first frame is a studio shot.

## References

- Thomas, J. J. & Cook, K. A. (Eds.), [*Illuminating the Path*](https://ils.unc.edu/courses/2017_fall/inls641_001/books/RD_Agenda_VisualAnalytics.pdf), IEEE, 2005
- Pirolli, P., [*Information Foraging Theory*](https://global.oup.com/academic/product/9780195173321), Oxford, 2007
- Keith, B., ["Interactive Narrative Analytics"](https://doi.org/10.1109/ACCESS.2025.3630352), *IEEE Access*, 2026
- Shahaf, D. & Guestrin, C., ["Connecting the Dots Between News Articles"](https://doi.org/10.1145/1835804.1835884), *KDD*, 2010
- Shahaf, D., Guestrin, C. & Horvitz, E., ["Metro Maps of Science"](https://doi.org/10.1145/2339530.2339705), *KDD*, 2012
- Harris, J., [10×10](https://jjh.org/10x10), 2004
- Boutaleb et al., [BERTrend](https://arxiv.org/abs/2411.05930), 2024
