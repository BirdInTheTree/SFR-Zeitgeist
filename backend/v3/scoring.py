"""Story-level scoring for SRF Zeitgeist v3."""

import math


SMOOTHING_ALPHA = 1.0


def novelty(today_segments: int, baseline_avg_segments: float, alpha: float = SMOOTHING_ALPHA) -> float:
    """Measure how strongly a story appears today compared with the previous 7 days."""
    return (today_segments + alpha) / (baseline_avg_segments + alpha)


def spread(distinct_programs: int) -> float:
    """Measure how many distinct programs carried the story today."""
    return 1.0 + math.log2(1.0 + distinct_programs)


def persistence(total_segments: int) -> float:
    """Measure how often the story reappears across today's segments."""
    return 1.0 + math.log2(1.0 + total_segments)


def prominence(total_story_seconds: float) -> float:
    """Measure total airtime of the story using segment duration, not program duration."""
    return 1.0 + math.log2(1.0 + (total_story_seconds / 60.0))


def score_story(
    today_segments: int,
    baseline_avg_segments: float,
    distinct_programs: int,
    total_segments: int,
    total_story_seconds: float,
) -> float:
    """Compute the final story score."""
    return (
        novelty(today_segments, baseline_avg_segments)
        * spread(distinct_programs)
        * persistence(total_segments)
        * prominence(total_story_seconds)
    )
