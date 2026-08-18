# Hermes Bot Mode Showcase Reel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble, fine-tune, render, and mux a high-engagement 9:16 vertical showcase video combining the Hermes Bot Mode screen recording walkthrough with the AI Avatar presenter, dynamic camera tracking, feature badges, and word-synced Thai karaoke captions.

**Architecture:** Hand-authored Remotion React composition (`HermesBotReel.tsx`) rendering 720x1280 @ 30fps with OffthreadVideo elements for screen recording and avatar, dynamic cosine camera transformations, custom Kanit typography, and post-render FFmpeg lossless 48kHz audio muxing.

**Tech Stack:** Remotion (React), TypeScript, FFmpeg, Whisper word timestamps.

## Global Constraints

- Design Space: 1080x1920 scaled to 720x1280 output (9:16 vertical ratio).
- Framerate: 30 FPS.
- Duration: 118.0 seconds (3,540 frames).
- Screen Recording Asset: `/Volumes/Ext_SS990Pro/Dev/browser-task-recorded/hermes-bot-mode-overview.mp4`.
- AI Avatar Video Asset: `/Users/nunmacminim4pro/Downloads/วิดีโออวตาร_720p (15).mp4`.
- Audio Track: Original 48kHz Stereo AAC from Avatar video, remuxed via FFmpeg without pitch or timing distortion.
- Subtitle Look: Gold Glow Karaoke (Kanit ExtraBold, `#F59E0B` active highlight with drop shadow, `#F8FAFC` white spoken).

---

### Task 1: Verify and Copy Assets to Remotion Public Folder

**Files:**
- Modify: `remotion-composer/public/hermes-bot-mode-reel/avatar_source.mp4`
- Modify: `remotion-composer/public/hermes-bot-mode-reel/screen_recording.mp4`

**Interfaces:**
- Consumes: Raw files at `/Volumes/Ext_SS990Pro/Dev/browser-task-recorded/hermes-bot-mode-overview.mp4` and `/Users/nunmacminim4pro/Downloads/วิดีโออวตาร_720p (15).mp4`
- Produces: Public assets accessible via `staticFile("hermes-bot-mode-reel/...")`

- [ ] **Step 1: Check source asset integrity and ensure public directory exists**

```bash
mkdir -p remotion-composer/public/hermes-bot-mode-reel
cp "/Volumes/Ext_SS990Pro/Dev/browser-task-recorded/hermes-bot-mode-overview.mp4" "remotion-composer/public/hermes-bot-mode-reel/screen_recording.mp4"
cp "/Users/nunmacminim4pro/Downloads/วิดีโออวตาร_720p (15).mp4" "remotion-composer/public/hermes-bot-mode-reel/avatar_source.mp4"
```

- [ ] **Step 2: Verify asset sizes and durations**

```bash
ffprobe -v error -show_entries format=duration,size "remotion-composer/public/hermes-bot-mode-reel/screen_recording.mp4"
ffprobe -v error -show_entries format=duration,size "remotion-composer/public/hermes-bot-mode-reel/avatar_source.mp4"
```

- [ ] **Step 3: Commit asset setup**

```bash
git add remotion-composer/public/hermes-bot-mode-reel/
git commit -m "chore: ensure hermes bot reel source assets in public directory"
```

---

### Task 2: Polish Remotion Composition and Typecheck

**Files:**
- Modify: `remotion-composer/src/HermesBotReel.tsx`
- Modify: `remotion-composer/src/hermesBotCaptions.ts`
- Modify: `remotion-composer/src/Root.tsx`

**Interfaces:**
- Consumes: `CAPTION_PAGES` from `hermesBotCaptions.ts`
- Produces: Validated `HermesBotReel` component registered in `Root.tsx`

- [ ] **Step 1: Inspect and refine camera keyframes for maximum clarity**

Verify `CAMERA_KEYFRAMES` smoothly focus on:
1. Bot Roster (t: 12-24s)
2. Group Workspaces (t: 35-58s)
3. Bot-to-bot handoff (t: 61-74s)
4. Cron & Routines (t: 77-87s)
5. Summary & Outro (t: 89-118s)

- [ ] **Step 2: Run TypeScript typecheck in remotion-composer**

```bash
cd remotion-composer && npm run build
```

- [ ] **Step 3: Test single-frame preview render**

```bash
cd remotion-composer && npx remotion still HermesBotReel /tmp/hermes_preview_frame_300.png --frame=300
```

- [ ] **Step 4: Commit polished composition**

```bash
git add remotion-composer/src/HermesBotReel.tsx remotion-composer/src/hermesBotCaptions.ts remotion-composer/src/Root.tsx
git commit -m "feat(remotion): polish HermesBotReel camera keyframes and typography"
```

---

### Task 3: Full Remotion Video Render

**Files:**
- Create: `projects/hermes-bot-mode-showcase/renders/hermes_bot_silent.mp4`

**Interfaces:**
- Consumes: Remotion composition `HermesBotReel`
- Produces: 720x1280 30fps silent video master (3,540 frames)

- [ ] **Step 1: Prepare output directory**

```bash
mkdir -p projects/hermes-bot-mode-showcase/renders
```

- [ ] **Step 2: Execute Remotion render**

```bash
cd remotion-composer && npx remotion render HermesBotReel ../projects/hermes-bot-mode-showcase/renders/hermes_bot_silent.mp4 --concurrency=4
```

- [ ] **Step 3: Verify rendered video stream**

```bash
ffprobe -v error -show_entries stream=width,height,r_frame_rate,nb_frames,duration ../projects/hermes-bot-mode-showcase/renders/hermes_bot_silent.mp4
```

---

### Task 4: Audio Extraction and Lossless Multiplexing

**Files:**
- Create: `projects/hermes-bot-mode-showcase/assets/audio/master_audio.aac`
- Create: `projects/hermes-bot-mode-showcase/renders/Hermes_Bot_Mode_Showcase_Reel_720p.mp4`

**Interfaces:**
- Consumes: `avatar_source.mp4` (audio stream) + `hermes_bot_silent.mp4` (video stream)
- Produces: Complete, synchronized deliverable video file

- [ ] **Step 1: Extract master 48kHz stereo AAC audio from avatar video**

```bash
mkdir -p projects/hermes-bot-mode-showcase/assets/audio
ffmpeg -y -i "/Users/nunmacminim4pro/Downloads/วิดีโออวตาร_720p (15).mp4" -vn -c:a aac -b:a 192k projects/hermes-bot-mode-showcase/assets/audio/master_audio.aac
```

- [ ] **Step 2: Multiplex audio into silent Remotion video render**

```bash
ffmpeg -y -i projects/hermes-bot-mode-showcase/renders/hermes_bot_silent.mp4 -i projects/hermes-bot-mode-showcase/assets/audio/master_audio.aac -c:v copy -c:a copy -map 0:v:0 -map 1:a:0 -shortest projects/hermes-bot-mode-showcase/renders/Hermes_Bot_Mode_Showcase_Reel_720p.mp4
```

- [ ] **Step 3: Verify final deliverable specs and playback integrity**

```bash
ffprobe -v error -show_entries format=duration,size,bit_rate:stream=codec_name,width,height,r_frame_rate,sample_rate,channels -of json projects/hermes-bot-mode-showcase/renders/Hermes_Bot_Mode_Showcase_Reel_720p.mp4
```

- [ ] **Step 4: Commit deliverable record & plan completion**

```bash
git add docs/superpowers/plans/2026-08-18-hermes-bot-mode-reel.md
git commit -m "docs: add implementation plan for Hermes Bot Mode showcase reel"
```
