"""
step1_fetch.py
--------------
Fetches the latest 3 videos from https://www.youtube.com/@samarthavastu999/videos,
generates structured Telugu Vastu articles and captions using Gemini 2.5 Flash,
and saves everything to public/videos.json.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv

# Load environment
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("No GEMINI_API_KEY found in .env file.")
    GEMINI_API_KEY = input("Please paste your GEMINI_API_KEY: ").strip()
    if not GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY is required. Exiting.")
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"GEMINI_API_KEY={GEMINI_API_KEY}\n")
    print("API key saved to .env")

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from google import genai

CHANNEL_URL = "https://www.youtube.com/@samarthavastu999/videos"
OUTPUT_PATH = os.path.join("public", "videos.json")
MAX_VIDEOS = 3


def fetch_latest_videos(channel_url: str, max_count: int) -> list:
    print(f"\nFetching latest {max_count} videos from {channel_url} ...")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlist_items": f"1-{max_count}",
        "skip_download": True,
    }
    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        entries = info.get("entries", [])[:max_count]
        for entry in entries:
            video_id = entry.get("id", "")
            title = entry.get("title", "Untitled")
            thumbnail = (
                entry.get("thumbnail")
                or f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            )
            videos.append({
                "video_id": video_id,
                "title": title,
                "thumbnail_url": thumbnail,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
            print(f"  Found: [{video_id}] {title}")
    return videos


def get_transcript_or_description(video_id: str, title: str) -> str:
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(["te", "te-IN"])
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(["te", "te-IN", "en"])
            except Exception:
                transcript = transcript_list.find_transcript(
                    [t.language_code for t in transcript_list]
                )
        chunks = transcript.fetch()
        text = " ".join(c.get("text", "") for c in chunks)
        if text.strip():
            print(f"    Transcript fetched ({len(text)} chars)")
            return text[:6000]
    except (NoTranscriptFound, TranscriptsDisabled):
        pass
    except Exception as e:
        print(f"    Transcript error: {e}")

    print(f"    No transcript - fetching description ...")
    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
            desc = info.get("description", "") or ""
            print(f"    Description fetched ({len(desc)} chars)")
            return desc[:6000]
    except Exception as e:
        print(f"    Could not fetch description: {e}")
        return f"Video about Vastu Shastra: {title}"


def generate_telugu_content(client, video_id: str, title: str, source_text: str) -> dict:
    prompt = f"""You are an expert Telugu Vastu Shastra writer for the YouTube channel "Samarthavastu".

Video Title: {title}
Video Content / Transcript:
\"\"\"
{source_text}
\"\"\"

Please generate the following in **Telugu language only**:

1. **telugu_subject** - A complete, structured Vastu Shastra article in Telugu (minimum 400 words).
   - Start with an engaging heading using "##"
   - Include subsections with "###" headings covering:
     . వాస్తు పరిచయం (Introduction to Vastu)
     . ముఖ్యమైన వాస్తు సూత్రాలు (Key Vastu Principles from the video)
     . ఇంట్లో వర్తించే సూచనలు (How to apply at home)
     . ప్రయోజనాలు (Benefits)
     . నిర్ణయం (Conclusion)
   - Use bullet points where appropriate
   - Write naturally flowing Telugu prose

2. **social_caption** - A short, engaging Telugu social media caption (max 3 sentences + 5 relevant hashtags).

Respond ONLY with a valid JSON object in this exact format (no markdown fences):
{{
  "telugu_subject": "...",
  "social_caption": "..."
}}"""

    print(f"    Calling Gemini for [{video_id}] ...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()
        result = json.loads(raw)
        return result
    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}. Using raw text as subject.")
        return {
            "telugu_subject": response.text,
            "social_caption": f"#{title.replace(' ', '')} #వాస్తు #Vastu #SamarthaVastu",
        }
    except Exception as e:
        print(f"    Gemini error: {e}")
        return {
            "telugu_subject": f"వాస్తు శాస్త్రం: {title}",
            "social_caption": f"#{title.replace(' ', '')} #వాస్తు #Vastu",
        }


def main():
    os.makedirs("public", exist_ok=True)

    videos = fetch_latest_videos(CHANNEL_URL, MAX_VIDEOS)
    if not videos:
        sys.exit("No videos found. Check channel URL and network connectivity.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    results = []
    for idx, video in enumerate(videos, 1):
        vid = video["video_id"]
        title = video["title"]
        print(f"\nVideo {idx}/{MAX_VIDEOS}: {title}")

        source_text = get_transcript_or_description(vid, title)
        ai_content = generate_telugu_content(client, vid, title, source_text)

        record = {
            "video_id": vid,
            "title": title,
            "thumbnail_url": video["thumbnail_url"],
            "url": video["url"],
            "telugu_subject": ai_content.get("telugu_subject", ""),
            "social_caption": ai_content.get("social_caption", ""),
        }
        results.append(record)

        if idx < MAX_VIDEOS:
            time.sleep(2)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(results)} videos to {OUTPUT_PATH}")
    print("Open public/index.html in your browser to preview the site.")


if __name__ == "__main__":
    main()
