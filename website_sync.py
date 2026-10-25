"""
website_sync.py
---------------
Samartha Vastu - Dynamic Website Gallery Synchronizer

Reads vastu_content_queue/master_schedule.json and exports a rich,
categorized video feed to public/videos_data.json and public/videos.json,
and syncs public/index.html so all YouTube videos render dynamically.

Categories:
  - 'vastu'     : వాస్తు & జ్యోతిష్యం (Vastu & Astrology)
  - 'spiritual' : ఆధ్యాత్మికం (Spiritual & Paranormal)
  - 'shorts'    : షార్ట్స్ (Shorts)
  - 'all'       : అన్నీ (All)

Usage:
    python website_sync.py
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("website_sync")

BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"
PUBLIC_DIR      = BASE_DIR / "public"
OUTPUT_JSON     = PUBLIC_DIR / "videos_data.json"
LEGACY_JSON     = PUBLIC_DIR / "videos.json"
INDEX_HTML_FILE = PUBLIC_DIR / "index.html"

SPIRITUAL_KEYWORDS = [
    "ఆత్మ", "పునర్జన్మ", "దయ్యం", "భయం", "పారానార్మల్", "పరిశోధన", "రహస్యం", 
    "శివ", "విష్ణు", "దేవు", "దేవాలయం", "మంత్ర", "పూజ", "ఆధ్యాత్మిక", "గ్రహ", 
    "శని", "రాహు", "కేతు", "కాలసర్ప", "దోషం"
]

def clean_description(raw: str) -> str:
    clean = re.sub(r"#\S+", "", raw or "")
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()

def format_date_str(ud: str) -> str:
    """Converts 20261022 or ISO date to '22 Oct 2026'."""
    if not ud:
        return ""
    try:
        clean_d = ud.split("T")[0].replace("-", "")
        if len(clean_d) == 8 and clean_d.isdigit():
            dt = datetime.strptime(clean_d, "%Y%m%d")
            return dt.strftime("%d %b %Y")
    except Exception:
        pass
    return ud[:10]

def categorize_video(item: dict) -> tuple[str, str]:
    """Returns (category_slug, category_label)."""
    if item.get("is_short"):
        return "shorts", "షార్ట్స్"
    
    title = (item.get("title") or "").lower()
    desc = (item.get("description") or "").lower()
    text = f"{title} {desc}"
    
    for kw in SPIRITUAL_KEYWORDS:
        if kw in text:
            return "spiritual", "ఆధ్యాత్మికం"
            
    return "vastu", "వాస్తు & జ్యోతిష్యం"

def sync_website_data() -> dict:
    log.info("Starting website data synchronization from master_schedule.json...")
    
    if not SCHEDULE_FILE.exists():
        log.error("master_schedule.json not found at %s", SCHEDULE_FILE)
        return {"count": 0, "success": False}
        
    with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
        schedule = json.load(f)
        
    if not isinstance(schedule, list):
        schedule = schedule.get("items", [])
        
    processed_videos = []
    
    for item in schedule:
        vid = item.get("video_id")
        if not vid:
            continue
            
        title = (item.get("title") or "సమర్థ వాస్తు").strip()
        raw_desc = item.get("description") or item.get("caption") or ""
        clean_desc = clean_description(raw_desc)
        upload_date = item.get("upload_date") or ""
        formatted_date = format_date_str(upload_date)
        is_short = bool(item.get("is_short", False))
        status = item.get("status", "pending")
        
        category_slug, category_label = categorize_video(item)
        
        thumb_url = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        fallback_thumb = f"https://img.youtube.com/vi/{vid}/0.jpg"
        
        video_url = f"https://www.youtube.com/shorts/{vid}" if is_short else f"https://www.youtube.com/watch?v={vid}"
        embed_url = f"https://www.youtube.com/embed/{vid}?autoplay=1&rel=0"
        
        processed_videos.append({
            "id": item.get("id", f"yt_{vid}"),
            "video_id": vid,
            "title": title,
            "description": clean_desc[:240] + ("..." if len(clean_desc) > 240 else ""),
            "full_description": clean_desc,
            "upload_date": upload_date,
            "date_display": formatted_date,
            "url": video_url,
            "embed_url": embed_url,
            "thumbnail_url": thumb_url,
            "thumbnail_fallback": fallback_thumb,
            "is_short": is_short,
            "status": status,
            "published_at": item.get("published_at"),
            "category": category_slug,
            "category_label": category_label,
        })
        
    def video_sort_key(v: dict):
        is_pub = 1 if v["status"] == "published" else 0
        pub_time = v.get("published_at") or ""
        up_date = v.get("upload_date") or ""
        return (is_pub, pub_time, up_date)
        
    processed_videos.sort(key=video_sort_key, reverse=True)
    
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(processed_videos, f, ensure_ascii=False, indent=2)
    log.info("Wrote %d videos to %s", len(processed_videos), OUTPUT_JSON)
    
    with open(LEGACY_JSON, "w", encoding="utf-8") as f:
        json.dump(processed_videos, f, ensure_ascii=False, indent=2)
    log.info("Updated legacy %s for backward compatibility", LEGACY_JSON)
    
    update_index_html_embedded_data(processed_videos)
    
    return {
        "count": len(processed_videos),
        "success": True,
        "output_file": str(OUTPUT_JSON),
    }

def update_index_html_embedded_data(videos: list[dict]):
    if not INDEX_HTML_FILE.exists():
        return
    try:
        content = INDEX_HTML_FILE.read_text(encoding="utf-8")
        json_str = json.dumps(videos, ensure_ascii=False)
        pattern = r"window\.__SAMARTHA_VIDEOS__\s*=\s*\[.*?\];"
        replacement = f"window.__SAMARTHA_VIDEOS__ = {json_str};"
        
        if re.search(pattern, content, flags=re.DOTALL):
            new_content = re.sub(pattern, lambda _: replacement, content, flags=re.DOTALL)
            INDEX_HTML_FILE.write_text(new_content, encoding="utf-8")
            log.info("Updated embedded window.__SAMARTHA_VIDEOS__ inside index.html")
    except Exception as exc:
        log.warning("Could not update embedded data in index.html: %s", exc)

if __name__ == "__main__":
    res = sync_website_data()
    print(f"Website Sync Complete: {res['count']} videos exported.")
