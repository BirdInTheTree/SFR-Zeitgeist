# Keywords

The keyword is what appears on the grid. It must work as a *trigger word* ([Pirolli, 2007](https://global.oup.com/academic/product/9780195173321)) — one glance and you know the story.

The LLM prompt with all keyword rules is in [docs/prompts/segment.md](prompts/segment.md).

## How keywords stay consistent

### Within one day

Broadcasts are processed chronologically. Each LLM call receives the keywords from yesterday's zeitgeist and all previously processed broadcasts today. The LLM reuses exact keywords for the same story — so if Tagesschau 12:45 calls a story "Artemis", Schweiz aktuell 19:00 sees "Artemis" in the list and reuses it.

### Across days

A story that runs for multiple days keeps its original keyword. The code maintains a story registry (`story_registry.json`) with each story's keyword and fingerprint (entities + frequent words from segment text).

When a new day is processed, each story's fingerprint is compared against the registry. If entity overlap >= 8 or top-word overlap >= 5, the story gets the original keyword.

"Israel Todesstrafe" on day 1 stays "Israel Todesstrafe" on day 2 — even if the LLM might prefer "Knesset Todesstrafe" for the new day's coverage.

## Text validation

Same keyword does not always mean same story. Before merging two segments under one keyword, the code checks that their texts actually overlap (at least 3 shared top-words or 3 shared entities). Threshold is high because German capitalizes all nouns, creating false entity matches. If texts don't overlap, the segments are split into separate stories.

## How the prompt was chosen

Three prompt variants were tested on the same broadcast:

| Variant | Approach | Result |
|---------|----------|--------|
| A | "Choose the ONE word that captures the zeitgeist" | Generic: "Elections", "Sport", "Drones" |
| B | Rules: "Use most recognizable proper noun, max 2 words" | Specific: "Netanyahu", "SVP", "Marco Odermatt" |
| C | Good/bad examples | Hyphenated: "SVP-Elections", "Drones-Finland" |

Variant B won. Rules give the LLM a decision procedure. Examples give it patterns to mimic — which produces inconsistent results.
