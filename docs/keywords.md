# Keywords

The keyword is what appears on the grid. It must work as a *trigger word* ([Pirolli, 2007](https://global.oup.com/academic/product/9780195173321)) — one glance and you know the story.

## Rules for the LLM

- Use the most recognizable proper noun: a person ("Odermatt"), a place ("Roveredo"), an organization ("NATO")
- If no proper noun fits, use the specific German term: "Eigenmietwert", "Cyberangriffe"
- Add a second word only if the first is ambiguous: "Trump NATO" vs "Trump Briefwahl"
- Maximum 2 words
- Person names: include first name if not globally famous ("Muriel Furrer", not "Furrer")
- No nicknames, no abbreviations the audience wouldn't know
- Never use English
- Never merge words: "St. Moritz", not "StMoritz"
- If two segments cover the same story from different angles, use one keyword for both

## Keyword chaining

Broadcasts are processed in chronological order. Each broadcast receives the list of keywords already assigned earlier that day. The LLM is instructed to reuse exact keywords for the same story.

This gives cross-program consistency: if Tagesschau 12:45 calls the story "Artemis", Schweiz aktuell 19:00 will also call it "Artemis" — because it sees "Artemis" in the existing keyword list.

## Cross-day consistency

A story that runs for multiple days keeps its original keyword. The canonical story registry stores each story's keyword and fingerprint (entities + frequent words from the segment text).

When a new day is processed, each story's fingerprint is compared against the registry. If entity overlap >= 8 or top-word overlap >= 5, the story gets the original keyword.

"Israel Todesstrafe" on day 1 stays "Israel Todesstrafe" on day 2 — even if the LLM might prefer "Knesset Todesstrafe" for the new day's coverage.

## Text validation

Same keyword does not always mean same story. Before merging two segments under one keyword, the code checks that their texts actually overlap (at least 2 shared top-words or 2 shared entities). If they don't, the segments are split into separate stories.

## How the prompt was chosen

Three prompt variants were tested on the same broadcast:

| Variant | Approach | Result |
|---------|----------|--------|
| A | "Choose the ONE word that captures the zeitgeist" | Generic: "Elections", "Sport", "Drones" |
| B | Rules: "Use most recognizable proper noun, max 2 words" | Specific: "Netanyahu", "SVP", "Marco Odermatt" |
| C | Good/bad examples | Hyphenated: "SVP-Elections", "Drones-Finland" |

Variant B won. Rules give the LLM a decision procedure. Examples give it patterns to mimic — which produces inconsistent results.
