"""Track official Binance spot-listing announcements and send scheduled Telegram alerts.

Alerts: 24h, 12h, and 2h before the announced start, plus a launch-time check.
All timestamps are stored in UTC and rendered in Asia/Kabul. No trades are placed.
"""
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Kabul")
LIST_API_URLS = (
    "https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query",
    "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query",
)
DETAIL_API_URLS = (
    "https://www.binance.com/bapi/apex/v1/public/apex/cms/article/detail/query",
    "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query",
)
ANNOUNCEMENT_BASE = "https://www.binance.com/en/support/announcement/"
LISTING_CATALOG_ID = 48
PAGE_SIZE = 50
STATE_FILE = Path("listing_state.json")
REPORT_FILE = Path("listing_report.json")
ALERTS = (("24H", timedelta(hours=24)), ("12H", timedelta(hours=12)), ("2H", timedelta(hours=2)), ("START", timedelta(0)))
ALERT_WINDOW_MINUTES = 7
MAX_DETAIL_LOOKUPS = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BinanceListingWatcher/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.binance.com/en/support/announcement/",
    "lang": "en",
    "Cache-Control": "no-cache",
}


def fetch_json(url, timeout=10):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    if not raw.strip():
        raise RuntimeError("Empty response")
    return json.loads(raw)


def fetch_listing_articles():
    errors = []
    for base in LIST_API_URLS:
        params = urllib.parse.urlencode({
            "type": 1, "pageNo": 1, "pageSize": PAGE_SIZE,
            "catalogId": LISTING_CATALOG_ID,
        })
        try:
            payload = fetch_json(base + "?" + params)
            data = payload.get("data") or {}
            articles = data.get("articles")
            if articles is None:
                articles = []
                for catalog in data.get("catalogs") or []:
                    if int(catalog.get("catalogId") or LISTING_CATALOG_ID) == LISTING_CATALOG_ID:
                        articles.extend(catalog.get("articles") or [])
            if isinstance(articles, list):
                return articles
            errors.append(base + ": unexpected article-list shape")
        except Exception as exc:
            errors.append(base + ": " + type(exc).__name__ + ": " + str(exc)[:120])
    raise RuntimeError("; ".join(errors))


def fetch_article_detail(code):
    params = urllib.parse.urlencode({"articleCode": code})
    errors = []
    for base in DETAIL_API_URLS:
        try:
            payload = fetch_json(base + "?" + params)
            data = payload.get("data") or {}
            if isinstance(data, dict):
                # Binance has changed the nesting of article details between API versions.
                candidates = [data, data.get("article"), data.get("articleDetail")]
                for item in candidates:
                    if isinstance(item, dict):
                        text = " ".join(str(item.get(k) or "") for k in (
                            "title", "body", "content", "description", "releaseDate", "publishDate"
                        ))
                        if text.strip():
                            return text
                return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:100])
    raise RuntimeError("; ".join(errors) or "No article detail returned")


