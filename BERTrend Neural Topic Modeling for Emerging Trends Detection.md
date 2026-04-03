BERTrend (ноябрь 2024, ACL) — главная находка

  

  Статья прямо для нашей задачи. Тестировалась на New York Times (184K статей, 2019-2023).

  

  Как работает:

  1. Документы делятся на временные окна (у них — 2 дня для новостей)

  2. BERTopic извлекает темы из каждого окна (embeddings → UMAP → HDBSCAN → class-based

  TF-IDF)

  3. Темы сравниваются между окнами по cosine similarity — новые vs продолжающиеся

  4. Метрика популярности: количество документов + exponential decay по времени. Если тема

  перестала появляться — она затухает

  5. Классификация сигналов: noise (ниже 10 перцентиля) / weak signal (10-50%) / strong signal

   (выше 50%)

  

  Почему это работает для нас:

  - Временные окна = наши часы
  - Документы = субтитры программ
  - Strong signal = то что попадает в 10x10 сетку
  - Decay = вчерашние темы уходят, сегодняшние поднимаются


  Ключевое: они не используют LLM для извлечения — используют BERTopic (embeddings +clustering). LLM только опционально для генерации человекочитаемых описаний трендов.
  TDT — классика
 Topic Detection and Tracking — целая research program (с конца 90-х), изначально для broadcast news. Буквально наш случай. Современное обновление — time-aware document embeddings (LREC-COLING 2024).

  

  Burst detection

 Google Trends использует statistical heuristics, X (Twitter) — Poisson models для token  bursts. Это похоже на IDF-подход — "слово стало появляться чаще чем обычно".

  

  ---

  Что это значит для нашего проекта

  

  Можно не изобретать велосипед. BERTrend — готовый open-source фреймворк. Вопрос: нужен ли

  нам он целиком, или мы берём только идею (временные окна + popularity metric + signal

  classification)?

  

  Для MVP на одном часе достаточно упрощённой версии:

  - embeddings субтитров → clustering → keywords из кластеров

  - Без decay пока (у нас один час)

  - Когда добавим историю — включаем decay и signal classification