# Deploy KCT 24-12 Hermes Agent

Non-secret config bundle lives here. Secrets (`.env` with
`OPENROUTER_API_KEY` + `TELEGRAM_BOT_TOKEN`) are kept in `~/.hermes/.env`
on the server and are NOT part of this repo.

## Files
- `deploy/SOUL.md`         — persona (onegroupnik 24-12, dry tech humor, [SILENT] discipline)
- `deploy/config.yaml`     — template of `~/.hermes/config.yaml` (no secrets)
- `deploy/deploy.sh`       — one-shot server install script

## Server procedure
1. On the server: `git clone <fork-url> ~/kct-hermes && cd ~/kct-hermes`
2. `./deploy/deploy.sh` (installs uv deps, copies config into $HERMES_HOME)
3. Put your real `~/.hermes/.env` with the two keys (the local
   `~/.hermes-kct/.env` from the dev machine can be `scp`'d over).
4. `HERMES_HOME=~/.hermes hermes gateway install` then `hermes gateway start`.
5. Add the bot to the 24-12 group (admin: disable privacy mode via BotFather,
   or add it to `group_allow_from`/`allowed_chats` in config.yaml).

## Known quirks (as of 2026-09-06)
- The old public endpoint `portal.it-college.ru/schedule25.php` is dead
  ("Портал на ремонте!"); schedules now live behind the student-portal login
  at `students.it-college.ru/Schedule/schedule26.php`. The tool logs in
  through `schedule.login_url` with credentials read from `.env`
  (`STUDENTS_USERNAME` / `STUDENTS_PASSWORD`; or `STUDENTS_SESSION` for a
  pre-made session-cookie value). Credentials never live in config.yaml or
  source.
- GLM-5.3-flash on OpenRouter is validated for text + image (vision) turns.
- macOS dev boxes may see "SQLite 3.50.4 WAL bug" warnings — harmless;
  server Linux distros are typically on 3.51+.