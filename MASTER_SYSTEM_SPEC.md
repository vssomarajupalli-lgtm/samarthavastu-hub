# Samartha Vastu Automation Hub — Master System Specification

**Workspace Path:** `E:\samarthavastu-hub`  
**GitHub Repository:** `https://github.com/vssomarajupalli-lgtm/samarthavastu-hub` (`main` branch)  
**Location:** Menakuru, Andhra Pradesh, India  
**Brand:** Samartha Vastu / Samartha Astro-Vastu (`సమర్థ వాస్తు`)  
**Principal Consultant:** SVSN Raju (`SVSN రాజు`, MA Astrology & Vastu Shastra)  
**YouTube Channel:** `@samarthavastu999` (Channel ID: `UCDtcb0drjmLgG3ARTh4e7jw`)  
**Consultation & Admin WhatsApp:** `+91 8919395559`  
**Public WhatsApp Group Invite Code:** `DvPDx43oel4LQQgqCsn7Tr`

---

## 1. Purpose of This Document

This file is the authoritative architectural specification and operational contract for `E:\samarthavastu-hub`. Any AI coding assistant or autonomous agent working inside this repository **must** read this document before modifying any script, selector, schedule file, or Windows task.

Every design choice in this repository exists to solve real-world browser, font-shaping, scheduling, and DOM reliability challenges encountered in production. **Do not regress or bypass the guardrails documented in Section 5.**

---

## 2. System Architecture & Environment

### 2.1 Location
Menakuru, Andhra Pradesh, India.

### 2.2 Core Stack
- **Language:** Python 3 automation scripts.
- **Browser Automation:** Playwright CDP connected to an isolated Chrome profile (`chrome_whatsapp_profile`) on port `9222` (`http://127.0.0.1:9222`).
- **Scheduling:** Windows Task Scheduler (`SamarthaVastu_Daily_8AM`).
- **Hosting:** Netlify / GitHub Pages via `origin main` (PWA deployment from `public/`).

### 2.3 Task Scheduler Schedule (`SamarthaVastu_Daily_8AM`)
Configured via `register_task.ps1` / `register_task.bat` (requires Administrator elevation):
- **Daily trigger** starting strictly at **06:00 AM**, repeating every **1 hour** for a duration of **15 hours** (last execution check at **21:00 / 9:00 PM**).
- **Never fires at 12:00 AM midnight** (a 16-hour repetition starting at 08:00 AM was historically corrected to 15 hours starting at 06:00 AM).
- **Logon trigger** for the current user with a 45-second delay.
- **Power settings:** `AllowStartIfOnBatteries = true`, `DontStopIfGoingOnBatteries = true`, `StartWhenAvailable = true`.

---

## 3. Time-Guard & Active Hours Logic (`auto_publisher.py`)

### 3.1 Active Hours Window
For all non-manual runs (`not MANUAL_RUN`):
- **Pre-wait check:** Immediately on script start, if `now.hour < 6 or now.hour >= 21`, log `[Time Guard]` and `sys.exit(0)` silently before sleeping.
- **Stabilization delay:** After desktop unlock, wait **300 seconds (5 minutes)** for network and desktop stabilization.
- **Post-wait check:** Re-check `now.hour < 6 or now.hour >= 21` right before showing the confirmation popup. If time crossed `21:00` during the 5-minute wait, exit silently with zero popup.

### 3.2 Execution Constraints
- Local execution is strictly between **06:00 AM and 09:00 PM** (`6 <= now.hour < 21`).
- Silent immediate exit if launched outside active hours — zero popups, zero posts.
- If the laptop is never powered on during the `06:00`–`21:00` window on a given day, that day is skipped cleanly.

### 3.3 Human-in-the-Loop Confirmation
- After stabilization within active hours, present a **Yes / No** confirmation dialog displaying today's scheduled Telugu title.
- Clicking **Yes** runs the pipeline; clicking **No** snoozes automatic prompts for the remainder of that calendar day without hourly nagging.

### 3.4 Manual Bypass
- `Publish_Now.bat` runs `python auto_publisher.py --manual`, which completely bypasses the active-hours gate and the 5-minute stabilization wait whenever explicitly invoked by the user.

