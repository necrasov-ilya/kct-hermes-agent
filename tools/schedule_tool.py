#!/usr/bin/env python3
"""
School Schedule Tool

Fetches the weekly class schedule for a configured group from the college
portal (JSON POST API, with HTML-embedded-JSON fallback) and answers questions
like "what classes do we have this week / today / what's next".

Ported from the SEORA_bot schedule module (portal.it-college.ru/schedule25.php).

Configuration (config.yaml):
    schedule:
      group: "ИТ24-12"
      url: "https://portal.it-college.ru/schedule25.php"   # optional (may change)
      direct_json_url: ""                                  # optional fallback (see below)
      subgroup: "*"                                        # optional
      refresh_hours: 6                                     # optional

Cache: <hermes_home>/schedule_cache.json (one entry per week, re-fetched when
stale or when the week rolls over).

If the portal's POST endpoint 404s (server changes), set ``direct_json_url``
to any URL that accepts the same JSON body and returns the event array (or
JSON embedded in HTML) — the same fetch/parse pipeline is applied.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://portal.it-college.ru/schedule25.php"
REQUEST_TIMEOUT = 20.0

WEEKDAY_KEYS = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

DAY_RU = {
    "monday": "Пн",
    "tuesday": "Вт",
    "wednesday": "Ср",
    "thursday": "Чт",
    "friday": "Пт",
    "saturday": "Сб",
    "sunday": "Вс",
}

DAY_RU_FULL = {
    "monday": "Понедельник",
    "tuesday": "Вторник",
    "wednesday": "Среда",
    "thursday": "Четверг",
    "friday": "Пятница",
    "saturday": "Суббота",
    "sunday": "Воскресенье",
}

# Matches array-of-objects JSON blobs embedded in HTML (e.g. inside <script>).
_JS_ARRAY_RE = re.compile(r"\[(?:\s*\{[\s\S]*?\}\s*,?\s*)+\]")


def _cache_path():
    from hermes_constants import get_hermes_dir

    return get_hermes_dir() / "schedule_cache.json"


def _schedule_settings() -> Dict[str, Any]:
    """Read the schedule.* config block. Returns {} when unconfigured."""
    try:
        from hermes_cli.config import cfg_get, load_config

        cfg = load_config()
        group = str(cfg_get(cfg, "schedule", "group") or "").strip()
        url = str(cfg_get(cfg, "schedule", "url") or "").strip() or DEFAULT_URL
        direct_url = str(cfg_get(cfg, "schedule", "direct_json_url") or "").strip()
        subgroup = str(cfg_get(cfg, "schedule", "subgroup") or "").strip() or "*"
        refresh_hours = float(cfg_get(cfg, "schedule", "refresh_hours") or 6)
        if not group:
            return {}
        return {
            "group": group,
            "url": url,
            "direct_json_url": direct_url,
            "subgroup": subgroup,
            "refresh_hours": max(refresh_hours, 0.25),
        }
    except Exception:
        return {}


def check_schedule_requirements() -> bool:
    """Tool is listed only when a schedule group is configured."""
    return bool(_schedule_settings())


async def _fetch_events(settings: Dict[str, Any], monday: datetime) -> List[Dict[str, Any]]:
    """POST the portal endpoint and return raw event dicts for the week.

    Tries the configured ``url`` first, then the optional ``direct_json_url``
    fallback, then the default portal URL (deduplicated). This survives the
    known case where the portal 404s the PHP endpoint on some networks while a
    mirror/fresh URL works, and vice versa.
    """
    week_start = monday
    week_end = monday + timedelta(days=6)
    # The portal returns truncated data on narrow ranges; ask a wider window
    # and filter locally to the exact week.
    broad_start = (monday - timedelta(days=7)).strftime("%Y-%m-%d")
    broad_end = (monday + timedelta(days=21)).strftime("%Y-%m-%d")

    url_order: List[str] = []
    for candidate in (settings.get("url"), settings.get("direct_json_url"), DEFAULT_URL):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in url_order:
            url_order.append(candidate)

    async def _post(url: str, verify: bool):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=verify) as client:
            return await client.post(url, headers=headers, json=payload)

    text = ""
    last_error = "no schedule url available"
    for url in url_order:
        payload = {
            "group": settings["group"],
            "subgroup": settings["subgroup"],
            "d_start": broad_start,
            "d_end": broad_end,
        }
        headers = {
            "Content-Type": "application/json;charset=utf-8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "User-Agent": "Mozilla/5.0",
        }
        try:
            resp = await _post(url, True)
        except httpx.ConnectError:
            # Broken TLS chain: retry without verification.
            try:
                resp = await _post(url, False)
            except Exception as e:
                last_error = f"connect to {url} failed: {e}"
                continue
        except Exception as e:
            last_error = f"connect to {url} failed: {e}"
            continue
        if resp.status_code != 200:
            last_error = f"{url} returned HTTP {resp.status_code}"
            continue

        text = resp.text or ""

        # 1) Direct JSON body.
        try:
            data = resp.json()
            events = data if isinstance(data, list) else []
            week_events = _filter_events_to_week(events, week_start, week_end)
            if week_events is not None:
                return week_events
        except Exception:
            pass

        # 2) JSON array embedded in HTML (<script> or raw text).
        for candidate in _JS_ARRAY_RE.findall(text):
            try:
                arr = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                if any("start" in e or "title" in e for e in arr if isinstance(e, dict)):
                    return _filter_events_to_week(arr, week_start, week_end)

        last_error = f"{url} returned 200 but no parsable events were found"

    raise RuntimeError(last_error)


def _filter_events_to_week(events: List[Dict[str, Any]], week_start, week_end) -> List[Dict[str, Any]]:
    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        day_val = e.get("Day") or e.get("date") or e.get("start")
        if not day_val:
            continue
        try:
            if isinstance(day_val, str) and len(day_val) >= 10:
                dt = datetime.fromisoformat(day_val[:10])
            else:
                continue
        except ValueError:
            continue
        if week_start.date() <= dt.date() <= week_end.date():
            out.append(e)
    return out


def _normalize_events(raw: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group raw portal events by weekday key (monday..sunday)."""
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for entry in raw:
        try:
            dt_raw = entry.get("start") or entry.get("date") or entry.get("begin")
            if not dt_raw:
                continue
            dt = datetime.fromisoformat(str(dt_raw).replace(" ", "T"))
            weekday = WEEKDAY_KEYS[dt.weekday()]
            by_day.setdefault(weekday, [])

            subgroups: List[str] = []
            item_room = str(entry.get("room", "")).strip()
            sub_items: List[str] = []
            sub_rooms: List[str] = []
            sg = entry.get("SubGroup")
            if isinstance(sg, list):
                for sub in sg:
                    if not isinstance(sub, dict):
                        continue
                    sgrid = str(sub.get("SGrID", "")).strip()
                    stitle = str(sub.get("STitle", "")).strip()
                    sroom = str(sub.get("SGCaID", "")).strip()
                    piece = (
                        f"{sgrid}: " if sgrid else ""
                    ) + stitle + (f" каб.{sroom}" if sroom else "")
                    piece = piece.strip()
                    if piece:
                        sub_items.append(piece)
                    if sroom:
                        sub_rooms.append(sroom)
                subgroups = sub_items
                uniq_rooms = sorted({r for r in sub_rooms if r})
                if not item_room and len(uniq_rooms) == 1:
                    item_room = uniq_rooms[0]
            elif isinstance(entry.get("subgroups"), list):
                subgroups = [str(s).strip() for s in entry.get("subgroups") if str(s).strip()]
            else:
                topic = str(entry.get("topic", ""))
                if topic:
                    tags = re.findall(r"\b([A-Za-zА-Яа-я0-9]+)\s*:", topic)
                    subgroups = sorted({t.strip() for t in tags if t.strip()})

            time_str = dt.strftime("%H:%M")
            end_raw = entry.get("end")
            if end_raw:
                try:
                    dt_end = datetime.fromisoformat(str(end_raw).replace(" ", "T"))
                    time_str = f"{time_str}–{dt_end.strftime('%H:%M')}"
                except ValueError:
                    pass

            by_day[weekday].append(
                {
                    "time": time_str,
                    "subject": str(entry.get("title", "")).strip(),
                    "room": item_room,
                    "subgroups": subgroups,
                }
            )
        except (ValueError, TypeError, AttributeError):
            continue

    for lessons in by_day.values():
        lessons.sort(key=lambda l: l.get("time", ""))
    return by_day


