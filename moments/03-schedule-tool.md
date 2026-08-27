# Момент 3 — тул расписания

**Файлы:** новый `tools/schedule_tool.py` (~470 строк), правки `toolsets.py`
(`school_schedule` в `_HERMES_CORE_TOOLS` + toolset `school` в TOOLSETS с описанием конфига).

## Что это
Тул `school_schedule` — еженедельное расписание группы с портала колледжа.
Порт логики из SEORA_bot (`utils/schedule_parser.py` + `schedule_loader.py`), переписан
на httpx + асинхронно, вшит в hermes registry (автодисковерия tools/*.py).

Схема: `{what: week|today|next, week_offset: 0|1, day: monday..sunday}`.
- week — вся неделя (или один день через day),
- today — занятия сегодня,
- next — что дальше сейчас по времени (первые до 3 пар).

## Конфиг (config.yaml)
```yaml
schedule:
  group: "ИТ24-12"
  url: "https://portal.it-college.ru/schedule25.php"  # или другой живой URL
  direct_json_url: ""   # опц. fallback, принимает тот же JSON-тело
  subgroup: "*"
  refresh_hours: 6
```
Тул показывается модели только когда `schedule.group` задан (check_fn).
Кэш: `<hermes_home>/schedule_cache.json`, запись на неделю; при сбое fetch отдаём
устаревший кэш с пометкой в ответ.

## Отличия от SEORA-версии
1. **URL-цепочка**: пробуем `url` → `direct_json_url` → дефолтный портал-URL
   (дедупликация). Причина: с внешних (наших) IP портал отдаёт 404 на
   schedule25.php — с сети колледжа он жив (SEORA работает). Если на серяке
   тоже будет 404, подставляем рабочий URL через `url`/`direct_json_url`.
2. **TLS**: пробуем verify=True, при ConnectError — fallback verify=False
   (у портала исторически кривая TLS-цепь, requests-версия ехала сразу с verify=False).
   **Баг, пойманный в тесте**: в httpx `verify` — параметр клиента, не запроса.
3. Пустая неделя не перетирает кэш (как в SEORA); события сортируются по времени.

## Проверено
- py_compile + ruff 0.15.10 — чисто.
- Живой прогон: fetch с этой машины упал (404, гео), пайплайн прогнан на
  синтетике — нормализация (SubGroup → "BE: Поток 2 каб.2-1"), формат недельного
  вида, «выходной», next-логика, фильтр по дню — всё корректно (см. вывод ниже
  в консоли, сохранилось в моменте 3). Живые данные с сети колледжа валидируем
  на серяке при деплое.