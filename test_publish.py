"""
test_publish.py
---------------
Comprehensive test script for the Samartha Vastu Meta publishing pipeline.

Tests (in order):
  T1 — Load & validate .env credentials
  T2 — Validate access token via /debug_token
  T3 — Verify Facebook Page access (GET /{page-id})
  T4 — Verify Instagram account access (GET /{ig-user-id})
  T5 — DRY-RUN: Simulate dual publish (no real posts)
  T6 — LIVE: Publish sample Telugu post to Facebook Page
  T7 — LIVE: Publish sample Telugu post to Instagram

Usage:
  python test_publish.py              # runs T1–T5 (safe, no live posts)
  python test_publish.py --live-fb    # also runs T6 (live Facebook post)
  python test_publish.py --live-ig    # also runs T7 (live Instagram post)
  python test_publish.py --live-all   # runs T6 + T7 (both live)
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# Import our publishing module
sys.path.insert(0, os.path.dirname(__file__))
from meta_publisher import (
    MetaConfig,
    PublishResult,
    debug_token,
    post_facebook_photo,
    post_instagram_image,
    publish_to_all,
    _api_get,
    GRAPH_BASE,
    GRAPH_VERSION,
)

# ─── Arg parse ────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(description="Samartha Vastu Meta API test suite")
ap.add_argument("--live-fb",  action="store_true", help="Run live Facebook post (T6)")
ap.add_argument("--live-ig",  action="store_true", help="Run live Instagram post (T7)")
ap.add_argument("--live-all", action="store_true", help="Run both live posts (T6 + T7)")
args = ap.parse_args()

RUN_LIVE_FB = args.live_fb or args.live_all
RUN_LIVE_IG = args.live_ig or args.live_all

# ─── Sample content ───────────────────────────────────────────────────────────
# Public image URLs for testing (YouTube thumbnail — always accessible)
TEST_VIDEO_ID  = "9g8YCXL0wPw"   # First video from videos.json
TEST_FB_IMAGE  = f"https://img.youtube.com/vi/{TEST_VIDEO_ID}/maxresdefault.jpg"
# Instagram crawler blocks img.youtube.com, so we use a verified public JPEG for IG testing
TEST_IG_IMAGE  = "https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?w=1080&auto=format&fit=crop&q=80"

TEST_CAPTION = textwrap.dedent("""\
    🕉️ వాస్తు శాస్త్రం ప్రకారం మీ ఇల్లు సక్రమంగా ఉందా?

    పునర్జన్మ రహస్యం — సైన్స్ కు కూడా అంతుచిక్కని నిజాలు.
    సమర్థవాస్తు ఛానెల్‌లో పూర్తి వీడియో చూడండి!

    🎬 https://www.youtube.com/watch?v={video_id}
    🌐 https://samarthavastu.com

    #SamarthaVastu #వాస్తుశాస్త్రం #Vastu #Telugu #VastuTips #పునర్జన్మ
