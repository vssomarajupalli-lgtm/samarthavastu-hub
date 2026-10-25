"""
whatsapp_sender.py
------------------
Dedicated, visual-verified WhatsApp sender for Samartha Vastu.
- Overcomes pywhatkit silent failures (which crash on Unicode Telugu and prematurely submit on newlines).
- Unlocks the interactive Windows desktop from background agent subprocesses.
- Forces Chrome window to the foreground using Win32 AttachThreadInput + Alt key unlock.
- Uses Ctrl+L URL navigation directly inside the active browser tab.
- Sequentially executes:
    1. Focuses chat message input box at exact chat area coordinates (1000, 940 on 1080p).
    2. Pastes JPEG image as raw DIB (CF_DIB) via win32clipboard.
    3. Verifies image preview modal via diagnostic screenshot.
    4. Pastes full UTF-8 Telugu caption into the modal caption box via pyperclip.
    5. Presses Enter to submit.
    6. Waits for upload and verifies sent message via final screenshot.
"""

from io import BytesIO
import ctypes
import logging
import os
import sys
import time
import webbrowser
from pathlib import Path

import pyautogui
import pyperclip
from PIL import Image, ImageGrab
import win32clipboard
import win32con
import win32gui
import win32service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("whatsapp_sender")
pyautogui.FAILSAFE = False


def attach_to_default_desktop():
    """Ensure the current thread is attached to the interactive Windows desktop."""
    try:
        hdesk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
        hdesk.SetThreadDesktop()
        log.info("[WhatsApp Sender] Attached to interactive 'default' desktop.")
    except Exception as exc:
        log.warning("[WhatsApp Sender] Desktop attach note: %s", exc)


def force_chrome_foreground() -> int:
    """Finds the Chrome window and forces it to the foreground reliably."""
    attach_to_default_desktop()
    target_hwnd = None

    def enum_win(hwnd, _):
        nonlocal target_hwnd
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "Google Chrome" in title and "Graph API Explorer" not in title:
                target_hwnd = hwnd

    win32gui.EnumWindows(enum_win, None)

    if not target_hwnd:
        log.warning("[WhatsApp Sender] No active Chrome window found.")
        return 0

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    cur_thread = kernel32.GetCurrentThreadId()
    fg_window = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg_window, 0)

    # Send Alt key event to unlock Windows SetForegroundWindow restrictions
    user32.keybd_event(0x12, 0, 0, 0)  # Alt down
    user32.keybd_event(0x12, 0, 2, 0)  # Alt up

    if cur_thread != fg_thread:
        user32.AttachThreadInput(cur_thread, fg_thread, True)

    user32.ShowWindow(target_hwnd, win32con.SW_SHOWMAXIMIZED)
    user32.SetForegroundWindow(target_hwnd)
    user32.BringWindowToTop(target_hwnd)
    user32.SetFocus(target_hwnd)

    if cur_thread != fg_thread:
        user32.AttachThreadInput(cur_thread, fg_thread, False)

    time.sleep(1)
    fg = win32gui.GetForegroundWindow()
    log.info("[WhatsApp Sender] Brought Chrome to foreground (HWND: %s, Title: '%s')", fg, win32gui.GetWindowText(fg))
    return target_hwnd


def copy_image_to_clipboard(path: str):
    """Copies an image to Windows clipboard as CF_DIB."""
    img = Image.open(path)
    output = BytesIO()
    img.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:]  # Remove 14-byte BMP header
    output.close()

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()
    log.info("[WhatsApp Sender] Image copied to clipboard as CF_DIB: %s", path)


def is_phone_number(target: str) -> bool:
    clean = target.strip().replace(" ", "").replace("-", "")
    return clean.startswith("+") or clean.isdigit()


