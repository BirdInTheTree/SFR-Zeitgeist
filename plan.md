---
type: plan
project: srf-10x10
status: active
---

# SRF 10x10 — визуальный снимок швейцарского эфира

## Идея
Интерпретация Jonathan Harris 10x10 (2004) на данных SRF. Сетка 10x10 содержательных слов из субтитров — "о чём говорит Швейцария прямо сейчас." Обновляется каждый час.

## Зачем
- Демо для заявки на PO AI National AI Service Team, SRF
- Показывает: "я понимаю ваши данные, ваш API, и могу сделать из них продукт для зрителя"
- Показывает gap: от show-centric навигации к topic-centric

## Данные
- **EPG API**: `srf.ch/play/v3/api/srf/production/tv-program-guide?date=YYYY-MM-DD` — без ключа, ~158 программ/день, ~6-7 в час
- **Integration Layer 2.1**: `il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn/{urn}` — метаданные + ссылки на субтитры
- **Субтитры**: VTT файлы (прямые URL), ~75% программ имеют субтитры
- **Prime time час (20:00, 1 апреля)**: 4 программы, 22K слов, 3 из 4 с субтитрами

## Операционализация "содержательного слова"
Подход: trend detection (BERTrend, ACL 2024) + контент-анализ.
- На уровне часа: BERTopic (embeddings → clustering → c-TF-IDF)
- При накоплении данных: BERTrend (temporal trend detection, signal classification: noise / weak / strong)
- Метод определения: см. Ben Mansour et al. 2025 (LLM > YAKE > TextRank на F1), BERTrend (Boutaleb et al. 2024)

---

## План по шагам

### Шаг 1. Скачать и сохранить субтитры ✅
**Что:** берём EPG за конкретную дату и час → для каждой программы с `mediaUrn` скачиваем VTT субтитры.
**Скрипт:** `fetch_subtitles.py`
**Вход:** дата, час (например 2026-04-01, 20:00)
**Выход:** `demo-data/hour_20_programs.json` (метаданные + текст субтитров)
**Статус:** ✅ сделано, данные есть

### Шаг 2. Очистить субтитры
**Что:** VTT содержит HTML-теги (`<font color="#00ffff">`), таймкоды, номера блоков, точки-заглушки. Нужно убрать всё кроме чистого текста.
**Скрипт:** `clean_subtitles.py`
**Вход:** `hour_20_programs.json` с сырым subtitle_text
**Выход:** `hour_20_clean.json` с чистым текстом (без HTML, без таймкодов)
**Проверка:** глазами — открыть и посмотреть что текст читаемый

### Шаг 3. Извлечь содержательные слова
**Что:** из чистого текста субтитров → список содержательных слов с весами.
**Метод:** начать с BERTopic (embeddings + c-TF-IDF). Если результат плохой — попробовать YAKE, затем LLM.
**Скрипт:** `extract_keywords.py`
**Вход:** `hour_20_clean.json`
**Выход:** `hour_20_keywords.json` — список слов с весами, привязкой к программе и таймкоду
**Проверка:** глазами — слова должны быть осмысленные, не "der", "und", "font"

### Шаг 4. Ранжировать и выбрать топ-100
**Что:** из всех слов всех программ → единый ранжированный список. Топ-100 → сетка 10x10.
**Логика:** 
- Вес = c-TF-IDF из BERTopic (или TF-IDF, если BERTopic не подходит)
- Имена собственные (PROPN) получают бонус — они информативнее
- Дедупликация (лемматизация)
**Скрипт:** `build_grid.py`
**Вход:** `hour_20_keywords.json`
**Выход:** `hour_20_grid.json` — 100 слов, упорядоченные по весу, с метаданными (источник, таймкод)
**Проверка:** глазами — сетка должна "рассказывать" о чём был час эфира

### Шаг 5. Визуализация (фронтенд)
**Что:** HTML/CSS сетка 10x10. Hover → программа + цитата. Клик → ссылка на Play SRF.
**Файлы:** `frontend/index.html`, `frontend/style.css`, `frontend/app.js`
**Вход:** `hour_20_grid.json`
**Проверка:** открыть в браузере, hover/click работают

### Шаг 6 (позже). Автоматизация
- Скрипт забирает данные каждый час
- Накопление истории → включаем BERTrend (temporal trends, signal classification)
- "Вчера vs сегодня" — как менялись темы

---

## Текущий фокус
**Шаг 2** — очистить субтитры от HTML-мусора. Данные шага 1 уже есть.

## Стек
- Python 3.13, venv: `~/venvs/SFR_env/`
- BERTopic (уже установлен через bertrend)
- spaCy `de_core_news_md` (нужно установить — для POS-фильтрации и лемматизации)
- Frontend: Vanilla HTML/CSS/JS

## Файловая структура
```
1-projects/SFR/
├── plan.md
├── demo-data/
│   ├── hour_20_programs.json     ← сырые данные (шаг 1) ✅
│   ├── Rundschau.vtt
│   ├── Boiling_Point.vtt
│   ├── Sternstunde_Philosophie.vtt
│   └── subtitles_for_bertrend.csv
├── backend/
│   ├── fetch_subtitles.py
│   ├── clean_subtitles.py        ← шаг 2
│   ├── extract_keywords.py       ← шаг 3
│   └── build_grid.py             ← шаг 4
└── frontend/
    ├── index.html                ← шаг 5
    ├── style.css
    └── app.js
```
