---
type: decision
project: srf-10x10
status: active
---

# SRF Zeitgeist — журнал решений

## Название
**SRF Zeitgeist** — не "10x10" (это бренд Harris'а). "Zeitgeist" — дух времени, что Швейцария обсуждает прямо сейчас.

## Размер сетки
- Harris: 10x10 = 100 слов из десятков источников (Reuters, BBC, NYT)
- У нас: один broadcaster (SRF), ~98 программ/день
- **Решение**: пробуем 10x10 = 100, но с правилом "одно лучшее слово на программу" чтобы обеспечить разнообразие
- Если 100 слишком — fallback на 7x7 = 49

## Источник данных
- **EPG API**: `srf.ch/play/v3/api/srf/production/tv-program-guide?date=YYYY-MM-DD` — бесплатно, без ключа, ~158 программ/день, **только последние ~2 недели**
- **Integration Layer 2.1**: `il.srgssr.ch/integrationlayer/2.1/mediaComposition/byUrn/{urn}` — метаданные + субтитры + видеопоток. Работает для любого URN (не ограничено 2 неделями)
- **Субтитры**: VTT формат, ~75% программ, прямые URL. Содержат таймкоды.
- **SRF Developer Portal API key**: `ulxLcVYS9tcgQHWB6Cv2TOytW6lsK1g8` (Video + Subtitles + Archives + Articles-pending)

## Данные (на 2 апреля 2026)
- 15 дней (18 марта — 1 апреля), 1172 программы, 3.5 млн слов
- EPG не отдаёт данные старше ~2 недель, но субтитры по URN живут дольше

## Метод извлечения ключевых слов

### Операционализация "содержательного слова"
Подход: **keyness** (corpus linguistics) — слово которое в target-период встречается статистически чаще чем в reference-период.

### Pipeline
```
Субтитры (VTT) → очистка HTML → spaCy (de_core_news_md)
→ POS-фильтр (NOUN, PROPN, VERB, ADJ)
→ лемматизация → стоп-лист
→ keyness: target (этот час/день) vs reference (остальные дни)
→ ранжирование → топ-N
```

### Методы которые пробовали (сравнение на данных 20:00 1 апреля)
| Метод | Результат | Вердикт |
|-------|-----------|---------|
| YAKE | Musk, Stadt, Bern, Iran — хорошие; Okay, Hey — мусор | Приемлемо |
| BERTopic c-TF-IDF | stadt, bern, kinder — только Rundschau доминирует | Плохо на малых данных |
| Keyness (vs week) | imam, chamenei, islamisch, epfl — специфика часа | Лучший для "что нового" |
| TF-IDF (sklearn) | Musk, stadt, okay — похоже на YAKE | Приемлемо |

**Выбор: keyness** — лингвистически обоснован, выявляет "что необычно сейчас", reference corpus масштабируется.

### Правило разнообразия
**Одно лучшее слово от каждой программы** (по keyness), потом второй круг. Решает:
- Разнообразие (не 36 слов из одной Tagesschau)
- Уникальные картинки (каждая программа = свой thumbnail или кадр)

### Литература
- Ben Mansour et al. 2025 (ACL): LLM > YAKE > TextRank для keyword extraction (F1)
- Boutaleb et al. 2024 (ACL): BERTrend — temporal trend detection, signal classification
- Campos et al. 2020: YAKE — unsupervised, multilingual, тестирован на немецких новостях
- Scott 1997: keyness в corpus linguistics
- Harris 2004: 10x10 — weighted linguistic analysis на RSS

## Фотографии

### Источник
- **Thumbnail программы**: один на весь выпуск, из Integration Layer (`imageUrl`)
- **Кадр из видео по таймкоду** (лучше): слово "Apple" на 02:15 → ffmpeg извлекает кадр на 02:15. Каждое слово = свой уникальный кадр.

### Правила smart crop (image_rules.md)
1. Убрать чёрные полосы (pillarbox/letterbox)
2. Face detection → кроп центрирован на лице
3. Голова целиком в кадре (margin 1.2x face_h сверху)
4. Лицо в верхних 35% кропа (не по центру)
5. Текст на изображении сохранять целиком (логотипы, заголовки)
6. Fallback без лица: нижние 60% (ТВ action area)
7. Target ratio 4:3, resize 280x210, JPEG q85

### Инструменты
- `face_recognition` (dlib) — face detection
- `PIL/Pillow` — crop, resize
- `ffmpeg` — извлечение кадров из видео по таймкоду

## Дизайн фронтенда

### Принципы (из скетча Harris'а)
- "Simple presentation layer. Let the data speak."
- "THE PICTURE must say & show all of this at once."
- "Artwork that grows" — живёт и меняется со временем
- "HOURLY SNAPSHOTS"

### Лейаут
- Сетка ~78% ширины, список слов ~22% справа
- Ячейки прямоугольные (4:3, как телевизор)
- Gap 3px между ячейками
- Белый фон, чёрная типографика, красный акцент

### Взаимодействие (как у Harris)
- Hover на картинке → слово появляется поверх, соответствующее слово справа подсвечивается
- Hover на слове → картинка подсвечивается в сетке
- **Двусторонняя связь**
- Активное слово: крупное (24px), красное
- Соседи ±1: 16px, тёмные
- Соседи ±3: 12px
- Соседи ±6: 10px
- Остальные: 9px базовый
- **Эффект "рыбьего глаза"** — padding увеличивается у соседей, раздвигает список
- Клик → zoom с изображением + цитата + ссылка на Play SRF
- Второй клик → fullscreen со словом поверх (полупрозрачная полоса)
- Esc закрывает. Стрелки переключают часы.

### Навигация
- Footer: дата + час + "previous hour · next hour · history"

### Шрифт
- DM Sans — чистый, не generic (не Inter/Roboto/Arial)

## Архитектура (rolling 24h window)
- **Target**: всегда последние 24 часа (rolling, без обнуления в полночь)
- **Reference**: предыдущие 14 дней (без target-периода)
- Каждый час: добавляем новый час, убираем самый старый из target window
- Keyness пересчитывается каждый час
- Снапшот сохраняется как JSON
- Размер сетки: **10x10 = 100 слов**

## Картинки — кадры из видео по таймкоду
- Не thumbnail программы (один на весь выпуск), а **кадр из видео в момент произнесения слова**
- VTT субтитры содержат таймкоды → находим когда слово произнесено
- ffmpeg извлекает кадр: `ffmpeg -ss TIMECODE -i HLS_URL -frames:v 1 frame.jpg`
- Результат: каждое слово = свой уникальный кадр
- Smart crop применяется к извлечённому кадру

## Получение данных за 4+ недели
- EPG API ограничен ~2 неделями
- **Show episodes API** (`/play/v3/api/srf/production/videos-by-show-id`) отдаёт эпизоды за месяцы/годы
- 247 TV-шоу, пагинация по 20 эпизодов
- Субтитры по URN доступны независимо от возраста EPG

## Стек
- Python 3.13, venv: `~/venvs/SFR_env/`
- spaCy `de_core_news_md` — POS, лемматизация
- face_recognition (dlib) — face detection для smart crop
- BERTopic (установлен, может понадобиться)
- ffmpeg — извлечение кадров
- Frontend: vanilla HTML/CSS/JS, DM Sans font