def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(payload: Dict[str, Any]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("schedule cache write failed: %s", e)


async def _get_week(week_offset: int, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return {'monday': 'YYYY-MM-DD', 'days': {weekday: [lesson, ...]}} for a week.

    Serves from cache when the week matches and the entry is fresh; otherwise
    fetches and caches.
    """
    now = datetime.now()
    monday = (now - timedelta(days=now.weekday())) + timedelta(weeks=week_offset)

    cache = _load_cache()
    entry = cache.get(monday.strftime("%Y-%m-%d"))
    if entry and isinstance(entry.get("days"), dict):
        fetched_at = float(entry.get("fetched_at", 0))
        if time.time() - fetched_at < settings["refresh_hours"] * 3600:
            return {
                "monday": monday.strftime("%Y-%m-%d"),
                "group": entry.get("group", settings["group"]),
                "days": entry["days"],
            }

    try:
        raw = await _fetch_events(settings, monday)
        days = _normalize_events(raw)
        cache[monday.strftime("%Y-%m-%d")] = {
            "group": settings["group"],
            "fetched_at": time.time(),
            "days": days,
        }
        _save_cache(cache)
        return {"monday": monday.strftime("%Y-%m-%d"), "group": settings["group"], "days": days}
    except Exception as e:
        # Stale cache beats no answer.
        if entry and isinstance(entry.get("days"), dict):
            logger.warning("schedule fetch failed (%s); serving stale cache", e)
            return {
                "monday": monday.strftime("%Y-%m-%d"),
                "group": entry.get("group", settings["group"]),
                "days": entry["days"],
                "stale": True,
            }
        raise


def _format_lesson(lesson: Dict[str, Any]) -> str:
    line = f"{lesson.get('time', '')} — {lesson.get('subject', '')}".strip(" –")
    if lesson.get("room"):
        line += f", каб. {lesson['room']}"
    if lesson.get("subgroups"):
        line += f", {'; '.join(lesson['subgroups'])}"
    return line


def _format_week(week: Dict[str, Any]) -> str:
    days = week.get("days", {})
    if not any(days.get(k) for k in WEEKDAY_KEYS.values()):
        return f"Расписание на неделю {week['monday']} пустое или недоступно (группа {week.get('group', '')})."
    lines = [f"Группа {week.get('group', '')}, неделя с {week['monday']}."]
    if week.get("stale"):
        lines.append("Внимание: портал не ответил, показано закешированное расписание.")
    for key in (WEEKDAY_KEYS[k] for k in range(7)):
        lessons = days.get(key, [])
        head = f"{DAY_RU[key]} {DAY_RU_FULL[key][:0] or ''}".strip()
        lines.append("")
        lines.append(head)
        if not lessons:
            lines.append("— выходной")
            continue
        for lesson in lessons:
            lines.append(_format_lesson(lesson))
    return "\n".join(lines)


def _today_lessons(week: Dict[str, Any]) -> List[Dict[str, Any]]:
    return week.get("days", {}).get(WEEKDAY_KEYS[datetime.now().weekday()], [])


def _next_lessons(week: Dict[str, Any]) -> str:
    now = datetime.now()
    today_lessons = week.get("days", {}).get(WEEKDAY_KEYS[now.weekday()], [])
    upcoming = []
    for lesson in today_lessons:
        start = lesson.get("time", "").split("–")[0].strip()
        try:
            hh, mm = start.split(":")
            start_dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except ValueError:
            continue
        if start_dt > now:
            upcoming.append(lesson)
        if len(upcoming) >= 3:
            break
    if not upcoming:
        return f"Сегодня ({DAY_RU_FULL[WEEKDAY_KEYS[now.weekday()]].lower()}) занятий больше нет (или время в расписании распарситься не дало)."
    lines = ["Ближайшие занятия сегодня:"]
    for lesson in upcoming:
        lines.append(_format_lesson(lesson))
    return "\n".join(lines)


SCHOOL_SCHEDULE_SCHEMA = {
    "name": "school_schedule",
    "description": (
        "Class schedule for the configured university group (fetched from the "
        "college portal). Use it for questions about classes this week or today "
        "and what lesson is next. what='week' returns the full week (optionally "
        "one day), what='today' classes for today, what='next' the next lessons "
        "after the current time. week_offset: 0 = current week, 1 = next week."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "what": {
                "type": "string",
                "enum": ["week", "today", "next"],
                "description": "week = full schedule, today = lessons today, next = what is up next now. Default: week.",
            },
            "week_offset": {
                "type": "integer",
                "description": "0 = current week (default), 1 = next week.",
            },
            "day": {
                "type": "string",
                "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
                "description": "Optional: only this day of the week (only used with what='week').",
            },
        },
    },
}


async def _handle_schedule(args: Dict[str, Any], **kw: Any) -> str:
    settings = _schedule_settings()
    if not settings:
        return tool_error(
            "schedule is not configured: set `schedule.group` in config.yaml "
            "(e.g. ИТ24-12) to enable the schedule tool."
        )
    what = args.get("what") or "week"
    if what not in ("week", "today", "next"):
        return tool_error(f"unknown what={what!r}; use week | today | next")
    try:
        week_offset = int(args.get("week_offset", 0))
    except (TypeError, ValueError):
        return tool_error(f"week_offset must be an integer, got {args.get('week_offset')!r}")
    if what == "next" and week_offset != 0:
        return tool_error("what='next' only makes sense for week_offset=0")

    try:
        week = await _get_week(week_offset, settings)
    except Exception as e:
        return tool_error(f"failed to load schedule: {e}")

    if what == "week":
        day = args.get("day")
        days = week.get("days", {})
        if day:
            if day not in WEEKDAY_KEYS.values():
                return tool_error(f"unknown day {day!r}")
            lessons = days.get(day, [])
            header = f"Группа {week.get('group', '')}, {DAY_RU_FULL[day].lower()} (неделя с {week['monday']})."
            if not lessons:
                return f"{header}\n— выходной."
            lines = [header] + [_format_lesson(l) for l in lessons]
            if week.get("stale"):
                lines.append("(данные из кэша, портал не ответил)")
            return "\n".join(lines)
        return _format_week(week)

    if what == "today":
        if week_offset != 0:
            return tool_error("what='today' only makes sense for week_offset=0")
        lessons = _today_lessons(week)
        header = f"Группа {week.get('group', '')}, сегодня {DAY_RU_FULL[WEEKDAY_KEYS[datetime.now().weekday()]].lower()}."
        if not lessons:
            return f"{header}\n— выходной."
        lines = [header] + [_format_lesson(l) for l in lessons]
        if week.get("stale"):
            lines.append("(данные из кэша, портал не ответил)")
        return "\n".join(lines)

    return _next_lessons(week)


registry.register(
    name="school_schedule",
    toolset="school",
    schema=SCHOOL_SCHEDULE_SCHEMA,
    handler=_handle_schedule,
    check_fn=check_schedule_requirements,
    is_async=True,
    emoji="📅",
)