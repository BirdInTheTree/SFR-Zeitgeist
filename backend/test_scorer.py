"""Tests for scoring, fingerprinting, VTT parsing, and JSON extraction."""

import math
import pytest

from backend.scorer import (
    novelty,
    spread,
    persistence,
    prominence,
    primetime,
    score_story,
    SMOOTHING_ALPHA,
    PRIMETIME_BETA,
)
from backend.segmenter import compute_fingerprint, fingerprint_match


# ---------------------------------------------------------------------------
# scorer.py — individual signals
# ---------------------------------------------------------------------------


class TestNovelty:
    def test_spike_vs_zero_baseline(self):
        """New story with no baseline should score high."""
        result = novelty(10, 0.0)
        assert result == (10 + SMOOTHING_ALPHA) / (0.0 + SMOOTHING_ALPHA)
        assert result == 11.0

    def test_same_as_baseline(self):
        """Story matching its baseline should score ~1.0."""
        result = novelty(5, 5.0)
        assert result == pytest.approx(1.0)

    def test_below_baseline(self):
        """Story below baseline should score < 1.0 but >= 0.5 (floor)."""
        result = novelty(1, 10.0)
        assert result < 1.0
        assert result >= 0.5

    def test_zero_today(self):
        """Zero segments today hits the floor at 0.5."""
        result = novelty(0, 5.0)
        assert result == 0.5


class TestSpread:
    def test_one_program(self):
        result = spread(1)
        assert result == 1 + math.log2(2)
        assert result == 2.0

    def test_zero_programs(self):
        result = spread(0)
        assert result == 1 + math.log2(1)
        assert result == 1.0

    def test_many_programs(self):
        """More programs = higher score, but log-dampened."""
        assert spread(5) > spread(3) > spread(1)


class TestPersistence:
    def test_one_segment(self):
        assert persistence(1) == 1 + math.log2(2)

    def test_monotonic(self):
        """More segments = higher score."""
        assert persistence(10) > persistence(5) > persistence(1)


class TestProminence:
    def test_one_minute(self):
        result = prominence(60.0)
        assert result == 1 + math.log2(2)

    def test_zero_seconds(self):
        result = prominence(0.0)
        assert result == 1.0

    def test_long_story(self):
        """10 minutes of airtime should score higher than 1 minute."""
        assert prominence(600.0) > prominence(60.0)


class TestPrimetime:
    def test_tier2_both(self):
        """Story airing both pre and post 18:00 gets max boost."""
        result = primetime(True, True)
        assert result == 1 + PRIMETIME_BETA * 2

    def test_tier1_evening_only(self):
        result = primetime(False, True)
        assert result == 1 + PRIMETIME_BETA * 1

    def test_tier0_daytime_only(self):
        result = primetime(True, False)
        assert result == 1.0

    def test_tier0_nothing(self):
        result = primetime(False, False)
        assert result == 1.0


class TestScoreStory:
    def test_all_signals_multiply(self):
        """Final score is the product of all five signals."""
        result = score_story(
            today_segments=5,
            baseline_avg_segments=1.0,
            distinct_programs=3,
            total_segments=5,
            total_story_seconds=300.0,
            has_pre18=True,
            has_post18=True,
        )
        expected = (
            novelty(5, 1.0)
            * spread(3)
            * persistence(5)
            * prominence(300.0)
            * primetime(True, True)
        )
        assert result == pytest.approx(expected)

    def test_zero_baseline_spike(self):
        """Breaking news: high segments, zero baseline → very high score."""
        breaking = score_story(10, 0.0, 3, 10, 600.0, True, True)
        background = score_story(2, 2.0, 1, 2, 120.0, True, False)
        assert breaking > background * 10

    def test_evergreen_suppressed(self):
        """Recurring topic (weather) with stable baseline → novelty ~1.0."""
        weather = score_story(3, 3.0, 1, 3, 180.0, True, True)
        spike = score_story(3, 0.0, 1, 3, 180.0, True, True)
        assert spike > weather


# ---------------------------------------------------------------------------
# segmenter.py — fingerprinting
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    def test_basic_structure(self):
        fp = compute_fingerprint("Der Bundesrat hat heute eine Entscheidung getroffen.")
        assert "entities" in fp
        assert "top_words" in fp
        assert "word_count" in fp
        assert fp["word_count"] == 7

    def test_entities_extracted(self):
        """Capitalized words not at sentence start should be entities."""
        text = "Heute hat Bundesrat Berset in Bern eine Erklärung abgegeben."
        fp = compute_fingerprint(text)
        assert "Bundesrat" in fp["entities"]
        assert "Berset" in fp["entities"]
        assert "Bern" in fp["entities"]

    def test_sentence_start_excluded(self):
        """First word of sentence should not be counted as entity."""
        text = "Wetter ist heute gut. Morgen wird es regnen."
        fp = compute_fingerprint(text)
        # "Wetter" is first word, "Morgen" follows period — both sentence starts
        assert "Wetter" not in fp["entities"]
        assert "Morgen" not in fp["entities"]

    def test_stopwords_excluded_from_top_words(self):
        fp = compute_fingerprint("werden werden werden werden werden")
        assert len(fp["top_words"]) == 0

    def test_top_words_sorted(self):
        text = "Klimaschutz Klimaschutz Energiewende Energiewende Nachhaltigkeit"
        fp = compute_fingerprint(text)
        assert fp["top_words"] == sorted(fp["top_words"])

    def test_empty_text(self):
        fp = compute_fingerprint("")
        assert fp["entities"] == []
        assert fp["top_words"] == []
        assert fp["word_count"] == 0


