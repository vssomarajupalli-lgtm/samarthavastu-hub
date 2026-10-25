"""
html_poster_generator.py
-------------------------
Headless Chrome 4:5 (1080x1350) Poster Generator for Samartha Vastu.

Solves the Pillow basic FreeType rendering limitations:
- 100% native HarfBuzz Indic text shaping for flawless Telugu conjuncts / ottulu
  (వాస్తు, జ్యోతిష్య, సంప్రదించండి, శాస్త్రీయ, వీడియో చూడండి).
- Full color emoji rendering (📞, ✉️, 📺, 💬, ✨) without hollow square boxes (□).
- Double gold ornamental borders with deep royal maroon gradient.
- Embedded high-res YouTube thumbnail and scannable QR code.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import qrcode
import requests
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("html_poster_generator")

BASE_DIR = Path(__file__).resolve().parent
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome_binary() -> str:
    for candidate in CHROME_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError("Google Chrome executable not found on the system.")


def generate_qr_base64(url: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=5,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def fetch_thumbnail_base64(video_id: str, fallback_url: str = "") -> str:
    urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/0.jpg",
    ]
    if fallback_url and fallback_url not in urls:
        urls.append(fallback_url)

    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                # Inspect image dimensions with PIL to reject YouTube's 120x90 placeholder
                img = Image.open(io.BytesIO(resp.content))
                if img.size == (120, 90) or img.size[0] < 200:
                    continue
                b64 = base64.b64encode(resp.content).decode()
                return f"data:image/jpeg;base64,{b64}"
        except Exception:
            continue

    # Fallback solid maroon image
    fb_img = Image.new("RGB", (1280, 720), (35, 8, 8))
    buf = io.BytesIO()
    fb_img.save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_poster_html(item: dict) -> str:
    video_id = item.get("video_id", "")
    title = (item.get("title") or "సమర్థ వాస్తు").strip()
    is_short = item.get("is_short", False)
    yt_url = f"https://www.youtube.com/shorts/{video_id}" if is_short else f"https://www.youtube.com/watch?v={video_id}"

    qr_b64 = generate_qr_base64(yt_url)
    thumb_b64 = fetch_thumbnail_base64(video_id, item.get("thumbnail_url", ""))

    title_len = len(title)
    if title_len > 125:
        title_font_size = "23px"
        title_line_height = "1.36"
        title_padding = "10px 24px"
        line_clamp = "4"
    elif title_len > 80:
        title_font_size = "28px"
        title_line_height = "1.42"
        title_padding = "14px 26px"
        line_clamp = "3"
    else:
        title_font_size = "34px"
        title_line_height = "1.48"
        title_padding = "18px 30px"
        line_clamp = "3"

    html = f"""<!DOCTYPE html>
<html lang="te">
<head>
<meta charset="utf-8">
<title>SAMARTHA ASTRO-VASTU Poster</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700;800;900&family=Noto+Sans+Telugu:wght@400;600;700;800;900&family=Ramabhadra&display=swap" rel="stylesheet">
<style>
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

body {{
    width: 1080px;
    height: 1350px;
    overflow: hidden;
    background: radial-gradient(circle at 50% 25%, #2a0808 0%, #150303 55%, #0a0101 100%);
    font-family: 'Noto Sans Telugu', 'Segoe UI Emoji', 'Nirmala UI', sans-serif;
    color: #fff5dc;
    position: relative;
    padding: 24px;
}}

/* Double Gold Borders */
.outer-frame {{
    width: 100%;
    height: 100%;
    border: 3px solid #d4a017;
    border-radius: 20px;
    padding: 14px;
    position: relative;
    background: transparent;
    box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.8), 0 0 30px rgba(212, 160, 23, 0.35);
}}

.inner-frame {{
    width: 100%;
    height: 100%;
    border: 1.5px solid rgba(255, 213, 79, 0.5);
    border-radius: 14px;
    padding: 24px 30px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    align-items: center;
    position: relative;
    background: rgba(18, 4, 4, 0.4);
}}

