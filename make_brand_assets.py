"""
make_brand_assets.py
--------------------
Generates high-fidelity brand assets for SAMARTHA ASTRO-VASTU (సమర్థ ఆస్ట్రో-వాస్తు):
  - public/favicon.svg
  - public/icon.svg
  - public/icon-192.png
  - public/icon-512.png
  - public/og-preview.png (1200x630 OpenGraph / WhatsApp preview card)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise RuntimeError("Chrome not found")


# ── 1. Create SVGs ──────────────────────────────────────────────────────────
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <radialGradient id="bg" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="#3a0b0b" />
      <stop offset="60%" stop-color="#180404" />
      <stop offset="100%" stop-color="#0a0101" />
    </radialGradient>
    <linearGradient id="gold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fff5cc" />
      <stop offset="35%" stop-color="#ffd54f" />
      <stop offset="70%" stop-color="#d4a017" />
      <stop offset="100%" stop-color="#8c5806" />
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Outer Rounded Shield -->
  <rect x="4" y="4" width="120" height="120" rx="30" fill="url(#bg)" stroke="url(#gold)" stroke-width="3.5" />
  
  <!-- Inner Sacred Halo & Rays -->
  <circle cx="64" cy="64" r="50" fill="none" stroke="url(#gold)" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.85" />
  <circle cx="64" cy="64" r="44" fill="none" stroke="url(#gold)" stroke-width="1" opacity="0.6" />

  <!-- 12-Ray Vedic Sun / Yantra Star -->
  <g stroke="url(#gold)" stroke-width="1.2" opacity="0.45">
    <line x1="64" y1="16" x2="64" y2="112" />
    <line x1="16" y1="64" x2="112" y2="64" />
    <line x1="30" y1="30" x2="98" y2="98" />
    <line x1="30" y1="98" x2="98" y2="30" />
  </g>

  <!-- Sacred OM Emblem in Center -->
  <g filter="url(#glow)">
    <circle cx="64" cy="64" r="32" fill="#1f0505" stroke="url(#gold)" stroke-width="2" />
    <text x="64" y="75" font-family="'Segoe UI Emoji', 'Noto Sans Telugu', 'Nirmala UI', serif" font-size="34" font-weight="900" fill="url(#gold)" text-anchor="middle">🕉</text>
  </g>
</svg>"""


