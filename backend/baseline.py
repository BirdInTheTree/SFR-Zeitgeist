"""Baseline computation for novelty scoring.

Loads previous weeks' zeitgeist outputs to compute average segment counts
per story. Used by the novelty signal: spike = this week vs baseline.
"""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "demo-data"

BASELINE_WEEKS = 4  # 4 weeks of history for novelty baseline


def load_baseline(week_start: str) -> dict[str, float]:
    """Load baseline segment counts from previous weeks.

    Returns average weekly segment count per story_id.
    """
    start_dt = date.fromisoformat(week_start)
    story_counts: dict[str, list[int]] = defaultdict(list)
    weeks_found = 0

    for w in range(1, BASELINE_WEEKS + 1):
        prev_monday = (start_dt - timedelta(weeks=w)).isoformat()
        prev_compact = prev_monday.replace("-", "")
        prev_path = OUTPUT_DIR / f"zeitgeist_week_{prev_compact}.json"
        if not prev_path.exists():
            continue
        weeks_found += 1
        try:
            data = json.loads(prev_path.read_text())
        except Exception:
            continue

        week_stories = set()
        for entry in data:
            sid = entry.get("story_id", "")
            n_segs = entry.get("n_segments", 1)
            story_counts[sid].append(n_segs)
            week_stories.add(sid)

        for sid in story_counts:
            if sid not in week_stories:
                story_counts[sid].append(0)

    if weeks_found == 0:
        return {}

    baseline = {}
    for sid, counts in story_counts.items():
        while len(counts) < weeks_found:
            counts.append(0)
        baseline[sid] = sum(counts) / weeks_found

    logger.info("Baseline loaded: %d stories from %d weeks", len(baseline), weeks_found)
    return baseline
