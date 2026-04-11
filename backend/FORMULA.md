# SRF Zeitgeist v2 — Story-Level Pipeline

## What changed from v1

v1 extracted **phrases** (noun chunks + named entities via spaCy), then ranked by spike frequency.  
v2 extracts **stories** (editorial segments via LLM), then ranks by a multi-signal formula.

| | v1 (phrase-level) | v2 (story-level) |
|---|---|---|
| Unit of analysis | Noun phrase ("Kanton Bern") | Editorial story segment |
| Extraction | spaCy NLP | LLM segmentation |
| Dedup | Cosine similarity, substring, co-occurrence | LLM merges segments into stories |
| Repeat handling | Excluded from count | Counted via log-dampened persistence |
| Scoring | `spike × log₂(unit_count)` | `novelty × spread × persistence × prominence` |

## Scoring Formula

```
score(s) = novelty(s) × spread(s) × persistence(s) × prominence(s) × primetime(s)
```

### Components

**novelty** — is this story new today, or business as usual?

```
novelty(s) = (N_today(s) + α) / (N̄_prev7(s) + α)
```

- `N_today(s)`: total segments about story s today (including repeats)
- `N̄_prev7(s)`: average daily segments about s over previous 7 days
- `α = 1`: Laplace smoothing

Inspired by Google Trends: raw volume doesn't matter, growth relative to baseline does.

**spread** — how many editorial desks picked up this story?

```
spread(s) = 1 + log₂(1 + U_today(s))
```

- `U_today(s)`: distinct editorial units (Tagesschau, 10vor10, Schweiz aktuell...)

From agenda-setting theory: a story covered by multiple independent desks is more significant than one show's pet topic.

**persistence** — how often did the story come back during the day?

```
persistence(s) = 1 + log₂(1 + N_today(s))
```

- `N_today(s)`: total segments (same as in novelty)

Includes repeats. If an editor chose to keep this story in 5 re-airings, that's a signal. Log dampening prevents 10 repeats from dominating: `1 + log₂(11) ≈ 4.5`, not `10`.

**prominence** — how much airtime did the story actually get?

```
prominence(s) = 1 + log₂(1 + M_today(s) / 60)
```

- `M_today(s)`: total duration of this story's segments in seconds
- Divided by 60 to work in minutes

Counts segment duration, not program duration. A 30-second mention ≠ an 8-minute investigation.

**primetime** — did this story make it to evening prime time?

```
primetime(s) = 1 + β × tier(s)
```

- `β = 0.25`: gentle correction, not a dominant signal
- `tier = 2`: story has segments both before AND after 18:00 (breaking news that was urgent enough for daytime AND kept for evening prime — double editorial filter)
- `tier = 1`: story has segments only after 18:00 (evening editorial pick)
- `tier = 0`: story has segments only before 18:00 (didn't survive to primetime)

Uses `program_start_time` (when the show aired), not VTT timecodes within the broadcast. A future refinement: replace the hard 18:00 cutoff with a list of flagship evening programs (Tagesschau 19:30, 10vor10, Rundschau).

### Why multiplicative

Each signal is necessary but not sufficient:
- High novelty + low spread = niche topic (spike in one show)
- High spread + low novelty = ongoing background story
- High persistence + low prominence = brief repeated mentions
- High primetime + low spread = one evening show's choice
- All five high = the story Switzerland is actually talking about today

### Repeat handling

Repeats (same newscast re-aired later) are **not excluded**. They contribute through log-dampened persistence and prominence. This is deliberate:

- An editor choosing to keep a story in the 19:30 re-airing is an editorial signal
- But 5 re-airings shouldn't count as 5× the importance — logarithm handles this
- Repeats do NOT inflate spread (same editorial unit)
- Segments that are identical re-airings are merged into one story card

## Pipeline Steps

```
demo-data/week/*.json
  → filter news (genre=Nachrichten)
  → fetch VTT subtitles (Integration Layer, cached)
  → LLM segments each broadcast into stories
  → LLM merges segments across broadcasts (keyword clustering, repeat detection)
  → score each story (novelty × spread × persistence × prominence × primetime)
  → rank top 49
  → extract frame at first mention timecode (ffmpeg)
  → smart crop (4:3, face detection)
  → zeitgeist_YYYYMMDD.json
```

## Usage

```bash
# Single day
python -m backend.v2.pipeline 2026-04-01

# All available days
python -m backend.v2.pipeline --all

# Without image extraction
python -m backend.v2.pipeline 2026-04-01 --no-images
```

## Output

`demo-data/v2/zeitgeist_YYYYMMDD.json` — same structure as v1 but with story-level fields:

```json
{
  "story_id": "kanton_bern",
  "keyword": "Kanton Bern",
  "score": 28.5,
  "novelty": 3.0,
  "spread": 2.6,
  "persistence": 2.3,
  "prominence": 1.6,
  "n_segments": 8,
  "n_repeats": 3,
  "distinct_programs": 4,
  "total_seconds": 245.0,
  "editorial_units": ["10 vor 10", "Schweiz aktuell", "Tagesschau"],
  "quotes": [...],
  "imageUrl": "demo-data/v2/cropped/..."
}
```