""").format(video_id=TEST_VIDEO_ID)

# ─── Test helpers ─────────────────────────────────────────────────────────────
PASS  = "✅ PASS"
FAIL  = "❌ FAIL"
SKIP  = "⏭  SKIP"
INFO  = "ℹ️ "

results: list[tuple[str, str, str]] = []   # (test_id, status, detail)

def run_test(test_id: str, description: str):
    """Print a test header."""
    print(f"\n{'─'*62}")
    print(f"  {test_id}: {description}")
    print(f"{'─'*62}")

def record(test_id: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((test_id, status, detail))
    print(f"\n  → {status}  {detail}")


# ═══════════════════════════════════════════════════════════════
# T1 — Load & validate .env credentials
# ═══════════════════════════════════════════════════════════════
run_test("T1", "Load & validate .env credentials")

try:
    cfg = MetaConfig.from_env()
    print(f"  FB_PAGE_ID        : {cfg.page_id}")
    print(f"  IG_USER_ID        : {cfg.ig_user_id}")
    print(f"  META_ACCESS_TOKEN : {cfg.token_preview}")
    print(f"  SITE_URL          : {cfg.site_url}")
    print(f"  Graph API version : {GRAPH_VERSION}")
    record("T1", True, "All required env vars loaded")
except EnvironmentError as e:
    record("T1", False, str(e))
    print("\n⛔ Cannot continue without credentials. Exiting.")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# T2 — Validate access token via /debug_token
# ═══════════════════════════════════════════════════════════════
run_test("T2", "Validate access token via /debug_token")

token_info = debug_token(cfg)
print(f"  Raw response: {json.dumps(token_info, indent=4)[:600]}")

token_valid = token_info.get("is_valid", False)
app_id      = token_info.get("app_id", "?")
token_type  = token_info.get("type", "?")
expires     = token_info.get("expires_at", 0)
scopes      = token_info.get("scopes", [])
expires_str = (
    datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M")
    if expires else "never / long-lived"
)

print(f"\n  is_valid   : {token_valid}")
print(f"  app_id     : {app_id}")
print(f"  token_type : {token_type}")
print(f"  expires_at : {expires_str}")
print(f"  scopes     : {', '.join(scopes) if scopes else 'not returned'}")

record("T2", token_valid,
       f"Token valid={token_valid}, type={token_type}, expires={expires_str}")

# Warn on missing scopes
REQUIRED_SCOPES = {
    "pages_manage_posts", "pages_read_engagement",
    "instagram_basic", "instagram_content_publish",
    "public_profile",
}
missing_scopes = REQUIRED_SCOPES - set(scopes) if scopes else set()
if missing_scopes:
    print(f"\n  ⚠️  Possibly missing scopes: {', '.join(missing_scopes)}")
    print(f"     (scopes list may be empty for some token types — check App Dashboard)")


# ═══════════════════════════════════════════════════════════════
# T3 — Verify Facebook Page access
# ═══════════════════════════════════════════════════════════════
run_test("T3", "Verify Facebook Page access")

fb_page_data = _api_get(cfg.page_id, {
    "fields":       "id,name,category,fan_count,link",
    "access_token": cfg.access_token,
})
print(f"  Response: {json.dumps(fb_page_data, indent=4)}")

fb_ok = "id" in fb_page_data and "error" not in fb_page_data
record(
    "T3", fb_ok,
    f"Page: {fb_page_data.get('name', '?')} | "
    f"Fans: {fb_page_data.get('fan_count', '?')} | "
    f"URL: {fb_page_data.get('link', '?')}"
    if fb_ok else str(fb_page_data.get("error", fb_page_data))
)


# ═══════════════════════════════════════════════════════════════
# T4 — Verify Instagram Business Account access
# ═══════════════════════════════════════════════════════════════
run_test("T4", "Verify Instagram Business Account access")

ig_data = _api_get(cfg.ig_user_id, {
    "fields":       "id,name,username,biography,followers_count,media_count",
    "access_token": cfg.access_token,
})
print(f"  Response: {json.dumps(ig_data, indent=4)}")

ig_ok = "id" in ig_data and "error" not in ig_data
record(
    "T4", ig_ok,
    f"@{ig_data.get('username','?')} | "
    f"Followers: {ig_data.get('followers_count','?')} | "
    f"Posts: {ig_data.get('media_count','?')}"
    if ig_ok else str(ig_data.get("error", ig_data))
)


# ═══════════════════════════════════════════════════════════════
# T5 — DRY-RUN: Simulate dual publish
# ═══════════════════════════════════════════════════════════════
run_test("T5", "DRY-RUN: Simulate dual publish (FB + IG)")

print(f"\n  Test image URL (FB): {TEST_FB_IMAGE}")
print(f"  Test image URL (IG): {TEST_IG_IMAGE}")
print(f"\n  Caption preview:\n")
print(textwrap.indent(TEST_CAPTION, "    "))

dry_results = publish_to_all(
    cfg         = cfg,
    fb_image_url= TEST_FB_IMAGE,
    ig_image_url= TEST_IG_IMAGE,
    caption     = TEST_CAPTION,
    dry_run     = True,
)

dr_fb = dry_results["facebook"]
dr_ig = dry_results["instagram"]
print(f"\n  Facebook : {dr_fb}")
print(f"  Instagram: {dr_ig}")
record("T5", dr_fb.success and dr_ig.success,
       "Dry-run payloads validated for both platforms")


# ═══════════════════════════════════════════════════════════════
# T6 — LIVE Facebook post
# ═══════════════════════════════════════════════════════════════
run_test("T6", "LIVE Facebook Page photo post")

if not RUN_LIVE_FB:
    print(f"  {SKIP} Pass --live-fb or --live-all to run this test.")
    results.append(("T6", SKIP, "Skipped (use --live-fb)"))
else:
    print(f"  Posting to Facebook Page {cfg.page_id} …")
    fb_live = post_facebook_photo(
        cfg       = cfg,
        image_url = TEST_FB_IMAGE,
        caption   = TEST_CAPTION,
        dry_run   = False,
    )
    print(f"\n  {fb_live}")
    if fb_live.success:
        print(f"  Post URL: {fb_live.url}")
    else:
        print(f"  Error: {fb_live.error}")
        print(f"  Full response: {json.dumps(fb_live.extra, indent=4)}")
    record("T6", fb_live.success,
           f"Post ID: {fb_live.post_id}" if fb_live.success else fb_live.error or "")


# ═══════════════════════════════════════════════════════════════
# T7 — LIVE Instagram post
# ═══════════════════════════════════════════════════════════════
run_test("T7", "LIVE Instagram Business Account image post")

if not RUN_LIVE_IG:
    print(f"  {SKIP} Pass --live-ig or --live-all to run this test.")
    results.append(("T7", SKIP, "Skipped (use --live-ig)"))
else:
    print(f"  Posting to Instagram @samarthavastu999 ({cfg.ig_user_id}) …")
    ig_live = post_instagram_image(
        cfg       = cfg,
        image_url = TEST_IG_IMAGE,
        caption   = TEST_CAPTION,
        dry_run   = False,
    )
    print(f"\n  {ig_live}")
    if ig_live.success:
        print(f"  Post URL: {ig_live.url}")
    else:
        print(f"  Error: {ig_live.error}")
        print(f"  Full response: {json.dumps(ig_live.extra, indent=4)}")
    record("T7", ig_live.success,
           f"Media ID: {ig_live.post_id}" if ig_live.success else ig_live.error or "")


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'═'*62}")
print(f"  TEST RESULTS SUMMARY — Samartha Vastu Meta Publisher")
print(f"{'═'*62}")
total = pass_c = fail_c = skip_c = 0
for tid, status, detail in results:
    total += 1
    short = detail[:65] + "…" if len(detail) > 65 else detail
    print(f"  {tid}  {status}  {short}")
    if PASS in status:  pass_c += 1
    elif FAIL in status: fail_c += 1
    else: skip_c += 1

print(f"\n  Total: {total}  |  Pass: {pass_c}  |  Fail: {fail_c}  |  Skip: {skip_c}")
print(f"{'═'*62}\n")

if fail_c > 0:
    sys.exit(1)
