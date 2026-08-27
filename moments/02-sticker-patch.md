# Момент 2 — патч стикеров (native pixels)

**Файл:** `plugins/platforms/telegram/adapter.py` (`_handle_sticker`, был 10301-10364)

## Было
Статичный WEBP-стикер: скачать → auxiliary vision-модель описывает (`vision_analyze_tool`)
→ кэш описания по file_unique_id → в промпт только текстовая инъекция. Аним/видео —
эмодзи-инъекция. Проблема: наша нативная мультимодальная модель (GLM-5.3-flash) не видела
самих стикеров — только lossy-описание от aux. Для чата 24-12 (стикер = экспрессия) —
неприемлемо.

## Стало
Статичный стикер: скачать WEBP → `cache_image_from_bytes` →
`event.media_urls=[path]`, `event.media_types=["image/webp"]` + текстовая подсказка
"static sticker 😄 from 'pack'~ attached below as an image" (+ кэшированное описание
ранее, если кэш есть). Дальше штатный `gateway/run.py`-pipeline сам решает по session-модели:
- native: пиксели как image_url-контент-парты (наша модель);
- text: пред-описание через vision-модель (фолбэк для текстовых моделей — поведение
  эквивалентное старому, только описывает штатный pipeline).
- download-error: кэш-описание, иначе "could not be loaded".
Аним/видео: без изменений (эмодзи-подсказка).

`sticker_cache.py` не тронут (чистые функции, тесты `tests/gateway/test_sticker_cache.py`
проходят без изменений). Обновлён комментарий в call-site ~9983.

## Проверено
- `_event_media_is_image` в run.py доверяет per-attachment MIME `image/webp` → image ✓
- message_type STICKER не мешает: image-ветка определяется MIME'ом, не type'ом ✓
- тесты на _handle_sticker-поведение в репо нет (только кэш-фукции) ✓