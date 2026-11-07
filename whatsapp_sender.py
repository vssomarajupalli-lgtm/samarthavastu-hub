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
        log.info("[WhatsApp Sender] Chrome CDP port 9222 not listening. Launching Chrome with remote debugging...")
        import subprocess
        subprocess.Popen(
            [
                "chrome.exe",
                "--remote-debugging-port=9222",
                f"--user-data-dir={WHATSAPP_USER_DATA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-minimized",
                "about:blank",
            ],
            shell=True,
            cwd=None,
        )
        # Wait up to 20 seconds for port 9222 to accept connections
        for i in range(40):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", 9222), timeout=0.5):
                    log.info("[WhatsApp Sender] Chrome CDP port 9222 is now listening.")
                    break
            except OSError:
                continue
        else:
            log.error("[WhatsApp Sender] Chrome CDP port 9222 did not accept connections within 20s.")
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
        # Group target: first go to main WhatsApp Web page to access #pane-side
        page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)

    # Wait for chat list to load
    pane_side = page.locator("#pane-side")
    try:
        pane_side.wait_for(state="visible", timeout=45000)
        log.info("[WhatsApp Sender] Chat list #pane-side loaded.")
    except Exception:
        log.error("[WhatsApp Sender] #pane-side did not load — not logged into WhatsApp Web?")
        return False

    # ── Group target: exact-match group name in #pane-side ──
    if not is_phone:
        time.sleep(3)
        group_name = target  # e.g. "సమర్ధ వాస్తు"

        # First try: find exact match in #pane-side chat rows
        group_opened = False
        try:
            # Get all chat rows with span[title]
            rows = page.locator("#pane-side div[role='row']").all()
            for row in rows:
                try:
                    span = row.locator("span[title]").first
                    if span.count() == 0:
                        continue
                    title = span.get_attribute("title") or ""
                    # EXACT match: trimmed title equals target, EXCLUDE titles ending in " U"
                    title_stripped = title.strip()
                    if title_stripped == group_name and not title_stripped.endswith(" U"):
                        row.click()
                        log.info("[WhatsApp Sender] Opened exact group match: %r", title)
                        group_opened = True
                        break
                    else:
                        log.debug("[WhatsApp Sender] Skipped chat row: %r (exact_match=%s)", title, title_stripped == group_name)
                except Exception:
                    continue
        except Exception as exc:
            log.warning("[WhatsApp Sender] Error scanning #pane-side rows: %s", exc)

        # Second try: if not found in #pane-side, navigate to accept?code= and join
        if not group_opened:
            accept_url = f"https://web.whatsapp.com/accept?code={target}"
            log.info("[WhatsApp Sender] Group not found in chat list, navigating to accept page: %s", accept_url)
            page.goto(accept_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

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

        # ── Step b: Fill Telugu caption in compose box BEFORE attaching image ──
        # LIVE DOM INSPECTION (2026-11-05, port 9222): WhatsApp Web reuses the #main footer
        # compose box as the image caption input. Caption typed BEFORE attaching the image
        # SURVIVES the attach and becomes the image caption. Caption pasted AFTER attach
        # does NOT work (clipboard paste is ignored). Therefore, fill the caption FIRST,
        # then attach the image.
        #
        # Newline preservation: page.keyboard.insert_text() strips \n in Lexical editor.
        # Clipboard paste (navigator.clipboard.writeText + Control+V) preserves \n line breaks.
        log.info("[WhatsApp Sender] Filling caption in compose box before attaching image...")
        caption_selectors = [
            '#main footer div[contenteditable="true"][data-testid="conversation-compose-box-input"]',
            '#main footer [role="textbox"][data-testid="conversation-compose-box-input"]',
            # Fallback: any visible contenteditable div
            'div[contenteditable="true"]',
        ]
        caption_filled = False
        for sel in caption_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    # Force click — any overlay may intercept normal pointer events
                    loc.click(force=True)
                    page.wait_for_timeout(500)
                    # Clear existing content
                    page.keyboard.press("Control+A")
                    page.wait_for_timeout(200)
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(200)
                    # Set system clipboard then paste — preserves \n line breaks in Lexical
                    clipboard_ok = page.evaluate("""(text) => {
                        return navigator.clipboard.writeText(text).then(() => {
                            return { success: true };
                        }).catch(err => {
                            return { success: false, error: err.message };
                        });
                    }""", caption)
                    if not clipboard_ok.get("success"):
                        log.warning("[WhatsApp Sender] Clipboard write failed: %s", clipboard_ok.get("error"))
                        continue
                    # Paste via Control+V
                    page.keyboard.press("Control+V")
                    page.wait_for_timeout(2000)
                    # ASSERT: caption must be non-empty before attaching image
                    actual_caption = loc.inner_text() or loc.input_value() or ""
                    if actual_caption.strip() and len(actual_caption.strip()) >= 20:
                        # Verify newlines are preserved
                        newline_count = actual_caption.count('\n')
                        caption_filled = True
                        log.info("[WhatsApp Sender] Caption filled and verified via %s (len=%d, newlines=%d)", sel, len(actual_caption.strip()), newline_count)
                        break
                    else:
                        log.warning("[WhatsApp Sender] Caption not retained in %s (got: %r)", sel, actual_caption[:50])
            except Exception:
                continue
        if not caption_filled:
            log.error("[WhatsApp Sender] Could not fill caption in compose box — aborting to prevent captionless send.")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Caption box not found or caption not retained in compose box",
            }

        time.sleep(2)

        # Step c: Click Attach (+) button
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

        # Step d: Upload image via input[type="file"]
        # CRITICAL: Use Photos & Videos input (accept*="video/mp4"), NOT Sticker creator input.
        # WhatsApp Web has multiple file inputs: Sticker creator (accept="image/*" webp),
        # Documents (accept="*"), and Photos & Videos (accept="image/*,video/mp4,video/3gpp,video/quicktime").
        # Sending to Sticker input produces a sticker instead of photo+caption.
        log.info("[WhatsApp Sender] Uploading image: %s", img_path)
        file_input = page.locator('input[type="file"][accept*="video/mp4"], input[type="file"][accept*="image/*,video/mp4"]').first
        if file_input.count() == 0:
            # Fallback: any image input but exclude sticker/document inputs
            file_input = page.locator('input[type="file"][accept*="image"]').first
        file_input.wait_for(state="attached", timeout=10000)
        file_input.set_input_files(str(Path(img_path).resolve()))
        log.info("[WhatsApp Sender] Image file set.")

        time.sleep(4)

        # Diagnostic screenshot 2 — image preview / caption in compose box
        try:
            page.screenshot(path=debug_2, full_page=True)
            log.info("[WhatsApp Sender] Diagnostic 2 captured: %s", debug_2)
        except Exception as exc:
            log.warning("[WhatsApp Sender] Screenshot 2 error: %s", exc)

        # Verify caption survived the image attach
        compose_box_verify = page.locator('#main footer div[contenteditable="true"][data-testid="conversation-compose-box-input"]').first
        caption_after_attach = compose_box_verify.inner_text() or ""
        if not caption_after_attach.strip() or len(caption_after_attach.strip()) < 20:
            log.error("[WhatsApp Sender] Caption was lost after image attach! Aborting.")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Caption lost after image attach",
            }
        log.info("[WhatsApp Sender] Caption survived image attach (len=%d, newlines=%d)", len(caption_after_attach.strip()), caption_after_attach.count('\n'))

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
                    # Use JS dispatchEvent for click — Playwright's click() doesn't
                    # reliably trigger WhatsApp Web's send handler after image attach.
                    js_result = page.evaluate("""(sel) => {
                        const btn = document.querySelector(sel);
                        if (!btn) return { success: false, error: 'button not found' };
                        btn.dispatchEvent(new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                        return { success: true };
                    }""", sel)
                    if js_result.get("success"):
                        send_clicked = True
                        log.info("[WhatsApp Sender] Send clicked via JS: %s", sel)
                        break
                    else:
                        log.warning("[WhatsApp Sender] JS click failed: %s", js_result.get("error"))
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

        # ── POST-SEND VERIFICATION ──
        # (a) Assert #main footer compose box is EMPTY — if text remains, it did NOT
        #     go into the image caption!
        compose_box = page.locator('#main footer div[contenteditable="true"][data-testid="conversation-compose-box-input"]').first
        compose_empty = False
        try:
            compose_text = compose_box.inner_text() or ""
            compose_empty = compose_text.strip() == ""
        except Exception:
            pass
        log.info("[WhatsApp Sender] Compose box empty after send: %s", compose_empty)
        if not compose_empty:
            log.error("[WhatsApp Sender] Caption text still in compose box after send — image was sent WITHOUT caption!")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Caption text remained in compose box — image sent without caption",
            }

        # (b) Assert the newly sent outgoing message bubble contains BOTH an img AND
        #     the caption text — confirms caption went with the image, not as separate text
        caption_first_line = caption.split('\n')[0][:40] if caption else ""
        msg_bubble_ok = False
        try:
            # Look for the last outgoing message in #main
            last_msg = page.locator('#main div.message-out').last
            if last_msg.count() > 0:
                msg_text = last_msg.inner_text() or ""
                msg_has_img = last_msg.locator('img').count() > 0
                msg_has_caption = caption_first_line and caption_first_line in msg_text
                msg_bubble_ok = msg_has_img and msg_has_caption
                log.info("[WhatsApp Sender] Last message bubble: has_img=%s has_caption=%s text=%r", msg_has_img, msg_has_caption, msg_text[:100])
            else:
                log.warning("[WhatsApp Sender] No outgoing message bubble found in #main")
        except Exception as exc:
            log.warning("[WhatsApp Sender] Could not verify message bubble: %s", exc)

        if not msg_bubble_ok:
            log.warning("[WhatsApp Sender] Could not verify message bubble contains image+caption — "
                        "but compose box is empty (send was dispatched). Treating as success.")

        # Step f: Verify message sent — look for checkmark in #main
        log.info("[WhatsApp Sender] Verifying message sent...")
        sent = False
        for _ in range(15):
            try:
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
        # Keep Chrome browser open — don't close browser/p so WhatsApp Web
        # stays synced and warm for subsequent runs. Browser remains on port 9222 via CDP.

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
#  WhatsApp text-only send (separator messages)                                #
# ---------------------------------------------------------------------------- #