### 3.5 Stage B Idempotency (`preview_sent_date`, `separator_sent_date`)
- `run_stage_b_prepare_tomorrow()` checks `preview_sent_date` on the `preview_approved` item before any WhatsApp Web navigation.
- If `preview_sent_date == today_str`, Stage B exits immediately with **ZERO WhatsApp Web navigation** and **ZERO duplicate messages** — preventing repeated hourly Task Scheduler triggers from re-sending the separator + poster.
- **Separator anti-spam:** `separator_sent_date` is tracked separately. The separator text `"📋 రేపటి వీడియో ప్రివ్యూ (Tomorrow's Scheduled Preview)"` is sent at most once per day. If `separator_sent_date == today_str`, the separator is skipped on retries (only the poster is retried if it previously failed).
- After a successful Stage B send (separator + poster both dispatched), both `preview_sent_date` and `separator_sent_date` are set to `today_str` and `master_schedule.json` is atomically saved via `save_schedule()`.
- If the poster send fails, `preview_sent_date` remains unset so the next hourly run retries the poster (without re-sending the separator).
- `main()` also checks `preview_sent_date` before calling Stage B for both `--prepare-tomorrow` and `--daily-run` modes, skipping Stage B entirely if already sent today.

---

## 4. Media & Poster Standards

### 4.1 Branded Posters (`1080x1350` — 4:5 Portrait)
- **Generator:** `html_poster_generator.py` via Headless Chrome HTML/CSS (never PIL text drawing, which breaks Telugu vowel/conjunct ligatures).
- **Source Thumbnail Resolution Cascade:** `maxresdefault.jpg` → `sddefault.jpg` → `hqdefault.jpg`.
- **Theme:** Royal dark maroon & gold ornamental border, Samartha Astro-Vastu header, sharp 16:9 video artwork, bold Telugu headline (`Noto Sans Telugu`), SVSN Raju (`MA Astrology & Vastu Shastra`) credentials, consultation phone `+91 8919395559`, and QR code.
- **Hard Dimension Gate:** `ensure_poster_exists()` in `auto_publisher.py` verifies `width == 1080 and height == 1350`. Any missing or legacy `480x360` image is automatically regenerated via Headless Chrome before publishing.

### 4.2 YouTube Shorts Video (`1080x1920` — 9:16 Vertical)
- **Generator:** `youtube_shorts_uploader.py` via Headless Chrome HTML/CSS rendered to PNG + FFmpeg MP4 encode (`logs/temp_short.mp4`).
- **Font Shaping:** HarfBuzz via Headless Chrome (`Noto Sans Telugu`) — Telugu typography is never rendered with Pillow.
- **UI Safe-Zone Compliance:**
  - **Top Clear Zone (`y = 0..180`):** Kept free of critical text so YouTube's Pause, Mute, and Menu icons never overlap content.
  - **Header (`y = 200..360`):** Gold `సమర్థ వాస్తు` title and `SAMARTHA ASTRO-VASTU` subtitle.
  - **Center Hero (`y = 390..960`):** `980px`-wide centered 16:9 thumbnail (`object-fit: cover`) inside a rounded gold border with shadow.
  - **Middle Headline Card (`y = 990..1360`):** Centered Telugu video title + SVSN Raju (`MA Astrology & Vastu Shastra`) badge.
  - **Safe CTA Banner (`y = 1390..1600`):** Telugu watch callout + `WhatsApp: +91 8919395559` positioned clear of YouTube's bottom `280px` channel/title overlay.
- **Hard Dimension Gate:** Rendered PNG is verified to be strictly `1080x1920` prior to FFmpeg encoding; otherwise the upload aborts.

---

## 5. Platform-Specific Automation & Bug Fixes

### 5.1 YouTube Shorts (`youtube_shorts_uploader.py`)
- Connects to `http://127.0.0.1:9222` (`browser.contexts[0]`) and opens a dedicated tab via Playwright CDP.
- **Duplicate Prevention:** Checks YouTube Studio Shorts list (`https://studio.youtube.com/channel/UCDtcb0drjmLgG3ARTh4e7jw/videos/short`) for an existing `Draft` or `Private` row matching today's title before initiating a fresh upload.
- **Title Injection & Assertion (Lexical Editor):** YouTube Studio's title/description fields use the Lexical rich-text editor, which ignores `page.keyboard.insert_text()` and `page.keyboard.type()`. Text is inserted via `page.evaluate()` running `document.execCommand('selectAll', false, null)` + `document.execCommand('insertText', false, <text>)`, followed by a wait for Lexical to render. YouTube auto-fills `"temp short"` from `temp_short.mp4`. The uploader focuses `#title-textarea #textbox`, executes `Control+A` + `Backspace`, inserts `<Telugu Title> #Shorts #SamarthaVastu` (`<= 100` chars) via `document.execCommand('insertText')`, blurs out, and loops (`while actual_title.strip() != short_title.strip()`) up to 5 retries to guarantee `"temp short"` never survives. **The assertion operator is `!=` (not equal), preventing infinite retry loops when the title is already correct.**
- **COPPA / "Not Made for Kids" Hard Assertion:** On the Details step, explicitly scroll the upload modal's inner scroll container so `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]` (fallback `tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]`) is visible (`scroll_into_view_if_needed()`). Click `#radioContainer` inside that radio button (fallback: click element / JS `.click()`), wait 500ms, and **strictly assert** `aria-checked="true"` (retry up to 5 times). If the radio cannot be checked after 5 retries, abort the upload.
- **Robust `#next-button` Progression (Details → Video elements → Checks → Visibility):** Do NOT hang waiting for `"Checks complete"` footer text if `"Video processing is taking longer than expected"` is shown — YouTube allows clicking `#next-button` all the way to Visibility and publishing Public while HD/processing finishes in the background! On each step, scroll the modal footer into view so `#next-button` is not intercepted by the backdrop, ensure `#next-button` is visible and enabled (`disabled` and `aria-disabled` both falsy), click `#next-button` (Playwright `.click()` with DOM `.click()` fallback if intercepted), and assert the stepper actually advanced until `tp-yt-paper-radio-button[name="PUBLIC"]` is visible.
- **Visibility Step:** Scrolls `PUBLIC` radio into view, clicks `tp-yt-paper-radio-button[name="PUBLIC"] #radioContainer` (with outer fallback), asserts `checked` / `aria-checked="true"`, and asserts `#done-button` displays `"Publish"` (not `"Save"`). Clicks `#done-button`, handles optional `"Publish anyway"` secondary dialog if processing is still running, waits up to `45s` for the post-publish share dialog, and verifies HTTP 200 on `https://www.youtube.com/shorts/<11-char-id>`.
- **Fake URL Blacklist:** The placeholder/fallback ID `gg3nNP0kueg` is explicitly rejected. On upload failure, no fake/fallback URL is assigned — `short_url` remains empty and `success` is `False`.