class TestFingerprintMatch:
    def test_matching_entities(self):
        fp1 = {"entities": ["Berset", "Bern", "Bundesrat", "Schweiz"], "top_words": []}
        fp2 = {"entities": ["Berset", "Bern", "Bundesrat", "Genf"], "top_words": []}
        assert fingerprint_match(fp1, fp2) is True

    def test_matching_words(self):
        fp1 = {"entities": [], "top_words": ["klimaschutz", "energiewende", "nachhaltigkeit"]}
        fp2 = {"entities": [], "top_words": ["klimaschutz", "energiewende", "nachhaltigkeit"]}
        assert fingerprint_match(fp1, fp2) is True

    def test_no_match(self):
        fp1 = {"entities": ["Berset"], "top_words": ["klima"]}
        fp2 = {"entities": ["Trump"], "top_words": ["waffen"]}
        assert fingerprint_match(fp1, fp2) is False

    def test_threshold_boundary_entities(self):
        """Exactly 2 entity overlap is not enough (threshold is 3)."""
        fp1 = {"entities": ["A", "B", "C"], "top_words": []}
        fp2 = {"entities": ["A", "B", "D"], "top_words": []}
        assert fingerprint_match(fp1, fp2) is False

    def test_threshold_boundary_words(self):
        """Exactly 2 word overlap is not enough (threshold is 3)."""
        fp1 = {"entities": [], "top_words": ["a", "b", "c"]}
        fp2 = {"entities": [], "top_words": ["a", "b", "d"]}
        assert fingerprint_match(fp1, fp2) is False

    def test_exact_threshold_entities(self):
        """Exactly 3 entity overlap should match."""
        fp1 = {"entities": ["A", "B", "C", "D"], "top_words": []}
        fp2 = {"entities": ["A", "B", "C", "E"], "top_words": []}
        assert fingerprint_match(fp1, fp2) is True


# ---------------------------------------------------------------------------
# segmenter.py — VTT parsing
# ---------------------------------------------------------------------------

from backend.segmenter import parse_vtt, tc_to_seconds, seconds_to_tc, _extract_json


class TestParseVtt:
    def test_basic(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:06.000 --> 00:00:10.000
Second block
"""
        blocks = parse_vtt(vtt)
        assert len(blocks) == 2
        assert blocks[0]["text"] == "Hello world"
        assert blocks[0]["start"] == 1.0
        assert blocks[0]["end"] == 5.0
        assert blocks[1]["text"] == "Second block"

    def test_html_tags_stripped(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
<c.color1>This is <b>bold</b> text</c>
"""
        blocks = parse_vtt(vtt)
        assert blocks[0]["text"] == "This is bold text"

    def test_empty_blocks_skipped(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000


00:00:06.000 --> 00:00:10.000
Real text
"""
        blocks = parse_vtt(vtt)
        assert len(blocks) == 1
        assert blocks[0]["text"] == "Real text"

    def test_no_timestamps(self):
        blocks = parse_vtt("Just some text without timestamps")
        assert blocks == []

    def test_empty_string(self):
        assert parse_vtt("") == []

    def test_numbered_cues(self):
        """VTT with numeric cue identifiers."""
        vtt = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
First

2
00:00:06.000 --> 00:00:10.000
Second
"""
        blocks = parse_vtt(vtt)
        assert len(blocks) == 2
        assert blocks[0]["text"] == "First"


class TestTimecodes:
    def test_tc_to_seconds(self):
        assert tc_to_seconds("00:01:30.000") == 90.0
        assert tc_to_seconds("01:00:00.000") == 3600.0
        assert tc_to_seconds("00:00:05.500") == 5.5

    def test_seconds_to_tc(self):
        assert seconds_to_tc(90.0) == "00:01:30.000"
        assert seconds_to_tc(3661.5) == "01:01:01.500"

    def test_roundtrip(self):
        tc = "00:12:34.567"
        assert seconds_to_tc(tc_to_seconds(tc)) == tc

    def test_comma_separator(self):
        """Some VTT files use comma instead of dot."""
        assert tc_to_seconds("00:01:30,500") == 90.5


class TestExtractJson:
    def test_plain_array(self):
        result = _extract_json('[{"keyword": "test"}]')
        assert result == [{"keyword": "test"}]

    def test_markdown_fence(self):
        result = _extract_json('```json\n[{"keyword": "test"}]\n```')
        assert result == [{"keyword": "test"}]

    def test_text_before_json(self):
        result = _extract_json('Here is the result:\n[{"keyword": "test"}]')
        assert result == [{"keyword": "test"}]

    def test_nested_object(self):
        result = _extract_json('{"segments": [{"keyword": "test"}]}')
        assert result["segments"] == [{"keyword": "test"}]

    def test_trailing_comma(self):
        """LLMs sometimes add trailing commas."""
        result = _extract_json('[{"keyword": "test",}]')
        # Should either parse or fall through to regex cleanup
        assert result is not None
