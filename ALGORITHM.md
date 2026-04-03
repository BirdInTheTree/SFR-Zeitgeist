---
type: decision
project: srf-10x10
status: active
---

# SRF Zeitgeist — алгоритм отбора слов

## Задача

Из субтитров SRF за последние 24 часа выбрать 100 фраз, которые определяют zeitgeist — "о чём говорит Швейцария прямо сейчас". Результат: сетка 10×10 с фразами и кадрами из эфира.

---

## Принцип: velocity, not volume

Не "самые частые фразы", а "самые быстро выросшие". Фраза попадает в сетку если сегодня она звучит **аномально часто** по сравнению с обычным фоном.

**Обоснование:** Google Year in Search methodology — "search terms that saw the highest increase in traffic compared to the same period last year. This approach deliberately excludes evergreen searches like 'weather' or 'news'." ([Google Trends Data Methodology](https://trends.withgoogle.com/year-in-search/data-methodology/))

---

## Единица анализа: noun phrases + named entities

Не отдельные слова, а **именные группы** (noun phrases) и **именованные сущности** (named entities), извлечённые spaCy из немецких субтитров.

| Что берём | Пример | Почему |
|-----------|--------|--------|
| Noun phrases (noun chunks) | "Kanton Bern", "Artemis-2-Mission" | Самодостаточные единицы смысла |
| Named entities (PER, ORG, LOC, GPE) | "Aline Trede", "NASA", "Florida" | Конкретные actor'ы событий |

| Что НЕ берём | Пример | Почему |
|--------------|--------|--------|
| Отдельные глаголы | "aufholt", "beleidigt" | Не несут значения без контекста |
| Отдельные прилагательные | "bäuerlichen", "azurblauen" | То же |
| Местоимения, частицы | "er", "Ahm", "ja" | Шум разговорной речи |

**Обоснование:** 
- GDELT Television News Ngram Dataset работает с n-grams (1-5 слов), а не с отдельными словами. ([GDELT TV News Ngram 2.0](https://blog.gdeltproject.org/announcing-the-television-news-ngram-2-0-dataset/))
- Harris 10x10 output: "aid", "tsunami", "disaster", "sri lanka" — всегда существительные или именные группы, никогда глаголы.
- Статья "Keyphrase Cloud Generation of Broadcast News" (Marujo et al. 2013): "keyphrases are usually nouns or noun phrases, verbs or verb phrases are less frequent."

---

## Главный фильтр: фраза в ≥2 разных программах

Фраза попадает в кандидаты только если она встречается **минимум в двух разных программах** за 24 часа.

**Что это решает:**

| Проблема | Пример | Почему фильтр работает |
|----------|--------|----------------------|
| Персонажи фикшн | "Holly" (Boiling Point) | Появляется только в одной программе |
| Кулинарные термины | "Karottenpüree" (Boiling Point) | Только в одной программе |
| Разговорный мусор | "Ahm" | Стилистика одного ведущего |
| Случайные имена | "Siggi" (Frühling) | Персонаж одного фильма |
| **Публичные фигуры** | "Aline Trede" (Rundschau + Schweiz aktuell) | **Проходит** — обсуждается в нескольких программах |
| **Новостные темы** | "NASA" (Tagesschau + 10vor10) | **Проходит** — покрыта несколькими программами |
| **События** | "Artemis-Mission" (Tagesschau + 10vor10 + Wissen) | **Проходит** |

**Обоснование:**
- Harris использовал несколько источников (Reuters, BBC, NYT). Слово попадало в топ если оно появлялось **across sources**. Повторяющиеся изображения в сетке = визуальный индикатор важности. ("When we see a frequently repeated image, we know it's important." — Harris, RESEARCH.md)
- Google: trending query определяется по spike **across users**, не по одному пользователю.
- GDELT: trending terms определяются по spike **across news sources**.
- Multi-source appearance = фундаментальный индикатор значимости в media studies (agenda-setting theory: тема становится "важной" когда её подхватывают несколько медиа).

---

## Evergreen подавление: автоматическое

Не нужен ручной стоп-лист ("Schweiz", "heute", "Sendung"). Spike-расчёт автоматически подавляет слова с высоким baseline:

```
spike("Schweiz") = freq_today("Schweiz") / avg_freq_14days("Schweiz")
                 = 50 / 48 = 1.04  → почти не изменилось → низкий score

spike("Artemis") = freq_today("Artemis") / avg_freq_14days("Artemis")  
                 = 25 / 0.5 = 50.0  → резкий рост → высокий score
```

**Обоснование:** Google Year in Search: "This approach deliberately excludes evergreen searches." Механизм — сравнение с baseline, не ручной список.

---

## Ранжирование: spike × coverage

```
score = spike × log₂(program_count)
```

Где:
- **spike** = частота фразы за 24h / средняя частота за 14 дней
- **program_count** = количество разных программ где фраза появилась

`log₂` нужен чтобы coverage влиял, но не доминировал:
- 2 программы: log₂(2) = 1.0
- 4 программы: log₂(4) = 2.0
- 8 программ: log₂(8) = 3.0

Фраза с spike 50 в 2 программах (score=50) проигрывает фразе с spike 30 в 8 программах (score=90). Широкое покрытие важнее экстремального spike.

---

## Временные окна

| Окно | Роль | Размер |
|------|------|--------|
| **Target** | Что сейчас обсуждается | Rolling 24 часа |
| **Reference** | Что обычно обсуждается | Предыдущие 14 дней |

Rolling 24h: нет обнуления в полночь. В 14:00 вторника target = 14:00 понедельника → 14:00 вторника. Каждый час: новый час добавляется, старейший уходит.

**Обоснование:** GDELT использует rolling comparison ("comparing the day's terms against their popularity over the previous two weeks"). Google Trends: "compared to the same period last year" (rolling baseline).

---

## Pipeline

```
[EPG API] → список программ за 24h
     ↓
[Integration Layer] → VTT субтитры для каждой программы
     ↓
[Очистка] → убрать HTML-теги, таймкоды, мусор
     ↓
[spaCy de_core_news_md] → извлечь noun phrases + named entities
     ↓
[Подсчёт частот] → target (24h) и reference (14 дней)
     ↓
[Spike] → target_freq / reference_avg_freq для каждой фразы
     ↓
[Фильтр] → оставить только фразы в ≥2 программах
     ↓
[Score] → spike × log₂(program_count)
     ↓
[Ранжирование] → топ-100 по score
     ↓
[Картинки] → для каждой фразы: кадр из видео по таймкоду (ffmpeg)
     ↓
[Сетка 10×10] → JSON для фронтенда
```

---

## Карточка слова (zoom view)

При клике на ячейку — показывать **все программы** где фраза встретилась (как у Harris: "HEADLINES: click to read articles"):

```
tsunami
HEADLINES: (click to watch)
1. Tagesschau — "Die Artemis-2-Mission startet..."
2. 10 vor 10 — "NASA bestätigt den Starttermin..."
3. Wissen@SRF — "Die Reise zum Mond dauert..."
```

Каждая ссылка ведёт на Play SRF.

---

## Источники

- Google Year in Search Data Methodology: [trends.withgoogle.com](https://trends.withgoogle.com/year-in-search/data-methodology/)
- GDELT Television News Ngram 2.0: [blog.gdeltproject.org](https://blog.gdeltproject.org/announcing-the-television-news-ngram-2-0-dataset/)
- GDELT Topic Mining with Ngrams: [blog.gdeltproject.org](https://blog.gdeltproject.org/topic-mining-the-worlds-news-with-gdelt-with-ngrams-felipe-hoffa/)
- BERTrend (Boutaleb et al. 2024): [arxiv.org/abs/2411.05930](https://arxiv.org/abs/2411.05930)
- WISDOM (2024): [arxiv.org/abs/2409.15340](https://arxiv.org/abs/2409.15340)
- Keyphrase Cloud Generation of Broadcast News (Marujo et al. 2013): [arxiv.org/abs/1306.4606](https://arxiv.org/abs/1306.4606)
- Ben Mansour et al. 2025 — LLM vs traditional keyword extraction: [ACL AISD](https://aclanthology.org/2025.aisd-main.2.pdf)
- Jonathan Harris 10x10 (2004): [jjh.org/10x10](https://jjh.org/10x10), [tenbyten.org documentation](https://web.archive.org/web/20050227035405/http://www.tenbyten.org/info.html)