### 5.2 WhatsApp Web (`whatsapp_sender.py`)
- Connects via `connect_over_cdp("http://127.0.0.1:9222")` using the isolated profile; waits for `#pane-side`.
- Opens target chats cleanly via DOM (`918919395559` for Personal Admin; group invite/sidebar match for Public Group `DvPDx43oel4LQQgqCsn7Tr`), confirming `#main footer` is mounted before interacting.
- **Image + Caption Delivery:** Uploads `.jpg` via `input[type="file"][accept*="image"]`, locates the media-preview caption input and inserts full Telugu caption.
- **Live Caption Selector (verified 2026-11-04, port 9222):** WhatsApp Web has ONLY ONE `contenteditable` element on the page — the main footer input (`#main footer div[contenteditable="true"][data-testid="conversation-compose-box-input"]`). WhatsApp Web reuses this same element for media-preview caption input when the image preview modal is open. There is NO separate `data-testid="media-caption"` contenteditable div.
- **Modal Backdrop Interception:** The media preview modal backdrop intercepts normal pointer events, so the caption input click must use `force=True`.
- **Lexical Editor:** WhatsApp Web's composer uses the Lexical rich-text editor, which ignores `page.keyboard.insert_text()` and `page.keyboard.type()`. Caption text is inserted via `page.evaluate()` running `document.execCommand('selectAll')` + `document.execCommand('insertText', false, <caption>)`, followed by a 1.5s wait for Lexical to render. Caption retention is verified via `innerText` length >= 20 characters before clicking Send.
- Returns `False` on any failure — never logs false `[OK]`.
- **Vertical Stacking Separator (`send_whatsapp_text`):** Sends `"📋 రేపటి వీడియో ప్రివ్యూ (Tomorrow's Scheduled Preview)"` as a standalone text bubble before Stage B's preview image so WhatsApp always stacks posters full-width vertically for easy pinch-to-zoom on mobile. Injected in `auto_publisher.py` Stage B via `dispatch_whatsapp_text()` before the poster dispatch.
- **Return Contract (`dispatch_whatsapp_text`):** Always returns a `dict` `{"success": bool, "target": str, "tag": str, "error": str|None}` — never a raw `bool`. Callers must use `.get("success")` on the dict, not on a bool. This prevents `AttributeError: 'bool' object has no attribute 'get'` crashes on hourly Task Scheduler retries.

### 5.3 Meta Graph API (`meta_publisher.py`)
- Publishes `1080x1350` poster + Telugu caption to Facebook Page and Instagram Business account using credentials in `.env`.

---

## 6. Strict Code Guardrails (Enforced by Recent Audits)

### 6.1 Zero `pyautogui` / Zero Coordinate Clicks / Zero `Ctrl+L`
- All browser interactions must use Playwright CDP locators scoped to specific tabs on port `9222`.
- **Per commit `9c8276e`:** The legacy GUI fallback function `upload_short_via_gui()` (which contained `pyautogui`, `Ctrl+L` address-bar pasting, coordinate clicks such as `(1670, 268)`, and `win32gui`/`win32con` window hijacking) was permanently scrubbed from `youtube_shorts_uploader.py`.
- Never run `taskkill /im chrome.exe`. Only connect to or launch Chrome with `--remote-debugging-port=9222 --user-data-dir=E:\samarthavastu-hub\chrome_whatsapp_profile`.

