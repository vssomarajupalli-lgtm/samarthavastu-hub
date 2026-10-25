"""
queue_builder.py
----------------
Samartha Vastu - Content Queue Builder

Scans vastu_content_queue/transcripts/ for .txt files, parses Telugu TITLE:
and CAPTION: fields, then auto-generates or updates master_schedule.json
assigning 2 posts per day (09:00 and 18:00) for all pending items.

Usage:
    python queue_builder.py           # scan & build / refresh schedule
    python queue_builder.py --status  # print current queue status table
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# --- Paths ---
BASE_DIR        = Path(__file__).resolve().parent
QUEUE_DIR       = BASE_DIR / "vastu_content_queue"
VIDEOS_DIR      = QUEUE_DIR / "videos"
THUMBNAILS_DIR  = QUEUE_DIR / "thumbnails"
TRANSCRIPTS_DIR = QUEUE_DIR / "transcripts"
SCHEDULE_FILE   = QUEUE_DIR / "master_schedule.json"

# --- Schedule config ---
DAILY_SLOTS = ["09:00:00", "18:00:00"]   # 2 posts per day => 50 days for 100 videos
DATE_START  = date.today()               # first slot from today


def section(title: str):
    bar = "-" * 62
    print(f"\n{bar}\n  {title}\n{bar}")


def parse_transcript(txt_path: Path) -> dict:
    """
    Parse a UTF-8 .txt file with TITLE: and CAPTION: fields.
    Returns {"title": ..., "caption": ...}
    """
    text          = txt_path.read_text(encoding="utf-8")
    title         = ""
    caption_lines = []
    in_caption    = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:") and not title:
            title      = stripped[len("TITLE:"):].strip()
            in_caption = False
        elif stripped.upper().startswith("CAPTION:"):
            caption_lines.append(stripped[len("CAPTION:"):].strip())
            in_caption = True
        elif in_caption:
            caption_lines.append(stripped)

    caption = "\n".join(caption_lines).strip()
    return {"title": title, "caption": caption}


def discover_items() -> list:
    items     = []
    txt_files = sorted(TRANSCRIPTS_DIR.glob("*.txt"))

    for txt_file in txt_files:
        item_id    = txt_file.stem
        thumb_path = THUMBNAILS_DIR / f"{item_id}.jpg"
        video_path = VIDEOS_DIR     / f"{item_id}.mp4"
        parsed     = parse_transcript(txt_file)

        items.append({
            "id":              item_id,
            "title":           parsed["title"],
            "caption":         parsed["caption"],
            "transcript_file": str(txt_file.relative_to(BASE_DIR)),
            "thumbnail_file":  str(thumb_path.relative_to(BASE_DIR)) if thumb_path.exists() else None,
            "video_file":      str(video_path.relative_to(BASE_DIR)) if video_path.exists() else None,
            "has_thumbnail":   thumb_path.exists(),
            "has_video":       video_path.exists(),
        })

    return items


def load_schedule() -> list:
    if SCHEDULE_FILE.exists():
        # utf-8-sig silently strips the BOM that PowerShell adds when writing UTF-8
        with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("items", [])
    return []


def save_schedule(items: list):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"  Saved -> {SCHEDULE_FILE}")


def build_slot_generator(start_date: date, slots: list):
    current = start_date
    while True:
        for slot_time in slots:
            yield current.strftime("%Y-%m-%d"), slot_time
        current += timedelta(days=1)


def build_or_update_schedule(discovered: list) -> list:
    existing     = load_schedule()
    existing_ids = {item["id"]: item for item in existing}

    used_slots = set()
    for item in existing:
        if item.get("scheduled_date") and item.get("scheduled_time"):
            used_slots.add((item["scheduled_date"], item["scheduled_time"]))

    if used_slots:
        latest_date_str = max(s[0] for s in used_slots)
        slot_start = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
    else:
        slot_start = DATE_START

    slot_gen = build_slot_generator(slot_start, DAILY_SLOTS)

    def next_free_slot():
        while True:
            d, t = next(slot_gen)
            if (d, t) not in used_slots:
                used_slots.add((d, t))
                return d, t

    merged = []
    for item in discovered:
        if item["id"] in existing_ids:
            merged.append(existing_ids[item["id"]])
        else:
            sdate, stime = next_free_slot()
            schedule_entry = dict(
                **item,
                status         = "pending",
                scheduled_date = sdate,
                scheduled_time = stime,
                scheduled_at   = f"{sdate}T{stime}",
                published_at   = None,
                fb_post_id     = None,
                fb_post_url    = None,
                ig_media_id    = None,
                ig_post_url    = None,
                wa_sent        = False,
            )
            merged.append(schedule_entry)

    return merged


def print_status(schedule: list):
    section("Master Schedule - Status")
    print(f"{'ID':<12} {'Date':<12} {'Time':<10} {'Status':<12} {'Title':<40}")
    print("-" * 90)
    for item in schedule:
        status = item.get("status", "pending")
        icon   = "[OK]" if status == "published" else ("[PEND]" if status == "pending" else "[ERR]")
        title  = (item.get("title") or "")[:38]
        print(
            f"{item['id']:<12} "
            f"{item.get('scheduled_date',''):<12} "
            f"{item.get('scheduled_time',''):<10} "
            f"{icon} {status:<9} "
            f"{title}"
        )

    total     = len(schedule)
    published = sum(1 for i in schedule if i.get("status") == "published")
    pending   = total - published
    print(f"\n  Total: {total}  |  Published: {published}  |  Pending: {pending}")


def main():
    parser = argparse.ArgumentParser(description="Samartha Vastu Queue Builder")
    parser.add_argument("--status", action="store_true", help="Print schedule status and exit")
    args = parser.parse_args()

    section("Samartha Vastu Queue Builder")

    for d in [VIDEOS_DIR, THUMBNAILS_DIR, TRANSCRIPTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    discovered = discover_items()
    print(f"\n  Discovered {len(discovered)} items in transcripts/")

    if not discovered:
        print("  WARNING: No .txt files found in vastu_content_queue/transcripts/")
        print("  Add files like video_01.txt (with TITLE: and CAPTION: fields).")
        sys.exit(0)

    for item in discovered:
        thumb_icon = "[thumb OK]" if item["has_thumbnail"] else "[NO THUMBNAIL]"
        video_icon = "[video OK]" if item["has_video"]     else "[no video]"
        print(f"  * {item['id']} {thumb_icon} {video_icon}")
        print(f"    Title  : {item['title'][:70]}")
        caption_preview = (item['caption'] or '')[:70]
        print(f"    Caption: {caption_preview}...")

    schedule = build_or_update_schedule(discovered)

    if args.status:
        print_status(schedule)
        sys.exit(0)

    save_schedule(schedule)
    print_status(schedule)

    if schedule:
        first = min(schedule, key=lambda x: x.get("scheduled_date", "9999"))
        last  = max(schedule, key=lambda x: x.get("scheduled_date", "0000"))
        print(f"\n  Schedule spans: {first['scheduled_date']} -> {last['scheduled_date']}")
        pending_count = sum(1 for i in schedule if i.get("status") == "pending")
        days_needed   = (pending_count + len(DAILY_SLOTS) - 1) // len(DAILY_SLOTS)
        print(f"  {pending_count} pending posts -> ~{days_needed} days at {len(DAILY_SLOTS)} posts/day")
        print(f"\n  Queue built successfully! Run auto_publisher.py to start publishing.\n")


if __name__ == "__main__":
    main()
