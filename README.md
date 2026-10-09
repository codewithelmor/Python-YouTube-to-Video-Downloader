# YouTube to HEVC MP4 Downloader

A simple Python script to download **YouTube videos or entire playlists** as **MP4 files with x265 (HEVC) video and MP3 audio**, using `yt-dlp` and `FFmpeg`. You choose the video resolution (up to 8K) and the MP3 audio bitrate.

## Features
* **HEVC / x265 Video in MP4**: Downloads the best matching streams, then re-encodes the video to H.265 (HEVC) inside an `.mp4` container (tagged `hvc1` so it plays on Apple devices too).
* **Selectable Resolution**: For a single video, the script lists the resolutions that video actually offers (e.g. 8K, 4K, 2K, 1080p, 720p...) or lets you pick **Best available**. For playlists you choose a cap (8K, 4K, 2K, 1080p, 720p, 480p, 360p) and each video downloads at that resolution or the best one below it.
* **Selectable MP3 Audio Quality**: Choose 128, 192, 256, 320 kbps, or a custom bitrate. Audio is encoded as MP3 (stereo) inside the MP4.
* **Playlist Support**: Paste a playlist URL and every video is downloaded and encoded, organized into a subfolder named after the playlist. Unavailable/private videos are skipped, and one failed video won't stop the rest.
* **Choose What to Download**: Pick **video only**, **captions only**, or **both** at the start. Captions-only mode skips the video download, resolution and bitrate prompts entirely, so it is fast and doesn't need the x265/MP3 encoders (just FFmpeg).
* **English Captions**: Manual captions are used when available, otherwise auto-generated ones. They are saved as an `.srt` with exactly the same name as the video, e.g. `Artist - Title.mp4` and `Artist - Title.srt`, so players pick it up automatically. Auto-generated captions have their repeated rolling lines removed, and a matching plain-text transcript (`Artist - Title.txt`) is written alongside.
* **Standardized Filenames**: Files are saved as **`<artist> - <title>.mp4`**.
* **Automated & Clean Tagging**: If the artist's name is duplicated inside the title (e.g. *"Artist - Song Title"*), it is scrubbed from the title tag.
* **Startup Check**: The script verifies that FFmpeg is installed and includes the `libx265` and `libmp3lame` encoders before doing anything.

## Prerequisites

This project requires **FFmpeg** (a full build including `libx265` and `libmp3lame`) installed and available on your system PATH.

* **macOS**: `brew install ffmpeg`
* **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install ffmpeg`
* **Windows**: Download the binaries from the official [FFmpeg site](https://ffmpeg.org) and add the `bin` folder to your System Environment Variables (PATH).

---

## Setup Instructions

### 1. Clone or Create the Project
```bash
cd path/to/your/project
```

### 2. Create a Virtual Environment
* **macOS / Linux:**
  ```bash
  python3 -m venv venv
  ```
* **Windows:**
  ```cmd
  python -m venv venv
  ```

### 3. Activate the Virtual Environment
* **macOS / Linux:**
  ```bash
  source venv/bin/activate
  ```
* **Windows (Command Prompt):**
  ```cmd
  venv\Scripts\activate.bat
  ```
* **Windows (PowerShell):**
  ```powershell
  venv\Scripts\Activate.ps1
  ```
  *(Note: If you get a script execution error in PowerShell, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` first).*

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Usage

1. Run the script:
   ```bash
   python main.py
   ```
2. Paste your **YouTube video or playlist URL**.
3. Choose what to download:
   * `1` Video only (HEVC/x265 MP4)
   * `2` Captions only (English `.srt` + `.txt` transcript, no video)
   * `3` Both video and captions
4. Provide a **Target Directory** (e.g., `downloads`, `~/Videos/YouTube`, or leave blank for the current folder).
   * For a single video, the files are saved directly into this folder.
   * For a playlist, a subfolder named after the playlist is created inside it.
5. *(Video or both)* Choose your **video resolution** from the menu.
6. *(Video or both)* Choose your **MP3 audio bitrate** (128, 192, 256, 320 kbps, or custom).
7. The script downloads what you asked for. Video is re-encoded to HEVC + MP3 in an MP4, tagged, and the temporary source file is deleted. Captions are cleaned and saved next to it with the same file name.

---

## Encoding Settings

At the top of `main.py`:

```python
HEVC_CRF = "23"         # lower = better quality / bigger file (18-28 is the sane range)
HEVC_PRESET = "medium"  # ultrafast ... medium ... slow ... veryslow
```

## Notes

* **Encoding is CPU-heavy.** x265 is slow, especially at 4K and 8K. Expect long encode times for high resolutions; use a faster preset (e.g. `fast`) if needed.
* **Resolution availability depends on the video.** Many videos have nothing above 1080p. YouTube only serves 4K/8K for videos uploaded in those resolutions.
* **Re-encoding is lossy.** YouTube serves AV1/VP9/H.264, not HEVC, so converting to x265 re-compresses the video. Lower the CRF if you want to preserve more detail (at the cost of file size).
* **MP3 in MP4 compatibility.** MP3 audio inside an MP4 is valid and plays in VLC, mpv, and most modern players, but some players (notably certain Apple/TV apps) prefer AAC.
* **Captions:** Not every video has captions; if none exist, the script prints a warning and carries on. Manual captions are left exactly as uploaded; only YouTube's rolling auto-captions are de-duplicated. Set `WRITE_TRANSCRIPT_TXT = False` at the top of `main.py` to skip the `.txt` transcript.
* **Upscaling is not performed.** The chosen resolution is a maximum, never an upscale.

---

## Troubleshooting

* **"FFmpeg not found" / missing encoder:** Ensure FFmpeg is installed with `libx265` and `libmp3lame`, and that `ffmpeg` runs from your terminal. Restart your terminal/IDE after installing.
* **Download Fails / HTTP Errors:** YouTube changes frequently. Update `yt-dlp` inside your virtual environment:
  ```bash
  pip install --upgrade yt-dlp
  ```
* **Playlist Only Partially Downloads:** Some videos may be private, deleted, or region-locked. These are skipped and reported in the console.

## Deactivation
```bash
deactivate
```
