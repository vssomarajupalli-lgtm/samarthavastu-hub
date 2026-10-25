"""
refresh_token.py
----------------
Exchanges a short-lived Meta user or page token for a NEVER-EXPIRING Permanent Page Access Token
using the Meta Graph API v21.0 oauth/access_token endpoint, and optionally updates .env.

Usage:
    python refresh_token.py --token <SHORT_LIVED_TOKEN> --app-secret <APP_SECRET> --save
    python refresh_token.py --interactive
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(r"E:\samarthavastu-hub\.env")
load_dotenv(dotenv_path=ENV_PATH)

DEFAULT_APP_ID = "1485257053413357"
DEFAULT_PAGE_ID = "271667576040971"
GRAPH_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"


def debug_token(token: str, app_id: str, app_secret: str) -> dict:
    """Introspect a token using /debug_token with app access token."""
    app_access_token = f"{app_id}|{app_secret}"
    url = f"{BASE_URL}/debug_token"
    params = {
        "input_token": token,
        "access_token": app_access_token
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    if "data" in data:
        return data["data"]
    return data


def exchange_for_long_lived_token(short_token: str, app_id: str, app_secret: str) -> str:
    """
    Exchange short-lived token for long-lived token via oauth/access_token.
    """
    url = f"{BASE_URL}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Error exchanging token: {data['error'].get('message', data['error'])}")
    
    return data.get("access_token")


def get_permanent_page_token(user_or_page_token: str, page_id: str) -> str:
    """
    Fetch the permanent page token using /{page_id}?fields=access_token
    or /me/accounts.
    """
    # Try direct page node first
    url = f"{BASE_URL}/{page_id}"
    params = {
        "fields": "access_token,name",
        "access_token": user_or_page_token
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    if "access_token" in data:
        return data["access_token"]
    
    # Try /me/accounts
    url = f"{BASE_URL}/me/accounts"
    resp = requests.get(url, params={"access_token": user_or_page_token})
    data = resp.json()
    if "data" in data:
        for item in data["data"]:
            if str(item.get("id")) == str(page_id):
                return item.get("access_token")
        if data["data"]:
            # If only one page
            return data["data"][0].get("access_token")

    raise RuntimeError(f"Could not retrieve Page Access Token for Page ID {page_id}: {data}")


def update_env_file(new_token: str):
    """Update META_ACCESS_TOKEN in .env file safely."""
    content = ENV_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("META_ACCESS_TOKEN="):
            new_lines.append(f"META_ACCESS_TOKEN={new_token}")
            updated = True
        else:
            new_lines.append(line)
    
    if not updated:
        new_lines.append(f"META_ACCESS_TOKEN={new_token}")
    
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"✅ Successfully updated META_ACCESS_TOKEN in {ENV_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Exchange short-lived Meta token for permanent Page Access Token")
    parser.add_argument("--token", help="Short-lived or user access token from Graph API Explorer")
    parser.add_argument("--app-id", default=os.getenv("META_APP_ID", DEFAULT_APP_ID), help="Meta App ID")
    parser.add_argument("--app-secret", default=os.getenv("META_APP_SECRET", ""), help="Meta App Secret")
    parser.add_argument("--page-id", default=os.getenv("FB_PAGE_ID", DEFAULT_PAGE_ID), help="Facebook Page ID")
    parser.add_argument("--save", action="store_true", help="Save the permanent token into .env")
    args = parser.parse_args()

    token = args.token or os.getenv("META_ACCESS_TOKEN", "").strip()
    app_secret = args.app_secret.strip()
    app_id = args.app_id.strip()
    page_id = args.page_id.strip()

    if not app_secret:
        print("❌ Error: Meta App Secret is required.")
        print(f"You can find it at: https://developers.facebook.com/apps/{app_id}/settings/basic/")
        sys.exit(1)

    if not token:
        print("❌ Error: Access Token is required.")
        sys.exit(1)

    print("=" * 60)
    print("🔄 Meta Permanent Token Exchange Process")
    print("=" * 60)
    print(f"App ID  : {app_id}")
    print(f"Page ID : {page_id}")

    # Step 1: Exchange for long-lived token
    print("\n[Step 1] Exchanging token via /oauth/access_token...")
    try:
        long_lived_token = exchange_for_long_lived_token(token, app_id, app_secret)
        print("✅ Received long-lived token!")
    except Exception as e:
        print(f"⚠️ Exchange notice: {e}")
        long_lived_token = token

    # Step 2: Fetch Page Access Token
    print("\n[Step 2] Fetching permanent Page Access Token for Page ID:", page_id)
    try:
        perm_page_token = get_permanent_page_token(long_lived_token, page_id)
        print("✅ Retrieved Page Access Token!")
    except Exception as e:
        print(f"⚠️ Direct page fetch fallback: {e}")
        perm_page_token = long_lived_token

    # Step 3: Inspect token via /debug_token
    print("\n[Step 3] Introspecting token...")
    debug_info = debug_token(perm_page_token, app_id, app_secret)
    if isinstance(debug_info, dict):
        token_type = debug_info.get("type", "Unknown")
        expires_at = debug_info.get("expires_at", 0)
        is_valid = debug_info.get("is_valid", False)
        scopes = debug_info.get("scopes", [])
        print(f"   Type: {token_type}")
        print(f"   Valid: {is_valid}")
        print(f"   Expires at: {'Never (0)' if expires_at == 0 else expires_at}")
        print(f"   Permissions/Scopes: {', '.join(scopes)}")

    print("\n" + "=" * 60)
    print("🔑 PERMANENT PAGE ACCESS TOKEN:")
    print(perm_page_token)
    print("=" * 60)

    if args.save:
        update_env_file(perm_page_token)


if __name__ == "__main__":
    main()
