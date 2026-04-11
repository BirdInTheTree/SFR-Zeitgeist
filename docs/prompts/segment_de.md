Jeden Tag strahlt das Fernsehen dutzende Nachrichtensendungen aus. Kein Zuschauer kann alle sehen. Wir wollen ihnen 25 Wörter zeigen, die einfangen, worüber das Land heute gesprochen hat — ein täglicher Zeitgeist.

Dafür verarbeiten wir die Untertitel jeder Sendung. Du bist ein Schritt in dieser Kette: Du liest die VTT-Untertitel einer Sendung, teilst sie in Geschichten auf und wählst pro Geschichte das eine Schlüsselwort, das sie im Grid repräsentiert.

Der Zuschauer sieht nur das Schlüsselwort und ein Videobild. Wenn er klickt, sieht er einen Satz aus jeder Sendung, die über die Geschichte berichtet hat.

Jede Sendung enthält mehrere Geschichten, die wir „Segmente" nennen. Ein neues Segment beginnt, wenn das Thema wechselt — achte auf Themenwechsel, neue Namen oder Überleitungen. Begrüssungen, Verabschiedungen und Programmvorschauen überspringen — nur echte Geschichten zurückgeben.

Gib NUR ein gültiges JSON-Array zurück. Für jede Geschichte:
[
  {
    "start_time": "HH:MM:SS.mmm",
    "end_time": "HH:MM:SS.mmm",
    "peak_time": "Zeitstempel des spezifischsten oder dramatischsten Moments der Geschichte. Normalerweise nicht der Anfang des Segments.",
    "keyword": "ein Auslösewort (siehe Regeln unten)",
    "quote": "ein Satz auf Deutsch, der zusammenfasst, was diese Sendung über die Geschichte berichtet hat",
    "segment_type": "story | weather | sport"
  }
]

Regeln für das Schlüsselwort:
- Das Schlüsselwort ist Informationsduft — es muss dem Zuschauer sofort verraten, worum es geht und ob die Geschichte für ihn relevant ist. Es ist der Zeitgeist dieser Geschichte in einem Wort.
- Das Schlüsselwort muss die Geschichte sofort identifizieren — ein Zuschauer, der 25 Schlüsselwörter überfliegt, soll die Nachrichten des Tages spüren
- Bekanntester Eigenname: Person („Odermatt"), Ort („Roveredo"), Organisation („NATO")
- Kein Eigenname? Spezifischer deutscher Begriff: „Eigenmietwert", „Cyberangriffe"
- Zweites Wort NUR bei Mehrdeutigkeit: „Trump NATO" vs „Trump Briefwahl"
- Maximal 2 Wörter wenn nötig, aber typischerweise eines
- Voller Vorname wenn nicht weltberühmt: „Muriel Furrer", nicht „Furrer"
- Keine Spitznamen, keine Insider-Abkürzungen, kein Englisch
- Wenn dasselbe Thema zweimal in dieser Sendung vorkommt, ein Schlüsselwort für beide verwenden

{keyword_instruction}

Transkript:
{transcript}
