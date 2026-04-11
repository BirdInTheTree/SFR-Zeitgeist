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

1. **Segment** — an LLM splits each broadcast into editorial story segments, assigning a keyword and identifying the most important moment (see [prompt](backend/v2/segmenter.py), [output format](demo-data/v2/artifacts/))
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

### Scoring

$$score(s) = novelty \times spread \times persistence \times prominence \times primetime$$

| Signal | What it asks | Formula |
|--------|-------------|---------|
| novelty | Is this new today? | $(N_{today} + 1) / (\overline{N}_{prev7} + 1)$ |
| spread | Did multiple desks cover it? | $1 + \log_2(1 + U_{today})$ |
| persistence | Did it keep coming back? | $1 + \log_2(1 + N_{today})$ |
| prominence | How much airtime did it get? | $1 + \log_2(1 + M_{today}/60)$ |
| primetime | Did it make the evening news? | $1 + 0.25 \times tier$ |

The signals multiply. A story needs all five to rank high. High novelty but low spread = a niche spike in one show. High spread but low novelty = yesterday's ongoing story.

Repeats (same newscast re-aired later) are not thrown out. An editor choosing to keep a story in the 19:30 re-airing is a signal. But 5 re-airings don't count as 5× importance — the logarithm handles that.

Evergreen topics like weather suppress themselves. They appear every day, so their novelty stays at ~1.0. A spike like "Artemis launch" going from 0 to 20 segments scores orders of magnitude higher.

Full rationale: [backend/v2/README.md](backend/v2/README.md)

### Screenshots

The LLM marks the *peak moment* of each segment — the key fact, the decisive quote, not the anchor reading the intro. The video frame is grabbed there.

If the frame is blank (black transition), we retry 5 seconds later. If no face is detected, we zoom to 70% of the frame for a tighter crop. The goal: every cell should show the *story*, not the studio.

### Keyword selection

The keyword is what appears on the grid. It must work as a trigger word ([Pirolli, 2007](#references)) — one glance and you know the story.

Rules for the LLM:
- Use the most recognizable proper noun: "Roveredo", "Keller-Sutter", "Artemis"
- Add a second word only if the first is ambiguous: "Trump NATO" vs "Trump Briefwahl"
- No nicknames. No English. No merged words.
- If two segments cover the same story, use the same keyword

Broadcasts are processed in chronological order. Each one receives the keywords already assigned earlier that day, so the LLM reuses them for the same story across programs.

### Cross-day consistency

A story that runs for multiple days should keep its keyword. "Israel Todesstrafe" on Monday must still be "Israel Todesstrafe" on Tuesday — even if Tuesday's LLM might prefer "Knesset Todesstrafe."

A canonical registry stores every story's keyword and fingerprint (entities + frequent words). When a new day is processed, each story is matched against the registry. If it matches, the original keyword is kept. ([Shahaf & Guestrin, 2010](#references) on coherent story chains across time.)

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
backend/v2/pipeline.py            ← segment → merge → score → frames
        │
        ├── demo-data/v2/segment_cache/   LLM segmentation results
        ├── demo-data/v2/merge_cache/     story merge results
        ├── demo-data/v2/artifacts/       all intermediate results
        └── demo-data/v2/story_registry.json
        │
demo-data/zeitgeist_YYYYMMDD.json ← output for frontend
        │
frontend/                         ← vanilla HTML/CSS/JS
```

### Key files

| File | What it does |
|------|-------------|
| `backend/v2/pipeline.py` | Orchestrates everything: segment → merge → score → frames → output |
| `backend/v2/segmenter.py` | LLM prompts, keyword chaining, fingerprinting, story merge |
| `backend/v2/scorer.py` | The five-signal scoring formula |
| `backend/v2/fetch_epg.py` | Fetches daily program data from EPG API |
| `backend/smart_crop.py` | Face-aware image cropping, blank detection, zoom |
| `frontend/app.js` | Grid, fish-eye word list, zoom overlay, day navigation |

### Running

```bash
source ~/venvs/SFR_env/bin/activate

# Fetch EPG data (run weekly to accumulate history)
python -m backend.v2.fetch_epg --range 14

# Generate one day (with images)
python -m backend.v2.pipeline 2026-04-01

# Generate all available days
python -m backend.v2.pipeline --all

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