/* Corner Ornaments */
.corner {{
    position: absolute;
    width: 28px;
    height: 28px;
    border-color: #ffd54f;
    border-style: solid;
    pointer-events: none;
}}
.c-tl {{ top: 6px; left: 6px; border-width: 4px 0 0 4px; }}
.c-tr {{ top: 6px; right: 6px; border-width: 4px 4px 0 0; }}
.c-bl {{ bottom: 6px; left: 6px; border-width: 0 0 4px 4px; }}
.c-br {{ bottom: 6px; right: 6px; border-width: 0 4px 4px 0; }}

/* Header */
.header-box {{
    text-align: center;
    width: 100%;
}}

.header-top-bar {{
    height: 3px;
    width: 60%;
    margin: 0 auto 12px auto;
    background: linear-gradient(90deg, transparent, #ffd54f, transparent);
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
    margin-bottom: 2px;
    line-height: 1.15;
}}

.main-title-te {{
    font-family: 'Ramabhadra', 'Noto Sans Telugu', sans-serif;
    font-size: 28px;
    font-weight: 800;
    color: #ffe599;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
    line-height: 1.25;
}}

.sub-title {{
    font-size: 19px;
    font-weight: 700;
    color: #e6b840;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
}}

.divider-line {{
    display: flex;
    align-items: center;
    justify-content: center;
    width: 85%;
    margin: 0 auto;
}}
.divider-line::before, .divider-line::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(212, 160, 23, 0.6), transparent);
}}
.divider-diamond {{
    color: #ffd54f;
    font-size: 14px;
    margin: 0 14px;
}}

/* Center Thumbnail Frame */
.thumbnail-frame {{
    width: 960px;
    height: 540px;
    border-radius: 16px;
    border: 3px solid #d4a017;
    background: #000;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.85), 0 0 25px rgba(212, 160, 23, 0.3);
}}

.thumbnail-img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}}

/* Video Title Card */
.title-box {{
    width: 960px;
    min-height: 160px;
    max-height: 195px;
    background: linear-gradient(180deg, rgba(26, 6, 6, 0.92) 0%, rgba(14, 3, 3, 0.96) 100%);
    border: 1.5px solid rgba(212, 160, 23, 0.6);
    border-radius: 14px;
    padding: {title_padding};
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.75);
}}

.video-title {{
    font-size: {title_font_size};
    font-weight: 700;
    line-height: {title_line_height};
    color: #fff9ea;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: {line_clamp};
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.8);
}}

/* Footer Section */
.footer-box {{
    width: 960px;
    height: 200px;
    background: linear-gradient(180deg, rgba(24, 5, 5, 0.92) 0%, rgba(12, 2, 2, 0.98) 100%);
    border: 1.5px solid rgba(212, 160, 23, 0.55);
    border-radius: 14px;
    padding: 16px 28px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 12px 35px rgba(0, 0, 0, 0.85);
}}

.footer-left {{
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 8px;
    flex: 1;
}}

.contact-label {{
    font-size: 22px;
    font-weight: 700;
    color: #ffd54f;
    letter-spacing: 0.3px;
}}

.contact-details {{
    font-size: 20px;
    font-weight: 600;
    color: #ffffff;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.contact-wa {{
    font-size: 19.5px;
    font-weight: 600;
    color: #4ade80;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.brand-motto {{
    font-size: 18.5px;
    color: #e5cd9e;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
}}

.emoji {{
    font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif;
    font-style: normal;
    font-weight: normal;
    display: inline-block;
    vertical-align: middle;
}}

.footer-right {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-left: 20px;
}}

.qr-frame {{
    padding: 6px;
    background: #ffffff;
    border: 2px solid #d4a017;
    border-radius: 10px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.6);
    display: flex;
    align-items: center;
    justify-content: center;
}}

.qr-img {{
    width: 110px;
    height: 110px;
    display: block;
}}

