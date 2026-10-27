# SAMARTHA ASTRO-VASTU (సమర్థ ఆస్ట్రో-వాస్తు)

> **వాస్తు • జ్యోతిష్య • తాంత్రిక • ఆధ్యాత్మిక విజ్ఞాన పీఠం**  
> Official Digital Portal & Automated Publishing Engine for **Samartha Astro-Vastu** (`@samarthavastu999`).  
> **Founder & Principal Consultant:** శ్రీ S.V.S.N. రాజు (M.A. Astrology & Vastu, Potti Sreeramulu Telugu University, Hyderabad)

---

## 🌟 Overview & Mission

**SAMARTHA ASTRO-VASTU** is dedicated to bringing authentic, Vedic, and scientific Vastu Shastra, Jyotisha, Tantrika, and Spiritual guidance to households worldwide.

> *"సమర్థ ఆస్ట్రో-వాస్తు – మీ ఇంటికి శాంతి, ఐశ్వర్యం, ఆరోగ్యం 🏡"*  
> ✨ ఇంటి వాస్తు చిట్కాలు | ✨ వ్యాపార వాస్తు సూచనలు | ✨ ప్లాట్ & భవనం వాస్తు విశ్లేషణ | ✨ దోష నివారణ మార్గాలు | ✨ శాస్త్రీయంగా, సులభంగా అర్థమయ్యే వాస్తు పరిష్కారాలు  
> **లక్ష్యం:** అనేక సమస్యలు మరియు దుఃఖాన్ని నివారించడానికి లేదా బయటపడటానికి స్వావలంబన పొందడానికి సామాన్యులకు ఈ జ్ఞానాన్ని పంచడం. వారి జీవితాలను సంతోషపెట్టడానికి — వాస్తు జ్ఞానం = జీవన మార్పు.

---

## 🌐 Official Channels & Portals