def write_svg_icons():
    (PUBLIC_DIR / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    (PUBLIC_DIR / "icon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    print("Wrote favicon.svg and icon.svg")


# ── 2. Render PNG App Icons via PIL ──────────────────────────────────────────
def make_png_icons():
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
        im = Image.new("RGB", (size, size), (12, 2, 2))
        draw = ImageDraw.Draw(im)

        # Gradient background rings
        for r in range(size // 2, 0, -2):
            t = r / (size // 2)
            c = (int(14 + (40 - 14) * (1 - t)), int(3 + (10 - 3) * (1 - t)), int(3 + (10 - 3) * (1 - t)))
            draw.ellipse([size // 2 - r, size // 2 - r, size // 2 + r, size // 2 + r], fill=c)

        # Outer gold rounded border
        pad = int(size * 0.05)
        rad = int(size * 0.22)
        draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=rad, outline=(212, 160, 23), width=int(size * 0.035))

        # Inner ring
        ipad = int(size * 0.12)
        draw.ellipse([ipad, ipad, size - ipad, size - ipad], outline=(255, 213, 79), width=int(size * 0.015))

        # Text
        try:
            f_main = ImageFont.truetype("C:/Windows/Fonts/georgiab.ttf", int(size * 0.26))
            f_sub = ImageFont.truetype("C:/Windows/Fonts/calibrib.ttf", int(size * 0.08))
        except Exception:
            f_main = ImageFont.load_default()
            f_sub = ImageFont.load_default()

        # Center letters: SAV
        main_text = "SAV"
        bbox = draw.textbbox((0, 0), main_text, font=f_main)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((size - tw) // 2, (size - th) // 2 - int(size * 0.04)), main_text, font=f_main, fill=(255, 213, 79))

        # Bottom label
        sub_text = "SAMARTHA"
        sbbox = draw.textbbox((0, 0), sub_text, font=f_sub)
        stw = sbbox[2] - sbbox[0]
        draw.text(((size - stw) // 2, (size + th) // 2 + int(size * 0.02)), sub_text, font=f_sub, fill=(255, 245, 220))

        out_file = PUBLIC_DIR / name
        im.save(out_file, format="PNG")
        print(f"Generated {name} ({size}x{size})")


# ── 3. Render 1200x630 OpenGraph Banner via Headless Chrome ──────────────────
def render_og_banner():
    og_html = """<!DOCTYPE html>
<html lang="te">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700;800;900&family=Noto+Sans+Telugu:wght@600;700;800&family=Ramabhadra&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    width: 1200px;
    height: 630px;
    overflow: hidden;
    background: radial-gradient(circle at 50% 30%, #350b0b 0%, #170404 55%, #0c0202 100%);
    color: #fff5dc;
    font-family: 'Noto Sans Telugu', 'Segoe UI Emoji', sans-serif;
    padding: 24px;
    position: relative;
  }
  .outer-frame {
    width: 100%;
    height: 100%;
    border: 3.5px solid #d4a017;
    border-radius: 24px;
    padding: 16px;
    box-shadow: inset 0 0 50px rgba(0,0,0,0.8), 0 0 40px rgba(212, 160, 23, 0.4);
    position: relative;
  }
  .inner-frame {
    width: 100%;
    height: 100%;
    border: 1.5px solid rgba(255, 213, 79, 0.5);
    border-radius: 16px;
    padding: 30px 40px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    align-items: center;
    background: rgba(18, 4, 4, 0.5);
    position: relative;
  }
  /* Corner accents */
  .c { position: absolute; width: 32px; height: 32px; border-color: #ffd54f; border-style: solid; pointer-events: none; }
  .c-tl { top: 8px; left: 8px; border-width: 4px 0 0 4px; }
  .c-tr { top: 8px; right: 8px; border-width: 4px 4px 0 0; }
  .c-bl { bottom: 8px; left: 8px; border-width: 0 0 4px 4px; }
  .c-br { bottom: 8px; right: 8px; border-width: 0 4px 4px 0; }

  .badge {
    background: rgba(212, 160, 23, 0.15);
    border: 1px solid rgba(212, 160, 23, 0.5);
    padding: 6px 18px;
    border-radius: 9999px;
    font-size: 15px;
    font-weight: 700;
    color: #ffd54f;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .title-group {
    text-align: center;
    margin: 8px 0;
  }
  .title-en {
    font-family: 'Cinzel', serif;
    font-size: 58px;
    font-weight: 900;
    letter-spacing: 2px;
    background: linear-gradient(180deg, #fff9ea 0%, #ffd54f 45%, #d4a017 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 4px 20px rgba(212, 160, 23, 0.35);
    line-height: 1.1;
  }
  .title-te {
    font-family: 'Ramabhadra', 'Noto Sans Telugu', sans-serif;
    font-size: 38px;
    font-weight: 800;
    color: #ffe082;
    margin-top: 4px;
    line-height: 1.2;
  }

  .subtitle {
    font-size: 21px;
    font-weight: 700;
    color: #fff5dc;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-top: 8px;
  }
  .bullet { color: #ffd54f; font-weight: 900; }
  .handle {
    background: #4a0d0d;
    border: 1px solid #d4a017;
    color: #ffd54f;
    padding: 2px 10px;
    border-radius: 9999px;
    font-family: monospace;
    font-size: 17px;
    font-weight: bold;
    margin-left: 6px;
  }

  .pillars {
    display: flex;
    gap: 16px;
    justify-content: center;
    width: 100%;
    margin-top: 8px;
  }
  .pillar-card {
    background: rgba(30, 8, 8, 0.7);
    border: 1px solid rgba(212, 160, 23, 0.4);
    border-radius: 12px;
    padding: 10px 16px;
    text-align: center;
    font-size: 14px;
    font-weight: 600;
    color: #ffeab0;
    flex: 1;
    max-width: 250px;
  }
  .pillar-card span { font-size: 18px; display: block; margin-bottom: 2px; }

  .footer-bar {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 12px;
    border-top: 1px solid rgba(212, 160, 23, 0.3);
    font-size: 15px;
    color: #ffd54f;
    font-weight: 600;
  }
  .portal-url {
    font-family: monospace;
    font-weight: 700;
    color: #ffffff;
    background: rgba(212, 160, 23, 0.2);
    padding: 4px 12px;
    border-radius: 6px;
    border: 1px solid rgba(212, 160, 23, 0.4);
  }
</style>
</head>
<body>
<div class="outer-frame">
  <div class="inner-frame">
    <div class="c c-tl"></div><div class="c c-tr"></div>
    <div class="c c-bl"></div><div class="c c-br"></div>

    <div class="badge">
      <span>✨</span>
      <span>SVSN రాజు (MA Astrology &amp; Vastu Shastra) — హైదరాబాద్</span>
      <span>✨</span>
    </div>

    <div class="title-group">
      <div class="title-en">SAMARTHA ASTRO-VASTU</div>
      <div class="title-te">(సమర్థ ఆస్ట్రో-వాస్తు)</div>
      <div class="subtitle">
        <span>వాస్తు</span>
        <span class="bullet">•</span>
        <span>జ్యోతిష్య</span>
        <span class="bullet">•</span>
        <span>తాంత్రిక</span>
        <span class="bullet">•</span>
        <span>ఆధ్యాత్మిక విజ్ఞాన పీఠం</span>
        <span class="handle">@samarthavastu999</span>
      </div>
    </div>

    <div class="pillars">
      <div class="pillar-card">
        <span>🌐</span>
        Google Earth Pro విశ్లేషణ
      </div>
      <div class="pillar-card">
        <span>🛠️</span>
        కూల్చివేతలు లేని పరిష్కారాలు
      </div>
      <div class="pillar-card">
        <span>📚</span>
        16 ప్రాచీన శాస్త్ర గ్రంథాలయం
      </div>
      <div class="pillar-card">
        <span>💻</span>
        ఆన్‌లైన్ గ్లోబల్ సేవలు
      </div>
    </div>

    <div class="footer-bar">
      <div>📞 +91 8919395559 &nbsp;|&nbsp; samarthavastu999@gmail.com</div>
      <div class="portal-url">https://samartha-astro-vastu.netlify.app</div>
    </div>
  </div>
</div>
</body>
</html>"""

    chrome_bin = find_chrome()
    og_img_path = PUBLIC_DIR / "og-preview.png"
    tmp_html = PUBLIC_DIR / "og-temp.html"
    tmp_html.write_text(og_html, encoding="utf-8")

    user_data = tempfile.mkdtemp(prefix="chrome_og_")
    cmd = [
        chrome_bin,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={user_data}",
        f"--screenshot={str(og_img_path)}",
        "--window-size=1200,630",
        "--hide-scrollbars",
        f"file:///{tmp_html.as_posix()}",
    ]

    try:
        print("Rendering og-preview.png (1200x630) via Headless Chrome...")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            print("Chrome warning:", res.stderr)
        if og_img_path.exists():
            print(f"og-preview.png successfully created ({og_img_path.stat().st_size} bytes)")
    finally:
        if tmp_html.exists():
            tmp_html.unlink()


if __name__ == "__main__":
    write_svg_icons()
    make_png_icons()
    render_og_banner()
    print("All brand assets successfully generated!")
