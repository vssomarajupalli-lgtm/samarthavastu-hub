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
from PIL import Image, ImageDraw, ImageFont

BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
LOGS_DIR        = BASE_DIR / "logs"
TEMP_MP4        = LOGS_DIR / "temp_short.mp4"
TEMP_FRAME      = LOGS_DIR / "temp_short_frame.jpg"

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

    # Bottom banner typography (ASCII/English only — zero PIL Telugu)
    font_sub = get_telugu_font(22, bold=True)
    b_txt = "WATCH FULL VIDEO: @SAMARTHAVASTU999  |  WHATSAPP: +91 8919395559"
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

            log.info("[YouTube Shorts] Opening YouTube Studio: %s", STUDIO_URL)
            page = context.new_page()
            page.goto(STUDIO_URL, timeout=25000)
            page.wait_for_load_state("networkidle")

            # Channel Verification & Account Switcher Guard
            current_url = page.url
            if DISALLOWED_CHANNEL in current_url or "@rajusvsn8246" in current_url:
                log.warning("[YouTube Shorts] Opened on personal channel %s. Attempting account switch to %s...", DISALLOWED_CHANNEL, TARGET_CHANNEL_NAME)
                try:
                    avatar_btn = page.locator('#avatar-btn, button#avatar-btn').first
                    avatar_btn.wait_for(state="visible", timeout=10000)
                    avatar_btn.click()
                    time.sleep(1.5)

                    switch_item = page.locator('tp-yt-paper-item:has-text("Switch account"), ytcp-text-menu-item:has-text("Switch account")').first
                    switch_item.wait_for(state="visible", timeout=8000)
                    switch_item.click()
                    time.sleep(2)

                    target_channel_btn = page.locator(f'ytd-account-item-renderer:has-text("{TARGET_CHANNEL_NAME}"), tp-yt-paper-item:has-text("{TARGET_CHANNEL_NAME}"), #channel-title:has-text("{TARGET_CHANNEL_NAME}")').first
                    target_channel_btn.wait_for(state="visible", timeout=8000)
                    target_channel_btn.click()
                    time.sleep(5)
                    page.wait_for_load_state("networkidle")
                except Exception as sw_err:
                    log.error("[YouTube Shorts] Account switch failed: %s", sw_err)

            # Strict guard check: NEVER upload to personal channel
            final_url = page.url
            if DISALLOWED_CHANNEL in final_url or "@rajusvsn8246" in final_url:
                raise RuntimeError(f"ABORTED: Connected to disallowed channel {DISALLOWED_CHANNEL} (@rajusvsn8246). Strictly prohibited from uploading to personal channel.")

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
        log.error("[YouTube Shorts] Playwright CDP failed: %s. Blind GUI coordinate fallback is disabled — will not hijack user's personal Chrome windows.", exc)
        return {"success": False, "short_url": None, "error": f"CDP error: {exc}"}

    if not short_url:
        log.error("[YouTube Shorts] No short URL captured from YouTube Studio UI after publish.")
        return {"success": False, "error": "No short URL captured from YouTube Studio UI"}

    log.info("[YouTube Shorts] Upload complete! Short URL: %s", short_url)
    return {"success": True, "short_url": short_url}


