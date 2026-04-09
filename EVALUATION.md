# Evaluation Snapshot

This document records lightweight validation for the current SRF Zeitgeist demo build.

The goal is not to claim full product validation. The goal is to show that the prototype already operates on a meaningful SRF-sized corpus, produces a usable daily topic surface, and has measurable filtering behavior.

## Scope

- Snapshot dates covered: `2026-03-19` to `2026-04-01`
- Source manifest: [demo-data/days.json](demo-data/days.json)
- Daily outputs: [demo-data/zeitgeist_20260401.json](demo-data/zeitgeist_20260401.json) and sibling snapshot files
- Candidate/filter log: [demo-data/llm_gate_log.txt](demo-data/llm_gate_log.txt)
- Raw scored cache example: [demo-data/cache/all_scored_apr1.json](demo-data/cache/all_scored_apr1.json)

## Corpus Size

| Metric | Value |
|--------|-------|
| Daily snapshots in demo | 12 |
| Total programs in saved archive window | 1,172 |
| News programs in that window | 541 |
| Total subtitle words processed | 3,553,292 |

Interpretation: this is already large enough to demonstrate real ranking behavior, not just toy examples.

## Output Quality Indicators

| Metric | Value |
|--------|-------|
| Total surfaced topics across 12 snapshots | 255 |
| Average topics per day | 21.2 |
| Min / max topics per day | 11 / 49 |
| Total linked source quotes | 848 |
| Average quotes per topic | 3.33 |
| Topics with imagery | 206 |
| Image coverage | 80.8% |

Interpretation: the current snapshots usually provide both textual evidence and a visual anchor for each topic, even though some days still fall short of filling the full 7×7 grid.

## Filter Funnel

LLM filter measurements were derived from [demo-data/llm_gate_log.txt](demo-data/llm_gate_log.txt).

| Metric | Value |
|--------|-------|
| Candidate phrases evaluated by the LLM gate | 2,632 |
| Candidate phrases kept | 940 |
| Aggregate pass rate | 35.7% |

Interpretation: the final grid is not a raw noun-phrase dump. Roughly two thirds of candidates are removed before display.

## Qualitative Spot Check

Quick visual inspection of the top snapshot for `2026-04-01` suggests:

- Quotes are generally anchored to the displayed phrase and provide useful source context.
- The remaining weak point is quote trimming: some quotes still start or end mid-sentence.
- Missing imagery is visible but not catastrophic at current coverage levels.

Interpretation: the current output is already demo-safe, but quote extraction would be the next quality improvement after presentation polish.

## Caveats

- This is a prototype evaluation, not a user study or offline benchmark against a labeled gold set.
- The current corpus mixes news and non-news programs in the saved archive window, while the ranking pipeline itself focuses on news content.
- Image coverage depends on whether a usable frame or image URL was available for a topic.
- The LLM pass-rate figure measures filtering behavior, not semantic precision or recall.

## Recommended Next Validation Step

If there is time for one more credibility upgrade, manually rate 25 surfaced topics on two axes:

1. Is this phrase genuinely topical for the day?
2. Does the attached quote explain why it is in the grid?

That would produce the first small human-quality baseline without requiring a larger research effort.