.qr-caption {{
    font-size: 15px;
    font-weight: 700;
    color: #ffd54f;
    margin-top: 6px;
    text-align: center;
}}
</style>
</head>
<body>
<div class="outer-frame">
  <div class="inner-frame">
    <div class="corner c-tl"></div>
    <div class="corner c-tr"></div>
    <div class="corner c-bl"></div>
    <div class="corner c-br"></div>

    <!-- Header -->
    <div class="header-box">
      <div class="header-top-bar"></div>
      <h1 class="main-title">SAMARTHA ASTRO-VASTU</h1>
      <div class="main-title-te">(సమర్థ ఆస్ట్రో-వాస్తు)</div>
      <div class="sub-title">వాస్తు • జ్యోతిష్య • తాంత్రిక • ఆధ్యాత్మిక విజ్ఞాన పీఠం &nbsp;|&nbsp; @samarthavastu999</div>
      <div class="divider-line">
        <span class="divider-diamond">◆</span>
      </div>
    </div>

    <!-- Center Thumbnail Frame -->
    <div class="thumbnail-frame">
      <img src="{thumb_b64}" class="thumbnail-img" alt="YouTube Thumbnail">
    </div>

    <!-- Video Title -->
    <div class="title-box">
      <div class="video-title">{title}</div>
    </div>

    <!-- Footer -->
    <div class="footer-box">
      <div class="footer-left">
        <div class="contact-label">వాస్తు &amp; జ్యోతిష్య సలహాల కోసం సంప్రదించండి:</div>
        <div class="contact-details"><span class="emoji">📞</span> +91 8919395559 &nbsp;|&nbsp; <span class="emoji">&#x2709;&#xFE0F;</span> samarthavastu999@gmail.com</div>
        <div class="contact-wa"><span class="emoji">💬</span> WhatsApp: https://wa.me/918919395559 &nbsp;|&nbsp; <span class="emoji">🌐</span> https://samartha-astro-vastu.netlify.app</div>
        <div class="brand-motto"><span class="emoji">✨</span> SAMARTHA ASTRO-VASTU (సమర్థ ఆస్ట్రో-వాస్తు) — శాస్త్రీయ పరిష్కారాలు, సంపద, ఆరోగ్యం</div>
      </div>
      <div class="footer-right">
        <div class="qr-frame">
          <img src="{qr_b64}" class="qr-img" alt="Scan QR">
        </div>
        <div class="qr-caption">వీడియో చూడండి / Scan QR</div>
        <div class="qr-handle" style="font-size:12px;color:#ffd54f;font-weight:bold;margin-top:2px;">@samarthavastu999</div>
      </div>
    </div>

  </div>
</div>
</body>
</html>"""
    return html


def render_html_to_poster(item: dict, output_path: str | Path) -> str:
    """
    Renders high-fidelity 4:5 (1080x1350) poster using headless Google Chrome.
    Guarantees 100% native HarfBuzz Telugu font shaping and full-color emojis.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chrome_bin = find_chrome_binary()

    html_content = build_poster_html(item)

    temp_html = output_path.with_suffix(".tmp.html")
    temp_html.write_text(html_content, encoding="utf-8")

    user_data = tempfile.mkdtemp(prefix="chrome_poster_")

    cmd = [
        chrome_bin,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={user_data}",
        f"--screenshot={str(output_path)}",
        "--window-size=1080,1350",
        "--hide-scrollbars",
        f"file:///{temp_html.as_posix()}",
    ]

    try:
        log.info("Rendering 4:5 poster via Chrome Headless: %s", output_path.name)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            log.warning("Chrome returned non-zero %d: %s", res.returncode, res.stderr)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Screenshot output not created: {output_path}")

        log.info("Poster rendered successfully (%d bytes): %s", output_path.stat().st_size, output_path)
    finally:
        # Cleanup temporary html
        try:
            if temp_html.exists():
                temp_html.unlink()
        except Exception:
            pass

    return str(output_path)


if __name__ == "__main__":
    sample_item = {
        "video_id": "9g8YCXL0wPw",
        "title": "సైన్స్ కు కూడా అంతుచిక్కని ఈ పునర్జన్మ రహస్యానికి సజీవ సాక్ష్యమే ఆగ్రాకు చెందిన డాక్టర్ తోరన్ సింగ్",
        "thumbnail_url": "https://img.youtube.com/vi/9g8YCXL0wPw/maxresdefault.jpg",
    }
    out = BASE_DIR / "vastu_content_queue" / "thumbnails" / "yt_9g8YCXL0wPw.jpg"
    render_html_to_poster(sample_item, out)
    print("Rendered test poster:", out)
