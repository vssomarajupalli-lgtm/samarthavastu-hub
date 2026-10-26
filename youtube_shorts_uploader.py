"""
youtube_shorts_uploader.py
--------------------------
Samartha Vastu - Automated 9:16 YouTube Shorts Generator & Uploader

Converts the daily 4:5 static poster (1080x1350) into a vertical 9:16 (1080x1920)
15-second .mp4 Short on a royal maroon & gold background, and automatically uploads
it to the @samarthavastu999 YouTube channel via Playwright CDP over the active Chrome profile.
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
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
LOGS_DIR        = BASE_DIR / "logs"
TEMP_MP4        = LOGS_DIR / "temp_short.mp4"
TEMP_FRAME      = LOGS_DIR / "temp_short_frame.jpg"

CDP_URL         = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")
STUDIO_URL      = "https://studio.youtube.com/channel/UC5u7BltNJ37eHudWoMHhFzQ"
CONTACT_PHONE   = "+91 8919395559"
CONTACT_EMAIL   = "samarthavastu999@gmail.com"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("youtube_shorts_uploader")


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


def get_telugu_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/NirmalaB.ttf" if bold else "C:/Windows/Fonts/Nirmala.ttc",
        "C:/Windows/Fonts/gautamib.ttf" if bold else "C:/Windows/Fonts/gautami.ttf",
        "C:/Windows/Fonts/Vani.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------- #
#  Step A: Static Poster to 9:16 Vertical .mp4 Short Conversion                #
# ---------------------------------------------------------------------------- #

def create_shorts_video(poster_path: str | Path, output_mp4: str | Path = TEMP_MP4) -> Path:
    """
    Takes 1080x1350 static poster and places it centered on a 1080x1920
    dark royal maroon/gold canvas, then generates a lightweight 15s .mp4 video using ffmpeg.
    """
    poster_path = Path(poster_path)
    if not poster_path.exists():
        raise FileNotFoundError(f"Poster image not found: {poster_path}")

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    output_mp4 = Path(output_mp4)

    poster = Image.open(poster_path).convert("RGB")
    cw, ch = 1080, 1920
    canvas = Image.new("RGB", (cw, ch), (28, 8, 8))
    draw = ImageDraw.Draw(canvas)

    # Vertical gradient maroon background
    for y in range(ch):
        t = y / ch
        r = int(28 + (45 - 28) * t * 0.4)
        g = int(8 + (12 - 8) * t * 0.4)
        b = int(8 + (12 - 8) * t * 0.4)
        draw.line([(0, y), (cw, y)], fill=(r, g, b))

    # Center poster at y = (1920 - 1350) // 2 = 285
    poster_y = 285
    canvas.paste(poster, (0, poster_y))

    # Gold framing borders
    accent_gold = (212, 160, 23)
    light_gold = (255, 213, 79)
    ivory_white = (255, 245, 220)

    draw.rectangle([0, 0, cw, 8], fill=accent_gold)
    draw.rectangle([0, poster_y - 2, cw, poster_y], fill=accent_gold)
    draw.rectangle([0, poster_y + 1350, cw, poster_y + 1352], fill=accent_gold)
    draw.rectangle([0, ch - 8, cw, ch], fill=accent_gold)

    # Top banner typography
    font_header = get_telugu_font(46, bold=True)
    font_sub    = get_telugu_font(22, bold=True)

    h_txt = "సమర్థ వాస్తు"
    hb = draw.textbbox((0, 0), h_txt, font=font_header)
    draw.text(((cw - (hb[2] - hb[0])) // 2, 75), h_txt, font=font_header, fill=light_gold)

    s_txt = "SAMARTHA VASTU #SHORTS"
    sb = draw.textbbox((0, 0), s_txt, font=font_sub)
    draw.text(((cw - (sb[2] - sb[0])) // 2, 155), s_txt, font=font_sub, fill=(215, 175, 75))

    # Bottom banner typography
    b_txt = f"🎥 పూర్తి వీడియో కోసం లింక్ చూడండి  |  📞 {CONTACT_PHONE}"
    bb = draw.textbbox((0, 0), b_txt, font=font_sub)
    draw.text(((cw - (bb[2] - bb[0])) // 2, 1740), b_txt, font=font_sub, fill=ivory_white)

    # Save temp frame
    canvas.save(TEMP_FRAME, quality=95)
    log.info("[Shorts Generator] Saved 1080x1920 canvas frame (%d bytes)", TEMP_FRAME.stat().st_size)

    # Run ffmpeg to generate lightweight 15-second 1080x1920 MP4 video
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(TEMP_FRAME),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264",
        "-t", "15",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        str(output_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log.error("[Shorts Generator] ffmpeg error: %s", res.stderr)
        raise RuntimeError(f"ffmpeg failed: {res.stderr}")

    # Remove temporary frame
    try:
        TEMP_FRAME.unlink(missing_ok=True)
    except Exception:
        pass

    log.info("[Shorts Generator] Video created successfully: %s (%d bytes)", output_mp4, output_mp4.stat().st_size)
    return output_mp4


# ---------------------------------------------------------------------------- #
#  Title & Description Builders for Shorts                                     #
# ---------------------------------------------------------------------------- #

def build_shorts_title(raw_title: str) -> str:
    """
    Builds YouTube Shorts title strictly <= 100 chars with #Shorts #SamarthaVastu tags.
    """
    clean_title = re.sub(r"#\S+", "", raw_title).strip()
    tag_suffix = " #Shorts #SamarthaVastu"
    max_title_len = 100 - len(tag_suffix)

    if len(clean_title) > max_title_len:
        clean_title = clean_title[:max_title_len].rsplit(" ", 1)[0]

    return f"{clean_title}{tag_suffix}"


def build_shorts_description(item: dict) -> str:
    """
    Builds rich description for YouTube Shorts with direct link to full video.
    """
    title = (item.get("title") or "").strip()
    video_id = item.get("video_id", "")
    raw_desc = item.get("description") or item.get("caption") or ""
    clean_desc = re.sub(r"#\S+", "", raw_desc).strip()
    clean_desc = re.sub(r"\n{3,}", "\n\n", clean_desc)

    yt_full_url = f"https://www.youtube.com/watch?v={video_id}"

    parts = [
        title,
        "",
        clean_desc[:1200] if len(clean_desc) > 1200 else clean_desc,
        "",
        "---",
        f"🎥 పూర్తి వీడియో ఇక్కడ చూడండి:\n{yt_full_url}",
        "",
        f"💬 WhatsApp Consultation: https://wa.me/918919395559",
        f"📞 Phone / సంప్రదించండి: {CONTACT_PHONE}",
        f"✉️ Email: {CONTACT_EMAIL}",
        "",
        "#Shorts #SamarthaVastu #VastuShastra #TeluguVastu #VastuTips",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------- #
#  Step B: Playwright CDP Automated Upload to YouTube Shorts                   #
# ---------------------------------------------------------------------------- #

def upload_short_to_youtube(item: dict, dry_run: bool = False) -> dict:
    """
    Uploads logs/temp_short.mp4 as a YouTube Short on @samarthavastu999 channel
    using Playwright connected to Chrome CDP on port 9222.
    """
    item_id = item.get("id", "")
    existing_url = item.get("yt_short_url")
    if existing_url:
        log.info("[YouTube Shorts] Already uploaded for %s: %s (Skipping)", item_id, existing_url)
        return {"success": True, "short_url": existing_url, "already_uploaded": True}

    poster_file = item.get("thumbnail_file") or f"vastu_content_queue/thumbnails/{item_id}.jpg"
    poster_path = Path(poster_file)
    if not poster_path.is_absolute():
        poster_path = BASE_DIR / poster_path

    if not poster_path.exists():
        log.error("[YouTube Shorts] Thumbnail not found: %s", poster_path)
        return {"success": False, "short_url": None, "error": f"Poster missing: {poster_path}"}

    # Generate 9:16 vertical 15s MP4
    mp4_path = create_shorts_video(poster_path)

    short_title = build_shorts_title(item.get("title", ""))
    short_desc = build_shorts_description(item)

    log.info("[YouTube Shorts] Title       : %s (%d chars)", short_title, len(short_title))
    log.info("[YouTube Shorts] Target Video: %s", item_id)

    if dry_run:
        mock_url = f"https://youtube.com/shorts/dry-run-{item.get('video_id')}"
        log.info("[YouTube Shorts] DRY-RUN — would publish Short: %s", mock_url)
        return {"success": True, "short_url": mock_url}

    from playwright.sync_api import sync_playwright

    short_url = None
    try:
        with sync_playwright() as p:
            log.info("[YouTube Shorts] Connecting to Chrome CDP at %s...", CDP_URL)
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
            context = browser.contexts[0]

            log.info("[YouTube Shorts] Opening YouTube Studio: %s", STUDIO_URL)
            page = context.new_page()
            page.goto(STUDIO_URL, timeout=25000)
            page.wait_for_load_state("networkidle")

            # 1. Click CREATE button
            create_btn = page.locator('button[aria-label="Create"], ytcp-button:has-text("Create")').first
            create_btn.wait_for(state="visible", timeout=15000)
            create_btn.click()
            time.sleep(1.5)

            # 2. Click "Upload videos"
            upload_item = page.locator('tp-yt-paper-item:has-text("Upload videos"), ytcp-text-menu-item:has-text("Upload videos")').first
            upload_item.wait_for(state="visible", timeout=10000)
            upload_item.click()
            time.sleep(2)

            # 3. Supply MP4 to input[type="file"]
            file_input = page.locator('input[type="file"]')
            file_input.wait_for(state="attached", timeout=10000)
            log.info("[YouTube Shorts] Uploading file %s...", mp4_path)
            file_input.set_input_files(str(mp4_path.resolve()))

            # 4. Wait for metadata form
            title_box = page.locator('#title-textarea #textbox').first
            title_box.wait_for(state="visible", timeout=30000)
            time.sleep(2)

            # Set title
            title_box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            time.sleep(0.5)
            title_box.fill(short_title)
            log.info("[YouTube Shorts] Title filled successfully.")

            # Set description
            desc_box = page.locator('#description-textarea #textbox').first
            if desc_box.is_visible():
                desc_box.click()
                desc_box.fill(short_desc)
                log.info("[YouTube Shorts] Description filled successfully.")

            # Select "No, it's not made for kids"
            kids_radio = page.locator('[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').first
            kids_radio.wait_for(state="visible", timeout=10000)
            kids_radio.click()
            log.info("[YouTube Shorts] Selected 'Not made for kids'.")
            time.sleep(1)

            # Wait a few seconds to extract short link
            time.sleep(4)
            for link in page.locator('a').all():
                href = link.get_attribute("href") or ""
                if "youtube.com/shorts/" in href or "youtu.be/" in href:
                    short_url = href.strip()
                    break

            # 5. Navigate through Next steps (Details -> Video elements -> Checks -> Visibility)
            next_btn = page.locator('#next-button').first
            for step_idx in range(1, 4):
                next_btn.wait_for(state="visible", timeout=10000)
                next_btn.click()
                log.info("[YouTube Shorts] Clicked Next (%d/3)", step_idx)
                time.sleep(2)

            # 6. Select "Public" visibility
            public_radio = page.locator('[name="PUBLIC"]').first
            public_radio.wait_for(state="visible", timeout=10000)
            public_radio.click()
            log.info("[YouTube Shorts] Selected 'Public' visibility.")
            time.sleep(1)

            # If short_url not captured yet, check again on Visibility screen
            if not short_url:
                for link in page.locator('a').all():
                    href = link.get_attribute("href") or ""
                    if "youtube.com/shorts/" in href or "youtu.be/" in href:
                        short_url = href.strip()
                        break

            # 7. Click Publish ("#done-button")
            done_btn = page.locator('#done-button').first
            done_btn.wait_for(state="visible", timeout=10000)
            done_btn.click()
            log.info("[YouTube Shorts] Clicked Publish / Done!")
            time.sleep(6)

            # Look for post-publish dialog short link if still not found
            if not short_url:
                for link in page.locator('a').all():
                    href = link.get_attribute("href") or ""
                    if "youtube.com/shorts/" in href or "youtu.be/" in href:
                        short_url = href.strip()
                        break

            # Fallback format if youtu.be was returned
            if short_url and "youtu.be/" in short_url:
                vid_part = short_url.split("youtu.be/")[-1].split("?")[0]
                short_url = f"https://www.youtube.com/shorts/{vid_part}"

            page.close()

    except Exception as exc:
        log.error("[YouTube Shorts] Upload failed: %s", exc)
        return {"success": False, "short_url": None, "error": str(exc)}

    if not short_url:
        short_url = f"https://www.youtube.com/@samarthavastu999/shorts"

    log.info("[YouTube Shorts] Upload complete! Short URL: %s", short_url)
    return {"success": True, "short_url": short_url}


# ---------------------------------------------------------------------------- #
#  CLI Runner                                                                  #
# ---------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Samartha Vastu YouTube Shorts Generator & Uploader")
    parser.add_argument("--video-id", type=str, help="Queue item ID or video ID to process")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without real upload")
    args = parser.parse_args()

    schedule = load_schedule()
    target_item = None

    if args.video_id:
        target_id = args.video_id if args.video_id.startswith("yt_") else f"yt_{args.video_id}"
        for item in schedule:
            if item.get("id") == target_id or item.get("video_id") == args.video_id:
                target_item = item
                break
    else:
        for item in schedule:
            if item.get("status") == "preview_approved":
                target_item = item
                break
        if not target_item:
            today_str = time.strftime("%Y-%m-%d")
            for item in schedule:
                if item.get("status") == "published" and (item.get("published_at") or "").startswith(today_str):
                    target_item = item
                    break

    if not target_item:
        print("No target video found in queue.")
        sys.exit(1)

    print(f"Target Video: {target_item['id']} - {target_item.get('title')[:45]}")
    res = upload_short_to_youtube(target_item, dry_run=args.dry_run)
    print("Result:", res)

    if res.get("success") and not args.dry_run:
        target_item["yt_short_url"] = res.get("short_url")
        save_schedule(schedule)
        print(f"Recorded yt_short_url in master_schedule.json: {res.get('short_url')}")


if __name__ == "__main__":
    main()
