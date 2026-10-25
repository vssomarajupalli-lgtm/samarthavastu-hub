"""
website_sync.py
---------------
Samartha Vastu - 5-Pillar Dynamic Website Synchronizer & Telugu Summary Engine

Categorizes videos into:
  - 'vastu'      : 🏡 వాస్తు శాస్త్రం (Vastu Shastra)
  - 'jyotisha'   : 🪐 జ్యోతిష్య శాస్త్రం (Jyotisha Shastra)
  - 'tantrika'   : 🔱 తాంత్రిక విద్యలు (Tantrika Vidyalu)
  - 'paranormal' : 🔮 అతీంద్రియ & పునర్జన్మ రహస్యాలు (Paranormal & Rebirth)
  - 'spiritual'  : 🕉️ ఆధ్యాత్మికం (Spiritual Wisdom)
  - 'shorts'     : ⚡ షార్ట్స్ (YouTube Shorts)

Extracts / generates 3-4 rich Telugu summary sentences (summary_telugu) for every video.
Embeds both window.__SAMARTHA_VIDEOS__ and window.__SAMARTHA_BOOKS__ into public/index.html
for instant, zero-bloat rendering offline (file:///) and online on GitHub Pages.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from books_library import generate_books_data

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
BOOKS_JSON_FILE = PUBLIC_DIR / "books_data.json"
INDEX_HTML_FILE = PUBLIC_DIR / "index.html"


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
    """Returns (category_slug, category_label) across the 5 pillars + shorts."""
    if item.get("is_short"):
        return "shorts", "షార్ట్స్"

    title = (item.get("title") or "").lower()
    desc = (item.get("description") or "").lower()

    # 1. Check Paranormal & Rebirth in Title first
    para_kw = [
        "పునర్జన్మ", "ఆత్మ", "దెయ్యం", "దయ్యం", "పారానార్మల్", "paranormal", "rebirth",
        "ghost", "spirit", "మరణానంతర", "సోల్", "ప్రేతాత్మ", "శవ", "భయం", "భయానక",
        "కుల్ధారా", "టైమ్ లూప్", "రీఇన్‌కార్నేషన్", "ఆత్మలను", "పునర్జన్మలు"
    ]
    if any(k in title for k in para_kw):
        return "paranormal", "అతీంద్రియ & పునర్జన్మ రహస్యాలు"

    # 2. Check Tantrika Vidyalu (Shakti Chakra, Yantra, Mantra, Tantra, Drishti)
    tantra_kw = [
        "శక్తి చక్ర", "తంత్ర", "తాంత్రిక", "యంత్ర", "మంత్ర", "దృష్టి", "నరదృష్టి",
        "చేతబడి", "ప్రయోగ", "రక్ష", "కవచ", "దిష్టి", "వశీకరణ", "బీజాక్షర", "గుప్త విద్య"
    ]
    if any(k in title for k in tantra_kw):
        return "tantrika", "తాంత్రిక విద్యలు"

    # 3. Check Jyotisha Shastra (Horoscope, Planets, Rashis, Nakshatras)
    jyotish_kw = [
        "జాతక", "గ్రహ", "రాశి", "నక్షత్ర", "లగ్న", "కుండలి", "దోష", "దశా", "అయనాంశ",
        "సాయన", "నిరయణ", "జ్యోతిష్య", "హోరా", "ముహూర్త", "జ్యోతిష", "రాహు", "కేతు",
        "శని", "గురు", "కుజ", "శుక్ర", "ఆర్క్‌నిమిషాల", "గ్రహస్థితులు"
    ]
    if any(k in title for k in jyotish_kw):
        return "jyotisha", "జ్యోతిష్య శాస్త్రం"

    # 4. Check Vastu Shastra (Directions, Plots, House Architecture, Doors)
    vastu_kw = [
        "వాస్తు", "ఇల్లు", "గృహ", "ద్వార", "స్థలం", "ఈశాన్య", "ఆగ్నేయ", "నైరుతి", "వాయువ్య",
        "ముఖద్వార", "వంటగది", "మెట్లు", "ప్లాట్", "దిశ", "దిశలు", "సరిహద్దు", "బాల్కనీ",
        "కూల్చివేత", "సంప్", "బోరు", "భవన", "నిర్మాణ", "ఆయాది", "పదవిన్యాస"
    ]
    if any(k in title for k in vastu_kw):
        return "vastu", "వాస్తు శాస్త్రం"

    # 5. Check Spiritual Wisdom (Temples, Dharma, Deities, Puranas)
    spirit_kw = [
        "దేవాలయం", "ఆలయం", "గుడి", "దేవుడు", "భక్తి", "ఆధ్యాత్మిక", "పురాణ", "స్తోత్ర",
        "తీర్థ", "ధర్మ", "శివ", "విష్ణు", "గీత", "ఉపనిషత్", "జ్ఞాన", "మహిమ", "స్వామి",
        "యోగి", "యోగా", "కోణార్క్", "తిరుపతి", "బృహదీశ్వర"
    ]
    if any(k in title for k in spirit_kw):
        return "spiritual", "ఆధ్యాత్మికం"

    # 6. Fallback checks in description
    if any(k in desc for k in para_kw):
        return "paranormal", "అతీంద్రియ & పునర్జన్మ రహస్యాలు"
    if any(k in desc for k in tantra_kw):
        return "tantrika", "తాంత్రిక విద్యలు"
    if any(k in desc for k in jyotish_kw):
        return "jyotisha", "జ్యోతిష్య శాస్త్రం"
    if any(k in desc for k in vastu_kw):
        return "vastu", "వాస్తు శాస్త్రం"

    return "spiritual", "ఆధ్యాత్మికం"


def generate_telugu_summary(title: str, description: str, category_slug: str) -> str:
    """Generates 3 to 4 clear, informative Telugu sentences summarizing the core topic."""
    clean = clean_description(description)
    lines = []
    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(b in line for b in [
            "http", "wa.me", "youtube.com", "📞", "✉️", "Contact:", "Phone:",
            "Email:", "సంప్రదించండి", "స్వాగతం - సమర్థ వాస్తు", "SVSN రాజు"
        ]):
            continue
        lines.append(line)

    body = " ".join(lines).strip()
    raw_sentences = [s.strip() for s in re.split(r"[.!?।\n]+", body) if len(s.strip()) > 18]
    telugu_sentences = [s for s in raw_sentences if re.search(r"[\u0C00-\u0C7F]", s)]

    if len(telugu_sentences) >= 3:
        picked = ". ".join(telugu_sentences[:4]).strip()
        return picked + ("." if not picked.endswith(".") else "")

    clean_t = re.sub(r'["\']', '', title)
    if category_slug == "vastu":
        return (
            f"ఈ విశిష్ట వీడియోలో '{clean_t}' గురించిన ప్రామాణిక వాస్తు సూత్రాలు మరియు విశ్లేషణను అందించడం జరిగింది. "
            f"గృహ నిర్మాణంలో దిశలు, పంచభూతాల సమతుల్యత మరియు సానుకూల ప్రాణశక్తి ప్రసరణ ఎంత కీలకమో శాస్త్రోక్తంగా వివరించారు. "
            f"ఎలాంటి అనవసర కూల్చివేతలు లేకుండా సరళమైన పద్ధతుల ద్వారా వాస్తు దోషాలను నివారించుకునే మార్గదర్శకాలు ఇందులో ఉన్నాయి. "
            f"పూర్తి వివరాలు మరియు పరిష్కారాల కోసం పైన ఉన్న లింక్ ద్వారా పూర్తి వీడియోను వీక్షించండి."
        )
    elif category_slug == "jyotisha":
        return (
            f"ఈ వీడియోలో '{clean_t}' అంశానికి సంబంధించిన ఖగోళ గ్రహస్థితులు మరియు జాతక ఫలితాలను సవివరంగా విశ్లేషించారు. "
            f"ప్రాచీన పరాశర మరియు వరాహమిహిర సిద్ధాంతాల ప్రకారం వ్యక్తిగత జీవితంపై గ్రహాల సంచార ప్రభావాన్ని వివరించడం జరిగింది. "
            f"దోషాల నివారణకు సరైన పూజా విధానాలు, శాంతి మార్గాలు మరియు ఆధ్యాత్మిక రెమెడీలను స్పష్టంగా తెలియజేశారు. "
            f"సమగ్ర జ్యోతిష్య విశ్లేషణ తెలుసుకోవడానికి పైన ఉన్న లింక్ ద్వారా యూట్యూబ్‌లో వీక్షించండి."
        )
    elif category_slug == "tantrika":
        return (
            f"ఈ వీడియోలో '{clean_t}' అంశానికి సంబంధించిన తాంత్రిక మరియు శక్తి చక్ర రహస్యాలను శాస్త్రీయంగా చర్చించారు. "
            f"గృహ రక్షణ, నరదృష్టి నివారణ మరియు నకారాత్మక తరంగాలను అడ్డుకునే ప్రాచీన యంత్ర, మంత్ర సూత్రాలను వివరించారు. "
            f"మూఢనమ్మకాలకు తావులేకుండా శాస్త్ర సమ్మతమైన పద్ధతిలో శక్తి ప్రసరణను ఎలా పెంచుకోవాలో మార్గదర్శనం చేశారు. "
            f"పూర్తి శాస్త్రీయ రహస్యాలు తెలుసుకోవడానికి పైన ఉన్న లింక్ ద్వారా వీడియోను చూడండి."
        )
    elif category_slug == "paranormal":
        return (
            f"ఈ పరిశోధనాత్మక వీడియోలో '{clean_t}' గురించిన వాస్తవాలు మరియు పారానార్మల్ ఆధారాలను సవివరంగా చర్చించారు. "
            f"ఆత్మలు, మరణానంతర ప్రయాణం మరియు పునర్జన్మల వెనుక దాగి ఉన్న అతీంద్రియ సంఘటనలను శాస్త్రీయ దృక్పథంతో విశ్లేషించారు. "
            f"భయాన్ని వీడి విశ్వంలోని అజ్ఞాత శక్తుల పనితీరును అర్థం చేసుకునేందుకు ఈ విశ్లేషణ ఎంతగానో ఉపయోగపడుతుంది. "
            f"ఆసక్తికరమైన పూర్తి పరిశోధనను చూడటానికి పైన ఉన్న లింక్ పై క్లిక్ చేసి వీడియోను వీక్షించండి."
        )
    elif category_slug == "shorts":
        return (
            f"ఈ సంక్షిప్త షార్ట్ వీడియోలో '{clean_t}' గురించిన ముఖ్యమైన వాస్తు/జ్యోతిష్య చిట్కాను క్షణాల్లో తెలుసుకోవచ్చు. "
            f"నిత్య జీవితంలో వెంటనే ఆచరించదగిన అత్యంత విలువైన శాస్త్రీయ పరిష్కారాన్ని ఇందులో వివరించడం జరిగింది. "
            f"త్వరిత అవగాహన కోసం పైన ఉన్న లింక్ ద్వారా ఈ షార్ట్ వీడియోను నేరుగా వీక్షించండి."
        )
    else:  # spiritual
        return (
            f"ఈ వీడియోలో '{clean_t}' యొక్క విశిష్ట ఆధ్యాత్మిక ప్రాముఖ్యత మరియు పురాణ విశేషాలు సమగ్రంగా పొందుపరచబడ్డాయి. "
            f"సనాతన ధర్మం, క్షేత్ర మహిమ మరియు దైవిక శక్తుల అనుగ్రహాన్ని పొందే ఆచారాలను సవివరంగా తెలియజేశారు. "
            f"అంతర్గత శాంతి మరియు భక్తి మార్గంలో ఉన్నతి సాధించడానికి అవసరమైన మార్గదర్శకాలను అందించారు. "
            f"పూర్తి ఆధ్యాత్మిక సమాచారం కోసం పైన ఉన్న లింక్ ద్వారా వీడియోను దర్శించండి."
        )


def sync_website_data() -> dict:
    log.info("Starting website data synchronization from master_schedule.json...")

    if not SCHEDULE_FILE.exists():
        log.error("master_schedule.json not found at %s", SCHEDULE_FILE)
        return {"count": 0, "success": False}

    with open(SCHEDULE_FILE, encoding="utf-8-sig") as f:
        schedule = json.load(f)

    if not isinstance(schedule, list):
        schedule = schedule.get("items", [])

    # Ensure books catalog is also generated
    generate_books_data()

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
        summary_te = generate_telugu_summary(title, clean_desc, category_slug)

        thumb_url = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        fallback_thumb = f"https://img.youtube.com/vi/{vid}/0.jpg"
        video_url = f"https://www.youtube.com/shorts/{vid}" if is_short else f"https://www.youtube.com/watch?v={vid}"

        processed_videos.append({
            "id": item.get("id", f"yt_{vid}"),
            "video_id": vid,
            "title": title,
            "summary_telugu": summary_te,
            "description": clean_desc[:240] + ("..." if len(clean_desc) > 240 else ""),
            "full_description": clean_desc,
            "upload_date": upload_date,
            "date_display": formatted_date,
            "url": video_url,
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
    log.info("Updated legacy %s", LEGACY_JSON)

    # Embed data into index.html
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

        # 1. Update Videos
        v_json_str = json.dumps(videos, ensure_ascii=False)
        v_pattern = r"window\.__SAMARTHA_VIDEOS__\s*=\s*\[.*?\];"
        v_replacement = f"window.__SAMARTHA_VIDEOS__ = {v_json_str};"
        if re.search(v_pattern, content, flags=re.DOTALL):
            content = re.sub(v_pattern, lambda _: v_replacement, content, flags=re.DOTALL)
            log.info("Updated embedded window.__SAMARTHA_VIDEOS__ inside index.html")

        # 2. Update Books
        if BOOKS_JSON_FILE.exists():
            with open(BOOKS_JSON_FILE, encoding="utf-8") as f:
                books_data = json.load(f)
            b_json_str = json.dumps(books_data, ensure_ascii=False)
            b_pattern = r"window\.__SAMARTHA_BOOKS__\s*=\s*\[.*?\];"
            b_replacement = f"window.__SAMARTHA_BOOKS__ = {b_json_str};"
            if re.search(b_pattern, content, flags=re.DOTALL):
                content = re.sub(b_pattern, lambda _: b_replacement, content, flags=re.DOTALL)
                log.info("Updated embedded window.__SAMARTHA_BOOKS__ inside index.html")

        INDEX_HTML_FILE.write_text(content, encoding="utf-8")
    except Exception as exc:
        log.warning("Could not update embedded data in index.html: %s", exc)


if __name__ == "__main__":
    res = sync_website_data()
    print(f"Website Sync Complete: {res['count']} videos exported.")
