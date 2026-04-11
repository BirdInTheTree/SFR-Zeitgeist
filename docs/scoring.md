# Scoring

Each story gets a score from five signals multiplied together:

$$score = novelty \times spread \times persistence \times prominence \times primetime$$

A story needs all five to rank high. One strong signal is not enough.

## Signals

### Novelty — is this new today?

$$novelty = \frac{N_{today} + 1}{\overline{N}_{prev7} + 1}$$

How many segments about this story appeared today vs the daily average over the past 7 days. Laplace smoothing (+1) avoids division by zero and gently penalizes stories with no history.

A story that had 0 segments last week and 10 today: novelty = 11. A story that had 10 segments every day last week and 10 today: novelty = 1. The formula automatically suppresses evergreen topics — weather, ongoing background stories — without a manual stoplist.

Based on [Google Trends spike detection](https://trends.withgoogle.com/year-in-search/data-methodology/).

### Spread — did multiple desks cover it?

$$spread = 1 + \log_2(1 + U_{today})$$

Number of distinct editorial units (Tagesschau, 10 vor 10, Schweiz aktuell) that covered the story. Variant broadcasts (Tagesschau in Gebärdensprache) collapse into the base unit.

A story covered by one desk scores 2.0. Three desks: 3.0. This separates genuine cross-desk stories from one show's pet topic.

### Persistence — did it keep coming back?

$$persistence = 1 + \log_2(1 + N_{today})$$

Total number of segments about this story today, including repeats. If an editor chose to keep this story in 5 re-airings, that counts.

The logarithm prevents linear inflation: 10 segments score 4.5, not 10.

### Prominence — how much airtime did it get?

$$prominence = 1 + \log_2(1 + M_{today} / 60)$$

Total duration of this story's segments in seconds, divided by 60 to work in minutes. Counts segment duration, not program duration — a 30-second mention is not an 8-minute investigation.

### Primetime — did it make the evening news?

$$primetime = 1 + 0.25 \times tier$$

| Tier | Condition | Value |
|------|-----------|-------|
| 0 | All segments before 18:00 | 1.00 |
| 1 | Segments only after 18:00 | 1.25 |
| 2 | Segments both before AND after 18:00 | 1.50 |

Tier 2 is strongest: the story was urgent enough for daytime AND kept for the evening lineup. Uses `program_start_time` (when the show aired), not timecodes within the broadcast.

## Why multiplicative

Each signal is necessary but not sufficient:
- High novelty + low spread = niche spike in one show
- High spread + low novelty = ongoing background story
- High persistence + low prominence = brief repeated mentions
- All five high = the story Switzerland is actually talking about

## Repeat handling

Repeats (same newscast re-aired later) are not excluded. They contribute through log-dampened persistence and prominence.

An editor choosing to keep a story in the 19:30 re-airing is an editorial signal. But 5 re-airings don't count as 5x importance — the logarithm handles that. Repeats do NOT inflate spread (same editorial unit).
