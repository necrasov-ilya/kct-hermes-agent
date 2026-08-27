# Момент 1 — разведка рантайма (Telegram + медиа + групповые режимы)

Дата: 2026-08-27. Репо: форк NousResearch/hermes-agent (kct-hermes-agent, ветка main).

## Выводы

### 1. Медиа в Telegram УЖЕ реализованы (гадж — не надо писать с нуля)
`plugins/platforms/telegram/adapter.py`:
- **Фото**: скачиваются в кэш (`cache_image_from_bytes`), кладутся в `event.media_urls` /
  `event.media_types` (adapter.py:9996-10025). Дальше `gateway/run.py` (~18711-18850) решает
  на каждый ход: модель нативно видит картинки → пиксели прикладываются как `image_url`
  контент-парты (native); нет → пред-анализ через vision-модель, текст-описание вставляется
  в сообщение (text mode). Логика: `agent/image_routing.py::decide_image_input_mode`,
  режим читается из `agent.image_input_mode` (auto|native|text, default auto).
- **Фолбэк capability**: models.dev-каталог + переопределение в конфиге:
  `model.supports_vision: true` (топовый шорткат для активной модели) или
  `providers.<provider>.models.<model>.supports_vision: true`.
- **Аудио/голосовые** → автостт; **видео** → конотка с path; **доки** → конотка с path.

### 2. Стикеры — ЕДИНСТВЕННОЕ место, где стоит патч
`adapter.py::_handle_sticker` (10301-10367):
- статичный WEBP-стикер: скачать → описать через auxiliary vision-модель
  (`tools.vision_tools.vision_analyze_tool` + `STICKER_VISION_PROMPT`) → кэш описания
  по `file_unique_id` в `~/.hermes/sticker_cache.json` (`gateway/sticker_cache.py`) →
  в текст сообщения вместо пикселей.
- аним/видео-стикеры: текстовая инъекция по эмодзи.
- **Проблема для нашего бота**: главная модель (GLM-5.3-flash) нативно мультимодальная,
  но стикер она получает lossy-описанием от чужой aux-модели, а не самими пикселями.
  В учебном чате стикер = 90% экспрессии, описание убивает интент.

**Патч**: статичный стикер → скачать WEBP → `event.media_urls=[path]` +
`event.media_types=["image/webp"]` + короткая текстовая подсказка (эмодзи/пак +
кэшированное описание, если есть). Дальше штатный pipeline run.py сам решает
native/text по session-модели. `image/webp` MIME доверен как image
(run.py `_event_media_is_image` строка ~3105, доверяет per-attachment MIME).
Аним/видео — как есть (эмодзи-подсказка).

Проверка: models.dev-каталог в OpenRouter API отдаёт для `z-ai/glm-5.3-flash`
input_modalities = [text, image, video], ctx 1.3M, цена ~$0.000000075/prompt-токен.
Т.е. нативный vision есть, aux vision-модель НЕ нужна. На случай если models.dev
ещё не знает про модель — зашьём `model.supports_vision: true` в конфиг.

### 3. Групповые режимы (всё в конфиге, код трогать не надо)
`extra:` секция telegram в gateway-config:
- `require_mention: true` — бот отвечает только на @упоминания/реплаи; всё остальное
  мимо (или в observe-режим ниже).
- `require_mention: false` (default) — каждое сообщение группы = запрос к агенту;
  агент сам решает отвечать или молчать. **Это наш режим** для чата 24-12:
  персона + `[SILENT]`-токены гейтвея (точно один из `[SILENT]`/`SILENT`/`NO_REPLY`/
  `"NO REPLY"` = ответ не доставляется, ход сохраняется в транскрипте — контекст живой).
- `observe_unmentioned_group_messages: true` + `observe_chats: [...]` — вариант
  "видит всё, отвечает на mention"; не наш, но есть.
- `allowed_chats` / `group_allow_from` / `dm_policy`/`group_policy` — доступ.
- per-канал: в gateway `~/.hermes/gateway-config.yaml` → `platforms.telegram.channel_overrides`
  по id канала: `model` / `system_prompt` (эфемерный промпт на ход) / provider.
  **Сюда положим персона-промпт 24-12.**

### 4. Регистрация тулзов (для расписания)
- Тул = `registry.register(name=..., toolset=..., schema=..., handler=..., is_async=...)`
  из `tools/registry.py`; любой `tools/*.py` подхватывается автодисковерией
  (`discover_builtin_tools`, glob tools/*.py + import).
- См. образец: `tools/vision_tools.py` (schema + handler + register, ~1720-1815).
- Toolset `hermes-telegram` (toolsets.py:489) = `_HERMES_CORE_TOOLS`; новый тул
  добавим в `_HERMES_CORE_TOOLS` (или отдельный toolset "school" включим в него).
- Конфиг тула: `hermes_cli.config.load_config()` / `cfg_get(cfg, "schedule", ...)`.
- Кэш-файл: `hermes_constants.get_hermes_dir()`.

### 5. Логика расписания в SEORA_bot (портируем)
- Источник: POST `https://portal.it-college.ru/schedule25.php`, JSON в теле:
  `{"group": "ИТ24-11", "subgroup": "*", "d_start": "YYYY-MM-DD", "d_end": "..."}`
  (запрашивают широкое окно -7..+21 день от понедельника, фильтруют локально на неделю).
- Ответ чаще HTML: парсят JSON-массив из `<script>`/regex, фолбэк — FullCalendar-карточки.
- Нормализация: события {start,title,room,SubGroup[{SGrID,STitle,SGCaID}]} →
  по дням {monday..sunday: [{time:"HH:MM-HH:MM", subject, room, subgroups[]}]}.
- Неделя: пн-чт = current, пт-вс = next (SEORA), refresh на each tool call.
- У нас группа **ИТ24-12** (SEORA — 24-11), всё остальное 1:1.

## Что делаем (план)
1. Патч `_handle_sticker` — нативные пиксели для статичных стикеров.
2. Новый `tools/schedule_tool.py` — тул `school_schedule(what=week|today|next, week_offset)`,
   порт фетча/парсера SEORA на httpx + кэш в hermes home + конфиг `schedule.*`.
3. Register toolset "school", включить в `_HERMES_CORE_TOOLS`.
4. Конфиг-бандл для сервака (отдельно от секретов): config.yaml-фрагмент,
   gateway-config.yaml (telegram + channel_overrides), SOUL.md-персона.
5. Локальная проверка: импорт/линт, юнит-прогон парсера расписания на живом ответе портала.