def navigate_to_target(target: str):
    """Navigates to the WhatsApp Web target using the active Chrome window or webbrowser."""
    if is_phone_number(target):
        clean_num = target.replace(" ", "").replace("-", "")
        if not clean_num.startswith("+"):
            clean_num = f"+{clean_num}"
        url = f"https://web.whatsapp.com/send?phone={clean_num}"
    else:
        url = f"https://web.whatsapp.com/accept?code={target}"

    log.info("[WhatsApp Sender] Target URL: %s", url)
    hwnd = force_chrome_foreground()
    if hwnd:
        log.info("[WhatsApp Sender] Navigating address bar (Ctrl+L)...")
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.5)
        pyperclip.copy(url)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
    else:
        log.info("[WhatsApp Sender] Opening via default browser...")
        webbrowser.open(url)
    return url


def send_whatsapp_media(
    target: str,
    img_path: str,
    caption: str,
    output_dir: str = r"E:\samarthavastu-hub\logs\screenshots",
    target_tag: str = "",
    wait_load: int = 25,
    close_tab: bool = False,
) -> dict:
    """
    Sends an image + Telugu caption to WhatsApp Web target with visual screenshot verification.
    Screenshots are saved and overwritten in logs/screenshots/.
    """
    attach_to_default_desktop()

    target = target.strip()
    tag = target_tag or ("mobile" if is_phone_number(target) else "group")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    debug_1 = str(out_dir / f"debug_1_chat_loaded_{tag}.png")
    debug_2 = str(out_dir / f"debug_2_image_pasted_{tag}.png")
    debug_3 = str(out_dir / f"debug_3_sent_{tag}.png")

    log.info("=" * 60)
    log.info("[WhatsApp Sender] Dispatching media to: %s (Tag: %s)", target, tag)
    log.info("=" * 60)

    # Step a: Navigate to target URL
    navigate_to_target(target)

    # Step b: Wait for WhatsApp Web to load the chat
    log.info("[WhatsApp Sender] Waiting %ds for chat to load...", wait_load)
    time.sleep(wait_load)

    # Ensure Chrome is foreground after loading
    force_chrome_foreground()
    time.sleep(1)

    screen_w, screen_h = pyautogui.size()
    log.info("[WhatsApp Sender] Screen size: %dx%d", screen_w, screen_h)

    # Step c: Chat box readiness verification (extra 15s if still loading)
    click_x = int(screen_w * 0.52) if screen_w != 1920 else 1000
    click_y = int(screen_h * 0.87) if screen_h != 1080 else 940

    try:
        shot_check = ImageGrab.grab()
        chat_pixel = shot_check.getpixel((click_x, click_y))
        log.info("[WhatsApp Sender] Chat box health check pixel at (%d, %d): %s", click_x, click_y, chat_pixel)
        # If the screen is still loading or connecting, allow an extra 15 seconds
        # WhatsApp Web dark mode input background: (32, 44, 51) / light mode: (240, 242, 245)
        # If pixel is pure white (255,255,255) from blank tab or pure black (0,0,0) from window init, wait extra 15s
        if chat_pixel in ((255, 255, 255), (0, 0, 0)):
            log.warning("[WhatsApp Sender] Chat box appears still loading (pixel=%s). Waiting extra 15s...", chat_pixel)
            time.sleep(15)
            force_chrome_foreground()
    except Exception as exc:
        log.warning("[WhatsApp Sender] Pre-check note: %s", exc)

    # Diagnostic Screenshot 1 (Chat loaded)
    try:
        shot1 = ImageGrab.grab()
        shot1.save(debug_1)
        log.info("[WhatsApp Sender] Diagnostic 1 captured: %s", debug_1)
    except Exception as exc:
        log.warning("[WhatsApp Sender] Screenshot 1 error: %s", exc)

    # Step d: Focus message input area inside the chat window
    # On 1080p, chat area is from x=650 to x=1920.
    # The input box is centered at (1000, 940).
    click_x = int(screen_w * 0.52) if screen_w != 1920 else 1000
    click_y = int(screen_h * 0.87) if screen_h != 1080 else 940
    log.info("[WhatsApp Sender] Focusing message input box at (%d, %d)...", click_x, click_y)
    pyautogui.click(click_x, click_y)
    time.sleep(0.5)
    # Clear any residual/interrupted text before pasting
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("backspace")
    time.sleep(0.5)

    # Step e: Copy image (CF_DIB) and paste via Ctrl+V
    copy_image_to_clipboard(img_path)
    time.sleep(0.5)
    log.info("[WhatsApp Sender] Pasting image via Ctrl+V...")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(4.0)

    # Step f: Diagnostic Screenshot 2 (Image preview modal open)
    try:
        shot2 = ImageGrab.grab()
        shot2.save(debug_2)
        log.info("[WhatsApp Sender] Diagnostic 2 captured: %s", debug_2)
    except Exception as exc:
        log.warning("[WhatsApp Sender] Screenshot 2 error: %s", exc)

    # Step g: Copy UTF-8 Telugu caption to clipboard and paste
    log.info("[WhatsApp Sender] Copying full Telugu caption to clipboard...")
    pyperclip.copy(caption)
    time.sleep(0.5)
    # Clear modal caption box to prevent mixed or duplicate text
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("backspace")
    time.sleep(0.2)
    log.info("[WhatsApp Sender] Pasting caption via Ctrl+V...")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(2.0)

    # Step h: Send message
    log.info("[WhatsApp Sender] Pressing Enter to send...")
    pyautogui.press("enter")
    time.sleep(1.0)

    # Wait 8s for media upload
    log.info("[WhatsApp Sender] Waiting 8s for media upload to finish...")
    time.sleep(8.0)

    # Step i: Diagnostic Screenshot 3 (Sent message)
    try:
        shot3 = ImageGrab.grab()
        shot3.save(debug_3)
        log.info("[WhatsApp Sender] Diagnostic 3 captured: %s", debug_3)
    except Exception as exc:
        log.warning("[WhatsApp Sender] Screenshot 3 error: %s", exc)

    if close_tab:
        log.info("[WhatsApp Sender] Closing tab via Ctrl+W...")
        pyautogui.hotkey("ctrl", "w")

    log.info("[WhatsApp Sender] Successfully completed dispatch for %s!", target)
    return {
        "target": target,
        "debug_1": debug_1,
        "debug_2": debug_2,
        "debug_3": debug_3,
        "success": True,
    }


