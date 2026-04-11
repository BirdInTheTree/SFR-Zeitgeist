# Prompts

All LLM prompts used by the pipeline. Source of truth — the code in `backend/segmenter.py` reads from these definitions.

## Segmentation prompt

Sent once per broadcast. Returns one JSON object per story segment.

```
Segment this SRF news broadcast into editorial stories.

For each segment return:
- start_time, end_time (from the timestamps in the transcript)
- peak_time: the timestamp of the most important moment in this segment
  (the key fact, the decisive quote — NOT the intro by the anchor)
- keyword: the word a newspaper editor would use as the HEADLINE WORD.
  Rules:
  - Use the most recognizable proper noun (person: "Odermatt", place: "Roveredo", org: "NATO")
  - If no proper noun, use the specific German term ("Eigenmietwert", "Cyberangriffe")
  - Add a second word ONLY if the first is ambiguous ("Trump NATO" vs "Trump Briefwahl")
  - Maximum 2 words. Never longer.
  - Person names: always include first name if not globally famous ("Muriel Furrer", not "Furrer")
  - No nicknames, no abbreviations the audience wouldn't know
  - Never use English. Never merge words ("StMoritz" → "St. Moritz")
  - If two segments cover the same story from different angles, use ONE keyword for both
- short_label: readable headline (3-6 words, German)
- segment_type: "story", "weather", "sport", "intro", "outro", "teaser"

{keyword_instruction}

Return ONLY valid JSON array:
[
  {"start_time": "HH:MM:SS.mmm", "end_time": "HH:MM:SS.mmm", "peak_time": "HH:MM:SS.mmm", "keyword": "...", "short_label": "...", "segment_type": "story"}
]

Transcript:
{transcript}
```

### Keyword chaining instruction

Added for every broadcast after the first one of the day:

```
IMPORTANT: These keywords already exist from earlier broadcasts today:
{keywords}
If a segment covers the same story, reuse the EXACT keyword. Only create a new keyword if it's a genuinely new topic.
```

## Summary prompt

Sent only for the top-N stories after scoring. One call per batch.

```
Write a one-sentence German summary for each of these news story segments.
Return ONLY a JSON array of strings, one summary per segment, in the same order.

Segments:
{segments_json}
```

## Design choices

**Why rules, not examples.** Tested three prompt variants on the same broadcast ([details](keywords.md#how-the-prompt-was-chosen)). Rules ("use most recognizable proper noun") produce specific keywords. Examples produce pattern-matching — the LLM copies the format but not the intent.

**Why minimal output.** The segmentation prompt returns 5 fields per segment, no summary. Summaries are generated separately, only for the final top-25 stories. This keeps the segmentation response short and reduces JSON parsing failures.

**Why keyword chaining.** Without it, the same story gets different keywords in different programs ("Roveredo Mafia" vs "Organisierte Kriminalität"). Passing existing keywords forces the LLM to reuse them.
