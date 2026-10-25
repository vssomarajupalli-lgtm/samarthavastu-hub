"""
meta_publisher.py
-----------------
Reusable Meta Graph API publishing module for Samartha Vastu.

Handles:
  - Facebook Page photo posts    → /{page-id}/photos
  - Instagram two-step publishing:
      Step 1: Create container   → /{ig-user-id}/media
      Step 2: Publish container  → /{ig-user-id}/media_publish
  - Token introspection / debug  → /debug_token

Graph API version: v21.0
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("meta_publisher")

# ─── Constants ────────────────────────────────────────────────────────────────
GRAPH_VERSION = "v21.0"
GRAPH_BASE    = f"https://graph.facebook.com/{GRAPH_VERSION}"
IG_CONTAINER_POLL_INTERVAL = 4   # seconds between status polls
IG_CONTAINER_MAX_POLLS     = 15  # give up after this many polls


# ─── Config dataclass ─────────────────────────────────────────────────────────
@dataclass
class MetaConfig:
    page_id:       str
    ig_user_id:    str
    access_token:  str
    site_url:      str = "https://samarthavastu.com"

    @classmethod
    def from_env(cls) -> "MetaConfig":
        """Load config from environment / .env file."""
        cfg = cls(
            page_id      = os.getenv("FB_PAGE_ID", ""),
            ig_user_id   = os.getenv("IG_USER_ID", ""),
            access_token = os.getenv("META_ACCESS_TOKEN", ""),
            site_url     = os.getenv("SITE_URL", "https://samarthavastu.com"),
        )
        missing = [k for k, v in {
            "FB_PAGE_ID":        cfg.page_id,
            "IG_USER_ID":        cfg.ig_user_id,
            "META_ACCESS_TOKEN": cfg.access_token,
        }.items() if not v]
        if missing:
            raise EnvironmentError(
                f"Missing required .env keys: {', '.join(missing)}"
            )
        return cfg

    @property
    def token_preview(self) -> str:
        return self.access_token[:12] + "..." if self.access_token else "NONE"


# ─── Result dataclass ─────────────────────────────────────────────────────────
@dataclass
class PublishResult:
    platform:   str
    success:    bool
    post_id:    Optional[str] = None
    error:      Optional[str] = None
    url:        Optional[str] = None
    extra:      dict = field(default_factory=dict)

    def __str__(self) -> str:
        if self.success:
            return f"[{self.platform}] ✅ Published → {self.url or self.post_id}"
        return f"[{self.platform}] ❌ Failed — {self.error}"


# ─── Core HTTP helper ─────────────────────────────────────────────────────────
def _api_post(endpoint: str, payload: dict, timeout: int = 30) -> dict:
    """POST to Graph API; always return parsed JSON."""
    url = f"{GRAPH_BASE}/{endpoint.lstrip('/')}"
    log.debug("POST %s  payload_keys=%s", url, list(payload.keys()))
    resp = requests.post(url, data=payload, timeout=timeout)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    if resp.status_code != 200:
        log.warning("HTTP %s from %s: %s", resp.status_code, url, data)
    return data


def _api_get(endpoint: str, params: dict, timeout: int = 15) -> dict:
    """GET from Graph API; always return parsed JSON."""
    url = f"{GRAPH_BASE}/{endpoint.lstrip('/')}"
    log.debug("GET %s  params=%s", url, list(params.keys()))
    resp = requests.get(url, params=params, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


# ─── Token debug ─────────────────────────────────────────────────────────────
def debug_token(cfg: MetaConfig) -> dict:
    """
    Call /debug_token to validate the access token and print its expiry,
    scopes, and associated pages/accounts.
    """
    log.info("Validating access token …")
    # Use app token (page token|page token works too for self-inspection)
    data = _api_get("debug_token", {
        "input_token":  cfg.access_token,
        "access_token": cfg.access_token,
    })
    return data.get("data", data)


# ─── Facebook Page publisher ──────────────────────────────────────────────────
def post_facebook_photo(
    cfg: MetaConfig,
    image_url: str,
    caption: str,
    dry_run: bool = False,
) -> PublishResult:
    """
    Post a photo to the Facebook Page feed using an image URL.

    Endpoint: POST /{page-id}/photos
    Docs: https://developers.facebook.com/docs/graph-api/reference/photo/
    """
    endpoint = f"{cfg.page_id}/photos"
    payload  = {
        "url":          image_url,
        "message":      caption,
        "access_token": cfg.access_token,
    }

    log.info("[Facebook] POST %s/%s", GRAPH_BASE, endpoint)
    log.info("[Facebook] Image URL : %s", image_url)
    log.info("[Facebook] Caption   : %s …", caption[:80])

    if dry_run:
        log.info("[Facebook] DRY-RUN — skipping real request")
        return PublishResult(
            platform="Facebook",
            success=True,
            post_id="dry-run-fb-id",
            url=f"https://www.facebook.com/{cfg.page_id}",
            extra={"payload": payload},
        )

    data = _api_post(endpoint, payload)

    if "id" in data:
        post_id = data["id"]
        result = PublishResult(
            platform="Facebook",
            success=True,
            post_id=post_id,
            url=f"https://www.facebook.com/{post_id.replace('_', '/posts/')}",
            extra=data,
        )
    else:
        result = PublishResult(
            platform="Facebook",
            success=False,
            error=json.dumps(data),
            extra=data,
        )

    log.info(str(result))
    return result


# ─── Instagram two-step publisher ─────────────────────────────────────────────
def _poll_ig_container(cfg: MetaConfig, container_id: str) -> bool:
    """
    Poll the IG container status until FINISHED or ERROR.
    Returns True if ready to publish.
    """
    for i in range(IG_CONTAINER_MAX_POLLS):
        data = _api_get(
            f"{container_id}",
            {"fields": "status_code,status", "access_token": cfg.access_token},
        )
        status = data.get("status_code", "")
        log.debug("[Instagram] Container %s status: %s (poll %d)", container_id, status, i + 1)
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            log.error("[Instagram] Container failed with status: %s — %s", status, data)
            return False
        time.sleep(IG_CONTAINER_POLL_INTERVAL)

    log.error("[Instagram] Container %s never reached FINISHED after %d polls",
              container_id, IG_CONTAINER_MAX_POLLS)
    return False


def post_instagram_image(
    cfg: MetaConfig,
    image_url: str,
    caption: str,
    dry_run: bool = False,
) -> PublishResult:
    """
    Publish a single image to Instagram Business Account.

    Step 1: POST /{ig-user-id}/media          → creates container
    Step 2: POST /{ig-user-id}/media_publish   → publishes container

    image_url MUST be a publicly accessible HTTPS URL (not localhost).
    Docs: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
    """
    # ── Step 1: Create media container ────────────────────────────────────
    endpoint_media = f"{cfg.ig_user_id}/media"
    payload_media  = {
        "image_url":    image_url,
        "caption":      caption,
        "access_token": cfg.access_token,
    }

    log.info("[Instagram] Step 1 — Create container")
    log.info("[Instagram] POST %s/%s", GRAPH_BASE, endpoint_media)
    log.info("[Instagram] Image URL : %s", image_url)
    log.info("[Instagram] Caption   : %s …", caption[:80])

    if dry_run:
        log.info("[Instagram] DRY-RUN — skipping container creation")
        return PublishResult(
            platform="Instagram",
            success=True,
            post_id="dry-run-ig-media-id",
            url="https://www.instagram.com/samarthavastu999/",
            extra={
                "step1_payload": payload_media,
                "step2_payload": {
                    "creation_id":  "dry-run-container-id",
                    "access_token": cfg.token_preview + "...",
                },
            },
        )

    data1 = _api_post(endpoint_media, payload_media)

    if "id" not in data1:
        return PublishResult(
            platform="Instagram",
            success=False,
            error=f"Container creation failed: {json.dumps(data1)}",
            extra=data1,
        )

    container_id = data1["id"]
    log.info("[Instagram] Container created: %s", container_id)

    # ── Poll until container is ready ─────────────────────────────────────
    if not _poll_ig_container(cfg, container_id):
        return PublishResult(
            platform="Instagram",
            success=False,
            error=f"Container {container_id} did not reach FINISHED state",
            extra=data1,
        )

    # ── Step 2: Publish container ──────────────────────────────────────────
    endpoint_pub = f"{cfg.ig_user_id}/media_publish"
    payload_pub  = {
        "creation_id":  container_id,
        "access_token": cfg.access_token,
    }

    log.info("[Instagram] Step 2 — Publish container %s", container_id)
    log.info("[Instagram] POST %s/%s", GRAPH_BASE, endpoint_pub)

    data2 = _api_post(endpoint_pub, payload_pub)

    if "id" in data2:
        media_id = data2["id"]
        result = PublishResult(
            platform="Instagram",
            success=True,
            post_id=media_id,
            url="https://www.instagram.com/samarthavastu999/",
            extra={"container_id": container_id, **data2},
        )
    else:
        result = PublishResult(
            platform="Instagram",
            success=False,
            error=f"Publish failed: {json.dumps(data2)}",
            extra={"container_id": container_id, **data2},
        )

    log.info(str(result))
    return result


# ─── Convenience: publish to both platforms ───────────────────────────────────
def publish_to_all(
    cfg: MetaConfig,
    fb_image_url: str,
    ig_image_url: str,
    caption: str,
    dry_run: bool = False,
) -> dict[str, PublishResult]:
    """
    Publish to Facebook and Instagram simultaneously.

    Args:
        cfg:           MetaConfig loaded from .env
        fb_image_url:  Horizontal YouTube thumbnail (16:9) for Facebook
        ig_image_url:  1080x1080 square card URL for Instagram
        caption:       Telugu caption (shared across platforms)
        dry_run:       If True, no real API calls are made

    Returns:
        {"facebook": PublishResult, "instagram": PublishResult}
    """
    log.info("=" * 60)
    log.info("Publishing to Facebook + Instagram %s",
             "[DRY-RUN]" if dry_run else "[LIVE]")
    log.info("=" * 60)

    fb_result = post_facebook_photo(cfg, fb_image_url, caption, dry_run)
    ig_result = post_instagram_image(cfg, ig_image_url, caption, dry_run)

    return {"facebook": fb_result, "instagram": ig_result}