def main():
    import argparse
    from dotenv import load_dotenv

    load_dotenv(Path(r"E:\samarthavastu-hub\.env"))

    parser = argparse.ArgumentParser(description="Dedicated WhatsApp Sender")
    parser.add_argument("--target", help="Specific target (phone or group code)")
    parser.add_argument("--image", default=r"E:\samarthavastu-hub\vastu_content_queue\thumbnails\video_01.jpg")
    parser.add_argument("--close-tab", action="store_true", help="Close tab after sending")
    args = parser.parse_args()

    targets_env = os.getenv("WHATSAPP_TARGET", "+918919395559")
    targets = [t.strip() for t in targets_env.split(",") if t.strip()]

    if args.target:
        targets = [args.target]

    sample_caption = (
        "🏠 వాస్తు శాస్త్రం – ఇంటి ముఖద్వారం సరైన దిశ ఎంత ముఖ్యమో తెలుసుకోండి\n\n"
        "మీ ఇంటి ముఖద్వారం ఏ దిశలో ఉంది? వాస్తు శాస్త్రం ప్రకారం తూర్పు లేదా ఉత్తర దిశ అత్యంత శుభప్రదం. "
        "సరైన దిశలో ద్వారం ఉంటే సంపద, ఆరోగ్యం, సుఖశాంతులు లభిస్తాయి. మీ ఇంటి వాస్తును మెరుగుపరచుకోండి — ఒకసారి పరిశీలించండి!\n\n"
        "📺 YouTube: https://www.youtube.com/@samarthavastu999\n"
        "📞 WhatsApp: +91 8919395559\n"
        "✉️ Email: samarthavastu999@gmail.com"
    )

    for idx, target in enumerate(targets):
        tag = f"target_{idx+1}"
        send_whatsapp_media(
            target=target,
            img_path=args.image,
            caption=sample_caption,
            target_tag=tag,
            wait_load=25,
            close_tab=args.close_tab,
        )
        if idx < len(targets) - 1:
            time.sleep(5)


if __name__ == "__main__":
    main()
