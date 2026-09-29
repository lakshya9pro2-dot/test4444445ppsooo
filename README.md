# DualSync Stream Player & Extractor Backend

A high-performance media extractor backend and synchronized HTML5 video player designed to combine and play **StreamTape video** with **Vidara multi-audio tracks** (Hindi & Telugu), featuring real-time synchronization, seamless audio switching, and automatic mutual fallbacks.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [How DualSync Works](#-how-dualsync-works)
  - [Dual Playback Architecture](#dual-playback-architecture)
  - [Mutual Fallback Logic](#mutual-fallback-logic)
  - [Multi-Audio Track Changer](#multi-audio-track-changer)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Starting the Backend](#starting-the-backend)
- [Player URL Formats](#-player-url-formats)
- [API Reference](#-api-reference)
  - [1. Parallel Resolver (`/api/resolve`)](#1-parallel-resolver-apiresolve)
  - [2. Multi-Audio HLS Master Playlist (`/playlist.m3u8`)](#2-multi-audio-hls-master-playlist-playlistm3u8)
  - [3. Generic Extractor (`/api/extract`)](#3-generic-extractor-apiextract)
  - [4. Dedicated Shortcuts](#4-dedicated-shortcuts)
- [Player Keyboard Shortcuts](#-player-keyboard-shortcuts)
- [Project Structure](#-project-structure)

---

## 🌟 Overview

Media hosted on platforms like **StreamTape** (MP4) and **Vidara** (HLS `.m3u8`) often have distinct advantages: StreamTape provides direct progressive MP4 video streams, while Vidara provides high-bitrate multi-lingual audio tracks (such as Hindi and Telugu).

This project integrates both into a unified, zero-lag playback experience:
- **Video Source**: StreamTape MP4 (muted).
- **Audio Source**: Vidara HLS Audio (unmuted), selectable between Hindi and Telugu.
- **Backend Service**: Lightweight Flask service running on port `4447` with parallel token extraction and HLS manifest generation.

---

## ✨ Key Features

- **⚡ Fast Parallel Extraction**: Resolves both media tokens simultaneously in ~0.6 seconds using `ThreadPoolExecutor`.
- **💬 WebVTT Subtitles (Closed Captions)**: Automatic detection, fetching, and millisecond-accurate cue parsing for WebVTT (`.vtt`) subtitles, rendered dynamically on screen with multi-language selector and keyboard shortcut toggle.
- **🖼️ Poster & Thumbnail Previews**: Automatically extracts cover thumbnails from stream metadata and binds them to player video posters, ambient background backdrops, and diagnostics card previews.
- **🎧 Multi-Audio Track Changer**: Switch between **Original Audio (Fast)** [Default], **Hindi (MS)**, and **Telugu (MS)** on the fly without stopping, reloading, or re-buffering the video stream.
- **🔄 Dual Synchronization Engine**:
  - Continuous drift monitor auto-aligns audio if desynchronization exceeds `250ms`.
  - Buffer synchronization pauses the partner stream if either stream buffers or stalls.
  - User-adjustable audio offset controls (`[-50ms]`, `[+50ms]`, `[Reset]`).
- **🛡️ Mutual Fallbacks**:
  - If Primary stream fails or returns a 404, automatically plays Secondary stream video + audio.
  - If Secondary stream fails, automatically un-mutes and plays Primary stream video + audio.
- **🌐 Full CORS Compatibility**: Built-in `Access-Control-Allow-Origin: *` headers for all API and media endpoints.

---

## 🧠 How DualSync Works

### Dual Playback Architecture

```
                 +----------------------------------------------------+
                 |                   Browser Player                   |
                 |                                                    |
                 |  +--------------------+    +--------------------+  |
                 |  | StreamTape Video   |    | Vidara Audio       |  |
                 |  | (Visible, Muted)   |    | (Hidden, Unmuted)  |  |
                 |  +---------+----------+    +---------+----------+  |
                 |            |                         |             |
                 |            +------------+------------+             |
                 |                         |                          |
                 |               Synchronization Loop                 |
                 |          (Play, Pause, Seek, Drift <0.25s)         |
                 +----------------------------------------------------+
```

### Mutual Fallback Logic

| Scenario | Primary Video Layer | Active Audio Track | Fallback Trigger |
| :--- | :--- | :--- | :--- |
| **Normal (Dual Mode)** | **StreamTape** (Muted) | **Vidara HLS** (Hindi/Telugu) | Both streams valid |
| **StreamTape Fails** | **Vidara** (Unmuted) | **Vidara HLS** | ST 404, token failure, or video error |
| **Vidara Fails** | **StreamTape** (Unmuted) | **StreamTape** (Native) | VA API error or HLS load failure |

### Multi-Audio Track Changer

The player includes built-in multi-audio tracks:

| Track Name | Language Code | Manifest URI | Default |
| :--- | :--- | :--- | :--- |
| **Original Audio (Fast)** | `original` | Native MP4 Audio Track | **Yes** |
| **Hindi (MS)** | `hindi-(ms)` | `https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8` | No |
| **Telugu (MS)** | `telugu-(ms)` | `https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8` | No |
| **Muted** | — | All audio tracks muted | Optional |

---

## 🚀 Getting Started

### Prerequisites

- **Python**: 3.10+ (with `flask` and `requests` installed)
- **Node.js**: (optional, used for fast JS token evaluation)

```bash
pip install flask requests
```

### Starting the Backend

To start the backend server on port `4447`:

```bash
python3 /home/linux/Downloads/app.py
```

To stop the backend server:

```bash
fuser -k 4447/tcp
```

---

## 🔗 Player URL Formats

Open any of the following URLs in your web browser:

### 1. Compound Path Format
```
http://localhost:4447/player.html/st?play=0A2vDYQz3wIbPQ6(id)/va?playd=d932127894f1(id)
```

### 2. Standard Query Parameter Format
```
http://localhost:4447/player.html?st=0A2vDYQz3wIbPQ6&va=d932127894f1
```

### 3. Single Stream Formats
```
# Primary Only
http://localhost:4447/player.html?st=0A2vDYQz3wIbPQ6

# Secondary Only (with Subtitles & Thumbnail)
http://localhost:4447/player.html?va=fea967f75055
```

### 4. Dual Stream with Subtitles & Thumbnail Preview
```
http://localhost:4447/player.html/st?play=0A2vDYQz3wIbPQ6(id)/va?playd=fea967f75055(id)
```

---

## 📡 API Reference

### 1. Parallel Resolver (`/api/resolve`)

Resolves both media streams concurrently and outputs the recommended playback mode, cover thumbnail, subtitles, and audio tracks.

- **URL**: `/api/resolve` or `/api/resolve/<subpath>`
- **Method**: `GET` or `POST`
- **Parameters**: `st` (Primary ID/URL), `va` (Secondary ID/URL)

```bash
curl "http://localhost:4447/api/resolve?st=0A2vDYQz3wIbPQ6&va=fea967f75055"
```

**Response Example:**
```json
{
  "status": "success",
  "mode": "dual",
  "st_id": "0A2vDYQz3wIbPQ6",
  "va_id": "fea967f75055",
  "thumbnail": "https://m696yefd.s1q2105.com/thumbnail/RX0nm3bGkZ/fea967f75055.jpg",
  "subtitles": [
    {
      "id": 1635710,
      "language": "English (MS)",
      "file_path": "https://m696yefd.s1q2105.com/subtitles/ucpQNqa1Qm/zrQZY0pecxbmaV5_subtitle_0.vtt",
      "status": 1
    }
  ],
  "primary": {
    "status": "success",
    "source": "Primary Server",
    "title": "Nilakanta.2026.UNCUT.1080p...",
    "url": "https://.../get_video?...",
    "stream_type": "mp4"
  },
  "secondary": {
    "status": "success",
    "source": "Secondary Server",
    "title": "video",
    "url": "https://.../master.m3u8",
    "stream_type": "m3u8",
    "thumbnail": "https://m696yefd.s1q2105.com/thumbnail/RX0nm3bGkZ/fea967f75055.jpg",
    "subtitles": [ ... ]
  },
  "audio_tracks": [
    {
      "id": "original",
      "name": "Original Audio (Fast)",
      "language": "original",
      "default": true,
      "url": null
    },
    {
      "id": "hindi",
      "name": "Hindi (MS)",
      "language": "hindi-(ms)",
      "default": false,
      "url": "https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8"
    },
    {
      "id": "telugu",
      "name": "Telugu (MS)",
      "language": "telugu-(ms)",
      "default": false,
      "url": "https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8"
    }
  ]
}
```

---

### 2. Multi-Audio HLS Master Playlist (`/playlist.m3u8`)

Generates a standard HLS master manifest associating the 1080p video stream with the Hindi and Telugu audio tracks.

```bash
curl "http://localhost:4447/playlist.m3u8"
```

**Manifest Content:**
```m3u8
#EXTM3U
#EXT-X-VERSION:6

# Audio Track 1: Hindi (MS)
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Hindi (MS)",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="hindi-(ms)",URI="https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8"
# Audio Track 2: Telugu (MS)
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Telugu (MS)",DEFAULT=NO,AUTOSELECT=YES,LANGUAGE="telugu-(ms)",URI="https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8"

# Video Stream
#EXT-X-STREAM-INF:BANDWIDTH=5000000,AVERAGE-BANDWIDTH=5000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1998x1080,FRAME-RATE=30.000,AUDIO="audio"
https://s13-25t.s1q2105.com/hls/XllfQzImUDsHoOts9WN4Bo8BhuzGNx8T/index_1998x1080.m3u8
```

---

### 3. Generic Extractor (`/api/extract`)

Extracts stream URL and metadata from any StreamTape or Vidara URL (including mirror domains).

```bash
# JSON Output
curl "http://localhost:4447/api/extract?url=https://streamtape.com/v/0A2vDYQz3wIbPQ6/"

# Plain Text Output
curl "http://localhost:4447/api/extract?url=https://vidara.to/v/d932127894f1&format=text"
```

---

### 4. Dedicated Shortcuts

| Route | Content-Type | Description |
| :--- | :--- | :--- |
| `GET /api/streamtape` | `application/json` | JSON stream URL and title for StreamTape default link |
| `GET /api/vidara` | `application/json` | JSON stream URL and title for Vidara default link |
| `GET /text/streamtape` | `text/plain` | Plain text (`Text: ... \n URL: ...`) for StreamTape |
| `GET /text/vidara` | `text/plain` | Plain text (`Text: ... \n URL: ...`) for Vidara |
| `GET /health` | `application/json` | Server health check (`{"status": "ok", "port": 4447}`) |

---

## ⌨️ Player Keyboard Shortcuts

| Key | Action |
| :--- | :--- |
| **`Space`** or **`K`** | Toggle Play / Pause |
| **`A`** | Cycle Audio Track (`Original Audio (Fast)` ➔ `Hindi (MS)` ➔ `Telugu (MS)` ➔ `Muted`) |
| **`C`** | Toggle Subtitles / Closed Captions On / Off |
| **`Left Arrow`** | Seek Backward 5 seconds |
| **`Right Arrow`** | Seek Forward 5 seconds |
| **`M`** | Toggle Mute |
| **`F`** | Toggle Fullscreen |

---

## 📁 Project Structure

```
.
├── app.py              # Flask backend server on port 4447 with parallel extractors
├── player.html         # HTML5 dual-playback synchronized video player
├── hls.min.js          # Standalone HLS.js library for offline/local playback
├── StreamTape.kt       # Original CloudStream3 Kotlin extractor for StreamTape
├── Vidara.kt           # Original CloudStream3 Kotlin extractor for Vidara
└── README.md           # Project documentation and API reference
```
