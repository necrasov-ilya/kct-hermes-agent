# Момент 4 — привязка ключей, смоук-тест гейтвея, деплой-бандл

## Ключи (локальная разработка)
- Профиль: `~/.hermes-kct/` (отдельный от родного профиля пользователя, ничего
  не перезаписали):
  - `.env` (chmod 600): `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`
  - `config.yaml`: model `z-ai/glm-5.3-flash` (provider openrouter,
    `supports_vision: true` на всякий случай), `agent.image_input_mode: auto`,
    `schedule.group: ИТ24-12` + url портала, `terminal.backend: local`,
    `gateway.platforms.telegram: enabled, require_mention: false`,
    закомментированный блок `allowed_chats`.
  - `SOUL.md`: скопирована ролька.

## Проверка провайдера (прямые запросы к OpenRouter API)
- Текстовый ход: 200, «Да».
- Вижн: 400 на моих кривых handcrafted-HEX-webp → перепроверка настоящим Pillow-
  изображением (64x64, красный квадрат): PNG и WEBP data-URL оба 200, модель
  ответила «Красный квадрат на белом» — **нативный vision у GLM-5.3-flash через
  OpenRouter работает, aux-модель не нужна**.

## Смоук-тест гейтвея (локальный запуск, 2 раза по ~2 мин)
Запуск: `HERMES_HOME=~/.hermes-kct uv run hermes gateway` (uv sync --extra messaging
отработал, deps все на месте).
- `~/.hermes-kct/logs/gateway.log`:
  `[Telegram] Connected to Telegram (polling mode)` → `✓ telegram connected` →
  `set_my_commands OK (60 cmds)` (токен валиден, бот жив) → чистое
  отключение по моему SIGTERM.
- Ошибок конфигурации/модели нет. Предупреждение об allowlist (без списка
  пользователей неизвестные отправители будут отказаны) учтено: в deploy-шник
  заложено «открыть GATEWAY_ALLOW_ALL_USERS или заполнить allowed_chats».
- Замечание: `schedule25.php` с нашей наружной сети — 404 (с сети колледжа живет,
  SEORA строилась на нём). On server это решается сетью или `direct_json_url`.

## Деплой-бандл в репо
- `deploy/README.md` — процедура для сервака.
- `deploy/SOUL.md`, `deploy/config.yaml` — без секретов.
- `deploy/deploy.sh [HERMES_HOME]` — uv sync --extra messaging + копирование
  конфига/роли + подсказка про .env и установку сервиса.

## Что осталось сделать пользователю (сервер)
1. Киднуть бота в чат 24-12 (и в тестовую группу), у бота отрубить privacy mode
   у BotFather (`/setprivacy` → Disable), иначе в группе он видит только
   команды/реплаи — и тогда смысл observe-режима теряется.
2. На серяке: клон форка → `./deploy/deploy.sh ~/.hermes` → свой `.env` с ключами
   → `hermes gateway start` → проверить расписание командой «что у нас завтра?».
3. Если расписание 404 с сети сервака — подставить рабочий URL в
   `schedule.url` / `schedule.direct_json_url`.
4. Лор про преподов/директора МСа — допиливается в `SOUL.md` без пересборки.

## Итог
Рантайм патчен (стикеры — нативные пиксели), тул расписания написан и прогнан,
ролька написана (антикринж-правила), ключи привязаны, гейтвей на реальных токенах
поднимается и подключается к Telegram. Код: `git status` покажет 3 изменённых
файла (plugins/platforms/telegram/adapter.py, toolsets.py) + новые
tools/schedule_tool.py, moments/, deploy/ — коммитить не коммитил, на тебе.