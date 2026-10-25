"""
youtube_sync.py
---------------
Samartha Vastu - Smart YouTube Priority Sync

1. Scans https://www.youtube.com/@samarthavastu999/videos and /shorts.
2. Tracks every video in vastu_content_queue/master_schedule.json by unique ID (yt_<VIDEO_ID>).
3. Filters out any video already marked "status": "published".
4. Sorts all remaining unposted videos by upload date from NEWEST to OLDEST (Present -> Past).
   - Any newly uploaded video is always picked #1 first.
   - Older unposted videos serve as fallbacks in order without ever repeating.
5. For the selected video, automatically generates:
   a) A 4:5 (1080x1350) branded poster in vastu_content_queue/thumbnails/yt_<VIDEO_ID>.jpg
      featuring the high-res YouTube thumbnail, gold "సమర్థ వాస్తు" header, Telugu title,
      scannable QR code to YouTube/WhatsApp, and footer "+91 8919395559 | samarthavastu999@gmail.com".
   b) A clean caption containing the Telugu title, description, exact clickable YouTube link,
      click-to-chat WhatsApp consultation link (https://wa.me/918919395559), and samarthavastu999@gmail.com (zero hashtags).

Usage:
    python youtube_sync.py               # Sync channel and prepare next video
    python youtube_sync.py --status      # Show sync and queue status
    python youtube_sync.py --poster-all  # Generate posters for all pending videos
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import qrcode
import requests
import yt_dlp
from PIL import Image, ImageDraw, ImageFont

# ── Paths & Constants ────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"

CHANNEL_VIDEOS_URL = "https://www.youtube.com/@samarthavastu999/videos"
CHANNEL_SHORTS_URL = "https://www.youtube.com/@samarthavastu999/shorts"

CONTACT_PHONE = "+91 8919395559"
CONTACT_EMAIL = "samarthavastu999@gmail.com"
WHATSAPP_LINK = "https://wa.me/918919395559"

# Poster Aesthetics (4:5 => 1080x1350)
CANVAS_W, CANVAS_H = 1080, 1350
BG_COLOR      = (28, 8, 8)          # Dark maroon
ACCENT_COLOR  = (212, 160, 23)      # Royal gold
ACCENT_LIGHT  = (255, 213, 79)      # Bright gold
BORDER_COLOR  = (180, 120, 10)      # Deep gold border
TEXT_WHITE    = (255, 245, 220)     # Warm ivory white

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("youtube_sync")


# ── Schedule Persistence ─────────────────────────────────────────────────────

def load_schedule() -> list:
    if not SCHEDULE_FILE.exists():
        return []
    with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("items", [])


def save_schedule(items: list):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    log.info("Saved %d items to %s", len(items), SCHEDULE_FILE)


# ── Font Helper ──────────────────────────────────────────────────────────────

def load_font(size: int, telugu: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load Telugu or Latin fonts gracefully on Windows."""
    candidates = []
    if telugu:
        if bold:
            candidates = [
                "C:/Windows/Fonts/gautamib.ttf",
                "C:/Windows/Fonts/NirmalaB.ttf",
                "C:/Windows/Fonts/Nirmala.ttc",
                "C:/Windows/Fonts/Vanib.ttf",
                "C:/Windows/Fonts/gautami.ttf",
            ]
        else:
            candidates = [
                "C:/Windows/Fonts/gautami.ttf",
                "C:/Windows/Fonts/Nirmala.ttc",
                "C:/Windows/Fonts/Vani.ttf",
                "C:/Windows/Fonts/gautamib.ttf",
            ]
    else:
        if bold:
            candidates = [
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/calibrib.ttf",
                "C:/Windows/Fonts/trebucbd.ttf",
            ]
        else:
            candidates = [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/calibri.ttf",
                "C:/Windows/Fonts/trebuc.ttf",
            ]

    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text_to_width(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Pixel-accurate text wrapping for Telugu / Unicode text."""
    words = text.split()
    lines = []
    current_line: list[str] = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    return lines


# ── YouTube Scanner ──────────────────────────────────────────────────────────

def fetch_flat_channel_entries(url: str, is_short: bool = False) -> list[dict]:
    """Quick flat extraction of channel tab (returns newest first)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    entries = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_entries = info.get("entries", [])
            for idx, entry in enumerate(raw_entries):
                vid = entry.get("id")
                if not vid or len(vid) != 11:
                    continue
                entries.append({
                    "video_id": vid,
                    "title": entry.get("title", ""),
                    "is_short": is_short,
                    "discovery_order": idx,  # 0 is newest on YouTube
                    "raw_thumbnail": (entry.get("thumbnails") or [{}])[-1].get("url")
                })
    except Exception as exc:
        log.error("Error scanning %s: %s", url, exc)
    return entries


def fetch_single_video_metadata(video_id: str) -> dict:
    """Fetch complete metadata (upload_date, description, high-res thumbnail)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            upload_date = info.get("upload_date") or ""
            desc = info.get("description") or ""
            title = info.get("title") or ""
            thumb = info.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            return {
                "video_id": video_id,
                "upload_date": upload_date,
                "description": desc,
                "title": title,
                "thumbnail_url": thumb,
            }
    except Exception as exc:
        log.warning("Could not fetch metadata for %s: %s", video_id, exc)
        return {
            "video_id": video_id,
            "upload_date": "",
            "description": "",
            "title": "",
            "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        }


# ── Clean Caption Builder ────────────────────────────────────────────────────

def clean_description(raw: str) -> str:
    """Strip hashtags and extraneous symbols."""
    # Strip #hashtags
    clean = re.sub(r"#\S+", "", raw)
    # Collapse 3+ newlines to 2
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def build_clean_caption(item: dict) -> str:
    """
    Telugu title, clean description, exact YouTube link,
    click-to-chat WhatsApp link, and contact info (zero hashtags).
    """
    title = (item.get("title") or "").strip()
    raw_desc = item.get("description") or ""
    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)

    desc = clean_description(raw_desc)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    parts = []
    if title:
        parts.append(title)
        parts.append("")
    if desc:
        parts.append(desc)
        parts.append("")

    parts.append(f"📺 పూర్తి వీడియో చూడండి: {yt_url}")
    parts.append(f"💬 వాట్సాప్ కన్సల్టేషన్: {WHATSAPP_LINK}")
    parts.append(f"📞 సంప్రదించండి: {CONTACT_PHONE}")
    parts.append(f"✉️ ఈమెయిల్: {CONTACT_EMAIL}")

    return "\n".join(parts)


def build_whatsapp_caption(item: dict, fb_url: str = "", ig_url: str = "", summary_suffix: str = "") -> str:
    """
    Build a WhatsApp-safe caption under 1000 characters with bold title,
    clean description snippet, and direct links.
    Optionally appends 3-line status summary for admin.
    """
    title = (item.get("title") or "").strip()
    raw_desc = item.get("description") or ""
    video_id = item.get("video_id", "")
    is_short = item.get("is_short", False)

    desc = clean_description(raw_desc)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    footer_lines = [
        f"📺 YouTube: {yt_url}",
        f"💬 WhatsApp: {WHATSAPP_LINK}",
        f"📞 Phone: {CONTACT_PHONE}",
        f"✉️ Email: {CONTACT_EMAIL}",
    ]
    if fb_url:
        footer_lines.append(f"🌐 Facebook: {fb_url}")
    if ig_url:
        footer_lines.append(f"📸 Instagram: {ig_url}")
    if summary_suffix:
        footer_lines.append("")
        footer_lines.append(summary_suffix)

    footer = "\n".join(footer_lines)

    # Budget chars for description to avoid WhatsApp 1024-character modal overflow
    max_desc_len = max(100, 950 - len(title) - len(footer) - 20)
    if len(desc) > max_desc_len:
        desc = desc[:max_desc_len].rsplit(" ", 1)[0] + "..."

    parts = []
    if title:
        parts.append(f"*{title}*")
        parts.append("")
    if desc:
        parts.append(desc)
        parts.append("")
    parts.append(footer)
    return "\n".join(parts)


# ── 4:5 Branded Poster Generator ─────────────────────────────────────────────

def download_youtube_thumbnail(video_id: str, fallback_url: str = "") -> Image.Image:
    """Download best available YouTube thumbnail."""
    candidates = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
    ]
    if fallback_url:
        candidates.append(fallback_url)

    for url in candidates:
        try:
            resp = requests.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.content) > 4000:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                return img
        except Exception:
            pass

    # Placeholder if all fail
    ph = Image.new("RGB", (1280, 720), (35, 10, 10))
    d = ImageDraw.Draw(ph)
    d.text((500, 340), "Samartha Vastu", fill=ACCENT_LIGHT)
    return ph


def generate_qr_code(url: str, size: int = 128) -> Image.Image:
    """Generate clean QR code pointing to URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.NEAREST)


