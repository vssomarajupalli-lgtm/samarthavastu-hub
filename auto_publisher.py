"""
auto_publisher.py
-----------------
Samartha Vastu - Automated Daily Publisher

Reads master_schedule.json and publishes due items to:
  - Facebook Page (Meta Graph API)
  - Instagram Business Account (Meta Graph API, two-step)
  - WhatsApp (pywhatkit.sendwhats_image)

Updates each item status to "published" with post URLs after success
so nothing is ever double-posted.

Usage:
    python auto_publisher.py              # run all items due now (scheduled_at <= now)
    python auto_publisher.py --publish-next  # force-publish the next pending item
    python auto_publisher.py --dry-run    # simulate without any real API calls
    python auto_publisher.py --item video_01  # publish a specific item by ID
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
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
BASE_DIR       = Path(__file__).resolve().parent
QUEUE_DIR      = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE  = QUEUE_DIR / "master_schedule.json"

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
WHATSAPP_TARGET   = os.getenv("WHATSAPP_TARGET",    "")   # comma-separated: group IDs and/or phone numbers
WHATSAPP_ADMIN    = os.getenv("WHATSAPP_ADMIN",     "")   # personal admin number (optional)

# --- Instagram polling ---
IG_POLL_INTERVAL = 4   # seconds
IG_POLL_MAX      = 20  # max polls before giving up


def section(title: str):
    bar = "=" * 62
    print(f"\n{bar}\n  {title}\n{bar}")


# ---------------------------------------------------------------------------- #
#  Schedule helpers                                                              #
# ---------------------------------------------------------------------------- #

def load_schedule() -> list:
    if not SCHEDULE_FILE.exists():
        log.error("master_schedule.json not found. Run queue_builder.py first.")
        sys.exit(1)
    # utf-8-sig silently strips BOM that PowerShell adds when writing UTF-8
    with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("items", [])


def save_schedule(items: list):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def get_due_items(schedule: list) -> list:
    """Return items whose scheduled_at <= now and status == pending."""
    now = datetime.now()
    due = []
    for item in schedule:
        if item.get("status") != "pending":
            continue
        scheduled_at_str = item.get("scheduled_at", "")
        if not scheduled_at_str:
            continue
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str)
            if scheduled_at <= now:
                due.append(item)
        except ValueError:
            pass
    return due


def get_next_pending(schedule: list):
    """Return the earliest pending item regardless of schedule time."""
    pending = [i for i in schedule if i.get("status") == "pending"]
    if not pending:
        return None
    return min(pending, key=lambda x: x.get("scheduled_at", "9999"))


# ---------------------------------------------------------------------------- #
#  Meta Graph API helpers                                                        #
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


# ---------------------------------------------------------------------------- #
#  Caption builder                                                               #
# ---------------------------------------------------------------------------- #

def build_caption(item: dict, fb_url: str = "", ig_url: str = "") -> str:
    """
    Builds a rich Telugu caption including the title, caption body, and links.
    """
    title   = item.get("title",   "")
    caption = item.get("caption", "")

    parts = []
    if title:
        parts.append(f"{title}")
        parts.append("")
    if caption:
        parts.append(caption)
        parts.append("")

    parts.append(f"📺 YouTube: {YOUTUBE_URL}")
    parts.append(f"📞 WhatsApp: {CONTACT_PHONE}")
    parts.append(f"✉️ Email: {CONTACT_EMAIL}")

    # Add live post links if available (for WhatsApp message)
    if fb_url or ig_url:
        parts.append("")
        if fb_url:
            parts.append(f"🌐 Facebook: {fb_url}")
        if ig_url:
            parts.append(f"📸 Instagram: {ig_url}")

    return "\n".join(parts)


def build_whatsapp_caption(item: dict, fb_url: str = "", ig_url: str = "") -> str:
    """Build a formatted WhatsApp message with title, caption, and live links."""
    title   = item.get("title",   "")
    caption = item.get("caption", "")

    lines = []
    if title:
        lines.append(f"*{title}*")
        lines.append("")
    if caption:
        lines.append(caption)
        lines.append("")
    lines.append(f"📺 YouTube: {YOUTUBE_URL}")
    lines.append(f"📞 WhatsApp: {CONTACT_PHONE}")
    lines.append(f"✉️ Email: {CONTACT_EMAIL}")
    if fb_url or ig_url:
        lines.append("")
        if fb_url:
            lines.append(f"🌐 Facebook: {fb_url}")
        if ig_url:
            lines.append(f"📸 Instagram: {ig_url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- #
#  Facebook publisher                                                            #
# ---------------------------------------------------------------------------- #

def publish_facebook(item: dict, local_thumb: str, caption: str, dry_run: bool) -> dict:
    """
    Upload local thumbnail directly to Facebook Page via multipart form-data,
    then fetch the Facebook CDN URL of the uploaded image so Instagram can use it.

    Returns:
        {
            "success":       bool,
            "post_id":       str,   # e.g. "271667576040971_123456789"
            "post_url":      str,   # https://www.facebook.com/PAGE/posts/PHOTO
            "cdn_image_url": str,   # highest-res CDN URL — pass to Instagram
        }
    """
    section("FACEBOOK PAGE POST")

    endpoint = f"{FB_PAGE_ID}/photos"
    log.info("[Facebook] Endpoint : POST %s/%s", GRAPH_BASE, endpoint)
    log.info("[Facebook] Local file: %s", local_thumb)
    log.info("[Facebook] Caption  : %s...", caption[:80])

    if dry_run:
        log.info("[Facebook] DRY-RUN - skipping real request")
        mock_id = f"271667576040971_dry-run-{item['id']}"
        # Return a realistic placeholder CDN URL so the IG dry-run also works
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
        return {"success": False, "post_id": None, "post_url": None,
                "cdn_image_url": None, "error": err}

    # ── Step 1: Upload file via multipart ─────────────────────────────────
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
        return {"success": False, "post_id": None, "post_url": None,
                "cdn_image_url": None, "error": str(exc)}

    if "id" not in data:
        log.error("[Facebook] Upload failed: %s", data)
        return {"success": False, "post_id": None, "post_url": None,
                "cdn_image_url": None, "error": str(data)}

    photo_id = data["id"]
    post_url = f"https://www.facebook.com/{photo_id.replace('_', '/posts/')}"
    log.info("[Facebook] Uploaded photo id: %s", photo_id)

    # ── Step 2: Fetch CDN URL from the uploaded photo ────────────────────
    cdn_image_url = None
    meta = _api_get(
        photo_id,
        {"fields": "images,link", "access_token": META_ACCESS_TOKEN},
    )
    images = meta.get("images", [])
    if images:
        # images are sorted largest first
        cdn_image_url = images[0].get("source")
        log.info("[Facebook] CDN image URL: %s", cdn_image_url)
    else:
        log.warning("[Facebook] Could not fetch CDN image URL for photo %s — Instagram step may fail", photo_id)

    log.info("[Facebook] Post URL: %s", post_url)
    return {
        "success":       True,
        "post_id":       photo_id,
        "post_url":      post_url,
        "cdn_image_url": cdn_image_url,
    }


# ---------------------------------------------------------------------------- #
#  Instagram publisher                                                           #
# ---------------------------------------------------------------------------- #

def _poll_ig_container(container_id: str) -> bool:
    for i in range(IG_POLL_MAX):
        data   = _api_get(container_id, {"fields": "status_code,status", "access_token": META_ACCESS_TOKEN})
        status = data.get("status_code", "")
        log.debug("[Instagram] Container %s status: %s (poll %d)", container_id, status, i + 1)
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            log.error("[Instagram] Container failed: %s", data)
            return False
        time.sleep(IG_POLL_INTERVAL)
    log.error("[Instagram] Container %s never reached FINISHED", container_id)
    return False


def publish_instagram(item: dict, image_url: str, caption: str, dry_run: bool) -> dict:
    """
    Two-step Instagram publish: create container -> poll -> publish.

    Args:
        image_url: Publicly accessible HTTPS URL of the image.
                   Pass the Facebook CDN URL returned by publish_facebook()
                   so no external hosting is required.

    Returns:
        {
            "success":  bool,
            "media_id": str,   # Instagram media ID
            "post_url": str,   # exact post permalink (or profile fallback)
        }
    """
    section("INSTAGRAM BUSINESS POST")

    ig_profile_url = "https://www.instagram.com/samarthavastu999/"

    log.info("[Instagram] Step 1 - Create container")
    log.info("[Instagram] Image URL: %s", image_url)
    log.info("[Instagram] Caption preview: %s...", caption[:80])

    if dry_run:
        log.info("[Instagram] DRY-RUN - skipping container creation")
        return {
            "success":  True,
            "media_id": f"dry-run-ig-{item['id']}",
            "post_url": ig_profile_url,
        }

    if not image_url:
        err = "No CDN image URL available for Instagram (Facebook upload may have failed)"
        log.error("[Instagram] %s", err)
        return {"success": False, "media_id": None, "post_url": None, "error": err}

    # ── Step 1: Create media container ───────────────────────────────────
    ep1      = f"{IG_USER_ID}/media"
    payload1 = {
        "image_url":    image_url,
        "caption":      caption,
        "access_token": META_ACCESS_TOKEN,
    }

    data1 = _api_post(ep1, payload1)
    if "id" not in data1:
        log.error("[Instagram] Container creation failed: %s", data1)
        return {"success": False, "media_id": None, "post_url": None, "error": str(data1)}

    container_id = data1["id"]
    log.info("[Instagram] Container created: %s", container_id)

    # ── Poll until FINISHED ───────────────────────────────────────────────
    if not _poll_ig_container(container_id):
        return {"success": False, "media_id": None, "post_url": None,
                "error": f"Container {container_id} did not reach FINISHED"}

    # ── Step 2: Publish container ─────────────────────────────────────────
    ep2      = f"{IG_USER_ID}/media_publish"
    payload2 = {"creation_id": container_id, "access_token": META_ACCESS_TOKEN}

    log.info("[Instagram] Step 2 - Publish container %s", container_id)
    data2 = _api_post(ep2, payload2)

    if "id" not in data2:
        log.error("[Instagram] Publish failed: %s", data2)
        return {"success": False, "media_id": None, "post_url": None, "error": str(data2)}

    media_id = data2["id"]
    log.info("[Instagram] Published media_id: %s", media_id)

    # ── Step 3: Fetch exact post permalink ────────────────────────────────
    permalink = ig_profile_url   # safe fallback
    pdata = _api_get(
        media_id,
        {"fields": "permalink", "access_token": META_ACCESS_TOKEN},
    )
    if pdata.get("permalink"):
        permalink = pdata["permalink"]
        log.info("[Instagram] Permalink: %s", permalink)
    else:
        log.warning("[Instagram] Could not fetch permalink for media %s — using profile URL", media_id)

    return {"success": True, "media_id": media_id, "post_url": permalink}


# ---------------------------------------------------------------------------- #
#  WhatsApp dispatcher                                                           #
# ---------------------------------------------------------------------------- #

def dispatch_whatsapp(item: dict, thumb_path: str, wa_caption: str, dry_run: bool) -> bool:
    """
    Send thumbnail image + Telugu caption to every target in WHATSAPP_TARGET.

    WHATSAPP_TARGET is a comma-separated string; each entry is either:
      - A WhatsApp Group Invite ID  (e.g. DvPDx43oel4LQQgqCsn7Tr)
      - A phone number with code    (e.g. +918919395559)

    A 5-second pause is inserted between consecutive targets so WhatsApp Web
    has time to close the previous tab before opening the next one.

    Returns True if ALL targets were dispatched successfully.
    """
    section("WHATSAPP DISPATCH")

    # ── Parse targets ──────────────────────────────────────────────────────
    raw_targets = WHATSAPP_TARGET or ""
    targets = [t.strip() for t in raw_targets.split(",") if t.strip()]

    # Filter out any leftover placeholder values
    targets = [t for t in targets if not t.startswith("+91XXXX")]

    if not targets:
        log.warning("[WhatsApp] WHATSAPP_TARGET not configured or still placeholder — skipping.")
        log.warning("[WhatsApp] Set WHATSAPP_TARGET=<GroupInviteID>,<+PhoneNumber> in .env")
        return False

    if not Path(thumb_path).exists():
        log.warning("[WhatsApp] Thumbnail not found at %s — skipping WhatsApp.", thumb_path)
        return False

    log.info("[WhatsApp] Targets (%d): %s", len(targets), targets)
    log.info("[WhatsApp] Image   : %s", thumb_path)
    log.info("[WhatsApp] Caption : %s...", wa_caption[:80])

    if dry_run:
        for t in targets:
            log.info("[WhatsApp] DRY-RUN — would send to: %s", t)
        return True

    from whatsapp_sender import send_whatsapp_media

    all_ok = True
    for idx, target in enumerate(targets):
        log.info("[WhatsApp] [%d/%d] Sending to: %s", idx + 1, len(targets), target)
        tag = f"target_{idx+1}"
        try:
            res = send_whatsapp_media(
                target=target,
                img_path=thumb_path,
                caption=wa_caption,
                output_dir=str(BASE_DIR),
                target_tag=tag,
                wait_load=25,
                close_tab=False,
            )
            if res.get("success"):
                log.info("[WhatsApp] [%d/%d] Dispatched OK → %s", idx + 1, len(targets), target)
            else:
                all_ok = False
        except Exception as exc:
            log.error("[WhatsApp] [%d/%d] Failed → %s : %s", idx + 1, len(targets), target, exc)
            all_ok = False

        # Pause between targets so WhatsApp Web can settle
        if idx < len(targets) - 1:
            log.info("[WhatsApp] Waiting 5s before next target...")
            time.sleep(5)

    return all_ok


# ---------------------------------------------------------------------------- #
#  Main publish routine                                                          #
# ---------------------------------------------------------------------------- #

def resolve_local_thumb(item: dict) -> str:
    """
    Returns the absolute local path to the item's thumbnail.
    Checks the canonical thumbnails/ location first, then falls back
    to the thumbnail_file path recorded in master_schedule.json.
    """
    local_path = THUMBNAILS_DIR / f"{item['id']}.jpg"
    if not local_path.exists():
        tf = item.get("thumbnail_file")
        if tf:
            local_path = BASE_DIR / tf
    return str(local_path)


def publish_item(item: dict, schedule: list, dry_run: bool, skip_whatsapp: bool = False, whatsapp_only: bool = False) -> bool:
    """
    Full publish pipeline for a single item:
      1. Facebook
      2. Instagram
      3. WhatsApp
    Updates schedule in place. Returns True if at least one platform succeeded.
    """
    item_id     = item["id"]
    local_thumb = resolve_local_thumb(item)

    log.info("=" * 62)
    log.info("Publishing item: %s", item_id)
    log.info("Title          : %s", item.get("title", ""))
    log.info("Thumbnail      : %s", local_thumb)
    log.info("=" * 62)

    if whatsapp_only:
        log.info("[WhatsApp Only] Skipping Facebook and Instagram publishing.")
        fb_result   = {"success": False, "skipped": True}
        ig_result   = {"success": False, "skipped": True}
        fb_post_url = item.get("fb_post_url", "")
        ig_post_url = item.get("ig_post_url", "")

        wa_caption = build_whatsapp_caption(item, fb_url=fb_post_url, ig_url=ig_post_url)
        wa_sent    = dispatch_whatsapp(item, local_thumb, wa_caption, dry_run)

        section(f"PUBLISH SUMMARY (WhatsApp Only) for {item_id}")
        print(f"  WhatsApp : {'[OK]' if wa_sent else '[FAIL]'}")
        return wa_sent

    # ── 1. Facebook: multipart upload → returns CDN URL ──────────────────
    fb_caption = build_caption(item)
    fb_result  = publish_facebook(item, local_thumb, fb_caption, dry_run)

    fb_post_id    = fb_result.get("post_id")
    fb_post_url   = fb_result.get("post_url", "")
    cdn_image_url = fb_result.get("cdn_image_url")   # Facebook-hosted CDN URL

    # ── 2. Instagram: use the Facebook CDN URL (no external hosting needed) ─
    ig_caption = build_caption(item)
    ig_result  = publish_instagram(item, cdn_image_url or "", ig_caption, dry_run)

    ig_media_id = ig_result.get("media_id")
    ig_post_url = ig_result.get("post_url", "")

    # ── 3. WhatsApp: local thumbnail + formatted caption with live links ──
    if not skip_whatsapp:
        wa_caption = build_whatsapp_caption(item, fb_url=fb_post_url, ig_url=ig_post_url)
        wa_sent    = dispatch_whatsapp(item, local_thumb, wa_caption, dry_run)
    else:
        log.info("[WhatsApp] Skipped (--skip-whatsapp active, keeping previous dispatch status).")
        wa_sent    = True

    # --- Update schedule entry ---
    any_success = fb_result.get("success") or ig_result.get("success")

    if any_success:
        for sched_item in schedule:
            if sched_item["id"] == item_id:
                sched_item["status"]       = "published" if not dry_run else "dry-run"
                sched_item["published_at"] = datetime.now().isoformat()
                sched_item["fb_post_id"]   = fb_post_id
                sched_item["fb_post_url"]  = fb_post_url
                sched_item["ig_media_id"]  = ig_media_id
                sched_item["ig_post_url"]  = ig_post_url
                sched_item["wa_sent"]      = wa_sent
                break

    # --- Summary ---
    section(f"PUBLISH SUMMARY for {item_id}")
    fb_icon = "[OK]" if fb_result.get("success") else "[FAIL]"
    ig_icon = "[OK]" if ig_result.get("success") else "[FAIL]"
    wa_icon = "[OK]" if wa_sent else "[SKIP/FAIL]"

    print(f"  Facebook  : {fb_icon}  {fb_post_url or fb_result.get('error','')}")
    print(f"  Instagram : {ig_icon}  {ig_post_url or ig_result.get('error','')}")
    print(f"  WhatsApp  : {wa_icon}")
    if dry_run:
        print("\n  [DRY-RUN] No real posts were made. Schedule NOT permanently updated.")
    elif any_success:
        print(f"\n  Item '{item_id}' marked as published in master_schedule.json")

    return any_success


# ---------------------------------------------------------------------------- #
#  Main                                                                          #
# ---------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Samartha Vastu Auto Publisher")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Simulate publishing without real API calls")
    parser.add_argument("--publish-next", action="store_true",
                        help="Force-publish the next pending item regardless of schedule time")
    parser.add_argument("--item",         type=str, default=None,
                        help="Publish a specific item by ID (e.g. --item video_01)")
    parser.add_argument("--skip-whatsapp", action="store_true",
                        help="Skip WhatsApp dispatch (e.g. if already sent previously)")
    parser.add_argument("--whatsapp-only", action="store_true",
                        help="Only dispatch to WhatsApp (skip Facebook and Instagram)")
    args = parser.parse_args()

    DRY_RUN = args.dry_run

    section("Samartha Vastu Auto Publisher" + (" [DRY-RUN]" if DRY_RUN else " [LIVE]"))

    # Config check
    print("\nConfig:")
    print(f"  FB_PAGE_ID        : {FB_PAGE_ID or '!!! NOT SET'}")
    print(f"  IG_USER_ID        : {IG_USER_ID or '!!! NOT SET'}")
    print(f"  META_ACCESS_TOKEN : {'OK (' + META_ACCESS_TOKEN[:8] + '...)' if META_ACCESS_TOKEN else '!!! NOT SET'}")
    print(f"  YOUTUBE_URL       : {YOUTUBE_URL}")
    print(f"  CONTACT_PHONE     : {CONTACT_PHONE}")
    print(f"  CONTACT_EMAIL     : {CONTACT_EMAIL}")
    print(f"  WHATSAPP_TARGET   : {WHATSAPP_TARGET or '!!! NOT SET'}")

    if not DRY_RUN and not META_ACCESS_TOKEN:
        log.error("META_ACCESS_TOKEN is not set in .env. Aborting.")
        sys.exit(1)

    # Load schedule
    schedule = load_schedule()
    log.info("Loaded %d items from master_schedule.json", len(schedule))

    # Determine items to publish
    if args.item:
        # Specific item by ID
        targets = [i for i in schedule if i["id"] == args.item]
        if not targets:
            log.error("Item '%s' not found in master_schedule.json", args.item)
            sys.exit(1)
    elif args.publish_next:
        # Force next pending
        nxt = get_next_pending(schedule)
        targets = [nxt] if nxt else []
    else:
        # All items due now
        targets = get_due_items(schedule)

    if not targets:
        print("\n  No items are due for publishing right now.")
        print("  Use --publish-next to force the next pending item,")
        print("  or --dry-run --publish-next to test the pipeline.\n")
        return

    log.info("Items to publish: %d", len(targets))
    published_count = 0

    for item in targets:
        success = publish_item(item, schedule, DRY_RUN, skip_whatsapp=args.skip_whatsapp, whatsapp_only=args.whatsapp_only)
        if success:
            published_count += 1
        if not DRY_RUN:
            save_schedule(schedule)   # save after each item

    section("DONE")
    print(f"  Published : {published_count} / {len(targets)} items")
    if DRY_RUN:
        print("  Mode      : DRY-RUN (no real posts made, schedule not modified)")
    print()


if __name__ == "__main__":
    main()
