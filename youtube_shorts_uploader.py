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
import socket
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
LOGS_DIR        = BASE_DIR / "logs"
TEMP_MP4        = LOGS_DIR / "temp_short.mp4"
TEMP_FRAME      = LOGS_DIR / "temp_short_frame.jpg"
OUT_DIR         = LOGS_DIR / "screenshots"

CDP_URL             = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")
TARGET_CHANNEL_ID   = "UCDtcb0drjmLgG3ARTh4e7jw"
TARGET_CHANNEL_NAME = "SAMARTHA VASTU"
STUDIO_URL          = f"https://studio.youtube.com/channel/{TARGET_CHANNEL_ID}"
DISALLOWED_CHANNEL  = "UC5u7BltNJ37eHudWoMHhFzQ"
CONTACT_PHONE       = "+91 8919395559"
CONTACT_EMAIL       = "samarthavastu999@gmail.com"

# --- Unified isolated Chrome automation profile ---
AUTOMATION_CHROME_PROFILE = r"E:\samarthavastu-hub\chrome_whatsapp_profile"
CHROME_CDP_PORT = 9222
CHROME_BIN_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome_bin() -> str:
    for c in CHROME_BIN_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return "chrome.exe"


def port_is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Return True if a TCP listener is accepting connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_chrome_cdp() -> bool:
    """
    Ensure Chrome is running with --remote-debugging-port=9222 on the isolated
    automation profile so Playwright CDP can connect. Never touches the user's
    personal Chrome profiles. Self-heals: terminates stale automation-profile
    Chrome processes, removes stale SingletonLock, then relaunches.
    """
    if port_is_listening(CHROME_CDP_PORT):
        log.info("[YouTube Shorts] Chrome CDP already listening on port %d.", CHROME_CDP_PORT)
        return True

    chrome_bin = find_chrome_bin()
    os.makedirs(AUTOMATION_CHROME_PROFILE, exist_ok=True)

    # Terminate ONLY chrome.exe processes bound to the automation profile.
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            cmdline_str = " ".join(cmdline)
            if proc.info.get('name', '').lower() == 'chrome.exe' and AUTOMATION_CHROME_PROFILE in cmdline_str:
                log.info("[YouTube Shorts] Terminating stale automation Chrome (PID %d) holding profile lock.", proc.info['pid'])
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Wait for processes to exit and release the profile lock.
    time.sleep(2)

    # Remove stale SingletonLock if present so Chrome can reuse the profile.
    singleton_lock = os.path.join(AUTOMATION_CHROME_PROFILE, "SingletonLock")
    if os.path.exists(singleton_lock):
        try:
            os.remove(singleton_lock)
            log.info("[YouTube Shorts] Removed stale SingletonLock in automation profile.")
        except OSError:
            pass

    log.info("[YouTube Shorts] Launching isolated Chrome for CDP on port %d...", CHROME_CDP_PORT)
    subprocess.Popen(
        [
            chrome_bin,
            f"--user-data-dir={AUTOMATION_CHROME_PROFILE}",
            f"--remote-debugging-port={CHROME_CDP_PORT}",
            "--start-minimized",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        shell=True,
    )

    # Wait up to 10 seconds for port 9222 to accept connections
    for _ in range(20):
        time.sleep(0.5)
        if port_is_listening(CHROME_CDP_PORT):
            log.info("[YouTube Shorts] Chrome CDP is now listening on port %d.", CHROME_CDP_PORT)
            return True

    log.error("[YouTube Shorts] Chrome CDP port %d did not accept connections within 10s.", CHROME_CDP_PORT)
    return False

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


# ---------------------------------------------------------------------------- #
#  Step A: Static Poster to 9:16 Vertical .mp4 Short Conversion                #
# ---------------------------------------------------------------------------- #

def _fetch_thumb_b64(video_id: str) -> str:
    """Fetch best available YouTube thumbnail as base64 data URL."""
    import base64, io
    import requests
    from PIL import Image as PILImage
    urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                img = PILImage.open(io.BytesIO(resp.content))
                if img.size == (120, 90) or img.size[0] < 200:
                    continue
                b64 = base64.b64encode(resp.content).decode()
                return f"data:image/jpeg;base64,{b64}"
        except Exception:
            continue
    # Fallback solid maroon
    fb = PILImage.new("RGB", (1280, 720), (28, 8, 8))
    buf = io.BytesIO()
    fb.save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _build_shorts_html(item: dict, thumb_b64: str) -> str:
    """Build a full-bleed 1080x1920 HTML/CSS template for YouTube Shorts."""
    video_id = item.get("video_id", "")
    title = (item.get("title") or "సమర్థ వాస్తు").strip()
    is_short = item.get("is_short", False)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    html = f"""<!DOCTYPE html>
<html lang="te">
<head>
<meta charset="utf-8">
<title>Samartha Vastu Short</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700;800;900&family=Noto+Sans+Telugu:wght@400;600;700;800;900&family=Ramabhadra&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    width: 1080px;
    height: 1920px;
    overflow: hidden;
    background: radial-gradient(circle at 50% 25%, #2a0808 0%, #150303 55%, #0a0101 100%);
    font-family: 'Noto Sans Telugu', 'Segoe UI Emoji', 'Nirmala UI', sans-serif;
    color: #fff5dc;
    position: relative;
}}
/* Ornamental gold outer border */
.outer-border {{
    position: absolute;
    top: 0; left: 0; width: 100%; height: 100%;
    border: 8px solid #d4a017;
    box-sizing: border-box;
    pointer-events: none;
    z-index: 10;
}}
/* Top header zone: y=200..360 */
.header-zone {{
    position: absolute;
    top: 200px; left: 0; width: 100%; height: 160px;
    text-align: center;
    z-index: 5;
}}
.main-title {{
    font-family: 'Cinzel', serif;
    font-size: 46px;
    font-weight: 900;
    letter-spacing: 2px;
    background: linear-gradient(180deg, #fff7c2 0%, #ffd54f 40%, #d4a017 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 4px 15px rgba(212, 160, 23, 0.3);
    line-height: 1.15;
    margin-bottom: 4px;
}}
.main-title-te {{
    font-family: 'Ramabhadra', 'Noto Sans Telugu', sans-serif;
    font-size: 28px;
    font-weight: 800;
    color: #ffe599;
    letter-spacing: 0.5px;
    line-height: 1.25;
}}
.sub-title {{
    font-size: 19px;
    font-weight: 700;
    color: #e6b840;
    letter-spacing: 0.5px;
    margin-top: 6px;
}}
/* Center hero thumbnail: y=390..960, 980px wide centered */
.hero-zone {{
    position: absolute;
    top: 390px; left: 50px; width: 980px; height: 570px;
    z-index: 5;
}}
.hero-frame {{
    width: 100%; height: 100%;
    border: 3px solid #d4a017;
    border-radius: 16px;
    background: #000;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 18px 45px rgba(0,0,0,0.85), 0 0 25px rgba(212,160,23,0.3);
}}
.hero-img {{
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
}}
/* Middle headline card: y=990..1360 */
.headline-zone {{
    position: absolute;
    top: 990px; left: 50px; width: 980px; height: 370px;
    z-index: 5;
}}
.headline-card {{
    width: 100%; height: 100%;
    background: linear-gradient(180deg, rgba(26,6,6,0.92) 0%, rgba(14,3,3,0.96) 100%);
    border: 1.5px solid rgba(212,160,23,0.6);
    border-radius: 14px;
    padding: 30px 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 10px 30px rgba(0,0,0,0.75);
}}
.video-title {{
    font-family: 'Noto Sans Telugu', 'Ramabhadra', sans-serif;
    font-size: 34px;
    font-weight: 800;
    line-height: 1.45;
    color: #fff9ea;
    text-align: center;
    text-shadow: 0 2px 8px rgba(0,0,0,0.8);
}}
.badges {{
    font-size: 18px;
    font-weight: 700;
    color: #ffd54f;
    letter-spacing: 0.5px;
    text-align: center;
    margin-top: 14px;
}}
.svsn-badge {{
    font-family: 'Ramabhadra', 'Noto Sans Telugu', sans-serif;
    color: #ffe599;
}}
/* Safe CTA banner: y=1390..1600 */
.cta-zone {{
    position: absolute;
    top: 1390px; left: 0; width: 100%; height: 210px;
    background: linear-gradient(180deg, rgba(24,5,5,0.92) 0%, rgba(12,2,2,0.98) 100%);
    border-top: 1px solid rgba(212,160,23,0.55);
    border-bottom: 8px solid #d4a017;
    z-index: 5;
    padding: 0 60px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
}}
.cta-line {{
    font-family: 'Noto Sans Telugu', sans-serif;
    font-size: 24px;
    font-weight: 800;
    color: #fff5dc;
    text-align: center;
    line-height: 1.4;
    text-shadow: 0 2px 8px rgba(0,0,0,0.8);
}}
.cta-phone {{
    font-size: 26px;
    font-weight: 900;
    color: #4ade80;
    text-align: center;
    text-shadow: 0 2px 8px rgba(0,0,0,0.8);
}}
</style>
</head>
<body>
<div class="outer-border"></div>
<div class="header-zone">
  <div class="main-title">సమర్థ వాస్తు</div>
  <div class="main-title-te">(సమంత ఆస్ట్రో-వాస్తు)</div>
  <div class="sub-title">SAMARTHA ASTRO-VASTU</div>
</div>
<div class="hero-zone">
  <div class="hero-frame">
    <img src="{thumb_b64}" class="hero-img" alt="YouTube Thumbnail">
  </div>
</div>
<div class="headline-zone">
  <div class="headline-card">
    <div class="video-title">{title}</div>
    <div class="badges">
      <span class="svsn-badge">SVSN రాజు &nbsp;|&nbsp; MA Astrology &amp; Vastu Shastra</span>
    </div>
  </div>
</div>
<div class="cta-zone">
  <div class="cta-line">పూర్తి వీడియో మా YouTube ఛానెల్‌లో చూడండి</div>
  <div class="cta-phone">📞 WhatsApp Consultation: +91 8919395559</div>
</div>
</body>
</html>"""
    return html


def _render_shorts_frame(html_content: str, output_png: Path) -> None:
    """Render the 1080x1920 HTML template via Headless Chrome to a PNG."""
    import tempfile, subprocess
    from html_poster_generator import find_chrome_binary

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    chrome_bin = find_chrome_binary()

    temp_html = output_png.with_suffix(".tmp.html")
    temp_html.write_text(html_content, encoding="utf-8")

    user_data = tempfile.mkdtemp(prefix="chrome_shorts_")
    cmd = [
        chrome_bin,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={user_data}",
        f"--screenshot={str(output_png)}",
        "--window-size=1080,1920",
        "--hide-scrollbars",
        f"file:///{temp_html.as_posix()}",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            log.warning("Chrome returned non-zero %d: %s", res.returncode, res.stderr)
        if not output_png.exists() or output_png.stat().st_size == 0:
            raise RuntimeError(f"Shorts frame screenshot not created: {output_png}")
    finally:
        try:
            if temp_html.exists():
                temp_html.unlink()
        except Exception:
            pass


def create_shorts_video(poster_path: str | Path, output_mp4: str | Path = TEMP_MP4) -> Path:
    """
    Creates a full-bleed 1080x1920 (9:16) YouTube Short using Headless Chrome
    HTML/CSS rendering with HarfBuzz Telugu shaping, then encodes via ffmpeg.
    Zero PIL-based drawing remains — no more tiny left-aligned thumbnails.
    """
    poster_path = Path(poster_path)
    if not poster_path.exists():
        raise FileNotFoundError(f"Poster image not found: {poster_path}")

    # Validate poster is 1080x1350 before using
    from PIL import Image as PILImage
    with PILImage.open(poster_path) as _chk:
        _pw, _ph = _chk.size
    if _pw < 1080 or _ph < 1350:
        raise ValueError(
            f"Poster {poster_path.name} is {_pw}x{_ph}, expected >=1080x1350. "
            f"Regenerate via html_poster_generator.py before creating Short."
        )

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output_mp4 = Path(output_mp4)

    item_id = poster_path.stem
    # Load item from schedule for title/video_id
    schedule = load_schedule()
    item = None
    for it in schedule:
        if it.get("id") == item_id:
            item = it
            break
    if item is None:
        item = {"id": item_id, "title": "సమర్థ వాస్తు", "video_id": item_id, "is_short": False}

    thumb_b64 = _fetch_thumb_b64(item.get("video_id", item_id))
    html = _build_shorts_html(item, thumb_b64)

    frame_png = OUT_DIR / f"shorts_frame_{item_id}.png"
    _render_shorts_frame(html, frame_png)

    # Hard validation: rendered frame must be exactly 1080x1920
    with PILImage.open(frame_png) as chk:
        fw, fh = chk.size
    if fw != 1080 or fh != 1920:
        raise RuntimeError(
            f"Rendered Shorts frame is {fw}x{fh}, expected 1080x1920. Aborting upload."
        )

    log.info("[Shorts Generator] Rendered 1080x1920 frame (%d bytes)", frame_png.stat().st_size)

    # FFmpeg: 15-second 1080x1920 MP4 from the PNG frame
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(frame_png),
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

    try:
        frame_png.unlink(missing_ok=True)
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
    if existing_url and "gg3nNP0kueg" not in existing_url and "@samarthavastu999/shorts" not in existing_url:
        log.info("[YouTube Shorts] Already uploaded for %s: %s (Skipping)", item_id, existing_url)
        return {"success": True, "short_url": existing_url, "already_uploaded": True}
    if existing_url:
        log.warning("[YouTube Shorts] Stale/fallback URL detected for %s: %s — will re-upload to get correct short URL", item_id, existing_url)

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
        # Ensure isolated Chrome with CDP on port 9222 is running before connecting.
        if not ensure_chrome_cdp():
            return {"success": False, "short_url": None, "error": "Chrome CDP on port 9222 could not be started"}

        with sync_playwright() as p:
            log.info("[YouTube Shorts] Connecting to Chrome CDP at %s...", CDP_URL)
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
            context = browser.contexts[0]

            # ── Step 1: Open existing draft or start new upload ───────────────
            drafts_url = f"https://studio.youtube.com/channel/{TARGET_CHANNEL_ID}/videos/short"
            log.info("[YouTube Shorts] Opening YouTube Shorts drafts page: %s", drafts_url)
            page = context.new_page()
            page.goto(drafts_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)

            # Channel guard
            current_url = page.url
            if DISALLOWED_CHANNEL in current_url or "@rajusvsn8246" in current_url:
                raise RuntimeError(f"ABORTED: Connected to disallowed channel {DISALLOWED_CHANNEL} (@rajusvsn8246).")

            # Try to find and click "Edit draft" for this video's title
            draft_title = item.get("title", "")
            edit_clicked = False
            try:
                # Find row containing the draft title (regardless of Draft/Private visibility)
                row = page.locator(f'ytcp-video-row:has-text("{draft_title[:40]}"), tr:has-text("{draft_title[:40]}")').first
                if row.count() > 0 and row.is_visible():
                    # Check visibility badge - proceed for both Draft and Private
                    row_text = row.inner_text() or ""
                    visibility_text = ""
                    for vw in ["Private", "Draft", "Public", "Unlisted", "Scheduled"]:
                        if vw.lower() in row_text.lower():
                            visibility_text = vw
                            break
                    log.info("[YouTube Shorts] Found existing draft with visibility='%s': %s", visibility_text, draft_title[:40])
                    
                    edit_btn = row.locator('[aria-label="Edit"], ytcp-button:has-text("Edit"), button:has-text("Edit"), ytcp-button:has-text("Edit draft"), button:has-text("Edit draft")').first
                    if edit_btn.count() > 0 and edit_btn.is_visible():
                        edit_btn.click()
                        log.info("[YouTube Shorts] Clicked 'Edit' for existing draft.")
                        edit_clicked = True
                    else:
                        # Try clicking the row itself to open details
                        row.click()
                        page.wait_for_timeout(3000)
                        log.info("[YouTube Shorts] Clicked row to open details.")
                        edit_clicked = True
            except Exception as exc:
                log.info("[YouTube Shorts] No existing draft found to edit: %s", exc)

            if not edit_clicked:
                # Start new upload via direct upload URL
                upload_url = f"https://studio.youtube.com/channel/{TARGET_CHANNEL_ID}/videos/upload?d=ud"
                log.info("[YouTube Shorts] Opening direct upload URL: %s", upload_url)
                page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)

                # 3. Supply MP4 to input[type="file"]
                file_input = page.locator('input[type="file"]').first
                file_input.wait_for(state="attached", timeout=10000)
                log.info("[YouTube Shorts] Uploading file %s...", mp4_path)
                file_input.set_input_files(str(mp4_path.resolve()))

            # Wait for wizard modal to appear
            page.wait_for_timeout(5000)

            # ── Step 2: Fill Short Title (Telugu) into the Details modal ──────
            title_box = page.locator('#title-textarea #textbox, #title-textarea input, div#textbox[role="textbox"]').first
            title_box.wait_for(state="visible", timeout=30000)
            title_box.click(force=True)
            page.wait_for_timeout(500)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(300)
            # Use document.execCommand('insertText') — YouTube Studio's Lexical editor
            # ignores page.keyboard.insert_text() and page.keyboard.type().
            exec_result = page.evaluate("""(text) => {
                const el = document.querySelector('#title-textarea #textbox, #title-textarea input, div#textbox[role="textbox"]');
                if (!el) return { success: false, error: 'element not found' };
                el.focus();
                document.execCommand('selectAll', false, null);
                const ok = document.execCommand('insertText', false, text);
                return { success: ok, innerText: el.innerText };
            }""", short_title)
            page.wait_for_timeout(1000)
            # Blur/tabs out to let YouTube register the change
            title_box.press("Tab")
            page.wait_for_timeout(1000)
            # Assert the title was actually set and is NOT "temp short"
            actual_title = title_box.input_value() or title_box.inner_text() or ""
            retry = 0
            while (not actual_title or actual_title.strip() == "temp short" or actual_title.strip() != short_title.strip()) and retry < 5:
                log.warning("[YouTube Shorts] Title not set correctly (got: %r), retrying...", actual_title)
                title_box.click(force=True)
                page.wait_for_timeout(500)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.wait_for_timeout(300)
                page.evaluate("""(text) => {
                    const el = document.querySelector('#title-textarea #textbox, #title-textarea input, div#textbox[role="textbox"]');
                    if (!el) return { success: false, error: 'element not found' };
                    el.focus();
                    document.execCommand('selectAll', false, null);
                    const ok = document.execCommand('insertText', false, text);
                    return { success: ok, innerText: el.innerText };
                }""", short_title)
                page.wait_for_timeout(1000)
                title_box.press("Tab")
                page.wait_for_timeout(1000)
                actual_title = title_box.input_value() or title_box.inner_text() or ""
                retry += 1
            if actual_title.strip() == "temp short" or not actual_title.strip():
                log.error("[YouTube Shorts] Title field still shows '%s' after retries — aborting to prevent 'temp short' publish.", actual_title)
                page.close()
                return {"success": False, "short_url": None, "error": "Title field not set correctly (still 'temp short' or empty)"}
            log.info("[YouTube Shorts] Title set to: %s (%d chars)", actual_title, len(actual_title))

            # ── Step 2b: Fill Short Description ───────────────────────────────
            desc_box = page.locator('#description-textarea #textbox, #description-textarea textarea').first
            if desc_box.count() > 0 and desc_box.is_visible():
                desc_box.click(force=True)
                page.wait_for_timeout(500)
                page.keyboard.press("Control+A")
                page.wait_for_timeout(300)
                page.keyboard.press("Backspace")
                page.wait_for_timeout(300)
                page.evaluate("""(text) => {
                    const el = document.querySelector('#description-textarea #textbox, #description-textarea textarea');
                    if (!el) return { success: false, error: 'element not found' };
                    el.focus();
                    document.execCommand('selectAll', false, null);
                    const ok = document.execCommand('insertText', false, text);
                    return { success: ok, innerText: el.innerText };
                }""", short_desc)
                page.wait_for_timeout(1000)
                desc_box.press("Tab")
                log.info("[YouTube Shorts] Description set.")

            # Save diagnostic screenshot after title/description step
            page.screenshot(path=str(OUT_DIR / "yt_step_title.png"), full_page=True)

            # ── Step 2c: Click "Not made for kids" radio ─────────────────────
            kids_radio = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"], tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]').first
            kids_asserted = False
            if kids_radio.count() > 0 and kids_radio.is_visible():
                # Scroll into view inside the modal's scrollable container
                kids_radio.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                # Click #radioContainer inside the radio button for reliable toggle
                radio_container = kids_radio.locator('#radioContainer').first
                if radio_container.count() > 0 and radio_container.is_visible():
                    radio_container.click()
                else:
                    kids_radio.click()
                page.wait_for_timeout(1000)
                # STRICTLY ASSERT aria-checked="true" (retry up to 5 times)
                for attempt in range(5):
                    checked_attr = kids_radio.get_attribute("checked") or ""
                    aria_checked = kids_radio.get_attribute("aria-checked") or ""
                    kids_asserted = ("checked" in checked_attr.lower()) or (aria_checked.lower() == "true")
                    if kids_asserted:
                        log.info("[YouTube Shorts] 'Not made for kids' selected and verified (aria-checked=%s).", aria_checked)
                        break
                    log.warning("[YouTube Shorts] Kids radio not yet checked (attempt %d/5), retrying...", attempt + 1)
                    radio_container.click() if radio_container.count() > 0 else kids_radio.click()
                    page.wait_for_timeout(1000)
                if not kids_asserted:
                    log.error("[YouTube Shorts] 'Not made for kids' radio could not be checked after 5 retries.")
                    page.close()
                    return {"success": False, "short_url": None, "error": "Kids radio not checked"}
                log.info("[YouTube Shorts] Selected 'Not made for kids'.")
            else:
                log.warning("[YouTube Shorts] Kids radio not visible — may already be set.")
                # Even if not visible, assert the current state
                if kids_radio.count() > 0:
                    aria_checked = kids_radio.get_attribute("aria-checked") or ""
                    kids_asserted = aria_checked.lower() == "true"
                    log.info("[YouTube Shorts] Kids radio aria-checked=%s (already set).", aria_checked)

            # Save diagnostic screenshot after kids step
            page.screenshot(path=str(OUT_DIR / "yt_step_kids.png"), full_page=True)

            # ── Step 3: Adaptive Next loop until visibility step ──────────────
            next_btn = page.locator('#next-button').first
            next_clicks = 0
            while next_clicks < 5:
                # Check if PUBLIC radio is already visible (we reached visibility step)
                public_check = page.locator('tp-yt-paper-radio-button[name="PUBLIC"], [name="PUBLIC"]')
                if public_check.count() > 0 and public_check.is_visible():
                    log.info("[YouTube Shorts] Reached visibility step after %d Next clicks.", next_clicks)
                    break

                if next_btn.count() > 0 and next_btn.is_visible():
                    # Scroll modal footer into view so Next button is not intercepted by backdrop
                    next_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)

                    disabled = next_btn.get_attribute("disabled")
                    aria_disabled = next_btn.get_attribute("aria-disabled") or ""
                    if disabled or aria_disabled.lower() == "true":
                        log.info("[YouTube Shorts] Next button disabled at step %d — stopping.", next_clicks)
                        break

                    # Click Next using Playwright .click(); fallback to DOM .click() if intercepted
                    try:
                        next_btn.click()
                    except Exception:
                        page.evaluate("""() => {
                            const btn = document.querySelector('#next-button');
                            if (btn) btn.click();
                        }""")
                    next_clicks += 1
                    log.info("[YouTube Shorts] Clicked Next #%d", next_clicks)
                    page.wait_for_timeout(3000)

                    # NON-BLOCKING: "Video processing is taking longer than expected" banner
                    # does NOT prevent clicking Next through to Visibility. YouTube allows
                    # publishing Public while HD processing finishes in the background.
                    processing_banner = page.locator('text="Video processing is taking longer than expected"')
                    if processing_banner.count() > 0 and processing_banner.first.is_visible():
                        log.info("[YouTube Shorts] Processing banner visible — continuing to Next regardless (non-blocking).")
                else:
                    log.info("[YouTube Shorts] Next button not visible — wizard may be done.")
                    break

            # Save diagnostic screenshot at visibility step
            page.screenshot(path=str(OUT_DIR / "yt_step_visibility.png"), full_page=True)

            # ── Step 4: Click PUBLIC radio ────────────────────────────────────
            public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"] #radioContainer, tp-yt-paper-radio-button[name="PUBLIC"]').first
            if public_radio.count() > 0 and public_radio.is_visible():
                # Click PUBLIC radio button (click #radioContainer inner element for reliable toggle)
                public_radio.scroll_into_view_if_needed()
                public_radio.click()
                page.wait_for_timeout(1000)

                # ASSERT: PUBLIC radio must be checked AND #done-button must say "Publish" (not "Save")
                public_checked = False
                done_says_publish = False
                for attempt in range(5):
                    # Check PUBLIC radio state
                    checked_attr = public_radio.get_attribute("checked") or ""
                    aria_checked = public_radio.get_attribute("aria-checked") or ""
                    public_checked = ("checked" in checked_attr.lower()) or (aria_checked.lower() == "true")

                    # Check #done-button text
                    done_btn_check = page.locator('#done-button').first
                    done_text = ""
                    if done_btn_check.count() > 0 and done_btn_check.is_visible():
                        done_text = done_btn_check.inner_text() or ""
                    done_says_publish = ("publish" in done_text.lower()) and ("save" not in done_text.lower())

                    if public_checked and done_says_publish:
                        log.info("[YouTube Shorts] PUBLIC selected and verified (checked=%s, done_button='%s').", checked_attr, done_text)
                        break

                    log.warning("[YouTube Shorts] PUBLIC not yet confirmed (checked=%s, done_button='%s'), retrying click...", checked_attr, done_text)
                    # Re-click the radio button
                    public_radio.click()
                    page.wait_for_timeout(1000)

                if not public_checked or not done_says_publish:
                    log.error("[YouTube Shorts] PUBLIC radio not properly selected after retries (checked=%s, done_button='%s').", checked_attr, done_text)
                    page.close()
                    return {"success": False, "short_url": None, "error": "PUBLIC radio not properly selected"}
            else:
                log.error("[YouTube Shorts] PUBLIC radio not visible after %d Next clicks.", next_clicks)
                page.close()
                return {"success": False, "short_url": None, "error": "PUBLIC radio not visible"}

            # ── Step 5: Click Done / Publish ──────────────────────────────────
            done_btn = page.locator('#done-button').first
            if done_btn.count() > 0 and done_btn.is_visible():
                done_text = done_btn.inner_text() or ""
                if "save" in done_text.lower():
                    log.error("[YouTube Shorts] Done button still says 'Save' — PUBLIC not applied. Aborting to prevent 'Saved as private'.")
                    page.close()
                    return {"success": False, "short_url": None, "error": "Done button still says Save — PUBLIC not applied"}
                done_btn.click()
                log.info("[YouTube Shorts] Clicked Publish / Done!")
                page.wait_for_timeout(3000)

                # Handle "Publish anyway" / checks dialog if it appears
                for attempt in range(3):
                    try:
                        confirm_btn = page.locator('#secondary-action-button, button:has-text("Publish anyway"), button:has-text("Continue"), [aria-label*="Publish anyway"]').first
                        if confirm_btn.count() > 0 and confirm_btn.is_visible():
                            confirm_btn.click()
                            log.info("[YouTube Shorts] Clicked confirmation dialog button.")
                            page.wait_for_timeout(3000)
                        else:
                            break
                    except Exception:
                        break

                # ── Step 6: Wait for post-publish share dialog ────────────
                for attempt in range(45):  # up to 45 seconds
                    short_url = _extract_short_url(page)
                    if short_url:
                        log.info("[YouTube Shorts] Captured Short URL: %s", short_url)
                        break
                    time.sleep(1)
                else:
                    log.warning("[YouTube Shorts] Short URL not captured after 45s wait.")

                # Save final screenshot
                page.screenshot(path=str(OUT_DIR / "yt_published.png"), full_page=True)

                # ── Step 7: VERIFY on Shorts table that Visibility says "Public" ──
                # Navigate back to Shorts page to confirm visibility
                page.goto(f"https://studio.youtube.com/channel/{TARGET_CHANNEL_ID}/videos/short", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

                # Find the row for this video and check visibility
                short_id = None
                if short_url:
                    short_id = short_url.split("/shorts/")[-1].split("?")[0]

                visibility_verified = False
                if short_id:
                    # Look for the row containing this short's video ID or title
                    row = page.locator(f'ytcp-video-row:has-text("{short_id}"), tr:has-text("{short_id}")').first
                    if row.count() > 0 and row.is_visible():
                        row_text = row.inner_text() or ""
                        if "Public" in row_text or "public" in row_text.lower():
                            visibility_verified = True
                            log.info("[YouTube Shorts] Verified: Row shows Public visibility: %s", row_text[:100])
                        else:
                            log.warning("[YouTube Shorts] Row found but visibility not Public: %s", row_text[:200])
                    else:
                        log.warning("[YouTube Shorts] Row not found for short ID %s", short_id)

                if not visibility_verified:
                    log.error("[YouTube Shorts] Could not verify Public visibility on Shorts table.")
                    page.close()
                    return {"success": False, "short_url": None, "error": "Visibility not verified as Public on Shorts table"}

                log.info("[YouTube Shorts] Upload verified as PUBLIC on Shorts table.")
            page.close()

    except Exception as exc:
        log.error("[YouTube Shorts] Playwright CDP failed: %s. Blind GUI coordinate fallback is disabled — will not hijack user's personal Chrome windows.", exc)
        return {"success": False, "short_url": None, "error": f"CDP error: {exc}"}

    if not short_url:
        log.error("[YouTube Shorts] No short URL captured from YouTube Studio UI after publish.")
        return {"success": False, "error": "No short URL captured from YouTube Studio UI"}

    log.info("[YouTube Shorts] Upload complete! Short URL: %s", short_url)
    return {"success": True, "short_url": short_url}


def _extract_short_url(page) -> str | None:
    """Extract a verified youtube.com/shorts/<11-char-id> URL from the current page."""
    try:
        for link in page.locator('a').all():
            href = link.get_attribute("href") or ""
            if "youtube.com/shorts/" in href or "youtu.be/" in href:
                url = href.strip()
                if "youtu.be/" in url:
                    vid_part = url.split("youtu.be/")[-1].split("?")[0]
                    url = f"https://www.youtube.com/shorts/{vid_part}"
                # Verify it's an 11-char short ID
                import re
                m = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', url)
                if m:
                    return url
    except Exception:
        pass
    return None


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
