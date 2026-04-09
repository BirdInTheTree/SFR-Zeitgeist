# V3 Pipeline

`backend/v3/` is a clean rewrite of the ranking pipeline.

It does not modify the current phrase-first implementation in `backend/pipeline.py`. The goal is to build a separate story-first pipeline in parallel.

## Target logic

1. Load raw VTT subtitles.
2. Keep only news-like programs.
3. Ask an LLM to split each broadcast into consecutive editorial segments.
4. For each segment, ask the LLM to return:
   - story label
   - keyword
   - summary
   - entities
   - whether the segment is an exact carry-over from the previous episode of the same program
5. Merge matching stories across programs for the target day.
6. Rank merged stories with the score below.
7. For each ranked story, find the first spoken occurrence of its keyword in the earliest segment and extract a screenshot.

## Scoring formula

The story score is:

$$
score(s) = novelty(s) \times spread(s) \times persistence(s) \times prominence(s)
$$

with:

$$
novelty(s)=\frac{N_{today}(s)+\alpha}{\overline{N}_{prev7}(s)+\alpha}
$$

$$
spread(s)=1+\log_2(1+U_{today}(s))
$$

$$
persistence(s)=1+\log_2(1+N_{today}(s))
$$

$$
prominence(s)=1+\log_2\left(1+\frac{M_{today}(s)}{60}\right)
$$

Where:

- $N_{today}(s)$ is the number of segments mapped to story $s$ today.
- $\overline{N}_{prev7}(s)$ is the average number of mapped segments for story $s$ over the previous 7 days.
- $U_{today}(s)$ is the number of distinct programs carrying story $s$ today.
- $M_{today}(s)$ is the sum of durations, in seconds, of segments mapped to story $s$ today.
- $\alpha$ is a smoothing constant, usually 1.

## Interpretation

- `novelty` measures how unusually present the story is today versus baseline.
- `spread` measures whether the story is carried by multiple programs, not just repeated inside one show.
- `persistence` measures how often editorially the story returns during the day.
- `prominence` measures how much actual airtime the story receives, using segment duration rather than program duration.

Exact repeats are not discarded and not penalized. They remain part of editorial policy and still contribute through persistence and prominence. They should not, however, create separate cards if they belong to the same merged story.

## Output target

The final output for the grid is story-centric:

- one card per merged story
- one keyword per card
- one screenshot taken at the first mention of that keyword in the earliest segment
- no program airtime shown in the card metadata