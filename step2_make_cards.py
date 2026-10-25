"""
step2_make_cards.py
-------------------
For each video in public/videos.json:
  1. Download the YouTube thumbnail (maxresdefault → hqdefault fallback).
  2. Place it letter-boxed (never cropped) inside a 1080x1080 dark maroon & gold canvas.
  3. Add "Samartha Vastu" header and "Watch Full Video on YouTube & Website" footer.
  4. Save as public/ig_cards/<video_id>.jpg
"""

import json
import os
import io
import sys
import textwrap

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ─── Config ──────────────────────────────────────────────────────────────────
VIDEOS_JSON   = os.path.join("public", "videos.json")
OUTPUT_DIR    = os.path.join("public", "ig_cards")
CANVAS_SIZE   = 1080
BG_COLOR      = (28, 8, 8)          # Dark maroon
ACCENT_COLOR  = (212, 160, 23)      # Gold
ACCENT_LIGHT  = (255, 213, 79)      # Bright gold
TEXT_WHITE    = (255, 245, 220)     # Warm white
OVERLAY_COLOR = (15, 3, 3, 200)     # Semi-transparent dark overlay
BORDER_COLOR  = (180, 120, 10)      # Deep gold border

# ─── Font helpers ─────────────────────────────────────────────────────────────
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try common system fonts, fall back to default."""
    candidates = []
    if bold:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "C:/Windows/Fonts/trebucbd.ttf",
            "C:/Windows/Fonts/georgiab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/trebuc.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ─── Download thumbnail ───────────────────────────────────────────────────────
def download_thumbnail(video_id: str, thumb_url: str) -> Image.Image | None:
    """Try maxresdefault → hqdefault → provided URL."""
    urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        thumb_url,
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        if not url:
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 5000:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                print(f"    Downloaded thumbnail ({img.size[0]}x{img.size[1]}) from {url}")
                return img
        except Exception as e:
            print(f"    Thumbnail attempt failed ({url}): {e}")
    return None


# ─── Draw gradient background ────────────────────────────────────────────────
def draw_gradient_bg(draw: ImageDraw.Draw, size: int):
    """Radial-ish gradient: dark maroon center → slightly lighter edges."""
    for y in range(size):
        t = y / size
        r = int(BG_COLOR[0] + (45 - BG_COLOR[0]) * t * 0.4)
        g = int(BG_COLOR[1] + (10 - BG_COLOR[1]) * t * 0.3)
        b = int(BG_COLOR[2] + (10 - BG_COLOR[2]) * t * 0.3)
        draw.line([(0, y), (size, y)], fill=(r, g, b))


# ─── Draw decorative corner ornaments ─────────────────────────────────────────
def draw_ornaments(draw: ImageDraw.Draw, size: int):
    """Gold corner lines."""
    m, l = 18, 60
    w = 3
    corners = [
        # top-left
        [(m, m), (m + l, m)], [(m, m), (m, m + l)],
        # top-right
        [(size - m, m), (size - m - l, m)], [(size - m, m), (size - m, m + l)],
        # bottom-left
        [(m, size - m), (m + l, size - m)], [(m, size - m), (m, size - m - l)],
        # bottom-right
        [(size - m, size - m), (size - m - l, size - m)],
        [(size - m, size - m), (size - m, size - m - l)],
    ]
    for line in corners:
        draw.line(line, fill=BORDER_COLOR, width=w)

    # thin full-perimeter border
    draw.rectangle([12, 12, size - 13, size - 13], outline=BORDER_COLOR, width=1)


# ─── Draw separator line ──────────────────────────────────────────────────────
def draw_separator(draw: ImageDraw.Draw, y: int, size: int):
    margin = 60
    draw.line([(margin, y), (size - margin, y)], fill=ACCENT_COLOR, width=1)
    # Small diamond in center
    cx = size // 2
    draw.polygon([(cx, y - 5), (cx + 5, y), (cx, y + 5), (cx - 5, y)], fill=ACCENT_COLOR)


# ─── Build one card ───────────────────────────────────────────────────────────
def build_card(video: dict, output_path: str):
    video_id  = video["video_id"]
    title     = video.get("title", "")
    thumb_url = video.get("thumbnail_url", "")

    print(f"  Building card for [{video_id}]")

    # Canvas
    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)
    draw_gradient_bg(draw, CANVAS_SIZE)

    # ── Header zone: 0–135 px ──────────────────────────────────────────────
    HEADER_H = 135
    # Gold horizontal bar at very top
    draw.rectangle([0, 0, CANVAS_SIZE, 4], fill=ACCENT_COLOR)

    # Header background (slightly lighter)
    header_overlay = Image.new("RGBA", (CANVAS_SIZE, HEADER_H), (40, 5, 5, 230))
    canvas.paste(Image.new("RGB", (CANVAS_SIZE, HEADER_H), (40, 5, 5)),
                 (0, 0), header_overlay)

    # Channel name (Dual-Title branding)
    font_channel = load_font(42, bold=True)
    ch_text = "SAMARTHA ASTRO-VASTU"
    bbox = draw.textbbox((0, 0), ch_text, font=font_channel)
    tw = bbox[2] - bbox[0]
    draw.text(((CANVAS_SIZE - tw) // 2, 18), ch_text, font=font_channel, fill=ACCENT_LIGHT)

    # Subtitle with Authority pillars & handle
    font_sub = load_font(21)
    sub_text = "వాస్తు • జ్యోతిష్య • తాంత్రిక • ఆధ్యాత్మిక విజ్ఞాన పీఠం (@samarthavastu999)"
    bbox2 = draw.textbbox((0, 0), sub_text, font=font_sub)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((CANVAS_SIZE - tw2) // 2, 78), sub_text, font=font_sub, fill=(240, 190, 80))

    draw_separator(draw, HEADER_H - 4, CANVAS_SIZE)

    # ── Footer zone: 945–1080 px ────────────────────────────────────────────
    FOOTER_Y  = 945
    FOOTER_H  = CANVAS_SIZE - FOOTER_Y

    footer_overlay = Image.new("RGBA", (CANVAS_SIZE, FOOTER_H), (40, 5, 5, 230))
    canvas.paste(Image.new("RGB", (CANVAS_SIZE, FOOTER_H), (40, 5, 5)),
                 (0, FOOTER_Y), footer_overlay)
    draw_separator(draw, FOOTER_Y + 4, CANVAS_SIZE)

    # Footer text
    font_footer = load_font(26, bold=True)
    ft_text = "Watch Full Video on YouTube & Official Website"
    bbox3 = draw.textbbox((0, 0), ft_text, font=font_footer)
    tw3 = bbox3[2] - bbox3[0]
    draw.text(((CANVAS_SIZE - tw3) // 2, FOOTER_Y + 18), ft_text,
              font=font_footer, fill=ACCENT_LIGHT)

    # URL hint
    font_url = load_font(20)
    url_text = "https://samartha-astro-vastu.netlify.app | @samarthavastu999"
    bbox4 = draw.textbbox((0, 0), url_text, font=font_url)
    tw4 = bbox4[2] - bbox4[0]
    draw.text(((CANVAS_SIZE - tw4) // 2, FOOTER_Y + 52), url_text,
              font=font_url, fill=(212, 160, 23))

    # Gold bottom bar
    draw.rectangle([0, CANVAS_SIZE - 4, CANVAS_SIZE, CANVAS_SIZE], fill=ACCENT_COLOR)

    # ── Thumbnail zone: 135–945 px (810 px tall, 1080 px wide) ────────────
    THUMB_ZONE_Y = HEADER_H
    THUMB_ZONE_H = FOOTER_Y - HEADER_H   # = 810
    THUMB_ZONE_W = CANVAS_SIZE            # = 1080

    thumb = download_thumbnail(video_id, thumb_url)

    if thumb:
        # Letterbox: fit 16:9 inside THUMB_ZONE_W x THUMB_ZONE_H
        tw_img, th_img = thumb.size
        scale = min(THUMB_ZONE_W / tw_img, THUMB_ZONE_H / th_img)
        new_w = int(tw_img * scale)
        new_h = int(th_img * scale)
        thumb_resized = thumb.resize((new_w, new_h), Image.LANCZOS)

        # Center inside the thumb zone
        x_off = (THUMB_ZONE_W - new_w) // 2
        y_off = THUMB_ZONE_Y + (THUMB_ZONE_H - new_h) // 2
        canvas.paste(thumb_resized, (x_off, y_off))

        # Subtle dark vignette on sides
        if new_w < THUMB_ZONE_W:
            for side_x, side_w in [(0, x_off), (x_off + new_w, THUMB_ZONE_W - x_off - new_w)]:
                if side_w > 0:
                    side = Image.new("RGB", (side_w, THUMB_ZONE_H), (28, 8, 8))
                    canvas.paste(side, (side_x, THUMB_ZONE_Y))
    else:
        # Fallback placeholder
        draw.rectangle([0, THUMB_ZONE_Y, CANVAS_SIZE, FOOTER_Y], fill=(35, 10, 10))
        font_ph = load_font(36, bold=True)
        ph = "🎬 Thumbnail Unavailable"
        bbox_ph = draw.textbbox((0, 0), ph, font=font_ph)
        draw.text(((CANVAS_SIZE - (bbox_ph[2]-bbox_ph[0])) // 2,
                   THUMB_ZONE_Y + THUMB_ZONE_H // 2 - 20), ph,
                  font=font_ph, fill=(120, 80, 20))

    # ── Video title overlay (bottom of image area) ─────────────────────────
    title_zone_y = FOOTER_Y - 95
    title_bg = Image.new("RGBA", (CANVAS_SIZE, 88), (10, 2, 2, 185))
    canvas.paste(Image.new("RGB", (CANVAS_SIZE, 88), (10, 2, 2)),
                 (0, title_zone_y),
                 title_bg)

    font_title = load_font(26, bold=True)
    # Wrap long titles
    max_chars = 52
    wrapped = textwrap.wrap(title, width=max_chars)[:2]
    for li, line in enumerate(wrapped):
        bbox_t = draw.textbbox((0, 0), line, font=font_title)
        tw_t = bbox_t[2] - bbox_t[0]
        draw.text(((CANVAS_SIZE - tw_t) // 2, title_zone_y + 8 + li * 36),
                  line, font=font_title, fill=TEXT_WHITE)

    # ── Corner ornaments on top of everything ──────────────────────────────
    draw_ornaments(draw, CANVAS_SIZE)

    # ── Save ────────────────────────────────────────────────────────────────
    canvas.save(output_path, "JPEG", quality=95, optimize=True)
    print(f"    Saved → {output_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(VIDEOS_JSON, encoding="utf-8") as f:
        videos = json.load(f)

    print(f"\nGenerating {len(videos)} Instagram square cards (1080x1080) …\n")
    for video in videos:
        vid = video["video_id"]
        out = os.path.join(OUTPUT_DIR, f"{vid}.jpg")
        build_card(video, out)

    print(f"\nDone! Cards saved to: {OUTPUT_DIR}")
    print("Open public/ig_cards/ to inspect the images.")


if __name__ == "__main__":
    main()
