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
       - WhatsApp Public Group (DvPDx43oel4LQQgqCsn7Tr) & Personal WhatsApp (+918919395559)
    5. Marks item as "status": "published".
    6. Calls website_sync.py to update public/videos_data.json and index.html.
    7. Runs auto_git_sync() to commit and push updates to GitHub.

  Stage B — Preparing & Sending Tomorrow's Preview (ONLY to Personal WhatsApp):
    1. Runs youtube_sync.py to ingest any newly uploaded videos from @samarthavastu999.
    2. Selects the newest unposted video (NEWEST -> OLDEST).
    3. Renders 4:5 poster using Headless Chrome (html_poster_generator.py).
    4. Marks item as "status": "preview_approved" for tomorrow.
    5. Sends poster + caption ONLY to Personal WhatsApp (+918919395559) prefixed with:
       "🔔 [TOMORROW'S PREVIEW — FOR YOUR CHECK ONLY]"
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
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("auto_publisher")

# --- Paths ---
BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
SCREENSHOTS_DIR = BASE_DIR / "logs" / "screenshots"

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
WHATSAPP_TARGET   = os.getenv("WHATSAPP_TARGET",    "DvPDx43oel4LQQgqCsn7Tr,+918919395559")
WHATSAPP_ADMIN    = os.getenv("WHATSAPP_ADMIN",     "+918919395559")
WHATSAPP_GROUP    = "DvPDx43oel4LQQgqCsn7Tr"

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
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def check_daily_published_lock(schedule: list, force: bool = False) -> bool:
    """
    Checks if a post was already published to public today (YYYY-MM-DD).
    Returns True if safe to publish to public, False if already published today.
    """
    if force:
        log.info("[Daily Lock] --force flag supplied: 1-post-per-day lock bypassed.")
        return True

    today_str = datetime.now().strftime("%Y-%m-%d")
    for item in schedule:
        if item.get("status") == "published":
            pub_at = item.get("published_at") or ""
            if pub_at.startswith(today_str):
                log.info("[Daily Lock Active] A post was ALREADY published to public today (%s):", today_str)
                log.info("  Item ID : %s", item.get("id"))
                log.info("  Title   : %s", (item.get("title") or "")[:50])
                log.info("  Time    : %s", pub_at)
                log.info("Skipping public re-publication to maintain strict 1-post-per-day rule.")
                return False
    return True


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
) -> str:
    """
    Builds WhatsApp formatted caption under 1000 characters to prevent modal overflow.
    If is_preview: prefixes with [TOMORROW'S PREVIEW — FOR YOUR CHECK ONLY].
    If is_admin: appends 3-line status receipt.
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
        footer_lines.append("📊 *Status:* Locked for Tomorrow's Morning Post")
        footer_lines.append(f"⏳ *Remaining Queue:* {remaining_unposted} unposted videos")
        footer_lines.append("(To skip or change: python auto_publisher.py --skip-tomorrow)")
    elif is_admin:
        footer_lines.append("")
        footer_lines.append("---")
        footer_lines.append("📊 *Daily Publishing Status:*")
        footer_lines.append(f"✅ *Published Today:* {title[:45]}")
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


# ---------------------------------------------------------------------------- #
#  Poster Resolver                                                               #
# ---------------------------------------------------------------------------- #

def ensure_poster_exists(item: dict) -> str:
    """Ensures 4:5 Headless Chrome poster exists at vastu_content_queue/thumbnails/yt_<ID>.jpg."""
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    poster_path = THUMBNAILS_DIR / f"{item['id']}.jpg"

    if not poster_path.exists() or poster_path.stat().st_size == 0:
        log.info("Generating Headless Chrome poster for: %s", item["id"])
        from html_poster_generator import render_html_to_poster
        render_html_to_poster(item, poster_path)

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
    if not dry_run and not check_daily_published_lock(schedule, force=force):
        return True

    # Find the target item: look for "preview_approved" first, then earliest pending
    target_item = None
    for item in schedule:
        if item.get("status") == "preview_approved":
            target_item = item
            break

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

    # 1. Facebook Page
    fb_res = publish_facebook(target_item, poster_path, caption, dry_run)
    fb_post_id  = fb_res.get("post_id")
    fb_post_url = fb_res.get("post_url", "")
    cdn_img_url = fb_res.get("cdn_image_url")

    # 2. Instagram
    ig_res = publish_instagram(target_item, cdn_img_url or "", caption, dry_run)
    ig_media_id = ig_res.get("media_id")
    ig_post_url = ig_res.get("post_url", "")

    # 3. WhatsApp Public Group & Personal WhatsApp
    group_caption = build_whatsapp_caption(target_item, is_preview=False, is_admin=False)
    admin_caption = build_whatsapp_caption(target_item, is_preview=False, is_admin=True, remaining_unposted=remaining_unposted)

    log.info("[WhatsApp] [1/2] Sending to Public Group: %s", WHATSAPP_GROUP)
    g_ok = dispatch_whatsapp_media(WHATSAPP_GROUP, poster_path, group_caption, tag="group_public", dry_run=dry_run)
    time.sleep(5)

    log.info("[WhatsApp] [2/2] Sending to Personal WhatsApp: %s", WHATSAPP_ADMIN)
    a_ok = dispatch_whatsapp_media(WHATSAPP_ADMIN, poster_path, admin_caption, tag="admin_personal", dry_run=dry_run)

    any_success = fb_res.get("success") or ig_res.get("success") or g_ok or a_ok
    if any_success and not dry_run:
        target_item["status"]       = "published"
        target_item["published_at"] = datetime.now().isoformat()
        target_item["fb_post_id"]   = fb_post_id
        target_item["fb_post_url"]  = fb_post_url
        target_item["ig_media_id"]  = ig_media_id
        target_item["ig_post_url"]  = ig_post_url
        target_item["wa_sent"]      = g_ok and a_ok
        save_schedule(schedule)

        # Update Website Data & Auto Git Sync
        try:
            from website_sync import sync_website_data
            log.info("[Website Sync] Updating public/videos_data.json and index.html...")
            sync_website_data()
            auto_git_sync(title=target_item.get("title", ""))
        except Exception as exc:
            log.warning("[Post-Publish Sync] Note: %s", exc)

    section(f"STAGE A SUMMARY for {item_id}")
    print(f"  Facebook  : {'[OK]' if fb_res.get('success') else '[FAIL]'}  {fb_post_url}")
    print(f"  Instagram : {'[OK]' if ig_res.get('success') else '[FAIL]'}  {ig_post_url}")
    print(f"  WhatsApp Group  : {'[OK]' if g_ok else '[FAIL]'}")
    print(f"  WhatsApp Admin  : {'[OK]' if a_ok else '[FAIL]'}")

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

    candidate["status"] = "preview_approved"
    poster_path = ensure_poster_exists(candidate)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != candidate["id"])

    preview_caption = build_whatsapp_caption(
        candidate,
        is_preview=True,
        is_admin=True,
        remaining_unposted=remaining_unposted,
    )

    log.info("[Stage B] Selected Tomorrow's Candidate: %s (%s)", candidate["id"], candidate.get("title", "")[:45])
    log.info("[Stage B] Upload Date: %s | Remaining Unposted: %d", candidate.get("upload_date"), remaining_unposted)
    log.info("[Stage B] Sending Preview ONLY to Personal WhatsApp: %s", WHATSAPP_ADMIN)

    sent = dispatch_whatsapp_media(
        WHATSAPP_ADMIN,
        poster_path,
        preview_caption,
        tag="admin_preview",
        dry_run=dry_run,
    )

    if not dry_run:
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

    next_candidate["status"] = "preview_approved"
    poster_path = ensure_poster_exists(next_candidate)
    remaining_unposted = sum(1 for i in schedule if i.get("status") not in ("published", "skipped") and i.get("id") != next_candidate["id"])

    preview_caption = build_whatsapp_caption(
        next_candidate,
        is_preview=True,
        is_admin=True,
        remaining_unposted=remaining_unposted,
    )

    log.info("Sending Replacement Preview ONLY to Personal WhatsApp: %s", WHATSAPP_ADMIN)
    dispatch_whatsapp_media(WHATSAPP_ADMIN, poster_path, preview_caption, tag="admin_preview_regen", dry_run=dry_run)

    if not dry_run:
        save_schedule(schedule)

    print(f"\n  Skipped previous video. New preview locked for tomorrow: [{next_candidate['id']}] {next_candidate.get('title','')}")


# ---------------------------------------------------------------------------- #
#  Main CLI Entrypoint                                                           #
# ---------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Samartha Vastu 2-Stage Daily Auto Publisher")
    parser.add_argument("--daily-run",         action="store_true",
                        help="Run full morning cycle: Stage A (publish today) + Stage B (prepare tomorrow)")
    parser.add_argument("--prepare-tomorrow",  action="store_true",
                        help="Run Stage B only: prepare & send tomorrow's preview to personal WhatsApp")
    parser.add_argument("--skip-tomorrow",     action="store_true",
                        help="Skip currently approved preview, pick next unposted, and send replacement")
    parser.add_argument("--publish-next",      action="store_true",
                        help="Publish next/approved item now")
    parser.add_argument("--dry-run",           action="store_true",
                        help="Simulate without real API calls")
    parser.add_argument("--force",             action="store_true",
                        help="Bypass daily 1-post-per-day lock")
    args = parser.parse_args()

    DRY_RUN = args.dry_run

    section("Samartha Vastu Publisher" + (" [DRY-RUN]" if DRY_RUN else " [LIVE]"))

    if not DRY_RUN:
        if not wait_for_internet(timeout_seconds=180):
            log.error("Aborting run due to lack of internet connectivity.")
            sys.exit(1)

    schedule = load_schedule()

    if args.skip_tomorrow:
        run_skip_tomorrow(schedule, dry_run=DRY_RUN)
        return

    if args.prepare_tomorrow:
        run_stage_b_prepare_tomorrow(schedule, dry_run=DRY_RUN)
        return

    if args.publish_next:
        run_stage_a_public_publish(schedule, dry_run=DRY_RUN, force=args.force)
        return

    if args.daily_run:
        run_stage_a_public_publish(schedule, dry_run=DRY_RUN, force=args.force)
        refreshed_schedule = load_schedule()
        run_stage_b_prepare_tomorrow(refreshed_schedule, dry_run=DRY_RUN)
        return

    print("Please specify a command mode:")
    print("  --daily-run         : Full daily cycle (Publish today + Prepare tomorrow)")
    print("  --prepare-tomorrow  : Prepare & send tomorrow's preview to Personal WhatsApp")
    print("  --skip-tomorrow     : Skip current tomorrow preview and select next video")
    print("  --publish-next      : Publish next item")


if __name__ == "__main__":
    main()