def upload_short_via_gui(item: dict, mp4_path: Path, short_title: str, short_desc: str) -> dict:
    """
    Robust native GUI automation fallback:
    Controls the user's active, authenticated Google Chrome window on the interactive desktop,
    ensures channel is strictly @samarthavastu999, and executes upload through YouTube Studio UI.
    """
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        import win32gui
        import win32con
        import win32service
        import pyperclip
        import pyautogui

        hdesk = win32service.OpenDesktop('default', 0, False, win32con.GENERIC_ALL)
        hdesk.SetThreadDesktop()

        # Find Chrome window
        target_hwnd = None
        def enum_cb(h, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(h):
                txt = win32gui.GetWindowText(h)
                if ("YouTube Studio" in txt or "Google Chrome" in txt) and "Visual Studio Code" not in txt and "Antigravity" not in txt:
                    target_hwnd = h
        win32gui.EnumWindows(enum_cb, None)

        if not target_hwnd:
            log.warning("[GUI Uploader] Active Chrome window not found. Launching Chrome...")
            subprocess.Popen(["chrome.exe", STUDIO_URL], shell=True)
            time.sleep(5)
            win32gui.EnumWindows(enum_cb, None)

        if not target_hwnd:
            return {"success": False, "error": "Could not locate or launch Chrome for GUI upload"}

        user32 = ctypes.windll.user32
        user32.ShowWindow(target_hwnd, win32con.SW_SHOWMAXIMIZED)
        user32.SetForegroundWindow(target_hwnd)
        time.sleep(1)

        # Navigate to STUDIO_URL to ensure we are strictly on SAMARTHA VASTU channel
        pyautogui.hotkey('ctrl', 'l')
        time.sleep(0.5)
        pyperclip.copy(STUDIO_URL)
        pyautogui.hotkey('ctrl', 'v')
        pyautogui.press('enter')
        time.sleep(6)

        # 1. Click Create button at (1670, 268)
        log.info("[GUI Uploader] Clicking Create button...")
        pyautogui.click(1670, 268)
        time.sleep(1.5)

        # 2. Click Upload videos at (1650, 340)
        log.info("[GUI Uploader] Clicking Upload videos...")
        pyautogui.click(1650, 340)
        time.sleep(2.5)

        # 3. Click Select files at (952, 810)
        log.info("[GUI Uploader] Clicking Select files...")
        pyautogui.click(952, 810)
        time.sleep(2.0)

        # 4. Supply MP4 path
        log.info("[GUI Uploader] Selecting MP4 file...")
        pyperclip.copy(str(mp4_path.resolve()))
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
        pyautogui.press('enter')
        time.sleep(6)

        # 5. Set Short Title in Details dialog
        log.info("[GUI Uploader] Setting Short title...")
        pyautogui.click(400, 640)
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.press('backspace')
        time.sleep(0.3)
        pyperclip.copy(short_title)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1)

        # 6. Click Next through all steps to Visibility (center: 1588, 860)
        for step in range(1, 4):
            log.info("[GUI Uploader] Clicking Next (%d/3)...", step)
            pyautogui.click(1588, 860)
            time.sleep(2.0)

        # 7. Select Public (if needed) & Click Publish (center: 1580, 870)
        log.info("[GUI Uploader] Clicking Publish at (1580, 870)...")
        pyautogui.click(1580, 870)
        time.sleep(7)

        # 8. Close dialog
        pyautogui.press('escape')
        time.sleep(1)

        # Query YouTube channel to get the newest Short URL — NEVER scrape channel page for a pre-existing short.
        short_url = None
        try:
            import urllib.request
            req = urllib.request.Request("https://www.youtube.com/@samarthavastu999/shorts", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
                matches = re.findall(r'"/shorts/([a-zA-Z0-9_-]{11})"', body)
                if matches:
                    candidate = f"https://www.youtube.com/shorts/{matches[0]}"
                    # Only accept if it is NOT the known stale/fallback ID
                    if "gg3nNP0kueg" not in candidate:
                        short_url = candidate
                        log.info("[GUI Uploader] Verified newest short URL: %s", short_url)
                    else:
                        log.warning("[GUI Uploader] Scraped short is the stale fallback gg3nNP0kueg — rejecting.")
        except Exception as e:
            log.warning("[GUI Uploader] Could not scrape newest short ID: %s", e)

        if not short_url:
            log.error("[GUI Uploader] No valid short URL could be verified after publish. Aborting URL assignment.")
            return {"success": False, "error": "Could not verify uploaded short URL after publish"}
        return {"success": True, "short_url": short_url}
    except Exception as exc:
        log.error("[GUI Uploader] GUI automation error: %s", exc)
        return {"success": False, "error": str(exc)}


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