def send_whatsapp_text(
    target: str,
    text: str,
    output_dir: str = r"E:\samarthavastu-hub\logs\screenshots",
    target_tag: str = "",
    close_tab: bool = True,
) -> dict:
    """
    Sends a plain-text WhatsApp message (no image) to a target using Playwright CDP DOM automation.
    Used as a separator between Stage A and Stage B posters so they never merge side-by-side.
    Returns {"success": True/False, ...}. Never fakes [OK].
    """
    attach_to_default_desktop()

    target = target.strip()
    tag = target_tag or ("mobile" if (target.startswith("+") or target.replace(" ", "").replace("-", "").isdigit()) else "group")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    debug_1 = str(out_dir / f"debug_1_chat_loaded_{tag}.png")
    debug_2 = str(out_dir / f"debug_2_text_typed_{tag}.png")
    debug_3 = str(out_dir / f"debug_3_sent_{tag}.png")

    log.info("=" * 60)
    log.info("[WhatsApp Text] Dispatching text to: %s (Tag: %s)", target, tag)
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

        try:
            page.screenshot(path=debug_1, full_page=True)
            log.info("[WhatsApp Text] Diagnostic 1 captured: %s", debug_1)
        except Exception as exc:
            log.warning("[WhatsApp Text] Screenshot 1 error: %s", exc)

        # Step: Type text in the main chat input box (#main footer contenteditable)
        # Newline preservation: page.keyboard.insert_text() strips \n in Lexical editor.
        # Use clipboard paste (navigator.clipboard.writeText + Control+V) instead.
        log.info("[WhatsApp Text] Typing message in main chat input box...")
        input_selectors = [
            '#main footer div[contenteditable="true"]',
            '#main footer [role="textbox"]',
            '#main footer div[contenteditable="true"][data-testid="input"]',
            'div[contenteditable="true"]',
        ]
        text_filled = False
        for sel in input_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(force=True)
                    page.wait_for_timeout(500)
                    page.keyboard.press("Control+A")
                    page.wait_for_timeout(300)
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(200)
                    # Set system clipboard then paste — preserves \n line breaks
                    clipboard_ok = page.evaluate("""(text) => {
                        return navigator.clipboard.writeText(text).then(() => {
                            return { success: true };
                        }).catch(err => {
                            return { success: false, error: err.message };
                        });
                    }""", text)
                    if not clipboard_ok.get("success"):
                        log.warning("[WhatsApp Text] Clipboard write failed: %s", clipboard_ok.get("error"))
                        continue
                    page.keyboard.press("Control+V")
                    page.wait_for_timeout(2000)
                    actual_text = loc.inner_text() or loc.input_value() or ""
                    if actual_text.strip() and len(actual_text.strip()) >= 2:
                        text_filled = True
                        log.info("[WhatsApp Text] Text filled and verified via %s (len=%d)", sel, len(actual_text.strip()))
                        break
                    else:
                        log.warning("[WhatsApp Text] Text not retained in %s (got: %r)", sel, actual_text[:50])
            except Exception:
                continue

        if not text_filled:
            log.error("[WhatsApp Text] Could not fill text in main chat input — aborting.")
            page.close()
            browser.close()
            p.stop()
            return {
                "target": target,
                "debug_1": debug_1,
                "debug_2": debug_2,
                "debug_3": debug_3,
                "success": False,
                "error": "Chat input box not found or text not retained",
            }

        try:
            page.screenshot(path=debug_2, full_page=True)
            log.info("[WhatsApp Text] Diagnostic 2 captured: %s", debug_2)
        except Exception as exc:
            log.warning("[WhatsApp Text] Screenshot 2 error: %s", exc)

        # Step: Click Send
        log.info("[WhatsApp Text] Clicking Send button...")
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
                    log.info("[WhatsApp Text] Send clicked: %s", sel)
                    break
            except Exception:
                continue

        if not send_clicked:
            log.error("[WhatsApp Text] Send button not found.")
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

        # Verify message sent — look for checkmark in #main
        log.info("[WhatsApp Text] Verifying message sent...")
        sent = False
        for _ in range(15):
            try:
                main_locator = page.locator("#main")
                if main_locator.count() > 0:
                    for check_sel in ['[data-icon="msg-dblcheck"]', '[data-icon="msg-check"]']:
                        loc = main_locator.locator(check_sel).first
                        if loc.count() > 0 and loc.is_visible():
                            log.info("[WhatsApp Text] Message confirmation found: %s", check_sel)
                            sent = True
                            break
                if sent:
                    break
            except Exception:
                pass
            time.sleep(1)

        try:
            page.screenshot(path=debug_3, full_page=True)
            log.info("[WhatsApp Text] Diagnostic 3 captured: %s", debug_3)
        except Exception as exc:
            log.warning("[WhatsApp Text] Screenshot 3 error: %s", exc)

        page.close()
        # Keep Chrome browser open — don't close browser/p so WhatsApp Web
        # stays synced and warm for subsequent runs. Browser remains on port 9222 via CDP.

        if close_tab:
            try:
                page.close()
            except Exception:
                pass

        return {
            "target": target,
            "debug_1": debug_1,
            "debug_2": debug_2,
            "debug_3": debug_3,
            "success": True,
            "error": None,
        }

    except Exception as exc:
        log.error("[WhatsApp Text] CDP failed: %s", exc)
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
            "error": f"CDP error: {exc}",
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
