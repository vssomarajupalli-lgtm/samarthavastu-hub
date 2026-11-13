import os
import json
import numpy as np
from datetime import datetime
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.VideoClip import TextClip
import moviepy.video.fx as vfx

# Try to import librosa for advanced Voice Activity Detection
try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    print("[INFO] librosa not available - will use fallback volume-based voice detection")

# Try to import yt_dlp for YouTube downloading
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    print("[INFO] yt_dlp not available - YouTube download disabled")

SCHEDULE_PATH = "E:/samarthavastu-hub/vastu_content_queue/master_schedule.json"


def get_todays_scheduled_video(schedule_path: str = SCHEDULE_PATH):
    """
    Read master_schedule.json and find the FIRST item where:
    - scheduled_date equals today's date (YYYY-MM-DD)
    - status is either "preview_approved" or "pending"
    - is_short is False (landscape videos only)
    Returns (video_id, youtube_url) or (None, None) if not found.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(schedule_path, "r", encoding="utf-8-sig") as f:
            schedule = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load schedule: {e}")
        return None, None

    for item in schedule:
        scheduled_date = item.get("scheduled_date") or ""
        status = item.get("status") or ""
        is_short = item.get("is_short", False)
        video_id = item.get("video_id")

        if scheduled_date == today_str and status in ("preview_approved", "pending") and not is_short and video_id:
            youtube_url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"[INFO] Found today's scheduled video: {item['id']} ({video_id}) - {item.get('title', '')[:50]}")
            return video_id, youtube_url

    print(f"[INFO] No pending landscape video scheduled for today ({today_str}).")
    return None, None


def download_youtube_video(url: str, output_path: str) -> bool:
    """
    Use yt_dlp to download the best mp4 format.
    Returns True on success, False on failure.
    """
    if not YT_DLP_AVAILABLE:
        print("[ERROR] yt_dlp not available - cannot download YouTube video")
        return False

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': False,
        'merge_output_format': 'mp4',
    }

    try:
        print(f"[INFO] Downloading YouTube video from: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"[SUCCESS] Video downloaded to: {output_path}")
        return True
    except Exception as e:
        print(f"[ERROR] YouTube download failed: {e}")
        return False

def detect_voice_start_librosa(audio_data, sr=16000, scan_duration=20):
    """
    Use librosa for true Voice Activity Detection.
    Computes spectral features over time to distinguish speech from music.
    Speech has: higher spectral centroid, wider bandwidth, higher flatness, more onsets.
    Returns the timestamp (in seconds) of the first detected speech segment.
    """
    try:
        # Limit to scan_duration seconds
        max_samples = sr * scan_duration
        if len(audio_data) > max_samples:
            audio_data = audio_data[:max_samples]
        
        # Convert to mono if stereo
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        # Frame parameters
        hop_length = 512      # ~32ms at 16kHz
        frame_length = 2048   # ~128ms at 16kHz
        
        # Compute spectral features over time
        # 1. Spectral centroid - speech has higher centroid than tonal music
        centroid = librosa.feature.spectral_centroid(y=audio_data, sr=sr, hop_length=hop_length, n_fft=frame_length)[0]
        
        # 2. Spectral bandwidth - speech has wider bandwidth
        bandwidth = librosa.feature.spectral_bandwidth(y=audio_data, sr=sr, hop_length=hop_length, n_fft=frame_length)[0]
        
        # 3. Spectral flatness - speech is less tonal (higher flatness) than pure-tone music
        flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length, n_fft=frame_length)[0]
        
        # 4. Spectral rolloff - speech energy extends to higher frequencies
        rolloff = librosa.feature.spectral_rolloff(y=audio_data, sr=sr, hop_length=hop_length, n_fft=frame_length)[0]
        
        # 5. Onset strength - speech has more transient onsets than sustained music
        onset_env = librosa.onset.onset_strength(y=audio_data, sr=sr, hop_length=hop_length)
        
        # 6. Zero crossing rate - speech has higher ZCR
        zcr = librosa.feature.zero_crossing_rate(audio_data, hop_length=hop_length)[0]
        
        # 7. RMS energy - for normalization
        rms = librosa.feature.rms(y=audio_data, hop_length=hop_length)[0]
        
        n_frames = len(centroid)
        if n_frames == 0:
            return None
        
        # Normalize features to [0, 1] range using robust statistics (median + IQR)
        def robust_normalize(x):
            med = np.median(x)
            iqr = np.percentile(x, 75) - np.percentile(x, 25)
            if iqr == 0:
                return np.zeros_like(x)
            return np.clip((x - med) / (1.5 * iqr + 1e-10), -3, 3)
        
        # Features that are HIGHER for speech
        centroid_norm = robust_normalize(centroid)
        bandwidth_norm = robust_normalize(bandwidth)
        flatness_norm = robust_normalize(flatness)
        rolloff_norm = robust_normalize(rolloff)
        onset_norm = robust_normalize(onset_env)
        zcr_norm = robust_normalize(zcr)
        
        # Combine into speech-likeness score (weighted sum)
        # Weights based on discriminative power for music vs speech
        speech_score = (
            0.25 * centroid_norm +
            0.20 * bandwidth_norm +
            0.20 * flatness_norm +
            0.15 * rolloff_norm +
            0.10 * onset_norm +
            0.10 * zcr_norm
        )
        
        # Smooth the score with a small median filter to reduce frame-level noise
        from scipy.ndimage import median_filter
        speech_score_smooth = median_filter(speech_score, size=5)
        
        # Find frames where speech score exceeds threshold
        # Threshold: 80th percentile (lower to catch transition earlier)
        threshold = np.percentile(speech_score_smooth, 80)
        
        speech_frames = np.where(speech_score_smooth > threshold)[0]
        
        if len(speech_frames) > 0:
            # Use sliding window to find first sustained speech region
            # Window of ~10 frames (~320ms), require at least 6 frames above threshold
            window_size = 10
            min_speech_in_window = 6
            
            for i in range(len(speech_score_smooth) - window_size + 1):
                window_frames = speech_frames[
                    (speech_frames >= i) & (speech_frames < i + window_size)
                ]
                if len(window_frames) >= min_speech_in_window:
                    # Found sustained speech region, return the first frame in window
                    voice_start_frame = window_frames[0]
                    voice_start_time = voice_start_frame * hop_length / sr
                    print(f"[INFO] VAD (librosa spectral): Voice detected at {voice_start_time:.2f}s (score={speech_score_smooth[voice_start_frame]:.2f}, threshold={threshold:.2f})")
                    return voice_start_time
        
        # Fallback: use librosa.effects.split on full signal as last resort
        intervals = librosa.effects.split(audio_data, top_db=35, frame_length=frame_length, hop_length=hop_length)
        if len(intervals) > 0:
            voice_start_time = intervals[0][0] / sr
            print(f"[INFO] VAD (librosa split fallback): Voice detected at {voice_start_time:.2f}s")
            return voice_start_time
        
        print("[INFO] VAD (librosa): No clear speech onset detected")
        return None
            
    except Exception as e:
        print(f"[WARNING] librosa VAD failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def detect_voice_start_fallback(audio_data, sr=16000, scan_duration=15):
    """
    Fallback: Simple volume-based detection (original method).
    """
    try:
        max_samples = sr * scan_duration
        if len(audio_data) > max_samples:
            audio_data = audio_data[:max_samples]
        
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)
        
        volumes = np.sqrt(np.mean(audio_data**2))
        # Simple threshold: 20% of max
        threshold = np.max(np.abs(audio_data)) * 0.20
        for i, sample in enumerate(audio_data):
            if np.abs(sample) > threshold:
                return i / sr
        return None
    except Exception as e:
        print(f"[WARNING] Fallback voice detection failed: {e}")
        return None


def process_video_to_reel(input_video_path, output_reel_path):
    print(f"[INFO] Processing {input_video_path} into a Reel...")
    
    # 1. Load Original Video
    clip = VideoFileClip(input_video_path)
    
    # 2. Find Voice Start (Scanning first 20 seconds with librosa VAD)
    print("[INFO] Scanning audio to detect voice start...")
    start_time = 0.0
    try:
        # Extract audio chunk using moviepy
        audio_chunk = clip.audio.subclipped(0, min(20, clip.duration))
        audio_data = audio_chunk.to_soundarray(fps=16000)
        
        # Try librosa VAD first (true voice detection)
        voice_start = None
        if LIBROSA_AVAILABLE:
            voice_start = detect_voice_start_librosa(audio_data, sr=16000, scan_duration=20)
        
        # Fallback to volume-based detection
        if voice_start is None:
            print("[INFO] Falling back to volume-based voice detection...")
            voice_start = detect_voice_start_fallback(audio_data, sr=16000, scan_duration=15)
        
        if voice_start is not None:
            start_time = voice_start
        else:
            print("[WARNING] All voice detection methods failed. Defaulting to 10s.")
            start_time = 10.0
            
        print(f"[INFO] Voice detected at {start_time:.2f} seconds.")
    except Exception as e:
        print(f"[WARNING] Audio scan failed: {e}. Defaulting to 10s.")
        start_time = 10.0
        
    # 3. Trim 57 seconds
    end_time = min(start_time + 57.0, clip.duration)
    trimmed = clip.subclipped(start_time, end_time)
    print(f"[INFO] Trimmed video from {start_time:.2f}s to {end_time:.2f}s")
    
    # 4. Create 9:16 Canvas (1080x1920)
    print("[INFO] Converting to 9:16 vertical format...")
    # Main video in center (resized to fit width 1080)
    main_video = trimmed.resized(width=1080).with_position("center")
    
    # Background video (stretched to height 1920 and darkened)
    bg_video = trimmed.resized(height=1920).cropped(x_center=trimmed.w/2, width=1080)
    bg_video = bg_video.with_effects([vfx.MultiplyColor(0.3)]) # Darkens the background by 70% to make main video pop
    
    # Telugu Text Overlay - "Watch full video, check link below"
    print("[INFO] Adding Telugu text overlay...")
    telugu_text = "📺 పూర్తి వీడియో కోసం\nకింద లింక్ చూడండి 👇"
    try:
        # Try to find a Telugu-supporting font on Windows
        telugu_font = None
        for font_name in ["Nirmala", "Gautami", "Arial-Unicode-MS", "Nirmala-UI", "Microsoft Sans Serif"]:
            try:
                text_clip = TextClip(
                    text=telugu_text,
                    font=font_name,
                    font_size=55,
                    color="yellow",
                    stroke_color="black",
                    stroke_width=3,
                    method="caption",
                    size=(1000, None)
                )
                telugu_font = font_name
                print(f"[INFO] Using font: {font_name} for Telugu text")
                break
            except Exception:
                continue
        
        if text_clip is not None:
            # Position at bottom center of 1080x1920 canvas
            text_clip = text_clip.with_position(("center", 1600)).with_duration(trimmed.duration)
            print(f"[INFO] Telugu text overlay added at position (center, 1600)")
        else:
            print("[WARNING] No suitable Telugu font found, skipping text overlay")
    except Exception as e:
        print(f"[WARNING] Failed to create Telugu text overlay: {e}")
        text_clip = None
    
    # 5. Composite and Export
    print("[INFO] Compositing final reel...")
    composite_clips = [bg_video, main_video]
    if text_clip is not None:
        composite_clips.append(text_clip)
    final_reel = CompositeVideoClip(composite_clips, size=(1080, 1920))
    
    print(f"[INFO] Exporting Reel to {output_reel_path} (This might take a few minutes)...")
    final_reel.write_videofile(
        output_reel_path, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac",
        preset="fast",
        threads=4
    )
    print(f"\n[SUCCESS] 🎬 Reel created successfully: {output_reel_path}")

    # Clean up memory
    clip.close()
    final_reel.close()

if __name__ == "__main__":
    print("="*50)
    print(" 🎬 Samartha Vastu - Video Engine (Phase 1 & 3)")
    print("="*50)

    # Check today's schedule and download the video
    video_id, youtube_url = get_todays_scheduled_video(SCHEDULE_PATH)

    if video_id and youtube_url:
        downloaded_path = "E:/samarthavastu-hub/downloaded_yt_video.mp4"
        output_path = "E:/samarthavastu-hub/final_reel_output.mp4"

        success = download_youtube_video(youtube_url, downloaded_path)
        if success and os.path.exists(downloaded_path):
            process_video_to_reel(downloaded_path, output_path)
        else:
            print("[ERROR] Failed to download YouTube video. Exiting.")
    else:
        print("[INFO] No pending landscape video scheduled for today. Exiting gracefully.")