def generate_branded_poster(item: dict, output_path: str | Path) -> str:
    """
    Creates a 4:5 (1080x1350) branded poster:
    - Gold "సమర్థ వాస్తు" header
    - High-res YouTube thumbnail fitted in frame
    - Telugu video title in clear ivory text
    - Scannable QR code to YouTube video
    - Footer with phone, email, and consultation link
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_id = item.get("video_id", "")
    title = (item.get("title") or "సమర్థ వాస్తు").strip()
    is_short = item.get("is_short", False)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    # 1. Canvas with dark maroon radial gradient
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    for y in range(CANVAS_H):
        t = y / CANVAS_H
        r = int(BG_COLOR[0] + (38 - BG_COLOR[0]) * t * 0.45)
        g = int(BG_COLOR[1] + (8 - BG_COLOR[1]) * t * 0.3)
        b = int(BG_COLOR[2] + (8 - BG_COLOR[2]) * t * 0.3)
        draw.line([(0, y), (CANVAS_W, y)], fill=(r, g, b))

    # Top gold accent bar
    draw.rectangle([0, 0, CANVAS_W, 6], fill=ACCENT_COLOR)

    # 2. Header: "సమర్థ వాస్తు"
    font_tel_header = load_font(48, telugu=True, bold=True)
    font_eng_sub    = load_font(20, telugu=False, bold=False)

    header_text = "సమర్థ వాస్తు"
    bbox_h = draw.textbbox((0, 0), header_text, font=font_tel_header)
    hw = bbox_h[2] - bbox_h[0]
    draw.text(((CANVAS_W - hw) // 2, 22), header_text, font=font_tel_header, fill=ACCENT_LIGHT)

    sub_text = "SAMARTHA VASTU  |  వాస్తు శాస్త్రం"
    bbox_s = draw.textbbox((0, 0), sub_text, font=font_eng_sub)
    sw = bbox_s[2] - bbox_s[0]
    draw.text(((CANVAS_W - sw) // 2, 85), sub_text, font=font_eng_sub, fill=(215, 175, 75))

    # Gold separator line with diamond
    def draw_sep(y_pos: int):
        draw.line([(50, y_pos), (CANVAS_W - 50, y_pos)], fill=ACCENT_COLOR, width=1)
        cx = CANVAS_W // 2
        draw.polygon([(cx, y_pos - 5), (cx + 5, y_pos), (cx, y_pos + 5), (cx - 5, y_pos)], fill=ACCENT_COLOR)

    draw_sep(128)

    # 3. Thumbnail Zone (y = 145 to 730)
    thumb_zone_w, thumb_zone_h = 1000, 570
    thumb_img = download_youtube_thumbnail(video_id, item.get("thumbnail_url", ""))

    scale = min(thumb_zone_w / thumb_img.size[0], thumb_zone_h / thumb_img.size[1])
    nw, nh = int(thumb_img.size[0] * scale), int(thumb_img.size[1] * scale)
    thumb_resized = thumb_img.resize((nw, nh), Image.LANCZOS)

    tx = (CANVAS_W - nw) // 2
    ty = 145 + (thumb_zone_h - nh) // 2

    # Draw gold border frame
    draw.rectangle([tx - 4, ty - 4, tx + nw + 3, ty + nh + 3], outline=ACCENT_COLOR, width=2)
    canvas.paste(thumb_resized, (tx, ty))

    # 4. Title Zone (y = 740 to 990)
    title_box_y = 740
    title_box_h = 245
    draw.rectangle([40, title_box_y, CANVAS_W - 40, title_box_y + title_box_h], fill=(16, 4, 4), outline=BORDER_COLOR, width=1)

    # Wrap title
    font_title = load_font(32, telugu=True, bold=True)
    wrapped_lines = wrap_text_to_width(draw, title, font_title, max_width=940)[:3]

    line_spacing = 56
    start_ty = title_box_y + (title_box_h - (len(wrapped_lines) * line_spacing)) // 2 + 6
    for idx, line in enumerate(wrapped_lines):
        lb = draw.textbbox((0, 0), line, font=font_title)
        lw = lb[2] - lb[0]
        draw.text(((CANVAS_W - lw) // 2, start_ty + idx * line_spacing), line, font=font_title, fill=TEXT_WHITE)

    draw_sep(1015)

    # 5. Footer & QR Code Zone (y = 1030 to 1330)
    foot_y = 1035
    qr_img = generate_qr_code(yt_url, size=136)
    qr_x = CANVAS_W - 60 - 136
    canvas.paste(qr_img, (qr_x, foot_y + 8))
    draw.rectangle([qr_x - 3, foot_y + 5, qr_x + 138, foot_y + 146], outline=ACCENT_COLOR, width=1)

    font_qr_label = load_font(15, telugu=True, bold=False)
    qr_lbl = "వీడియో చూడండి / Scan"
    qlb = draw.textbbox((0, 0), qr_lbl, font=font_qr_label)
    draw.text((qr_x + (136 - (qlb[2] - qlb[0])) // 2, foot_y + 152), qr_lbl, font=font_qr_label, fill=(215, 175, 75))

    font_foot_head = load_font(24, telugu=True, bold=True)
    font_contact   = load_font(24, telugu=False, bold=True)
    font_wa_link   = load_font(22, telugu=False, bold=False)

    draw.text((60, foot_y + 8), "వాస్తు & జ్యోతిష్య సలహాల కోసం సంప్రదించండి:", font=font_foot_head, fill=ACCENT_LIGHT)
    draw.text((60, foot_y + 54), f"📞 {CONTACT_PHONE}  |  ✉️ {CONTACT_EMAIL}", font=font_contact, fill=TEXT_WHITE)
    draw.text((60, foot_y + 98), f"💬 WhatsApp: {WHATSAPP_LINK}", font=font_wa_link, fill=ACCENT_COLOR)
    draw.text((60, foot_y + 138), "🌐 సమర్థ వాస్తు — శాస్త్రీయ పరిష్కారాలు, సంపద, ఆరోగ్యం", font=load_font(20, telugu=True), fill=(200, 160, 60))

    # Outer decorative border
    draw.rectangle([10, 10, CANVAS_W - 10, CANVAS_H - 10], outline=BORDER_COLOR, width=2)
    draw.rectangle([0, CANVAS_H - 6, CANVAS_W, CANVAS_H], fill=ACCENT_COLOR)

    # Save high-res JPEG
    canvas.save(output_path, "JPEG", quality=95, optimize=True)
    log.info("Branded poster generated: %s (1080x1350)", output_path)
    return str(output_path)


# ── Smart YouTube Sync Orchestrator ──────────────────────────────────────────

def sync_youtube(force_poster: bool = True) -> dict:
    """
    Executes the full YouTube Priority Sync:
    1. Scans channel /videos and /shorts.
    2. Merges with master_schedule.json.
    3. Keeps existing published items untouched.
    4. Sorts pending items from NEWEST to OLDEST (upload_date descending).
    5. Generates 4:5 poster & clean caption for the #1 top pending item.
    6. Saves master_schedule.json.
    """
    log.info("=" * 62)
    log.info("Starting Smart YouTube Priority Sync")
    log.info("=" * 62)

    # Load existing schedule
    schedule = load_schedule()
    existing_by_id = {item["id"]: item for item in schedule}
    log.info("Existing schedule items: %d", len(schedule))

    # 1. Scan channel
    log.info("Scanning YouTube: %s", CHANNEL_VIDEOS_URL)
    videos = fetch_flat_channel_entries(CHANNEL_VIDEOS_URL, is_short=False)
    log.info("Found %d videos on channel.", len(videos))

    log.info("Scanning YouTube: %s", CHANNEL_SHORTS_URL)
    shorts = fetch_flat_channel_entries(CHANNEL_SHORTS_URL, is_short=True)
    log.info("Found %d shorts on channel.", len(shorts))

    all_channel_entries = videos + shorts
    discovered_vids = {e["video_id"]: e for e in all_channel_entries}

    # 2. Identify items needing upload_date & metadata
    # To minimize network overhead, fetch metadata for items not yet in schedule
    new_vids = [e["video_id"] for e in all_channel_entries if f"yt_{e['video_id']}" not in existing_by_id]
    log.info("New YouTube videos detected: %d", len(new_vids))

    new_metadata: dict[str, dict] = {}
    if new_vids:
        log.info("Fetching upload dates & metadata for %d new videos...", len(new_vids))
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_vid = {executor.submit(fetch_single_video_metadata, vid): vid for vid in new_vids}
            for future in as_completed(future_to_vid):
                res = future.result()
                new_metadata[res["video_id"]] = res

    # 3. Build merged items list
    merged: list[dict] = []
    # Retain non-YouTube legacy items (like video_01)
    for item in schedule:
        if not item["id"].startswith("yt_"):
            merged.append(item)

    # Process all channel videos
    for entry in all_channel_entries:
        vid = entry["video_id"]
        sched_id = f"yt_{vid}"

        if sched_id in existing_by_id:
            # Preserve existing entry
            curr = existing_by_id[sched_id]
            # Fill missing title/is_short if absent
            if not curr.get("title") and entry.get("title"):
                curr["title"] = entry["title"]
            curr["is_short"] = entry["is_short"]
            merged.append(curr)
        else:
            # Create new pending item
            meta = new_metadata.get(vid, {})
            title = meta.get("title") or entry.get("title") or "సమర్థ వాస్తు"
            upload_date = meta.get("upload_date") or ""
            desc = meta.get("description") or ""

            item_dict = {
                "id": sched_id,
                "video_id": vid,
                "title": title,
                "description": desc,
                "caption": "",  # will be populated below
                "upload_date": upload_date,
                "url": f"https://www.youtube.com/shorts/{vid}" if entry["is_short"] else f"https://www.youtube.com/watch?v={vid}",
                "is_short": entry["is_short"],
                "discovery_order": entry["discovery_order"],
                "thumbnail_file": f"vastu_content_queue\\thumbnails\\{sched_id}.jpg",
                "has_thumbnail": False,
                "has_video": False,
                "status": "pending",
                "scheduled_date": None,
                "scheduled_time": "08:00:00",
                "scheduled_at": None,
                "published_at": None,
                "fb_post_id": None,
                "fb_post_url": None,
                "ig_media_id": None,
                "ig_post_url": None,
                "wa_sent": False,
            }
            item_dict["caption"] = build_clean_caption(item_dict)
            merged.append(item_dict)

    # 4. Sort:
    published_items = [i for i in merged if i.get("status") == "published"]
    archived_items  = [i for i in merged if i.get("status") in ("published", "skipped")]
    pending_items   = [i for i in merged if i.get("status") not in ("published", "skipped")]

    # Sort pending items: NEWEST upload date first (e.g. 20261024 > 20261022)
    # If upload_date is identical or empty, sort by discovery_order (0 is newest on YouTube)
    def pending_sort_key(item: dict):
        ud = item.get("upload_date") or ""
        order = item.get("discovery_order", 9999)
        return (ud, -order)

    # If an item is already marked 'preview_approved', preserve it at the head.
    # Enforce Invariant: Strictly only ONE item can ever be in 'preview_approved' status.
    approved_items = [i for i in pending_items if i.get("status") == "preview_approved"]
    pure_pending   = [i for i in pending_items if i.get("status") != "preview_approved"]
    if len(approved_items) > 1:
        log.warning(
            "Found %d preview_approved items; keeping only the first and resetting others to pending.",
            len(approved_items),
        )
        for extra in approved_items[1:]:
            extra["status"] = "pending"
        pure_pending = approved_items[1:] + pure_pending
        approved_items = approved_items[:1]

    pure_pending.sort(key=pending_sort_key, reverse=True)
    pending_items = approved_items + pure_pending

    # Assign sequential schedule slots (08:00 AM daily starting today)
    today = date.today()
    for idx, item in enumerate(pending_items):
        slot_date = (today + timedelta(days=idx)).strftime("%Y-%m-%d")
        slot_time = "08:00:00"
        item["scheduled_date"] = slot_date
        item["scheduled_time"] = slot_time
        item["scheduled_at"]   = f"{slot_date}T{slot_time}"

    # Final combined schedule: archived history + sorted pending queue
    final_schedule = archived_items + pending_items

    # 5. Process top pending item: ensure complete details, high-res poster & caption
    top_item = pending_items[0] if pending_items else None
    if top_item and force_poster:
        vid = top_item["video_id"]
        poster_path = BASE_DIR / "vastu_content_queue" / "thumbnails" / f"{top_item['id']}.jpg"

        # If top item lacks description or upload_date, fetch now
        if not top_item.get("description") or not top_item.get("upload_date"):
            log.info("Fetching complete details for #1 candidate video: %s", vid)
            full_meta = fetch_single_video_metadata(vid)
            if full_meta.get("description"):
                top_item["description"] = full_meta["description"]
            if full_meta.get("upload_date"):
                top_item["upload_date"] = full_meta["upload_date"]
            if full_meta.get("title"):
                top_item["title"] = full_meta["title"]
            top_item["caption"] = build_clean_caption(top_item)

        # Generate 4:5 branded poster using Headless Chrome (unbroken fonts & emojis)
        if not poster_path.exists() or not top_item.get("has_thumbnail"):
            log.info("Generating Headless Chrome branded poster for top item: %s", top_item["id"])
            try:
                from html_poster_generator import render_html_to_poster
                render_html_to_poster(top_item, poster_path)
            except Exception as exc:
                log.warning("Headless Chrome poster note: %s — falling back to PIL", exc)
                generate_branded_poster(top_item, poster_path)
            top_item["has_thumbnail"] = True
            top_item["thumbnail_file"] = f"vastu_content_queue\\thumbnails\\{top_item['id']}.jpg"

    # Save to master_schedule.json
    save_schedule(final_schedule)

    unposted_count = len(pending_items)
    log.info("=" * 62)
    log.info("YouTube Sync Complete!")
    log.info("  Total items    : %d", len(final_schedule))
    log.info("  Published      : %d", len(published_items))
    log.info("  Pending Queue  : %d", unposted_count)
    if top_item:
        log.info("  #1 Next Video  : [%s] %s (Upload: %s)", top_item["id"], top_item["title"][:50], top_item.get("upload_date"))
    log.info("=" * 62)

    return {
        "total": len(final_schedule),
        "published": len(published_items),
        "pending": unposted_count,
        "next_item": top_item,
    }


# ── CLI Interface ────────────────────────────────────────────────────────────

def print_queue_status():
    schedule = load_schedule()
    published = [i for i in schedule if i.get("status") == "published"]
    pending   = [i for i in schedule if i.get("status") != "published"]

    print("\n" + "=" * 80)
    print("  SAMARTHA VASTU - CONTENT QUEUE STATUS")
    print("=" * 80)
    print(f"Total: {len(schedule)} | Published: {len(published)} | Pending: {len(pending)}\n")

    print(f"{'#':<4} {'ID':<16} {'Upload':<10} {'Sched Date':<12} {'Status':<10} {'Title':<36}")
    print("-" * 90)

    for idx, item in enumerate(published[:5]):
        print(f"P{idx+1:<3} {item['id']:<16} {'-':<10} {item.get('published_at','[:10]'):<12} {'[DONE]':<10} {(item.get('title') or '')[:34]}")

    if len(published) > 5:
        print(f"    ... and {len(published)-5} more published items")

    print("-" * 90)
    for idx, item in enumerate(pending[:15]):
        thumb_icon = "🎨" if item.get("has_thumbnail") else "⚪"
        print(f"{idx+1:<4} {item['id']:<16} {item.get('upload_date',''):<10} {item.get('scheduled_date',''):<12} {thumb_icon} pending  {(item.get('title') or '')[:34]}")

    if len(pending) > 15:
        print(f"    ... and {len(pending)-15} more unposted items")
    print("=" * 80 + "\n")


def generate_all_pending_posters():
    schedule = load_schedule()
    pending = [i for i in schedule if i.get("status") != "published"]
    print(f"Generating posters for {len(pending)} pending items...")
    for idx, item in enumerate(pending):
        p_path = BASE_DIR / "vastu_content_queue" / "thumbnails" / f"{item['id']}.jpg"
        if not p_path.exists():
            print(f"[{idx+1}/{len(pending)}] Generating poster for {item['id']}...")
            generate_branded_poster(item, p_path)
            item["has_thumbnail"] = True
            item["thumbnail_file"] = f"vastu_content_queue\\thumbnails\\{item['id']}.jpg"
    save_schedule(schedule)
    print("All pending posters generated!")


def main():
    parser = argparse.ArgumentParser(description="Samartha Vastu Smart YouTube Sync")
    parser.add_argument("--status", action="store_true", help="Print queue status table")
    parser.add_argument("--poster-all", action="store_true", help="Generate posters for all pending videos")
    args = parser.parse_args()

    if args.status:
        print_queue_status()
        return

    if getattr(args, "poster_all", False):
        generate_all_pending_posters()
        return

    sync_youtube(force_poster=True)
    print_queue_status()


if __name__ == "__main__":
    main()