- **Live Website:** [https://vssomarajupalli-lgtm.github.io/samarthavastu-hub/](https://vssomarajupalli-lgtm.github.io/samarthavastu-hub/)
- **YouTube Channel:** [https://www.youtube.com/channel/UCDtcb0drjmLgG3ARTh4e7jw](https://www.youtube.com/channel/UCDtcb0drjmLgG3ARTh4e7jw) (`@samarthavastu999`)
- **Facebook:** [https://www.facebook.com/samarthavastu999](https://www.facebook.com/samarthavastu999)
- **X (Twitter):** [https://twitter.com/samarthavastu1](https://twitter.com/samarthavastu1)
- **Instagram:** [https://www.instagram.com/samarthavastu999](https://www.instagram.com/samarthavastu999)
- **WhatsApp Consultation:** `+91 8919395559` | **Email:** `samarthavastu999@gmail.com`

---

## 🏛️ Core Features

### 1. 4-Service Consultation Booking Flow
Direct interactive WhatsApp consultation booking with pre-filled details sent straight to Sri S.V.S.N. Raju:
1. **గృహ వాస్తు (Home Vastu):** Scientific, non-demolition analysis with subtle color and spatial corrections.
2. **ప్లాట్ & స్థల ఎంపిక (Plot Selection):** 100% Google Earth satellite compass verification and street thrust (`వీధి పోట్లు`) analysis.
3. **వ్యాపార & పారిశ్రామిక వాస్తు (Commercial Vastu):** Cash-flow acceleration and directional alignments for shops, factories, and offices.
4. **జాతకం & శుభ ముహూర్తాలు (Horoscope & Muhurtham):** Birth chart analysis, Dasha predictions, marriage compatibility, and auspicious Muhurthams.

### 2. 16 Classical Ancient Texts (ఉచిత శాస్త్ర గ్రంథాలయం)
Comprehensive digital library of 16 foundational Sanskrit-Telugu treatises, each featuring a verified 3-page Telugu summary reader, language badges (`[తెలుగు తాత్పర్యం]`, `[సంస్కృతం - తెలుగు]`, `[Sanskrit / English]`), and direct permanent links to Archive.org digital readers:
- **వాస్తు గ్రంథాలు:** విశ్వకర్మ ప్రకాశిక, మయమతం, మానసారం, సమరాంగణ సూత్రధార.
- **జ్యోతిష్య గ్రంథాలు:** బృహత్ పరాశర హోరా శాస్త్రం, బృహత్ జాతకం, ఫలదీపిక, ముహూర్త చింతామణి.
- **తాంత్రిక & మంత్ర విద్యలు:** మహానిర్వాణ తంత్రం, శారదా తిలక తంత్రం, యంత్ర చింతామణి, మంత్ర మహోదధి.
- **ఆధ్యాత్మిక & పారానార్మల్:** గరుడ పురాణం, శివ సంహిత, సౌందర్య లహరి, ప్రశ్నోపనిషత్తు.

### 3. High-Performance Categorized Video Explorer
- Instant dynamic filtering across 6 categories: All (105+), Vastu Shastra (49), Jyotisha (18), Tantrika (6), Paranormal & Rebirth (16), Spiritual (5), and Shorts (11).
- 12-card initial load with dynamic pagination (`➕ మరిన్ని వీడియోలు చూడండి`).
- Truly unique, topic-specific 3-sentence Telugu summaries generated per video (eliminating repeated YouTube boilerplate).
- Schema data footprint slimmed by ~76% (from 730 KB down to 173 KB).

---

## ⚙️ Architecture & Autonomous Automation

### "Hold-and-Carry-Forward" Queue Architecture (`auto_publisher.py`)
To prevent missed publications when the host laptop is kept closed or powered off for several days:
1. **Hold & Carry-Forward Lock:** A pending video marked `"status": "preview_approved"` is held and strictly published first upon the next system start, regardless of how many calendar days elapsed.
2. **Deterministic Resumption:** Stage A publication checks `pub_at.startswith(today_str)` rather than `sched_date == today_str`, preventing accidental queue jumps.
3. **Accurate Date Tracking:** When an item completes Stage A, its `scheduled_date` is updated to the actual execution date `datetime.now().strftime("%Y-%m-%d")`.
4. **Two-Stage Workflow:**
   - **Stage A (Daily 8:00 AM / Boot):** Multi-platform broadcast (YouTube Shorts, Facebook Page, Instagram, and WhatsApp Community Group `DvPDx43oel4LQQgqCsn7Tr`).
   - **Stage B:** Generates the next day's high-retention 9:16 Short video, synthesizes Telugu audio via Edge TTS (`te-IN-MohanNeural`), generates subtitle burn-ins via FFmpeg, uploads to Google Drive, and sends a private WhatsApp preview with action buttons to Admin (`+918919395559`).

### Autonomous Startup & Scheduler Integration
- **Windows Task Scheduler:** `SamarthaVastu_Daily_8AM` runs daily at 08:00 AM IST via `run_daily.ps1`.
- **Boot Sync:** `SamarthaVastu_BootSync.vbs` in Windows Startup directory guarantees execution upon first login each day if the 8 AM window was missed.

---

## 🛠️ Repository Structure

```text
samarthavastu-hub/
├── auto_publisher.py         # Autonomous multi-platform publishing engine (Stage A & Stage B)
├── website_sync.py           # Exports master schedule to slim JSON and embeds into HTML
├── books_library.py          # Classical 16-book catalog, summaries, and Archive.org links
├── run_daily.ps1             # PowerShell entry point for Task Scheduler
├── SamarthaVastu_BootSync.vbs# Silent startup trigger
├── public/
│   ├── index.html            # Ultra-fast, single-page responsive portal with gold aesthetics
│   ├── videos_data.json      # Slimmed 105+ video dataset (173 KB)
│   ├── books_data.json       # 16 classical books metadata
│   └── assets/
│       ├── channel_banner.jpg# Official YouTube channel banner
│       └── founder_raju.jpg  # Founder portrait in gold circular halo
└── vastu_content_queue/
    └── master_schedule.json  # Central queue tracking all published and preview items
```

---

## 📜 License & Copyright

© 2026 **SAMARTHA ASTRO-VASTU** (`@samarthavastu999`). All Rights Reserved.  
Content curated and presented by **శ్రీ S.V.S.N. రాజు**.
