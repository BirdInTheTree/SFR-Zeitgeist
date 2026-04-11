"""Canonical story registry for cross-week keyword consistency.

Stores each story's keyword and fingerprint (entities + top words).
When a new week is processed, stories are matched against the registry
to maintain keyword stability across weeks.

Currently disabled in weekly mode — keyword chaining within the week
provides sufficient consistency.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "demo-data" / "story_registry.json"

# Story-level fingerprint match thresholds.
# High because aggregated fingerprints are long (10-20 entities per story)
# and German capitalizes all nouns → many false entity matches.
_REGISTRY_ENTITY_THRESHOLD = 8
_REGISTRY_WORD_THRESHOLD = 5


def load_registry() -> dict:
    """Load the canonical story registry.

    Format: {story_id: {keyword, first_seen, last_seen, entities, top_words}}
    """
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {}


def save_registry(registry: dict) -> None:
    """Save the canonical story registry."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2))


def build_story_fingerprint(
    story_meta: dict, all_segments: list[dict],
) -> tuple[set, set]:
    """Aggregate fingerprint across all segments of a story."""
    all_entities = set()
    all_words = set()
    for idx in story_meta.get("segment_indices", []):
        if idx < len(all_segments):
            fp = all_segments[idx].get("fingerprint", {})
            all_entities.update(fp.get("entities", []))
            all_words.update(fp.get("top_words", []))
    return all_entities, all_words


def normalize_with_registry(
    stories_meta: list[dict],
    all_segments: list[dict],
    registry: dict,
    target_date: str,
) -> tuple[list[dict], int]:
    """Match stories against the registry. Adopt canonical keywords.

    Returns (updated stories_meta, number of matches found).
    """
    n_matched = 0

    for story in stories_meta:
        story_entities, story_words = build_story_fingerprint(story, all_segments)

        best_match = None
        best_overlap = 0

        for reg_id, reg_data in registry.items():
            reg_entities = set(reg_data.get("entities", []))
            reg_words = set(reg_data.get("top_words", []))

            entity_overlap = len(story_entities & reg_entities)
            word_overlap = len(story_words & reg_words)

            if (entity_overlap >= _REGISTRY_ENTITY_THRESHOLD
                    or word_overlap >= _REGISTRY_WORD_THRESHOLD):
                total = entity_overlap + word_overlap
                if total > best_overlap:
                    best_overlap = total
                    best_match = reg_id

        if best_match:
            old_kw = story["keyword"]
            story["story_id"] = best_match
            story["keyword"] = registry[best_match]["keyword"]
            registry[best_match]["last_seen"] = target_date
            registry[best_match]["entities"] = sorted(
                set(registry[best_match].get("entities", [])) | story_entities
            )
            registry[best_match]["top_words"] = sorted(
                set(registry[best_match].get("top_words", [])) | story_words
            )
            if old_kw != story["keyword"]:
                n_matched += 1
                logger.info(
                    "Registry match: '%s' → '%s' (from %s)",
                    old_kw, story["keyword"], registry[best_match]["first_seen"],
                )
        else:
            sid = story["story_id"]
            registry[sid] = {
                "keyword": story["keyword"],
                "first_seen": target_date,
                "last_seen": target_date,
                "entities": sorted(story_entities),
                "top_words": sorted(story_words),
            }

    return stories_meta, n_matched
