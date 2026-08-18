# Hermes Bot Mode Showcase Reel — Design Specification

**Date:** 2026-08-18  
**Topic:** Split-Zone AI Avatar + Screen Recording Video Reel (Hermes Bot Mode)  
**Status:** Approved by User  
**Target Medium:** 9:16 Vertical Reel (TikTok / IG Reels / YouTube Shorts / LinkedIn)  
**Resolution:** 720 x 1280 @ 30 FPS  
**Duration:** ~118.0 Seconds  

---

## 1. Overview & Objectives
Create a high-retention, studio-grade vertical showcase reel explaining **Hermes Bot Mode**. The composition pairs real screen recording walkthrough footage (`hermes-bot-mode-overview.mp4`) with a presenter-led AI Avatar video (`วิดีโออวตาร_720p (15).mp4`) seamlessly blended over pure black background, featuring dynamic camera zooming, synchronous feature pills, and glowing karaoke subtitles.

---

## 2. Media Assets & Contracts

| Asset Role | Source Path | Specs |
|---|---|---|
| **Screen Walkthrough** | `/Volumes/Ext_SS990Pro/Dev/browser-task-recorded/hermes-bot-mode-overview.mp4` | 1920x1080 @ 25fps, 110.56s duration |
| **AI Avatar Video** | `/Users/nunmacminim4pro/Downloads/วิดีโออวตาร_720p (15).mp4` | 1280x720 @ 25fps, 110.12s duration + 48kHz Stereo Audio |
| **Master Audio** | Extracted from Avatar MP4 | 48kHz Stereo AAC |
| **Subtitles** | Word-level Whisper timestamps | 72 precision Thai subtitle pages in `hermesBotCaptions.ts` |

---

## 3. Visual Architecture & Split-Zone Layout

### 3.1 1080x1920 Canvas Space (Downscaled to 720x1280 Output)
```
+-------------------------------------------------------------+
| TOP ZONE (0 - 920px)                                        |
| - Header Kicker & Dynamic Topic Badge (Cyan/Gold)           |
| - macOS Floating Glass Window (Red/Yellow/Green controls)   |
| - Screen Recording with Dynamic Camera Zoom (1.45x - 2.15x)  |
| - Interactive Feature Tracker Bar (5 core features)         |
+-------------------------------------------------------------+
| SEAM DIVIDER (920px) - Glowing Neon Hairline + Glass Blur   |
+-------------------------------------------------------------+
| BOTTOM ZONE (920 - 1920px)                                  |
| - AI Avatar Presenter (Cropped half-body, pure black blend) |
| - Gold Glow Thai Karaoke Subtitles across chest zone        |
+-------------------------------------------------------------+
```

### 3.2 Design Tokens & Theme
- **Theme:** Atelier Tech Dark Neon
- **Primary Accent:** Cyan (`#38BDF8`) & Royal Blue (`#3B82F6`)
- **Secondary Accent:** Gold (`#F59E0B`) & Emerald (`#10B981`)
- **Typography:** `KanitX` / `Kanit` Bold & ExtraBold for high-contrast Thai readability
- **Glassmorphism:** `rgba(15, 23, 42, 0.75)` backdrop with `rgba(56, 189, 248, 0.25)` hairline border

---

## 4. Camera Keyframes & Beat Choreography

The screen walkthrough viewport undergoes smooth cosine-interpolated camera transformations keyed to speech topics:

| Timestamp (s) | Beat Title | Focus Area | Zoom | Pan (X, Y) | Feature Badge |
|---|---|---|---|---|---|
| **0.0 – 11.5s** | Intro & Hero Overview | Full screen app overview | 1.55x | (0, 100) | `1 AI → MULTI-AGENT TEAM` |
| **11.5 – 34.3s** | Bot Roster & Personas | Bot list, persona roles, chats | 2.05x | (40, 20) | `NAMED BOTS & SEPARATE CHATS` |
| **34.3 – 60.8s** | Groups & Workspaces | Multi-bot group projects | 2.10x | (-40, -20) | `AI GROUP COLLABORATION` |
| **60.8 – 76.3s** | Agent-to-Agent Handoff | Bot-to-bot workflow pipeline | 2.15x | (-20, -50) | `AUTOMATIC TASK HANDOFF` |
| **76.3 – 88.6s** | Routines & Automation | Cron schedule & daily routines | 1.95x | (40, -70) | `HERMES CRON AUTOMATION` |
| **88.6 – 102.3s**| AI Workforce Impact | Multi-agent collaboration | 1.65x | (0, -10) | `PERSONAL AI ASSISTANTS` |
| **102.3 – 115.4s**| Summary & Business Value| Full workspace systematic impact | 1.50x | (0, 30) | `FAST · SYSTEMATIC · REAL BUSINESS` |
| **115.4 – 118.0s**| Endcard Outro | Final branding & takeaway | 1.45x | (0, 40) | `HERMES BOT MODE` |

---

## 5. Subtitle & Audio Pipeline

1. **Subtitles:**
   - Word-level synchronization using Whisper timing.
   - Active spoken word highlights in glowing Gold (`#F59E0B` with `text-shadow: 0 0 16px rgba(245,158,11,0.8)`).
   - Inactive words render in clean white (`#F8FAFC`).
2. **Audio Multiplexing:**
   - Remotion renders silent video master at 720x1280 @ 30fps.
   - FFmpeg remuxes lossless 48kHz audio track from original avatar footage with zero pitch shift or sync drift.

---

## 6. Verification & Quality Gates
- **Remotion Composition Build:** Check TypeScript types & asset bundle resolution in `remotion-composer/`.
- **Render Execution:** Render 3,540 frames (~118s @ 30fps) with hardware acceleration.
- **Audio/Video Sync Check:** Verify that avatar lip movements and karaoke text highlight match the audio stream perfectly.
- **Deliverable File:** Generate deliverable MP4 in `renders/` with proper metadata and playback confirmation.