### 6.2 Zero PIL / `ImageDraw` / `ImageFont` Telugu Rendering
- **Per commit `9c8276e`:** The legacy `get_telugu_font()` function and unused `ImageDraw`/`ImageFont` imports were removed from `youtube_shorts_uploader.py`.
- Telugu typography is rendered exclusively via Headless Chrome HarfBuzz HTML/CSS (`Noto Sans Telugu`) so complex Telugu conjuncts (`ఒత్తులు`, `గుణింతాలు`) shape accurately.

### 6.3 Atomic JSON Writes
- Always update `vastu_content_queue/master_schedule.json` via `save_schedule()` (write temp file + atomic replace) with UTF-8 encoding (`ensure_ascii=False`).

### 6.4 Truthfulness in Logs & Return Values
- Never return `True` or log `[OK]` unless post IDs, HTTP 200 Short URLs, or WhatsApp message checkmarks are verified in the live DOM/API response.
- `dispatch_whatsapp_text()` always returns a `dict` `{"success": bool, ...}` — never a raw `bool` — so callers can safely call `.get("success")` without `AttributeError`.

### 6.5 Git Cleanliness
- Keep `chrome_whatsapp_profile/` untracked.
- Keep `!public/thumbnails/**` tracked.
- Always `py_compile` modified Python files before committing and pushing to `origin main`.

---

## 7. Repository Architecture & Key Files

| File / Path | Role in Pipeline |
| :--- | :--- |
| `auto_publisher.py` | Master orchestrator: active-hours gate (`06:00`–`21:00`), 5-minute stabilization timer, Yes/No prompt, `ensure_poster_exists()` dimension check, Stage A & Stage B execution, atomic `save_schedule()`, Git push sync, `dispatch_whatsapp_text()` separator. |
| `vastu_content_queue/master_schedule.json` | Single source of truth for the content queue (`published` vs. pending items, Telugu titles, descriptions, source YouTube URLs, verified `yt_short_url`, Meta post IDs, and publish dates). |
| `html_poster_generator.py` | Renders crisp `1080x1350` (4:5 portrait) branded social posters via Headless Chrome HTML/CSS using `Noto Sans Telugu` (HarfBuzz complex script shaping). |
| `youtube_shorts_uploader.py` | Renders `1080x1920` (9:16) vertical frames via Headless Chrome HTML/CSS, encodes MP4s via FFmpeg, and automates YouTube Studio upload & `Public` publishing over Playwright CDP (`9222`). |
| `whatsapp_sender.py` | Pure Playwright CDP (`9222`) WhatsApp Web client supporting image + Telugu caption delivery and standalone plain-text messages (`send_whatsapp_text()`). |
| `meta_publisher.py` | Publishes `1080x1350` posters and Telugu captions to Facebook Page and Instagram Business via Meta Graph API tokens configured in `.env`. |
| `youtube_sync.py` | Syncs new videos from `@samarthavastu999`, fetches highest-resolution source thumbnails, validates/regenerates `1080x1350` posters, and populates `public/thumbnails/`. |
| `register_task.ps1` / `register_task.bat` | Registers/updates the Windows Scheduled Task `SamarthaVastu_Daily_8AM`. |
| `Publish_Now.bat` | One-click manual publisher (`python auto_publisher.py --manual`) bypassing time-window and startup-wait guards. |
| `vastu_content_queue/thumbnails/` | Local queue of validated `1080x1350` branded `.jpg` posters (`yt_<video_id>.jpg`). |
| `public/thumbnails/` | Public web thumbnails tracked in Git (`!public/thumbnails/**` in `.gitignore`) for the Samartha Vastu PWA. |
| `chrome_whatsapp_profile/` | Dedicated persistent Chrome user-data directory for WhatsApp Web & YouTube Studio sessions on port `9222` (untracked in Git). |
| `logs/` & `logs/screenshots/` | Execution logs (`daily_run.log`) and Playwright diagnostic screenshots. |

---

## 8. Quick Operational Reference

- **Normal Daily Operation:** Automatic between `06:00 AM` and `09:00 PM` (waits 5 minutes after unlock -> click **Yes** on prompt).
- **Manual Publish Anytime (Bypasses Time Gate):** Double-click `E:\samarthavastu-hub\Publish_Now.bat` (or run `python auto_publisher.py --manual`).
- **Update Windows Task Schedule (Requires Admin):** Right-click `E:\samarthavastu-hub\register_task.bat` -> **Run as administrator**.
- **Syntax Verification Before Commit:**
  ```powershell
  python -m py_compile auto_publisher.py youtube_shorts_uploader.py whatsapp_sender.py meta_publisher.py html_poster_generator.py youtube_sync.py
  ```