def flatten_strings(value):
    out = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            out.extend(flatten_strings(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(flatten_strings(child))
    return out


def parse_listing_time(text):
    """Parse an explicit date/time from announcement text; default only explicit UTC markers to UTC."""
    if not text:
        return None, None
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)

    # Prefer a date+time pair near the actual trading start wording.
    start_pos = -1
    for marker in ("trading will open", "trading opens", "will open trading", "trading will start", "will be available for trading"):
        pos = text.lower().find(marker)
        if pos >= 0 and (start_pos < 0 or pos < start_pos):
            start_pos = pos
    relevant = text[start_pos:start_pos + 900] if start_pos >= 0 else text

    patterns = (
        r"(20\\d{2}[-/]\\d{1,2}[-/]\\d{1,2})[ T,]+(\\d{1,2}:\\d{2}(?::\\d{2})?)\\s*(\\(\\s*UTC(?:\\s*[+-]\\s*\\d{1,2}(?::?\\d{2})?)?\\s*\\)|UTC(?:\\s*[+-]\\s*\\d{1,2}(?::?\\d{2})?)?)?",
        r"(\\d{1,2})\\s+(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(20\\d{2})[ ,]+(\\d{1,2}:\\d{2}(?::\\d{2})?)\\s*(\\(\\s*UTC(?:\\s*[+-]\\s*\\d{1,2}(?::?\\d{2})?)?\\s*\\)|UTC(?:\\s*[+-]\\s*\\d{1,2}(?::?\\d{2})?)?)?",
    )
    match = re.search(patterns[0], relevant, re.IGNORECASE)
    if match:
        date_part, time_part, zone_part = match.groups()
        fmt = "%Y-%m-%d %H:%M:%S" if time_part.count(":") == 2 else "%Y-%m-%d %H:%M"
        try:
            parsed = datetime.strptime(date_part.replace("/", "-") + " " + time_part, fmt)
        except ValueError:
            return None, None
    else:
        match = re.search(patterns[1], relevant, re.IGNORECASE)
        if not match:
            return None, None
        day, month, year, time_part, zone_part = match.groups()
        fmt = "%d %B %Y %H:%M:%S" if time_part.count(":") == 2 else "%d %B %Y %H:%M"
        try:
            parsed = datetime.strptime(f"{day} {month} {year} {time_part}", fmt)
        except ValueError:
            return None, None

    zone_text = (zone_part or "").upper().replace(" ", "").replace("(", "").replace(")", "")
    if not zone_text or zone_text == "UTC" or zone_text == "UTC+0" or zone_text == "UTC+00:00" or zone_text == "UTC+0000":
        tz = timezone.utc
    else:
        zone_match = re.search(r"UTC([+-])(\\d{1,2})(?::?(\\d{2}))?", zone_text)
        if not zone_match:
            # Do not guess when the notice uses an unfamiliar timezone.
            return None, None
        sign, hours, minutes = zone_match.groups()
        offset = int(hours) * 60 + int(minutes or 0)
        if sign == "-":
            offset = -offset
        tz = timezone(timedelta(minutes=offset))
    return parsed.replace(tzinfo=tz).astimezone(timezone.utc), zone_text or "UTC"


def is_spot_listing_title(title):
    normalized = re.sub(r"\\s+", " ", (title or "").strip()).lower()
    if not normalized:
        return False
    # Keep actual new-asset listings; avoid futures, margin-only, Launchpool-only and pair-add notices.
    if any(word in normalized for word in ("futures", "perpetual", "margin", "launchpool", "launchpad", "trading pairs", "adds support for")):
        return False
    return "will list" in normalized or "will add" in normalized and "spot trading" in normalized


def load_state():
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict) and isinstance(data.get("listings"), dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"schema_version": 1, "listings": {}}


def save_json(path, payload):
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False, "TELEGRAM_SECRETS_NOT_CONFIGURED"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("ok"):
            return True, "SENT"
        return False, "TELEGRAM_REJECTED"
    except Exception as exc:
        return False, "TELEGRAM_ERROR_" + type(exc).__name__


def render_alert(listing, alert_code, now):
    start = datetime.fromisoformat(listing["start_time_utc"])
    local_start = start.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    delta = dict(ALERTS).get(alert_code, timedelta(0))
    if alert_code == "24H":
        heading = "⏰ Binance Spot listing: 24 hours remaining"
    elif alert_code == "12H":
        heading = "⏰ Binance Spot listing: 12 hours remaining"
    elif alert_code == "2H":
        heading = "🚨 Binance Spot listing: 2 hours remaining"
    else:
        heading = "⚡ Binance listing start-time check"
    return (
        f"{heading}\\n"
        f"Announcement: {listing.get('title', 'Binance listing')}\\n"
        f"Start time (Kabul): {local_start}\\n"
        f"Symbol(s): {', '.join(listing.get('symbols') or ['See announcement'])}\\n"
        f"Status: {listing.get('status', 'SCHEDULED')}\\n"
        f"Announcement: {listing.get('url')}\\n"
        "This is an alert, not a buy instruction. Verify the live spot pair, spread, liquidity and price before any trade."
    )


