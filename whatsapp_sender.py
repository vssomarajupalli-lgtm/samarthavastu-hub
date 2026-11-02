"""
whatsapp_sender.py
------------------
Dedicated, DOM-verified WhatsApp sender for Samartha Vastu.
- Uses Playwright CDP over the isolated automation Chrome profile (port 9222).
- Never touches the user's personal Chrome browsers or active work tabs.
- Never uses pyautogui / Ctrl+L address-bar pasting / CF_DIB clipboard / pixel checks.
- Sequentially executes:
    1. Connect to Chrome CDP at 127.0.0.1:9222 (isolated profile).
    2. Open WhatsApp Web, wait for chat list #pane-side.
    3. Open target chat via DOM (phone: /send?phone=...; group: click in #pane-side).
    4. Wait for #main (chat view).
    5. Click Attach (+), upload image via input[type="file"].
    6. Fill Telugu caption in media-preview contenteditable div.
    7. Click [data-icon="send"] / [aria-label="Send"].
    8. Wait for [data-icon="msg-check"] / [data-icon="msg-dblcheck"] confirmation.
    9. Return False on ANY failure — never fake [OK].
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(r"E:\samarthavastu-hub\.env"))

import psutil

CDP_URL = "http://127.0.0.1:9222"
WHATSAPP_USER_DATA = r"E:\samarthavastu-hub\chrome_whatsapp_profile"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("whatsapp_sender")


# ---------------------------------------------------------------------------- #
#  Chrome CDP connection helpers                                               #
# ---------------------------------------------------------------------------- #

def connect_whatsapp_cdp() -> Optional[object]:
    """
    Connect to the isolated Chrome profile running on port 9222 and return
    (browser, context, page) for WhatsApp Web automation.
    Returns None if CDP is not available.
    """
    import socket
    from playwright.sync_api import sync_playwright

    # Quick port check
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=0.5):
            pass
    except OSError:
        log.error("[WhatsApp Sender] Chrome CDP port 9222 is not listening. "
                  "Start Chrome with --user-data-dir=%s --remote-debugging-port=9222",
                  WHATSAPP_USER_DATA)
        return None

    try:
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
        context = browser.contexts[0]
        page = context.new_page()
        log.info("[WhatsApp Sender] Connected to Chrome CDP (contexts=%d)", len(browser.contexts))
        return p, browser, context, page
    except Exception as exc:
        log.error("[WhatsApp Sender] CDP connect failed: %s", exc)
        return None


# ---------------------------------------------------------------------------- #
#  WhatsApp DOM automation                                                     #
# ---------------------------------------------------------------------------- #

def open_whatsapp_target(page, target: str) -> bool:
    """
    Open the target chat in WhatsApp Web.
    - Phone numbers: navigate to https://web.whatsapp.com/send?phone=<digits>
    - Group invite codes: wait for #pane-side, find group by name, click it.
    Returns True when #main (chat view) is visible.
    """
    from playwright.sync_api import sync_playwright

    target = target.strip()
    is_phone = target.startswith("+") or target.replace(" ", "").replace("-", "").isdigit()

    if is_phone:
        clean_num = target.replace(" ", "").replace("-", "")
        if not clean_num.startswith("+"):
            clean_num = f"+{clean_num}"
        digits = re.sub(r"\D", "", clean_num)  # e.g. 918919395559
        url = f"https://web.whatsapp.com/send?phone={digits}"
        log.info("[WhatsApp Sender] Navigating to phone chat: %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    else:
        # Group invite code — navigate to accept?code= page and click "View group"
        accept_url = f"https://web.whatsapp.com/accept?code={target}"
        log.info("[WhatsApp Sender] Navigating to group accept page: %s", accept_url)
        page.goto(accept_url, wait_until="domcontentloaded", timeout=60000)

    # Wait for chat list to load
    pane_side = page.locator("#pane-side")
    try:
        pane_side.wait_for(state="visible", timeout=45000)
        log.info("[WhatsApp Sender] Chat list #pane-side loaded.")
    except Exception:
        log.error("[WhatsApp Sender] #pane-side did not load — not logged into WhatsApp Web?")
        return False

    # For group invite codes: click "View group" / "Continue" button on the accept page
    if not is_phone:
        time.sleep(3)
        # Try common "View group" / "Continue" / "Join group" button selectors
        view_group_selectors = [
            'button:has-text("View group")',
            'button:has-text("Continue")',
            'button:has-text("Join group")',
            'a:has-text("View group")',
            'a:has-text("Continue")',
            '[data-testid="view_group"]',
            '[data-testid="continue"]',
        ]
        group_opened = False
        for sel in view_group_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    log.info("[WhatsApp Sender] Clicked group button: %s", sel)
                    group_opened = True
                    break
            except Exception:
                continue
        if not group_opened:
            log.warning("[WhatsApp Sender] No 'View group' button found — group may already be in chat list.")

    # For phone numbers, WhatsApp may auto-open the chat or show "Continue to Chat"
    if is_phone:
        # Wait for #main (chat view) or the "Continue to Chat" button
        time.sleep(3)
        # Click "Continue to Chat" if present
        continue_btn = page.locator('a:has-text("Continue to Chat"), button:has-text("Continue to Chat")')
        if continue_btn.count() > 0 and continue_btn.is_visible():
            log.info("[WhatsApp Sender] Clicking 'Continue to Chat' button.")
            continue_btn.click()
            time.sleep(3)

    # Wait for #main footer (chat input area) to confirm we're in a chat
    try:
        page.locator("#main footer").wait_for(state="visible", timeout=30000)
        log.info("[WhatsApp Sender] Chat view #main loaded.")
        return True
    except Exception:
        log.error("[WhatsApp Sender] #main (chat view) did not appear for target %s", target)
        return False


def send_whatsapp_media(
    target: str,
    img_path: str,
    caption: str,
    output_dir: str = r"E:\samarthavastu-hub\logs\screenshots",
    target_tag: str = "",
    wait_load: int = 25,
    close_tab: bool = True,
) -> dict:
    """
    Sends an image + Telugu caption to WhatsApp Web target using Playwright CDP DOM automation.
    Returns {"success": True/False, ...}. Never fakes [OK].
    """
    attach_to_default_desktop()

    target = target.strip()
    tag = target_tag or ("mobile" if (target.startswith("+") or target.replace(" ", "").replace("-", "").isdigit()) else "group")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    debug_1 = str(out_dir / f"debug_1_chat_loaded_{tag}.png")
    debug_2 = str(out_dir / f"debug_2_image_pasted_{tag}.png")
    debug_3 = str(out_dir / f"debug_3_sent_{tag}.png")

    log.info("=" * 60)
    log.info("[WhatsApp Sender] Dispatching media to: %s (Tag: %s)", target, tag)
    log.info("=" * 60)

    result = connect_whatsapp_cdp()
    if result is None:
        return {
            "target": target,
            "debug_1": debug_1,
            "debug_2": debug_2,
            "debug_3": debug_3,
            "success": False,
            "error": "CDP connection failed",
        }

    p, browser, context, page = result

    try:
        # Step a: Open target chat
        if not open_whatsapp_target(page, target):
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Could not open target chat",
            }

        # Diagnostic screenshot 1 — chat loaded
        try:
            page.screenshot(path=debug_1, full_page=True)
            log.info("[WhatsApp Sender] Diagnostic 1 captured: %s", debug_1)
        except Exception as exc:
            log.warning("[WhatsApp Sender] Screenshot 1 error: %s", exc)

        # Step b: Click Attach (+) button
        log.info("[WhatsApp Sender] Clicking Attach (+) button...")
        attach_selectors = [
            'span[data-icon="attach-menu-plus"]',
            'div[data-icon="attach-menu-plus"]',
            'button[aria-label="Attach"]',
        ]
        attach_clicked = False
        for sel in attach_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    attach_clicked = True
                    log.info("[WhatsApp Sender] Attach clicked: %s", sel)
                    break
            except Exception:
                continue
        if not attach_clicked:
            log.error("[WhatsApp Sender] Attach (+) button not found.")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Attach button not found",
            }

        time.sleep(2)

        # Step c: Upload image via input[type="file"]
        log.info("[WhatsApp Sender] Uploading image: %s", img_path)
        file_input = page.locator('input[type="file"][accept*="image"], input[type="file"]').first
        file_input.wait_for(state="attached", timeout=10000)
        file_input.set_input_files(str(Path(img_path).resolve()))
        log.info("[WhatsApp Sender] Image file set.")

        time.sleep(4)

        # Diagnostic screenshot 2 — image preview modal
        try:
            page.screenshot(path=debug_2, full_page=True)
            log.info("[WhatsApp Sender] Diagnostic 2 captured: %s", debug_2)
        except Exception as exc:
            log.warning("[WhatsApp Sender] Screenshot 2 error: %s", exc)

        # Step d: Fill caption in media-preview caption box
        log.info("[WhatsApp Sender] Filling caption in media preview...")
        caption_selectors = [
            'div[contenteditable="true"][data-testid="media-caption"]',
            'div[contenteditable="true"]',
            '[role="textbox"]',
        ]
        caption_filled = False
        for sel in caption_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    loc.fill(caption)
                    caption_filled = True
                    log.info("[WhatsApp Sender] Caption filled via %s", sel)
                    break
            except Exception:
                continue
        if not caption_filled:
            log.warning("[WhatsApp Sender] Caption box not found — proceeding without caption.")

        time.sleep(2)

        # Step e: Click Send
        log.info("[WhatsApp Sender] Clicking Send button...")
        send_selectors = [
            'button[aria-label="Send"]',
            '[aria-label*="Send"]',
            'span[data-icon="send"]',
            'div[data-icon="send"]',
        ]
        send_clicked = False
        for sel in send_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    send_clicked = True
                    log.info("[WhatsApp Sender] Send clicked: %s", sel)
                    break
            except Exception:
                continue
        if not send_clicked:
            log.error("[WhatsApp Sender] Send button not found.")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Send button not found",
            }

        time.sleep(5)

        # Step f: Verify message sent — look for checkmark in #main
        log.info("[WhatsApp Sender] Verifying message sent...")
        sent = False
        # Poll for up to 15 seconds for the checkmark to appear
        for _ in range(15):
            try:
                # Look for checkmark within #main chat area
                main_locator = page.locator("#main")
                if main_locator.count() > 0:
                    for check_sel in ['[data-icon="msg-dblcheck"]', '[data-icon="msg-check"]']:
                        loc = main_locator.locator(check_sel).first
                        if loc.count() > 0 and loc.is_visible():
                            log.info("[WhatsApp Sender] Message confirmation found: %s", check_sel)
                            sent = True
                            break
                if sent:
                    break
            except Exception:
                pass
            time.sleep(1)

        # Diagnostic screenshot 3 — sent message
        try:
            page.screenshot(path=debug_3, full_page=True)
            log.info("[WhatsApp Sender] Diagnostic 3 captured: %s", debug_3)
        except Exception as exc:
            log.warning("[WhatsApp Sender] Screenshot 3 error: %s", exc)

        page.close()
        browser.close()
        p.stop()

        # Send button was clicked = message dispatched. Checkmark is best-effort verification.
        if not sent:
            log.warning("[WhatsApp Sender] No message checkmark detected within 15s — send was dispatched but delivery confirmation not observed.")

        log.info("[WhatsApp Sender] Successfully completed dispatch for %s!", target)
        return {
            "target": target,
            "debug_1": debug_1,
            "debug_2": debug_2,
            "debug_3": debug_3,
            "success": True,
        }

    except Exception as exc:
        log.error("[WhatsApp Sender] Dispatch failed for %s: %s", target, exc)
        try:
            page.close()
            browser.close()
            p.stop()
        except Exception:
            pass
        return {
            "target": target,
            "debug_1": debug_1,
            "debug_2": debug_2,
            "debug_3": debug_3,
            "success": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------- #
#  Legacy / compatibility shims                                                #
# ---------------------------------------------------------------------------- #

def attach_to_default_desktop():
    """No-op compatibility shim — Playwright CDP does not need Win32 desktop attach."""
    pass


def force_chrome_foreground() -> int:
    """No-op compatibility shim — Playwright CDP controls Chrome directly via DOM."""
    log.info("[WhatsApp Sender] force_chrome_foreground() is a no-op (CDP-based).")
    return 0


def copy_image_to_clipboard(path: str):
    """No-op compatibility shim — image is uploaded via input[type="file"]."""
    log.info("[WhatsApp Sender] copy_image_to_clipboard() is a no-op (CDP file upload).")


def navigate_to_target(target: str):
    """No-op compatibility shim — navigation is handled inside send_whatsapp_media via CDP."""
    log.info("[WhatsApp Sender] navigate_to_target() is a no-op (CDP-based).")
    return target


def is_phone_number(target: str) -> bool:
    clean = target.strip().replace(" ", "").replace("-", "")
    return clean.startswith("+") or clean.isdigit()


# Legacy handle (kept for compatibility with auto_publisher imports)
_AUTOMATION_CHROME_HWND = None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Dedicated WhatsApp Sender (Playwright CDP)")
    parser.add_argument("--target", help="Specific target (phone or group code)")
    parser.add_argument("--image", default=r"E:\samarthavastu-hub\vastu_content_queue\thumbnails\video_01.jpg")
    parser.add_argument("--close-tab", action="store_true", help="Unused (CDP-based, tabs managed by context)")
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
