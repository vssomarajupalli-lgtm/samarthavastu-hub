"""
auto_publisher.py
-----------------
Samartha Vastu - 2-Stage Daily Auto Publisher & Queue Engine

Workflow:
  Stage A — Publishing Today's Approved Video (to Public):
    1. Pre-flight internet check (waits up to 3 minutes for graph.facebook.com).
    2. 1-Public-Post-Per-Day Lock (skips public publish if already published today).
    3. Finds the item marked "preview_approved" in master_schedule.json.
    4. Publishes to:
       - Facebook Page (photo + clean Telugu caption)
       - Facebook First Comment (YouTube video link with clickable preview card)
       - Instagram Business Account (4:5 poster + Telugu caption <= 2000 chars)
       - WhatsApp Public Group (DvPDx43oel4LQQgqCsn7Tr) & Personal WhatsApp (+918****5559)
       - Telegram Channel (@samarthaasrovastu_official)
    5. Marks item as "status": "published".
    6. Calls website_sync.py to update public/videos_data.json and index.html.
    7. Runs auto_git_sync() to commit and push updates to GitHub.

  Stage B — Preparing & Sending Tomorrow's Preview (ONLY to Personal WhatsApp):
    1. Runs youtube_sync.py to ingest any newly uploaded videos from @samarthavastu999.
    2. Selects the newest unposted video (NEWEST -> OLDEST).
    3. Renders 4:5 poster using Headless Chrome (html_poster_generator.py).
    4. Marks item as "status": "preview_approved" for tomorrow.
    5. Sends poster + caption ONLY to Personal WhatsApp (+918919395559) prefixed with:
       "📋 రేపటి వీడియో ప్రివ్యూ (Tomorrow's Scheduled Preview)"
       with a 3-line status receipt showing remaining unposted videos.

  Skip Control:
    python auto_publisher.py --skip-tomorrow
    Marks current "preview_approved" video as "skipped", selects next newest,
    renders poster, and sends updated preview to Personal WhatsApp.

Usage:
    python auto_publisher.py --daily-run         # Complete morning cycle (Stage A + Stage B)
    python auto_publisher.py --prepare-tomorrow  # Prepare & send tomorrow's preview only
    python auto_publisher.py --skip-tomorrow     # Skip tomorrow's preview & pick next
    python auto_publisher.py --publish-next      # Force-publish next/approved item
    python auto_publisher.py --dry-run           # Simulate without real posts
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
LOGS_DIR        = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DAILY_LOG_FILE  = LOGS_DIR / "daily_run.log"
SCREENSHOTS_DIR = LOGS_DIR / "screenshots"
PUBLISHER_LOCK  = LOGS_DIR / "publisher.lock"

# --- Single-instance publisher lock ---
_LOCK_FD = None
_STABILIZED = False

def acquire_publisher_lock() -> bool:
    """Acquire an OS-level single-instance lock on logs/publisher.lock.
    Returns True if lock acquired, False if another instance holds it."""
    global _LOCK_FD
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            import msvcrt
            _LOCK_FD = os.open(str(PUBLISHER_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
            try:
                msvcrt.locking(_LOCK_FD, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(_LOCK_FD)
                _LOCK_FD = None
                return False
        else:
            import fcntl
            _LOCK_FD = os.open(str(PUBLISHER_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(_LOCK_FD)
                _LOCK_FD = None
                return False
        return True
    except Exception:
        _LOCK_FD = None
        return False


def release_publisher_lock():
    """Release the single-instance publisher lock."""
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(_LOCK_FD, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(_LOCK_FD, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(_LOCK_FD)
        except Exception:
            pass
        _LOCK_FD = None
        try:
            PUBLISHER_LOCK.unlink(missing_ok=True)
        except Exception:
            pass


def wait_for_stabilization(seconds: int = 300):
    """Silent stabilization delay after desktop unlock so laptop startup settles.
    Does not print progress to avoid slowing perceived boot."""
    log.info("[Startup Gate] Stabilization delay: waiting %ds after desktop unlock before publishing...", seconds)
    time.sleep(seconds)
    log.info("[Startup Gate] Stabilization delay complete.")


def show_confirmation_dialog(video_title: str, completed_channels: int = 0, total_channels: int = 6, pending_channel: str = "") -> bool:
    """Native Windows MsgBox Yes/No confirmation before launching a publishing run.
    Returns True if Yes, False if No."""
    DECLINED_FILE = LOGS_DIR / "declined_today.txt"
    try:
        # Build status line showing partial progress
        if completed_channels >= total_channels:
            status_line = f"All {total_channels}/{total_channels} channels complete."
        elif pending_channel:
            status_line = f"{completed_channels}/{total_channels} Channels Completed — Pending: [{pending_channel}]. Resume pending channel(s) now?"
        else:
            status_line = f"{completed_channels}/{total_channels} Channels Completed."
        result = ctypes.windll.user32.MessageBoxW(
            0,
            f"Publish queued video now?\n\nTitle: {video_title}\n\n{status_line}\n\n[Yes] = Proceed with publishing\n[No] = Cancel and keep item in queue for next session",
            "Samartha Vastu - Publishing Confirmation",
            0x00000004 | 0x00000020 | 0x00010000 | 0x00010000,  # MB_YESNO | MB_ICONQUESTION | MB_TOPMOST | MB_SETFOREGROUND
        )
        if result == 6:  # IDYES = 6
            return True
        # User clicked No: record daily snooze so hourly task stops badgering
        try:
            DECLINED_FILE.parent.mkdir(parents=True, exist_ok=True)
            DECLINED_FILE.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")
        except Exception:
            pass
        log.info("[Startup Gate] User clicked No — daily snooze recorded in %s.", DECLINED_FILE)
        return False
    except Exception as exc:
        log.warning("[Startup Gate] Confirmation dialog failed: %s — defaulting to No (safe exit).", exc)
        try:
            DECLINED_FILE.parent.mkdir(parents=True, exist_ok=True)
            DECLINED_FILE.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")
        except Exception:
            pass
        return False

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DAILY_LOG_FILE, encoding="utf-8"),
    ]
)
log = logging.getLogger("auto_publisher")

# --- Meta Graph API ---
GRAPH_VERSION = "v21.0"
GRAPH_BASE    = f"https://graph.facebook.com/{GRAPH_VERSION}"

# --- Env config ---
FB_PAGE_ID        = os.getenv("FB_PAGE_ID",        "271667576040971")
IG_USER_ID        = os.getenv("IG_USER_ID",        "17841465418624878")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN",  "")
YOUTUBE_URL       = os.getenv("YOUTUBE_URL",        "https://www.youtube.com/@samarthavastu999")
CONTACT_PHONE     = os.getenv("CONTACT_PHONE",      "+91 8919395559")
CONTACT_EMAIL     = os.getenv("CONTACT_EMAIL",      "samarthavastu999@gmail.com")
WHATSAPP_TARGET   = os.getenv("WHATSAPP_TARGET",    "DvPDx43oel4LQQgqCsn7Tr,+918****5559")
WHATSAPP_ADMIN    = os.getenv("WHATSAPP_ADMIN",     "+918****5559")
WHATSAPP_GROUP    = "DvPDx43oel4LQQgqCsn7Tr"

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Instagram polling ---
IG_POLL_INTERVAL = 4   # seconds
IG_POLL_MAX      = 20  # max polls


def section(title: str):
    bar = "=" * 62
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------- #
#  Pre-flight Checks & Schedule Persistence                                    #
# ---------------------------------------------------------------------------- #

def wait_for_internet(timeout_seconds: int = 180) -> bool:
    """Wait up to timeout_seconds for internet connectivity (graph.facebook.com)."""
    log.info("[Pre-flight] Checking internet connectivity (up to %ds)...", timeout_seconds)
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            resp = requests.get("https://graph.facebook.com", timeout=5)
            if resp.status_code in (200, 400, 404):
                elapsed = time.time() - start_time
                log.info("[Pre-flight] Internet connectivity verified OK in %.1fs.", elapsed)
                return True
        except Exception:
            pass
        time.sleep(4)
    log.error("[Pre-flight] Internet connection check timed out after %ds.", timeout_seconds)
    return False


def load_schedule() -> list:
    if not SCHEDULE_FILE.exists():
        log.error("master_schedule.json not found. Run youtube_sync.py first.")
        sys.exit(1)
    with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("items", [])


def save_schedule(items: list):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = SCHEDULE_FILE.with_suffix(SCHEDULE_FILE.suffix + ".tmp")
    bak_file = SCHEDULE_FILE.with_suffix(SCHEDULE_FILE.suffix + ".bak")
    if SCHEDULE_FILE.exists():
        try:
            os.replace(SCHEDULE_FILE, bak_file)
        except OSError:
            pass
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, SCHEDULE_FILE)
    try:
        bak_file.unlink(missing_ok=True)
    except OSError:
        pass


def wait_for_unlocked_desktop(timeout_sec: int = 1800) -> bool:
    """
    Checks if Windows is currently on the Lock Screen (LogonUI.exe or inaccessible input desktop).
    If screen is locked, waits in a loop checking every 10 seconds until the user unlocks the desktop.
    Returns True when desktop is unlocked and interactive, False if timed out.
    """
    log.info("[Desktop Watcher] Checking if Windows desktop is unlocked...")
    start_time = time.time()
    first_locked_notice = False

    while time.time() - start_time < timeout_sec:
        is_locked = False

        # 1. Check if LogonUI.exe is running (Windows Lock / Login Screen)
        try:
            for proc in psutil.process_iter(['name']):
                if (proc.info.get('name') or '').lower() == 'logonui.exe':
                    is_locked = True
                    break
        except Exception:
            pass

        # 2. Check OpenInputDesktop
        if not is_locked:
            try:
                h_desk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
                if not h_desk:
                    is_locked = True
                else:
                    ctypes.windll.user32.CloseDesktop(h_desk)
            except Exception:
                pass

        if not is_locked:
            if first_locked_notice:
                elapsed = time.time() - start_time
                log.info("[Desktop Watcher] User unlocked the desktop after %.1fs! Resuming automation.", elapsed)
            else:
                log.info("[Desktop Watcher] Desktop is unlocked and ready.")
            return True

        if not first_locked_notice:
            log.warning(
                "[Desktop Watcher] Windows is currently on Lock Screen (LogonUI). Waiting up to %ds for user to unlock...",
                timeout_sec
            )
            first_locked_notice = True

        time.sleep(10)

    log.error("[Desktop Watcher] Timed out waiting for desktop unlock after %ds.", timeout_sec)
    return False


def is_daily_completed_for_item(item: dict) -> bool:
    """
    Checks if an item has successfully completed all 6 distribution channels:
    1. Facebook Page (fb_post_url)
    2. Instagram Business (ig_post_url)
    3. YouTube Shorts (yt_short_url)
    4. WhatsApp Public Group (wa_group_sent)
    5. WhatsApp Personal Admin (wa_admin_sent)
    6. Telegram Channel (tg_sent)
    """
    has_fb = bool(item.get("fb_post_url"))
    has_ig = bool(item.get("ig_post_url"))
    has_yt = bool(item.get("yt_short_url"))
    has_wa_grp = bool(item.get("wa_group_sent"))
    has_wa_adm = bool(item.get("wa_admin_sent"))
    has_tg = bool(item.get("tg_sent"))
    has_wa = bool(item.get("wa_sent") or (has_wa_grp and has_wa_adm))
    return bool(has_fb and has_ig and has_yt and has_wa and has_tg)


def check_daily_published_lock(schedule: list, force: bool = False) -> bool:
    """
    Checks if all channels (FB, IG, YouTube Shorts, WhatsApp Group & Personal Admin, Telegram)
    have completed for today (YYYY-MM-DD).
    Returns True (locked for the day) ONLY when an item published today has:
      - fb_post_url
      - ig_post_url
      - yt_short_url
      - wa_sent == True (or both wa_group_sent and wa_admin_sent)
      - tg_sent == True
    If any single channel was missed earlier in the day, returns False so the
    catch-up trigger automatically resumes and finishes only the missing channel(s).
    """
    if force:
        log.info("[Daily Lock] --force flag supplied: 1-post-per-day lock bypassed.")
        return False

    today_str = datetime.now().strftime("%Y-%m-%d")
    for item in schedule:
        pub_at = item.get("published_at") or ""
        is_today = pub_at.startswith(today_str)
        if is_today and item.get("status") == "published":
            if is_daily_completed_for_item(item):
                log.info("[Daily Lock Active] Today's post (%s) is 100%% complete across ALL channels:", today_str)
                log.info("  Item ID      : %s", item.get("id"))
                log.info("  Title        : %s", (item.get("title") or "")[:50])
                log.info("  FB URL       : %s", item.get("fb_post_url"))
                log.info("  IG URL       : %s", item.get("ig_post_url"))
                log.info("  Short URL    : %s", item.get("yt_short_url"))
                log.info("  WA Group/Adm : %s / %s", item.get("wa_group_sent"), item.get("wa_admin_sent"))
                log.info("  Telegram     : %s", item.get("tg_sent"))
                log.info("Strict 1-post-per-day lock is ACTIVE. Exiting in <1s.")
                return True
            else:
                log.info("[Daily Lock Inactive] Today's post (%s) is INCOMPLETE across channels:", today_str)
                log.info("  FB: %s | IG: %s | Shorts: %s | WA Group: %s | WA Admin: %s | Telegram: %s",
                         bool(item.get("fb_post_url")), bool(item.get("ig_post_url")),
                         bool(item.get("yt_short_url")), bool(item.get("wa_group_sent")),
                         bool(item.get("wa_admin_sent")), bool(item.get("tg_sent")))
                log.info("Resuming missing channel(s) now...")
                return False

    return False


# ---------------------------------------------------------------------------- #
#  Meta Graph API Helpers                                                        #
# ---------------------------------------------------------------------------- #

def _api_post(endpoint: str, payload: dict, timeout: int = 30) -> dict:
    url  = f"{GRAPH_BASE}/{endpoint.lstrip('/')}"
    resp = requests.post(url, data=payload, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _api_get(endpoint: str, params: dict, timeout: int = 15) -> dict:
    url  = f"{GRAPH_BASE}/{endpoint.lstrip('/')}"
    resp = requests.get(url, params=params, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def post_facebook_comment(photo_id: str, comment_text: str, dry_run: bool = False) -> dict:
    """Posts a First Comment under the Facebook photo with clickable YouTube link."""
    log.info("[Facebook] Adding First Comment to photo %s...", photo_id)
    if dry_run:
        log.info("[Facebook] DRY-RUN - would comment: %s", comment_text)
        return {"success": True, "comment_id": "dry_run_comment"}

    url = f"{GRAPH_BASE}/{photo_id}/comments"
    resp = requests.post(url, data={"message": comment_text, "access_token": META_ACCESS_TOKEN}, timeout=20)
    try:
        data = resp.json()
        if "id" in data:
            log.info("[Facebook] First Comment posted OK (ID: %s)", data["id"])
            return {"success": True, "comment_id": data["id"]}
        else:
            log.warning("[Facebook] First Comment note: %s", data)
            return {"success": False, "error": str(data)}
    except Exception as exc:
        log.error("[Facebook] First Comment error: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------- #
#  Caption Builders                                                              #
# ---------------------------------------------------------------------------- #

def clean_description(raw: str) -> str:
    clean = re.sub(r"#\S+", "", raw)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def build_public_caption(item: dict) -> str:
    """
    Clean Telugu caption for Facebook & Instagram (zero hashtags).
    Enforces safe length <= 2,000 characters for Instagram compliance.
    """
    title    = (item.get("title") or "").strip()
    raw_desc = item.get("description") or item.get("caption") or ""
    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)

    clean_desc = clean_description(raw_desc)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    footer_lines = [
        f"📺 పూర్తి వీడియో చూడండి: {yt_url}",
        f"💬 WhatsApp Consultation: https://wa.me/918919395559",
        f"📞 Contact: {CONTACT_PHONE}",
        f"✉️ Email: {CONTACT_EMAIL}",
    ]
    footer = "\n".join(footer_lines)

    max_desc_len = max(100, 2000 - len(title) - len(footer) - 20)
    if len(clean_desc) > max_desc_len:
        clean_desc = clean_desc[:max_desc_len].rsplit(" ", 1)[0] + "..."

    parts = []
    if title:
        parts.append(title)
        parts.append("")
    if clean_desc:
        parts.append(clean_desc)
        parts.append("")
    parts.append(footer)

    return "\n".join(parts)


def build_whatsapp_caption(
    item: dict,
    is_preview: bool = False,
    is_admin: bool = False,
    remaining_unposted: int = 0,
    fb_status: bool = True,
    ig_status: bool = True,
    yt_short_status: bool = False,
    yt_short_url: str = "",
) -> str:
    """
    Builds WhatsApp formatted caption under 1000 characters to prevent modal overflow.
    If is_preview: prefixes with [TOMORROW'S PREVIEW — FOR YOUR CHECK ONLY].
    If is_admin: appends channel publishing receipt.
    """
    title    = (item.get("title") or "").strip()
    raw_desc = item.get("description") or item.get("caption") or ""
    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)

    clean_desc = clean_description(raw_desc)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    header_prefix = "🔔 [TOMORROW'S PREVIEW — FOR YOUR CHECK ONLY]\n\n" if is_preview else ""

    footer_lines = [
        f"📺 YouTube: {yt_url}",
        f"💬 WhatsApp: https://wa.me/918919395559",
        f"📞 Phone: {CONTACT_PHONE}",
        f"✉️ Email: {CONTACT_EMAIL}",
    ]

    if is_preview:
        footer_lines.append("")
        footer_lines.append("---")
        footer_lines.append("📊 *Status:* Locked in Queue for Next Session (Hold & Carry-Forward Active)")
        footer_lines.append(f"⏳ *Remaining Queue:* {remaining_unposted} unposted videos")
        footer_lines.append("(To skip or change: python auto_publisher.py --skip-tomorrow)")
    elif is_admin:
        footer_lines.append("")
        footer_lines.append("---")
        footer_lines.append("📊 *Daily Publishing Status:*")
        footer_lines.append(f"✅ *Published Today:* {title[:40]}")
        fb_ico = "✅" if fb_status else "❌"
        ig_ico = "✅" if ig_status else "❌"
        yt_ico = "✅" if yt_short_status else "❌"
        footer_lines.append(f"🌐 FB: {fb_ico} | 📸 IG: {ig_ico} | ⚡ Short: {yt_ico}")
        if yt_short_url:
            footer_lines.append(f"⚡ Short: {yt_short_url}")
        footer_lines.append(f"⏳ *Remaining Queue:* {remaining_unposted} unposted videos")

    footer = "\n".join(footer_lines)

    max_desc_len = max(80, 940 - len(header_prefix) - len(title) - len(footer) - 20)
    if len(clean_desc) > max_desc_len:
        clean_desc = clean_desc[:max_desc_len].rsplit(" ", 1)[0] + "..."

    parts = []
    if header_prefix:
        parts.append(header_prefix.strip())
    if title:
        parts.append(f"*{title}*")
        parts.append("")
    if clean_desc:
        parts.append(clean_desc)
        parts.append("")
    parts.append(footer)
    return "\n".join(parts)


def build_telegram_caption(item: dict) -> str:
    """
    Builds Telegram formatted caption with HTML parsing (bold, links).
    Telegram allows up to 1024 characters for caption.
    """
    title    = (item.get("title") or "").strip()
    raw_desc = item.get("description") or item.get("caption") or ""
    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)

    clean_desc = clean_description(raw_desc)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    # Telegram uses HTML parse_mode
    parts = []
    if title:
        parts.append(f"<b>{title}</b>")
    if clean_desc:
        parts.append(clean_desc)
    parts.append("")
    parts.append(f"📺 <a href=\"{yt_url}\">Watch Full Video</a>")
    parts.append(f"💬 <a href=\"https://wa.me/918919395559\">WhatsApp Consultation</a>")
    parts.append(f"📞 {CONTACT_PHONE}")
    parts.append(f"✉️ {CONTACT_EMAIL}")

    caption = "\n".join(parts)

    # Telegram caption limit is 1024 chars
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    return caption


def build_daily_posting_report(today_item: dict, today_str: str, tomorrow_str: str) -> str:
    """
    Builds a unified WhatsApp Daily Posting Report for Stage B preview.
    Returns the report text to prepend to tomorrow's preview caption.
    """
    if not today_item:
        return ""

    lines = []
    lines.append("📊 *సమర్థ వాస్తు - డైలీ పోస్ట్ رిపోర్ట్*")
    lines.append(f"✅ ఈరోజు ({today_str}) పోస్ట్:")
    
    # Channel status mapping
    channels = [
        ("fb_post_url", "Facebook", "📍"),
        ("ig_post_url", "Instagram", "📍"),
        ("yt_short_url", "YouTube Shorts", "📍"),
        ("wa_group_sent", "WhatsApp Group", "📍"),
        ("tg_sent", "Telegram", "📍"),
    ]
    
    for field, name, icon in channels:
        status = "✅ Done" if today_item.get(field) else "❌ Failed"
        lines.append(f"{icon} {name}: {status}")
    
    lines.append("-----------------------------------")
    lines.append(f"🔜 *రేపటి ({tomorrow_str}) పోస్ట్ ప్రివ్యూ:*")
    lines.append("")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------- #
#  Facebook Publisher                                                            #
# ---------------------------------------------------------------------------- #

def publish_facebook(item: dict, local_thumb: str, caption: str, dry_run: bool) -> dict:
    section("FACEBOOK PAGE POST")

    endpoint = f"{FB_PAGE_ID}/photos"
    log.info("[Facebook] Endpoint : POST %s/%s", GRAPH_BASE, endpoint)
    log.info("[Facebook] Local file: %s", local_thumb)
    log.info("[Facebook] Caption  : %s...", caption[:80])

    if dry_run:
        log.info("[Facebook] DRY-RUN - skipping real request")
        mock_id = f"271667576040971_dry-run-{item['id']}"
        cdn_url = "https://scontent.cdninstagram.com/dry-run-image.jpg"
        return {
            "success":       True,
            "post_id":       mock_id,
            "post_url":      "https://www.facebook.com/271667576040971",
            "cdn_image_url": cdn_url,
        }

    if not Path(local_thumb).exists():
        err = f"Thumbnail not found: {local_thumb}"
        log.error("[Facebook] %s", err)
        return {"success": False, "post_id": None, "post_url": None, "cdn_image_url": None, "error": err}

    url = f"{GRAPH_BASE}/{endpoint}"
    try:
        with open(local_thumb, "rb") as img_file:
            resp = requests.post(
                url,
                data  = {"message": caption, "access_token": META_ACCESS_TOKEN},
                files = {"source": img_file},
                timeout = 60,
            )
        data = resp.json()
    except Exception as exc:
        log.error("[Facebook] Upload error: %s", exc)
        return {"success": False, "post_id": None, "post_url": None, "cdn_image_url": None, "error": str(exc)}

    if "id" not in data:
        log.error("[Facebook] Upload failed: %s", data)
        return {"success": False, "post_id": None, "post_url": None, "cdn_image_url": None, "error": str(data)}

    photo_id = data["id"]
    post_url = f"https://www.facebook.com/{photo_id.replace('_', '/posts/')}"
    log.info("[Facebook] Uploaded photo id: %s", photo_id)

    cdn_image_url = None
    meta = _api_get(photo_id, {"fields": "images,link", "access_token": META_ACCESS_TOKEN})
    images = meta.get("images", [])
    if images:
        cdn_image_url = images[0].get("source")
        log.info("[Facebook] CDN image URL: %s", cdn_image_url)

    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"
    comment_text = f"🎥 పూర్తి వీడియో ఇక్కడ చూడండి:\n{yt_url}"
    post_facebook_comment(photo_id, comment_text, dry_run=dry_run)

    return {
        "success":       True,
        "post_id":       photo_id,
        "post_url":      post_url,
        "cdn_image_url": cdn_image_url,
    }


# ---------------------------------------------------------------------------- #
#  Instagram Publisher                                                           #
# ---------------------------------------------------------------------------- #

def _poll_ig_container(container_id: str) -> bool:
    for i in range(IG_POLL_MAX):
        data   = _api_get(container_id, {"fields": "status_code,status", "access_token": META_ACCESS_TOKEN})
        status = data.get("status_code", "")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            log.error("[Instagram] Container failed: %s", data)
            return False
        time.sleep(IG_POLL_INTERVAL)
    return False


def publish_instagram(item: dict, image_url: str, caption: str, dry_run: bool) -> dict:
    section("INSTAGRAM BUSINESS POST")
    ig_profile_url = "https://www.instagram.com/samarthavastu999/"

    if dry_run:
        log.info("[Instagram] DRY-RUN - skipping container creation")
        return {"success": True, "media_id": f"dry-run-ig-{item['id']}", "post_url": ig_profile_url}

    if not image_url:
        return {"success": False, "media_id": None, "post_url": None, "error": "No CDN image URL available"}

    ep1 = f"{IG_USER_ID}/media"
    data1 = _api_post(ep1, {"image_url": image_url, "caption": caption, "access_token": META_ACCESS_TOKEN})
    if "id" not in data1:
        log.error("[Instagram] Container creation failed: %s", data1)
        return {"success": False, "media_id": None, "post_url": None, "error": str(data1)}

    container_id = data1["id"]
    log.info("[Instagram] Container created: %s, polling status...", container_id)

    if not _poll_ig_container(container_id):
        return {"success": False, "media_id": None, "post_url": None, "error": "Container did not reach FINISHED"}

    ep2 = f"{IG_USER_ID}/media_publish"
    data2 = _api_post(ep2, {"creation_id": container_id, "access_token": META_ACCESS_TOKEN})
    if "id" not in data2:
        return {"success": False, "media_id": None, "post_url": None, "error": str(data2)}

    media_id = data2["id"]
    log.info("[Instagram] Published media ID: %s", media_id)

    permalink = ig_profile_url
    pdata = _api_get(media_id, {"fields": "permalink", "access_token": META_ACCESS_TOKEN})
    if pdata.get("permalink"):
        permalink = pdata["permalink"]

    return {"success": True, "media_id": media_id, "post_url": permalink}


# ---------------------------------------------------------------------------- #
#  WhatsApp Dispatcher                                                           #
# ---------------------------------------------------------------------------- #

def dispatch_whatsapp_media(
    target: str,
    thumb_path: str,
    caption: str,
    tag: str,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        log.info("[WhatsApp] DRY-RUN — would send to: %s", target)
        return True

    # Ensure desktop is unlocked before automating Chrome / WhatsApp Web
    wait_for_unlocked_desktop(timeout_sec=1800)

    from whatsapp_sender import send_whatsapp_media

    try:
        res = send_whatsapp_media(
            target=target,
            img_path=thumb_path,
            caption=caption,
            output_dir=str(SCREENSHOTS_DIR),
            target_tag=tag,
            wait_load=25,
            close_tab=False,
        )
        return bool(res.get("success"))
    except Exception as exc:
        log.error("[WhatsApp] Dispatch failed for %s: %s", target, exc)
        return False


def dispatch_whatsapp_text(
    target: str,
    text: str,
    tag: str,
    dry_run: bool = False,
) -> dict:
    """
    Sends a plain-text WhatsApp message (no image) to a target.
    Used as a separator between Stage A and Stage B posters so they never merge side-by-side.
    Always returns a dict: {"success": bool, "target": str, "tag": str, "error": str|None}.
    """
    if dry_run:
        log.info("[WhatsApp] DRY-RUN — would send text to: %s", target)
        return {"success": True, "target": target, "tag": tag, "error": None, "dry_run": True}

    wait_for_unlocked_desktop(timeout_sec=1800)

    from whatsapp_sender import send_whatsapp_text

    try:
        res = send_whatsapp_text(
            target=target,
            text=text,
            output_dir=str(SCREENSHOTS_DIR),
            target_tag=tag,
            close_tab=False,
        )
        ok = bool(res.get("success"))
        return {
            "success": ok,
            "target": target,
            "tag": tag,
            "error": res.get("error") if not ok else None,
        }
    except Exception as exc:
        log.error("[WhatsApp] Text dispatch failed for %s: %s", target, exc)
        return {"success": False, "target": target, "tag": tag, "error": str(exc)}


# ---------------------------------------------------------------------------- #
#  Telegram Publisher                                                            #
# ---------------------------------------------------------------------------- #

def publish_to_telegram(item: dict, poster_path: str, caption: str, dry_run: bool = False) -> dict:
    """
    Publishes a photo with caption to the Telegram channel using the Bot API.
    Returns {"success": bool, "message_id": int|None, "error": str|None}.
    """
    if dry_run:
        log.info("[Telegram] DRY-RUN — would send photo to chat %s", TELEGRAM_CHAT_ID)
        return {"success": True, "message_id": 0, "error": None}

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("[Telegram] Bot token or chat ID not configured — skipping")
        return {"success": False, "message_id": None, "error": "Telegram not configured"}

    if not Path(poster_path).exists():
        err = f"Poster not found: {poster_path}"
        log.error("[Telegram] %s", err)
        return {"success": False, "message_id": None, "error": err}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(poster_path, "rb") as img_file:
            files = {"photo": img_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",  # supports bold, italic, links
            }
            resp = requests.post(url, files=files, data=data, timeout=30)
        result = resp.json()

        if result.get("ok"):
            message_id = result.get("result", {}).get("message_id")
            log.info("[Telegram] Published successfully to chat %s (message_id: %s)", TELEGRAM_CHAT_ID, message_id)
            return {"success": True, "message_id": message_id, "error": None}
        else:
            err = result.get("description", "Unknown Telegram API error")
            log.error("[Telegram] API error: %s", err)
            return {"success": False, "message_id": None, "error": err}

    except Exception as exc:
        log.error("[Telegram] Upload failed: %s", exc)
        return {"success": False, "message_id": None, "error": str(exc)}


# ---------------------------------------------------------------------------- #
#  Poster Resolver                                                               #
# ---------------------------------------------------------------------------- #

def ensure_poster_exists(item: dict) -> str:
    """Ensures 4:5 Headless Chrome poster exists at vastu_content_queue/thumbnails/yt_<ID>.jpg."""
    from PIL import Image as PILImage

    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    poster_path = THUMBNAILS_DIR / f"{item['id']}.jpg"

    needs_regen = False
    if not poster_path.exists() or poster_path.stat().st_size == 0:
        needs_regen = True
    else:
        # Validate existing poster is exactly 1080x1350
        try:
            with PILImage.open(poster_path) as chk:
                pw, ph = chk.size
            if pw != 1080 or ph != 1350:
                log.info("Poster %s is %dx%d, regenerating to 1080x1350", poster_path.name, pw, ph)
                needs_regen = True
        except Exception:
            needs_regen = True

    if needs_regen:
        log.info("Generating Headless Chrome poster for: %s", item["id"])
        from html_poster_generator import render_html_to_poster
        render_html_to_poster(item, poster_path)

        # Re-validate after regeneration
        try:
            with PILImage.open(poster_path) as chk:
                pw, ph = chk.size
            if pw != 1080 or ph != 1350:
                raise RuntimeError(
                    f"Regenerated poster {poster_path.name} is {pw}x{ph}, expected 1080x1350"
                )
        except Exception as exc:
            log.error("Poster validation failed for %s: %s", poster_path.name, exc)
            raise

    item["has_thumbnail"] = True
    item["thumbnail_file"] = f"vastu_content_queue\\thumbnails\\{item['id']}.jpg"

    return str(poster_path)


# ---------------------------------------------------------------------------- #
#  Git Auto-Sync                                                                 #
# ---------------------------------------------------------------------------- #

def auto_git_sync(title: str = ""):
    """
    Automatically commits and pushes published updates to GitHub.
    Runs after Stage A public publishing and website_sync.
    """
    log.info("[Git Auto-Sync] Checking git status...")
    try:
        subprocess.run(["git", "add", "vastu_content_queue/master_schedule.json", 
                        "public/videos_data.json", "public/videos.json", "public/index.html"], 
                       cwd=str(BASE_DIR), capture_output=True, text=True)
        diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(BASE_DIR))
        if diff_check.returncode != 0:
            commit_msg = f"chore(auto): daily update for {title[:40]} [{datetime.now().strftime('%Y-%m-%d')}]"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(BASE_DIR), capture_output=True, text=True)
            log.info("[Git Auto-Sync] Committed daily update: %s", commit_msg)
            
            remotes = subprocess.run(["git", "remote"], cwd=str(BASE_DIR), capture_output=True, text=True).stdout
            if "origin" in remotes.split():
                log.info("[Git Auto-Sync] Running git pull --rebase before push...")
                pull_res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True)
                if pull_res.returncode != 0:
                    log.warning("[Git Auto-Sync] Rebase pull note: %s", pull_res.stderr)
                log.info("[Git Auto-Sync] Pushing to GitHub origin/main...")
                push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True)
                if push_res.returncode == 0:
                    log.info("[Git Auto-Sync] Pushed successfully to GitHub!")
                else:
                    log.warning("[Git Auto-Sync] Push note: %s", push_res.stderr)
            else:
                log.info("[Git Auto-Sync] Local commit saved. (No remote 'origin' configured yet).")
        else:
            log.info("[Git Auto-Sync] No changes to commit.")
    except Exception as exc:
        log.warning("[Git Auto-Sync] Note: %s", exc)


# ---------------------------------------------------------------------------- #
#  Stage A: Public Daily Publish                                                 #
# ---------------------------------------------------------------------------- #

def run_stage_a_public_publish(schedule: list, dry_run: bool = False, force: bool = False) -> bool:
    """
    Executes Stage A:
    Publishes today's pre-approved video (or fallback next pending) to Facebook,
    Instagram, WhatsApp Public Group, and Personal WhatsApp.
    """
    section("STAGE A: PUBLISHING TODAY'S VIDEO TO PUBLIC")

    # Daily Lock Check
    if not dry_run and not force and check_daily_published_lock(schedule, force=force):
        return True

    # Find the target item:
    # 1. First check if today's item is incomplete across channels (e.g. missing WhatsApp, YouTube Shorts, etc.)
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_item = None
    for item in schedule:
        pub_at = item.get("published_at") or ""
        if pub_at.startswith(today_str) and not is_daily_completed_for_item(item):
            target_item = item
            log.info("[Stage A] Resuming today's incomplete post: %s (%s)", item["id"], item.get("title", "")[:40])
            break

    # 2. Look for "preview_approved" item
    if not target_item:
        for item in schedule:
            if item.get("status") == "preview_approved":
                target_item = item
                break

    # 3. Fallback to earliest pending
    if not target_item:
        for item in schedule:
            if item.get("status") not in ("published", "skipped"):
                target_item = item
                break

    if not target_item:
        log.warning("[Stage A] No approved or pending items found in queue.")
        return False

    item_id = target_item["id"]
    poster_path = ensure_poster_exists(target_item)
    caption = build_public_caption(target_item)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != item_id)

    log.info("Target Item: %s (%s)", item_id, target_item.get("title", "")[:45])
    log.info("Poster Path: %s", poster_path)
    log.info("Unposted Remaining: %d", remaining_unposted)

    # 1. Facebook Page + First Comment
    if target_item.get("fb_post_url"):
        log.info("[Facebook] Already published for %s: %s (Skipping re-post)", item_id, target_item["fb_post_url"])
        fb_res = {
            "success": True,
            "post_id": target_item.get("fb_post_id"),
            "post_url": target_item.get("fb_post_url"),
            "cdn_image_url": target_item.get("cdn_image_url"),
        }
    else:
        fb_res = publish_facebook(target_item, poster_path, caption, dry_run)
        if fb_res.get("success") and not dry_run:
            target_item["fb_post_id"]   = fb_res.get("post_id")
            target_item["fb_post_url"]  = fb_res.get("post_url", "")
            target_item["cdn_image_url"] = fb_res.get("cdn_image_url")
            save_schedule(schedule)

    fb_post_id  = fb_res.get("post_id")
    fb_post_url = fb_res.get("post_url", "")
    cdn_img_url = fb_res.get("cdn_image_url") or target_item.get("cdn_image_url")

    # 2. Instagram Business
    if target_item.get("ig_post_url"):
        log.info("[Instagram] Already published for %s: %s (Skipping re-post)", item_id, target_item["ig_post_url"])
        ig_res = {
            "success": True,
            "media_id": target_item.get("ig_media_id"),
            "post_url": target_item.get("ig_post_url"),
        }
    else:
        ig_res = publish_instagram(target_item, cdn_img_url or "", caption, dry_run)
        if ig_res.get("success") and not dry_run:
            target_item["ig_media_id"] = ig_res.get("media_id")
            target_item["ig_post_url"] = ig_res.get("post_url", "")
            save_schedule(schedule)

    ig_media_id = ig_res.get("media_id")
    ig_post_url = ig_res.get("post_url", "")

    # 3. YouTube Shorts (@samarthavastu999)
    existing_yt_url = target_item.get("yt_short_url", "")
    if existing_yt_url and "gg3nNP0kueg" not in existing_yt_url and "@samarthavastu999/shorts" not in existing_yt_url:
        log.info("[YouTube Shorts] Already published for %s: %s (Skipping re-upload)", item_id, existing_yt_url)
        yt_res = {
            "success": True,
            "short_url": existing_yt_url,
        }
    else:
        if existing_yt_url:
            log.warning("[YouTube Shorts] Stale/fallback URL detected for %s: %s — will re-upload to get correct short URL", item_id, existing_yt_url)
        try:
            wait_for_unlocked_desktop(timeout_sec=1800)
            from youtube_shorts_uploader import upload_short_to_youtube
            yt_res = upload_short_to_youtube(target_item, dry_run=dry_run)
            if yt_res.get("success") and not dry_run:
                target_item["yt_short_url"] = yt_res.get("short_url")
                save_schedule(schedule)
        except Exception as exc:
            log.error("[YouTube Shorts] Upload error: %s", exc)
            yt_res = {"success": False, "short_url": None, "error": str(exc)}

    yt_short_url = yt_res.get("short_url", "") if yt_res.get("success") else ""

    # 4. WhatsApp Public Group & Personal WhatsApp
    group_caption = build_whatsapp_caption(target_item, is_preview=False, is_admin=False)
    admin_caption = build_whatsapp_caption(
        target_item,
        is_preview=False,
        is_admin=True,
        remaining_unposted=remaining_unposted,
        fb_status=bool(fb_res.get("success")),
        ig_status=bool(ig_res.get("success")),
        yt_short_status=bool(yt_res.get("success")),
        yt_short_url=yt_short_url,
    )

    g_ok = target_item.get("wa_group_sent", False)
    if g_ok:
        log.info("[WhatsApp] Public Group already sent for %s (Skipping re-send)", item_id)
    else:
        log.info("[WhatsApp] [1/2] Sending to Public Group: %s", WHATSAPP_GROUP)
        g_ok = dispatch_whatsapp_media(WHATSAPP_GROUP, poster_path, group_caption, tag="group_public", dry_run=dry_run)
        if g_ok and not dry_run:
            target_item["wa_group_sent"] = True
            save_schedule(schedule)
        time.sleep(5)

    a_ok = target_item.get("wa_admin_sent", False)
    if a_ok:
        log.info("[WhatsApp] Personal Admin already sent for %s (Skipping re-send)", item_id)
    else:
        log.info("[WhatsApp] [2/2] Sending to Personal WhatsApp: %s", WHATSAPP_ADMIN)
        a_ok = dispatch_whatsapp_media(WHATSAPP_ADMIN, poster_path, admin_caption, tag="admin_personal", dry_run=dry_run)
        if a_ok and not dry_run:
            target_item["wa_admin_sent"] = True
            save_schedule(schedule)

    # 5. Telegram Channel
    tg_caption = build_telegram_caption(target_item)
    tg_ok = target_item.get("tg_sent", False)
    if tg_ok:
        log.info("[Telegram] Already sent for %s (Skipping re-send)", item_id)
    else:
        log.info("[Telegram] Sending to channel: %s", TELEGRAM_CHAT_ID)
        tg_res = publish_to_telegram(target_item, poster_path, tg_caption, dry_run=dry_run)
        tg_ok = tg_res.get("success", False)
        if tg_ok and not dry_run:
            target_item["tg_sent"] = True
            save_schedule(schedule)

    any_success = fb_res.get("success") or ig_res.get("success") or yt_res.get("success") or g_ok or a_ok or tg_ok
    if any_success and not dry_run:
        target_item["status"]        = "published"
        target_item["scheduled_date"] = datetime.now().strftime("%Y-%m-%d")
        if not target_item.get("published_at"):
            target_item["published_at"] = datetime.now().isoformat()
        target_item["fb_post_id"]    = fb_post_id
        target_item["fb_post_url"]   = fb_post_url
        target_item["ig_media_id"]   = ig_media_id
        target_item["ig_post_url"]   = ig_post_url
        target_item["yt_short_url"]  = yt_short_url
        target_item["wa_group_sent"] = bool(g_ok)
        target_item["wa_admin_sent"] = bool(a_ok)
        target_item["tg_sent"]       = bool(tg_ok)
        target_item["wa_sent"]       = bool(g_ok and a_ok)
        save_schedule(schedule)

        # 5. Update Website Data & Auto Git Sync
        try:
            from website_sync import sync_website_data
            log.info("[Website Sync] Updating public/videos_data.json and index.html...")
            sync_website_data()
            auto_git_sync(title=target_item.get("title", ""))
        except Exception as exc:
            log.warning("[Post-Publish Sync] Note: %s", exc)

    section(f"STAGE A SUMMARY for {item_id}")
    print(f"  Facebook       : {'[OK]' if fb_res.get('success') else '[FAIL]'}  {fb_post_url}")
    print(f"  Instagram      : {'[OK]' if ig_res.get('success') else '[FAIL]'}  {ig_post_url}")
    print(f"  YouTube Short  : {'[OK]' if yt_res.get('success') else '[FAIL]'}  {yt_short_url}")
    print(f"  WhatsApp Group : {'[OK]' if g_ok else '[FAIL]'}")
    print(f"  WhatsApp Admin : {'[OK]' if a_ok else '[FAIL]'}")
    print(f"  Telegram       : {'[OK]' if tg_ok else '[FAIL]'}")

    return any_success


# ---------------------------------------------------------------------------- #
#  Stage B: Prepare & Send Tomorrow's Preview                                    #
# ---------------------------------------------------------------------------- #

def run_stage_b_prepare_tomorrow(schedule: list, dry_run: bool = False) -> dict | None:
    """
    Executes Stage B:
    1. Runs youtube_sync.py to check for newly uploaded videos.
    2. Picks the newest unposted video.
    3. Renders 4:5 poster via Headless Chrome.
    4. Marks item as "preview_approved" for tomorrow.
    5. Sends poster + caption ONLY to Personal WhatsApp (+918919395559).
    """
    section("STAGE B: PREPARING & SENDING TOMORROW'S PREVIEW")

    # Ingest any new YouTube uploads
    try:
        from youtube_sync import sync_youtube
        log.info("[Stage B] Running youtube_sync to ensure newest uploads are queued first...")
        sync_youtube(force_poster=False)
        schedule = load_schedule()
    except Exception as exc:
        log.warning("[Stage B] Sync note: %s", exc)

    # Find candidate
    candidate = None
    for item in schedule:
        if item.get("status") == "preview_approved":
            candidate = item
            break

    if not candidate:
        for item in schedule:
            if item.get("status") not in ("published", "skipped"):
                candidate = item
                break

    if not candidate:
        log.warning("[Stage B] No unposted videos remaining in queue!")
        return None

    # Invariant: Strictly only ONE item can ever be in 'preview_approved' status
    for item in schedule:
        if item.get("status") == "preview_approved" and item.get("id") != candidate["id"]:
            item["status"] = "pending"

    # IDEMPOTENCY: If Stage B already succeeded for this candidate today,
    # exit immediately with ZERO WhatsApp Web navigation (prevents hourly
    # Task Scheduler triggers from re-sending duplicate separator + poster).
    today_str = datetime.now().strftime("%Y-%m-%d")
    if candidate.get("preview_sent_date") == today_str:
        log.info("[Stage B] Preview already sent today (%s) for %s — skipping all WhatsApp sends.", today_str, candidate["id"])
        return candidate

    candidate["status"] = "preview_approved"
    poster_path = ensure_poster_exists(candidate)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != candidate["id"])

    # Build daily posting report from today's completed item
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_dt = tomorrow_dt.replace(day=tomorrow_dt.day + 1)
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")
    
    today_item = None
    for item in schedule:
        pub_at = item.get("published_at") or ""
        if pub_at.startswith(today_str) and item.get("status") == "published":
            today_item = item
            break
    
    daily_report = build_daily_posting_report(today_item, today_str, tomorrow_str)

    preview_caption = build_whatsapp_caption(
        candidate,
        is_preview=True,
        is_admin=True,
        remaining_unposted=remaining_unposted,
    )
    
    # Prepend daily report to preview caption
    if daily_report:
        preview_caption = daily_report + preview_caption
        # Ensure combined caption doesn't exceed WhatsApp's 1024 char limit
        if len(preview_caption) > 1024:
            preview_caption = preview_caption[:1020] + "..."

    log.info("[Stage B] Selected Tomorrow's Candidate: %s (%s)", candidate["id"], candidate.get("title", "")[:45])
    log.info("[Stage B] Upload Date: %s | Remaining Unposted: %d", candidate.get("upload_date"), remaining_unposted)
    log.info("[Stage B] Sending Preview ONLY to Personal WhatsApp: %s", WHATSAPP_ADMIN)

    # ANTI-SPAM: Never resend separator if already sent today (prevents hourly
    # Task Scheduler retries from re-sending the separator text after a failed
    # poster send). Separator is sent at most once per day.
    sep_ok = True
    if candidate.get("separator_sent_date") != today_str:
        separator_text = "📋 రేపటి వీడియో ప్రివ్యూ (Tomorrow's Scheduled Preview)"
        log.info("[Stage B] Sending separator message before preview poster...")
        sep_res = dispatch_whatsapp_text(
            WHATSAPP_ADMIN,
            separator_text,
            tag="admin_preview_separator",
            dry_run=dry_run,
        )
        # sep_res is always a dict from dispatch_whatsapp_text(); guard against
        # any legacy bool return so a raw bool can never crash Stage B.
        sep_ok = sep_res if isinstance(sep_res, bool) else bool(sep_res and sep_res.get("success"))
        if sep_ok and not dry_run:
            candidate["separator_sent_date"] = today_str
            save_schedule(schedule)
            log.info("[Stage B] Separator sent successfully.")
        elif not dry_run:
            log.warning("[Stage B] Separator message dispatch failed, but continuing with preview...")
    else:
        log.info("[Stage B] Separator already sent today — skipping re-send.")
    time.sleep(3)  # wait 3 seconds so the text bubble separates from the poster

    sent = dispatch_whatsapp_media(
        WHATSAPP_ADMIN,
        poster_path,
        preview_caption,
        tag="admin_preview",
        dry_run=dry_run,
    )

    # Only mark Stage B fully complete when BOTH separator AND poster succeeded.
    # If the poster fails, preview_sent_date stays unset so the next hourly run
    # retries the poster (without re-sending the separator).
    if not dry_run and sep_ok and sent:
        candidate["preview_sent_date"] = datetime.now().strftime("%Y-%m-%d")
        save_schedule(schedule)

    section(f"STAGE B SUMMARY — TOMORROW'S PREVIEW SENT")
    print(f"  Tomorrow's Video : [{candidate['id']}] {candidate.get('title','')}")
    print(f"  Poster File      : {poster_path}")
    print(f"  Sent to WhatsApp : {'[OK]' if sent else '[FAIL]'} ({WHATSAPP_ADMIN})")
    print(f"  Queue Remaining  : {remaining_unposted} unposted videos")

    return candidate


# ---------------------------------------------------------------------------- #
#  Skip Tomorrow Control                                                         #
# ---------------------------------------------------------------------------- #

def run_skip_tomorrow(schedule: list, dry_run: bool = False):
    """
    Marks current "preview_approved" video as "skipped",
    picks the next newest unposted video, generates poster, and sends updated preview.
    """
    section("SKIP TOMORROW — REGENERATING NEXT VIDEO")

    current_preview = None
    for item in schedule:
        if item.get("status") == "preview_approved":
            current_preview = item
            break

    if current_preview:
        log.info("Marking '%s' (%s) as 'skipped'...", current_preview["id"], current_preview.get("title","")[:40])
        current_preview["status"] = "skipped"
    else:
        log.info("No current 'preview_approved' item found; selecting next unposted item.")

    next_candidate = None
    for item in schedule:
        if item.get("status") not in ("published", "skipped"):
            next_candidate = item
            break

    if not next_candidate:
        log.warning("No more unposted videos in queue!")
        save_schedule(schedule)
        return

    # Invariant: Strictly only ONE item can ever be in 'preview_approved' status
    for item in schedule:
        if item.get("status") == "preview_approved" and item.get("id") != next_candidate["id"]:
            item["status"] = "pending"

    next_candidate["status"] = "preview_approved"
    poster_path = ensure_poster_exists(next_candidate)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != next_candidate["id"])

    # Build daily posting report from today's completed item
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_dt = tomorrow_dt.replace(day=tomorrow_dt.day + 1)
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")
    
    today_item = None
    for item in schedule:
        pub_at = item.get("published_at") or ""
        if pub_at.startswith(today_str) and item.get("status") == "published":
            today_item = item
            break
    
    daily_report = build_daily_posting_report(today_item, today_str, tomorrow_str)

    preview_caption = build_whatsapp_caption(
        next_candidate,
        is_preview=True,
        is_admin=True,
        remaining_unposted=remaining_unposted,
    )
    
    # Prepend daily report to preview caption
    if daily_report:
        preview_caption = daily_report + preview_caption
        # Ensure combined caption doesn't exceed WhatsApp's 1024 char limit
        if len(preview_caption) > 1024:
            preview_caption = preview_caption[:1020] + "..."

    log.info("Sending Replacement Preview ONLY to Personal WhatsApp: %s", WHATSAPP_ADMIN)
    dispatch_whatsapp_media(WHATSAPP_ADMIN, poster_path, preview_caption, tag="admin_preview_regen", dry_run=dry_run)

    if not dry_run:
        save_schedule(schedule)

    print(f"\n  Skipped previous video. New preview locked for tomorrow: [{next_candidate['id']}] {next_candidate.get('title','')}")


# ---------------------------------------------------------------------------- #
#  WhatsApp-Only Dispatch                                                        #
# ---------------------------------------------------------------------------- #

def run_whatsapp_only(schedule: list, dry_run: bool = False) -> bool:
    """
    Dispatches WhatsApp media (Public Group + Admin) for the target video only.
    Useful for retrying WhatsApp delivery without re-posting to Facebook or Instagram.
    """
    section("WHATSAPP-ONLY DISPATCH")

    target_item = None
    # 1. Look for preview_approved item
    for item in schedule:
        if item.get("status") == "preview_approved":
            target_item = item
            break

    # 2. Look for item published today
    if not target_item:
        today_str = datetime.now().strftime("%Y-%m-%d")
        for item in schedule:
            if item.get("status") == "published" and (item.get("published_at") or "").startswith(today_str):
                target_item = item
                break

    # 3. Fallback to first unposted item
    if not target_item:
        for item in schedule:
            if item.get("status") not in ("published", "skipped"):
                target_item = item
                break

    if not target_item:
        log.warning("[WhatsApp Only] No items found in queue.")
        return False

    item_id = target_item["id"]
    poster_path = ensure_poster_exists(target_item)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != item_id)
    group_caption = build_whatsapp_caption(target_item, is_preview=False, is_admin=False)
    admin_caption = build_whatsapp_caption(target_item, is_preview=False, is_admin=True, remaining_unposted=remaining_unposted)

    log.info("[WhatsApp Only] Target: %s (%s)", item_id, target_item.get("title", "")[:40])

    g_ok = target_item.get("wa_group_sent", False)
    if g_ok:
        log.info("[WhatsApp] Public Group already marked sent for %s. Skipping re-send.", item_id)
    else:
        log.info("[WhatsApp] [1/2] Sending to Public Group: %s", WHATSAPP_GROUP)
        g_ok = dispatch_whatsapp_media(WHATSAPP_GROUP, poster_path, group_caption, tag="group_public", dry_run=dry_run)
        if g_ok and not dry_run:
            target_item["wa_group_sent"] = True
            save_schedule(schedule)
        time.sleep(5)

    a_ok = target_item.get("wa_admin_sent", False)
    if a_ok:
        log.info("[WhatsApp] Personal Admin already marked sent for %s. Skipping re-send.", item_id)
    else:
        log.info("[WhatsApp] [2/2] Sending to Personal WhatsApp: %s", WHATSAPP_ADMIN)
        a_ok = dispatch_whatsapp_media(WHATSAPP_ADMIN, poster_path, admin_caption, tag="admin_personal", dry_run=dry_run)
        if a_ok and not dry_run:
            target_item["wa_admin_sent"] = True
            target_item["wa_sent"] = bool(g_ok and a_ok)
            save_schedule(schedule)

    section(f"WHATSAPP-ONLY SUMMARY for {item_id}")
    print(f"  WhatsApp Group : {'[OK]' if g_ok else '[FAIL]'}")
    print(f"  WhatsApp Admin : {'[OK]' if a_ok else '[FAIL]'}")

    return bool(g_ok or a_ok)


# ---------------------------------------------------------------------------- #
#  Main CLI Entrypoint                                                           #
# ---------------------------------------------------------------------------- #

def main():
    global _STABILIZED, DRY_RUN, MANUAL_RUN

    parser = argparse.ArgumentParser(description="Samartha Vastu 2-Stage Daily Auto Publisher")
    parser.add_argument("--daily-run",         action="store_true",
                        help="Run full morning cycle: Stage A (publish today) + Stage B (prepare tomorrow)")
    parser.add_argument("--prepare-tomorrow",  action="store_true",
                        help="Run Stage B only: prepare & send tomorrow's preview to personal WhatsApp")
    parser.add_argument("--skip-tomorrow",     action="store_true",
                        help="Skip currently approved preview, pick next unposted, and send replacement")
    parser.add_argument("--publish-next",      action="store_true",
                        help="Publish next/approved item now")
    parser.add_argument("--whatsapp-only",     action="store_true",
                        help="Send only WhatsApp messages without touching Facebook or Instagram")
    parser.add_argument("--dry-run",           action="store_true",
                        help="Simulate without real API calls")
    parser.add_argument("--force",             action="store_true",
                        help="Bypass daily 1-post-per-day lock and skip 5-minute stabilization")
    parser.add_argument("--manual",            action="store_true",
                        help="Manual run from Publish_Now.bat - skips 5-minute stabilization delay")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    MANUAL_RUN = args.manual or args.force

    # --- Single-instance lock: prevent dual-process race condition ---
    if not acquire_publisher_lock():
        print("[FATAL] Another auto_publisher instance is already running (logs/publisher.lock held). Exiting to prevent race condition.")
        sys.exit(1)
    try:
        import atexit
        atexit.register(release_publisher_lock)
    except Exception:
        pass

    section("Samartha Vastu Publisher" + (" [DRY-RUN]" if DRY_RUN else " [LIVE]"))

    # (b1) Active-hours guard — automatic runs only between 06:00 and 22:00 local time.
    #      Midnight/late-night task triggers exit silently with ZERO popup and ZERO posts.
    if not DRY_RUN and not MANUAL_RUN:
        now_hour = datetime.now().hour
        if now_hour < 6 or now_hour >= 22:
            log.info("[Time Guard] Current time %02d:00 is outside 06:00-22:00 window. Exiting silently (zero popup, zero posts).", now_hour)
            release_publisher_lock()
            return

    # (b) INSTANT IDLENESS GATE — < 1s silent exit if everything is already done.
    #      Check BEFORE any wait, before any Chrome launch, before any prompt.
    if not DRY_RUN:
        schedule_for_lock = load_schedule()
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_item = None
        for item in schedule_for_lock:
            pub_at = item.get("published_at") or ""
            if pub_at.startswith(today_str) and item.get("status") == "published":
                today_item = item
                break
        if today_item:
            # Check ALL 7 channels complete + Stage B preview sent today
            has_fb = bool(today_item.get("fb_post_url"))
            has_ig = bool(today_item.get("ig_post_url"))
            has_yt = bool(today_item.get("yt_short_url"))
            has_wa_grp = bool(today_item.get("wa_group_sent"))
            has_wa_adm = bool(today_item.get("wa_admin_sent"))
            has_tg = bool(today_item.get("tg_sent"))
            has_wa = bool(today_item.get("wa_sent") or (has_wa_grp and has_wa_adm))
            preview_sent_today = today_item.get("preview_sent_date") == today_str
            if has_fb and has_ig and has_yt and has_wa and has_tg and preview_sent_today:
                log.info("[Time Guard] Today's item %s is 100%% complete across ALL channels. Exiting silently in <1s.", today_item.get("id"))
                release_publisher_lock()
                return

    # (b2) Daily Snooze — if user clicked No earlier today on an automatic run,
    #      exit silently in <1s so the Scheduled Task stops re-prompting.
    if not DRY_RUN and not MANUAL_RUN:
        declined_file = LOGS_DIR / "declined_today.txt"
        try:
            if declined_file.exists() and declined_file.read_text(encoding="utf-8").strip() == datetime.now().strftime("%Y-%m-%d"):
                release_publisher_lock()
                return
        except Exception:
            pass

    # (c) FAST READINESS — only when work actually remains:
    #     - Internet check with short timeout (max ~8s, not 180s)
    #     - Desktop unlock check (max ~30s)
    #     - Skip 300s stabilization; use max 30s settle instead
    if not DRY_RUN:
        if not wait_for_internet(timeout_seconds=8):
            log.error("Aborting run due to lack of internet connectivity.")
            release_publisher_lock()
            sys.exit(1)

    schedule = load_schedule()

    # (c2) Desktop unlock check (fast: max ~15s)
    if not DRY_RUN:
        if not wait_for_unlocked_desktop(timeout_sec=15):
            log.error("[Desktop Watcher] Could not proceed — desktop remained locked.")
            release_publisher_lock()
            sys.exit(1)

    # (d1) Re-check active-hours after readiness — if time crossed 22:00,
    #      exit silently with ZERO popup before showing confirmation.
    if not DRY_RUN and not MANUAL_RUN:
        now_hour = datetime.now().hour
        if now_hour >= 22:
            log.info("[Time Guard] Current time %02d:00 is at/after 22:00 after readiness wait. Exiting silently.", now_hour)
            release_publisher_lock()
            return

    # (e) Show topmost Yes/No MessageBox BEFORE Facebook or Instagram runs.
    target_item_for_dialog = None
    if args.whatsapp_only:
        for item in schedule:
            if item.get("status") == "preview_approved":
                target_item_for_dialog = item
                break
        if not target_item_for_dialog:
            today_str = datetime.now().strftime("%Y-%m-%d")
            for item in schedule:
                if item.get("status") == "published" and (item.get("published_at") or "").startswith(today_str):
                    target_item_for_dialog = item
                    break
        if not target_item_for_dialog:
            for item in schedule:
                if item.get("status") not in ("published", "skipped"):
                    target_item_for_dialog = item
                    break

    if args.skip_tomorrow:
        for item in schedule:
            if item.get("status") == "preview_approved":
                target_item_for_dialog = item
                break

    if args.prepare_tomorrow:
        candidate = None
        for item in schedule:
            if item.get("status") == "preview_approved":
                candidate = item
                break
        if not candidate:
            for item in schedule:
                if item.get("status") not in ("published", "skipped"):
                    candidate = item
                    break
        target_item_for_dialog = candidate

    if args.publish_next or args.daily_run:
        today_str = datetime.now().strftime("%Y-%m-%d")
        for item in schedule:
            pub_at = item.get("published_at") or ""
            if pub_at.startswith(today_str) and not is_daily_completed_for_item(item):
                target_item_for_dialog = item
                break
        if not target_item_for_dialog:
            for item in schedule:
                if item.get("status") == "preview_approved":
                    target_item_for_dialog = item
                    break
        if not target_item_for_dialog:
            for item in schedule:
                if item.get("status") not in ("published", "skipped"):
                    target_item_for_dialog = item
                    break

    if target_item_for_dialog and not DRY_RUN:
        dialog_title = target_item_for_dialog.get("title") or target_item_for_dialog.get("id", "Unknown")
        # Compute partial progress for dialog display
        today_str = datetime.now().strftime("%Y-%m-%d")
        pub_at = target_item_for_dialog.get("published_at") or ""
        is_today = pub_at.startswith(today_str)
        completed_channels = 0
        pending_channel = ""
        if is_today:
            completed_channels = sum(1 for f in [
                bool(target_item_for_dialog.get("fb_post_url")),
                bool(target_item_for_dialog.get("ig_post_url")),
                bool(target_item_for_dialog.get("yt_short_url")),
                bool(target_item_for_dialog.get("wa_group_sent")),
                bool(target_item_for_dialog.get("wa_admin_sent")),
                bool(target_item_for_dialog.get("tg_sent")),
            ])
            # Determine which channel is pending
            if not target_item_for_dialog.get("fb_post_url"):
                pending_channel = "Facebook Page"
            elif not target_item_for_dialog.get("ig_post_url"):
                pending_channel = "Instagram"
            elif not target_item_for_dialog.get("yt_short_url"):
                pending_channel = "YouTube Shorts"
            elif not target_item_for_dialog.get("wa_group_sent"):
                pending_channel = "WhatsApp Group"
            elif not target_item_for_dialog.get("wa_admin_sent"):
                pending_channel = "WhatsApp Admin"
            elif not target_item_for_dialog.get("tg_sent"):
                pending_channel = "Telegram"
        if not show_confirmation_dialog(dialog_title, completed_channels, 7, pending_channel):
            log.info("[Startup Gate] User clicked No — exiting safely (exit 0). Item remains queued for next session.")
            release_publisher_lock()
            return

    if args.whatsapp_only:
        run_whatsapp_only(schedule, dry_run=DRY_RUN)
        return

    if args.skip_tomorrow:
        run_skip_tomorrow(schedule, dry_run=DRY_RUN)
        return

    if args.prepare_tomorrow:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if any(item.get("status") == "preview_approved" and item.get("preview_sent_date") == today_str for item in schedule):
            log.info("[Stage B] Preview already sent today (%s) — skipping all WhatsApp sends.", today_str)
            return
        run_stage_b_prepare_tomorrow(schedule, dry_run=DRY_RUN)
        return

    if args.publish_next:
        run_stage_a_public_publish(schedule, dry_run=DRY_RUN, force=args.force)
        return

    if args.daily_run:
        run_stage_a_public_publish(schedule, dry_run=DRY_RUN, force=args.force)
        refreshed_schedule = load_schedule()
        today_str = datetime.now().strftime("%Y-%m-%d")
        if any(item.get("status") == "preview_approved" and item.get("preview_sent_date") == today_str for item in refreshed_schedule):
            log.info("[Stage B] Preview already sent today (%s) — skipping all WhatsApp sends.", today_str)
        else:
            run_stage_b_prepare_tomorrow(refreshed_schedule, dry_run=DRY_RUN)
        return

    print("Please specify a command mode:")
    print("  --daily-run         : Full daily cycle (Publish today + Prepare tomorrow)")
    print("  --prepare-tomorrow  : Prepare & send tomorrow's preview to Personal WhatsApp")
    print("  --skip-tomorrow     : Skip current tomorrow preview and select next video")
    print("  --publish-next      : Publish next item")
    print("  --whatsapp-only     : Dispatch to WhatsApp only (safe retry)")


if __name__ == "__main__":
    main()
