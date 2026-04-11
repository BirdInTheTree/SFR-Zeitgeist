"""
Story-level scoring formula for SRF Zeitgeist.

score(s) = novelty × spread × persistence × prominence × primetime

Based on: Google Trends (spike vs baseline), agenda-setting theory
(repetition signals importance), BERTrend (documents × update frequency).

All components except novelty are log-dampened (1 + log₂(1 + x))
so repeats contribute but don't dominate linearly.
primetime is a gentle editorial boost (β=0.25) based on time-of-day tiers.
"""

import math

SMOOTHING_ALPHA = 1
PRIMETIME_BETA = 0.25
# Programs starting at or after this hour count as evening/primetime.
# TODO: replace with flagship program list (Tagesschau 19:30, 10vor10, Rundschau)
# for a more accurate editorial signal than raw clock time.
PRIMETIME_HOUR = 18


def novelty(today_segments: int, baseline_avg_segments: float) -> float:
    """How much this story spiked today vs the 7-day average.

    Returns ratio with Laplace smoothing (α=1) to avoid division by zero
    and to gently penalize stories with no baseline.
    """
    return (today_segments + SMOOTHING_ALPHA) / (baseline_avg_segments + SMOOTHING_ALPHA)


def spread(distinct_programs: int) -> float:
    """How many different programs covered this story.

    Higher = story crossed editorial desks (Tagesschau + 10vor10 + Rundschau).
    """
    return 1 + math.log2(1 + distinct_programs)


def persistence(total_segments: int) -> float:
    """How many times the story appeared across all broadcasts today.

    Includes repeats — editorial decision to keep airing = signal.
    """
    return 1 + math.log2(1 + total_segments)


def prominence(total_story_seconds: float) -> float:
    """Total airtime dedicated to this story in minutes (log-dampened).

    Counts segment durations, not full program lengths.
    """
    minutes = total_story_seconds / 60.0
    return 1 + math.log2(1 + minutes)


def primetime(has_pre18: bool, has_post18: bool) -> float:
    """Editorial boost based on when during the day the story aired.

    tier 2: segments both before and after 18:00 — breaking news that
            was urgent enough for daytime AND kept for evening prime.
    tier 1: segments only after 18:00 — evening editorial pick.
    tier 0: segments only before 18:00 — didn't survive to primetime.

    Uses program_start_time (when the show aired), not VTT timecodes.
    """
    if has_pre18 and has_post18:
        tier = 2
    elif has_post18:
        tier = 1
    else:
        tier = 0
    return 1 + PRIMETIME_BETA * tier


def score_story(
    today_segments: int,
    baseline_avg_segments: float,
    distinct_programs: int,
    total_segments: int,
    total_story_seconds: float,
    has_pre18: bool = False,
    has_post18: bool = False,
) -> float:
    """Compute final story score. Five signals multiplied."""
    return (
        novelty(today_segments, baseline_avg_segments)
        * spread(distinct_programs)
        * persistence(total_segments)
        * prominence(total_story_seconds)
        * primetime(has_pre18, has_post18)
    )
