"""
step3_daily_post.py
--------------------
Reads public/videos.json, picks the first unpublished video,
posts to Facebook Page and Instagram Business Account via Meta Graph API,
then marks it as published: true in videos.json.

Usage:
  python step3_daily_post.py            # live post
  python step3_daily_post.py --dry-run  # preview payload without posting

Required .env keys:
  FB_PAGE_ID        - Your Facebook Page ID (numeric)
  IG_USER_ID        - Your Instagram Business Account ID (numeric)
  META_ACCESS_TOKEN - Page-scoped long-lived access token
  SITE_URL          - Your website URL (shown in caption)
"""

import json
import os
import sys
import argparse
import mimetypes
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Load environment ──────────────────────────────────────────────────────────
load_dotenv()

FB_PAGE_ID        = os.getenv("FB_PAGE_ID", "")
IG_USER_ID        = os.getenv("IG_USER_ID", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
SITE_URL          = os.getenv("SITE_URL", "https://samarthavastu.com")

VIDEOS_JSON = os.path.join("public", "videos.json")
IG_CARDS    = os.path.join("public", "ig_cards")
GRAPH_BASE  = "https://graph.facebook.com/v21.0"

# ─── Arg parsing ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Daily Samartha Vastu social media poster")
parser.add_argument("--dry-run", action="store_true",
                    help="Print payloads without actually posting")
args = parser.parse_args()
DRY_RUN = args.dry_run

# ─── Helper: print section ────────────────────────────────────────────────────
def section(title: str):
    bar = "─" * 60
    print(f"\n{bar}\n  {title}\n{bar}")


# ─── Load videos ──────────────────────────────────────────────────────────────
def load_videos() -> list:
    with open(VIDEOS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_videos(videos: list):
    with open(VIDEOS_JSON, "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)


# ─── Build caption ─────────────────────────────────────────────────────────────
def build_caption(video: dict) -> str:
    caption = video.get("social_caption", "")
    yt_url  = video.get("url", "")
    title   = video.get("title", "")

    parts = []
    if caption:
        parts.append(caption)
    parts.append(f"\n🎬 చూడండి: {yt_url}")
    parts.append(f"🌐 వెబ్‌సైట్: {SITE_URL}")
    parts.append("\n#SamarthaVastu #వాస్తుశాస్త్రం #Vastu #Telugu #VastuTips")
    return "\n".join(parts)


# ─── Facebook: post photo ──────────────────────────────────────────────────────
def post_facebook_photo(video: dict, caption: str, dry_run: bool) -> str | None:
    """Post the horizontal YouTube thumbnail to Facebook Page."""
    section("📘 FACEBOOK PAGE POST")

    thumb_url = video.get("thumbnail_url", "")
    # Prefer maxresdefault
    vid = video["video_id"]
    thumb_url = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"

    payload = {
        "url":     thumb_url,
        "message": caption,
        "access_token": META_ACCESS_TOKEN,
    }

    print(f"  Endpoint : POST {GRAPH_BASE}/{FB_PAGE_ID}/photos")
    print(f"  Photo URL: {thumb_url}")
    print(f"  Caption  :\n{caption}\n")

    if dry_run:
        print("  [DRY-RUN] No request sent.")
        return "dry-run-fb-post-id"

    if not FB_PAGE_ID or not META_ACCESS_TOKEN:
        print("  ⚠️  FB_PAGE_ID or META_ACCESS_TOKEN missing in .env — skipping Facebook post.")
        return None

    resp = requests.post(f"{GRAPH_BASE}/{FB_PAGE_ID}/photos", data=payload, timeout=30)
    data = resp.json()
    if resp.status_code == 200 and "id" in data:
        post_id = data["id"]
        print(f"  ✅ Facebook post created! ID: {post_id}")
        print(f"  🔗 https://www.facebook.com/{post_id}")
        return post_id
    else:
        print(f"  ❌ Facebook API error: {data}")
        return None


# ─── Instagram: upload image container then publish ───────────────────────────
def post_instagram_image(video: dict, caption: str, dry_run: bool) -> str | None:
    """
    Instagram Graph API two-step process:
      1. Create a media container (image URL or uploaded file)
      2. Publish the container
    """
    section("📸 INSTAGRAM BUSINESS POST")

    vid = video["video_id"]
    card_path = os.path.join(IG_CARDS, f"{vid}.jpg")

    # Check if square card exists
    if not os.path.exists(card_path):
        print(f"  ⚠️  Square card not found at {card_path}")
        print(f"      Run: python step2_make_cards.py first.")
        # Fall back to YouTube thumbnail URL
        image_url = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        print(f"      Falling back to YouTube thumbnail: {image_url}")
    else:
        # Instagram requires a publicly accessible URL for images.
        # If SITE_URL is set, assume cards are served from there.
        # Otherwise hint about using a temporary upload service.
        if SITE_URL and not SITE_URL.startswith("https://samarthavastu"):
            image_url = f"{SITE_URL.rstrip('/')}/ig_cards/{vid}.jpg"
        else:
            # For dry-run / demo: use YouTube thumbnail (publicly accessible)
            image_url = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
            print(f"  ℹ️  SITE_URL not configured — using YouTube thumbnail URL.")
            print(f"      For production: host your ig_cards/ folder publicly and set SITE_URL.")

    # Step 1: Create container
    container_payload = {
        "image_url":    image_url,
        "caption":      caption,
        "access_token": META_ACCESS_TOKEN,
    }

    print(f"  Step 1 — Create container")
    print(f"  Endpoint  : POST {GRAPH_BASE}/{IG_USER_ID}/media")
    print(f"  Image URL : {image_url}")
    print(f"  Caption   :\n{caption}\n")

    if dry_run:
        print("  [DRY-RUN] Step 1: No request sent. Mock container_id = dry-run-container-id")
        container_id = "dry-run-container-id"
    else:
        if not IG_USER_ID or not META_ACCESS_TOKEN:
            print("  ⚠️  IG_USER_ID or META_ACCESS_TOKEN missing in .env — skipping Instagram post.")
            return None

        r1 = requests.post(f"{GRAPH_BASE}/{IG_USER_ID}/media",
                           data=container_payload, timeout=30)
        d1 = r1.json()
        if r1.status_code != 200 or "id" not in d1:
            print(f"  ❌ Container creation failed: {d1}")
            return None
        container_id = d1["id"]
        print(f"  ✅ Container created: {container_id}")

    # Step 2: Publish
    publish_payload = {
        "creation_id":  container_id,
        "access_token": META_ACCESS_TOKEN,
    }

    print(f"\n  Step 2 — Publish container")
    print(f"  Endpoint : POST {GRAPH_BASE}/{IG_USER_ID}/media_publish")
    print(f"  Payload  : creation_id={container_id}")

    if dry_run:
        print("  [DRY-RUN] Step 2: No request sent. Mock media_id = dry-run-media-id")
        return "dry-run-media-id"

    r2 = requests.post(f"{GRAPH_BASE}/{IG_USER_ID}/media_publish",
                       data=publish_payload, timeout=30)
    d2 = r2.json()
    if r2.status_code == 200 and "id" in d2:
        media_id = d2["id"]
        print(f"  ✅ Instagram post published! Media ID: {media_id}")
        print(f"  🔗 https://www.instagram.com/samarthavastu999/")
        return media_id
    else:
        print(f"  ❌ Publish failed: {d2}")
        return None


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    mode = "DRY-RUN MODE — no real posts will be made" if DRY_RUN else "LIVE MODE"
    print(f"\n{'='*60}")
    print(f"  Samartha Vastu Daily Publisher")
    print(f"  {mode}")
    print(f"{'='*60}")

    # ── Load config summary ────────────────────────────────────────────────
    print("\n🔧 Config:")
    print(f"  FB_PAGE_ID        : {FB_PAGE_ID or '⚠️  NOT SET'}")
    print(f"  IG_USER_ID        : {IG_USER_ID or '⚠️  NOT SET'}")
    print(f"  META_ACCESS_TOKEN : {'✅ Set (' + META_ACCESS_TOKEN[:8] + '...)' if META_ACCESS_TOKEN else '⚠️  NOT SET'}")
    print(f"  SITE_URL          : {SITE_URL}")

    # ── Find first unpublished video ───────────────────────────────────────
    videos = load_videos()
    target = None
    target_idx = None
    for i, v in enumerate(videos):
        if not v.get("published", False):
            target = v
            target_idx = i
            break

    if target is None:
        print("\n✅ All videos are already published! Nothing to post.")
        print("   Run step1_fetch.py to fetch new videos.")
        sys.exit(0)

    print(f"\n📹 Selected video [{target['video_id']}]:")
    print(f"   Title: {target['title']}")

    # ── Build caption ──────────────────────────────────────────────────────
    caption = build_caption(target)
    section("📝 GENERATED CAPTION")
    print(caption)

    # ── Facebook post ──────────────────────────────────────────────────────
    fb_id = post_facebook_photo(target, caption, DRY_RUN)

    # ── Instagram post ─────────────────────────────────────────────────────
    ig_id = post_instagram_image(target, caption, DRY_RUN)

    # ── Mark as published ──────────────────────────────────────────────────
    if fb_id or ig_id:
        section("💾 Marking as Published")
        videos[target_idx]["published"]    = True
        videos[target_idx]["fb_post_id"]   = fb_id
        videos[target_idx]["ig_media_id"]  = ig_id
        if not DRY_RUN:
            save_videos(videos)
            print(f"  ✅ videos.json updated — video marked as published.")
        else:
            print(f"  [DRY-RUN] videos.json NOT modified.")
    else:
        print("\n⚠️  No posts were made successfully.")

    print(f"\n{'='*60}")
    print(f"  Done! {'(dry run)' if DRY_RUN else ''}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
