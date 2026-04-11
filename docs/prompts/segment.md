Every day, TV broadcasts dozens of news programs. A viewer can't watch them all. We want to show them 25 words that capture what the country talked about today — a daily zeitgeist.

To get there, we process each broadcast's subtitles. You are one step in this chain: you read one program's VTT subtitles, split them into stories, and pick the one keyword per story that will represent it in the final grid.

The viewer will see only the keyword and a video frame. When they click, they see a one-sentence quote from each program that covered the story.

Each program covers multiple stories we call "segments". A new segment begins when the topic changes — look for shifts in subject matter, named entities, or transitional phrases. Skip greetings, sign-offs, and program teasers — only return actual stories.

Return ONLY a valid JSON array. For each story:
[
  {
    "start_time": "HH:MM:SS.mmm",
    "end_time": "HH:MM:SS.mmm",
    "peak_time": "timestamp of the story's most specific or climactic moment. Usually not the beginning of the segment.",
    "keyword": "one trigger word (see rules below)",
    "quote": "one sentence in German summarizing what this program reported about the story",
    "segment_type": "story | weather | sport"
  }
]

Keyword rules:
- The keyword is information scent — it must instantly tell the viewer what the story is about and whether it's for them. Think of it as the zeitgeist of that story in one word.
- The keyword must instantly identify the story — a viewer scanning 25 keywords should feel today's news
- Most recognizable proper noun: person ("Odermatt"), place ("Roveredo"), org ("NATO")
- No proper noun? Specific German term: "Eigenmietwert", "Cyberangriffe"
- Second word ONLY if ambiguous: "Trump NATO" vs "Trump Briefwahl"
- Max 2 words if necessary, but typically one
- Full first name if not globally famous: "Muriel Furrer", not "Furrer"
- No nicknames, no insider abbreviations, no English
- If the same topic appears twice in this program, use one keyword for both

{keyword_instruction}

Transcript:
{transcript}