def run_listing_watcher(now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state()
    known = state["listings"]
    warnings = []
    articles = fetch_listing_articles()
    candidates = [
        item for item in articles
        if isinstance(item, dict) and is_spot_listing_title(str(item.get("title") or ""))
    ][:MAX_DETAIL_LOOKUPS]

    for article in candidates:
        code = str(article.get("code") or article.get("id") or "").strip()
        title = str(article.get("title") or "").strip()
        if not code or not title:
            continue
        url = ANNOUNCEMENT_BASE + code
        try:
            detail_text = fetch_article_detail(code)
            start_utc, timezone_label = parse_listing_time(title + " " + detail_text)
        except Exception as exc:
            warnings.append(f"{code}: detail unavailable ({type(exc).__name__})")
            start_utc, timezone_label = None, None

        if start_utc is None:
            # Preserve an existing parsed schedule if a later API response omits the body.
            old = known.get(code, {})
            start_text = old.get("start_time_utc")
            if start_text:
                try:
                    start_utc = datetime.fromisoformat(start_text)
                    timezone_label = old.get("announced_timezone", "UTC")
                except ValueError:
                    start_utc = None

        previous = known.get(code, {})
        item = {
            "code": code,
            "title": title,
            "url": url,
            "announced_at_utc": datetime.fromtimestamp(
                float(article.get("releaseDate") or article.get("publishDate") or 0) / 1000,
                timezone.utc,
            ).isoformat() if article.get("releaseDate") or article.get("publishDate") else previous.get("announced_at_utc"),
            "start_time_utc": start_utc.isoformat() if start_utc else None,
            "announced_timezone": timezone_label,
            "symbols": sorted(set(re.findall(r"\\(([A-Z0-9]{2,15})\\)", title))),
            "status": "SCHEDULED" if start_utc else "TIME_NOT_PARSED",
            "sent_alerts": previous.get("sent_alerts", []),
        }
        if previous.get("start_time_utc") and item["start_time_utc"] and previous["start_time_utc"] != item["start_time_utc"]:
            item["sent_alerts"] = []
            item["schedule_changed"] = True
        known[code] = item

    due_events = []
    now_utc = now.astimezone(timezone.utc)
    for code, item in list(known.items()):
        if not item.get("start_time_utc"):
            continue
        try:
            start = datetime.fromisoformat(item["start_time_utc"]).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        # Retain the schedule in reports for 48 hours after launch, then drop it from state.
        if now_utc > start + timedelta(hours=48):
            del known[code]
            continue
        if start < now_utc - timedelta(minutes=ALERT_WINDOW_MINUTES):
            continue
        for alert_code, offset in ALERTS:
            if alert_code in item.get("sent_alerts", []):
                continue
            target = start - offset
            lateness = (now_utc - target).total_seconds()
            if 0 <= lateness <= ALERT_WINDOW_MINUTES * 60:
                ok, delivery = send_telegram(render_alert(item, alert_code, now_utc))
                event = {
                    "code": code, "symbol": item.get("symbols", []), "title": item["title"],
                    "alert": alert_code, "target_time_utc": target.isoformat(),
                    "target_time_local": target.astimezone(LOCAL_TZ).isoformat(),
                    "delivery": delivery, "sent": ok, "url": item["url"],
                }
                due_events.append(event)
                if ok:
                    item.setdefault("sent_alerts", []).append(alert_code)
                # When no Telegram is configured, leave alert unsent so report clearly shows delivery is unavailable.
    state["updated_at_utc"] = now_utc.isoformat()
    save_json(STATE_FILE, state)

    upcoming = []
    for item in known.values():
        if not item.get("start_time_utc"):
            continue
        try:
            start = datetime.fromisoformat(item["start_time_utc"]).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        if start >= now_utc - timedelta(hours=24):
            row = dict(item)
            row["start_time_local"] = start.astimezone(LOCAL_TZ).isoformat()
            row["hours_until_start"] = round((start - now_utc).total_seconds() / 3600, 2)
            upcoming.append(row)
    upcoming.sort(key=lambda x: x["start_time_utc"] or "")
    report = {
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_local": now_utc.astimezone(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Kabul",
        "status": "SUCCESS",
        "source": "Binance official announcement API, category 48",
        "announcements_checked": len(articles),
        "scheduled_listings_found": len(upcoming),
        "upcoming_listings": upcoming,
        "alerts_due_this_run": due_events,
        "warnings": warnings[:20],
        "notification_status": "TELEGRAM_CONFIGURED" if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID") else "TELEGRAM_SECRETS_NOT_CONFIGURED",
        "notice": "Times are parsed from official announcement text. If no explicit trading start time can be parsed, the listing is not eligible for timed alerts. No trade is placed.",
    }
    save_json(REPORT_FILE, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    try:
        run_listing_watcher()
    except Exception as exc:
        now = datetime.now(timezone.utc)
        report = {
            "generated_at_utc": now.isoformat(),
            "generated_at_local": now.astimezone(LOCAL_TZ).isoformat(),
            "timezone": "Asia/Kabul",
            "status": "ERROR",
            "scheduled_listings_found": 0,
            "upcoming_listings": [],
            "alerts_due_this_run": [],
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "notice": "Listing feed failed; no listing alert is inferred from stale data.",
        }
        save_json(REPORT_FILE, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
