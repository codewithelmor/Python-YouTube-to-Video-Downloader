import glob
import html
import os
import re
import shutil
import subprocess
import textwrap
import yt_dlp

# ---------------------------------------------------------------------------
# Encoding settings (tweak to taste)
# ---------------------------------------------------------------------------
HEVC_CRF = "23"        # x265 quality: lower = better quality / bigger file (18-28 is the sane range)
HEVC_PRESET = "medium" # x265 speed: ultrafast ... medium ... slow ... veryslow

# Caption options
WRITE_TRANSCRIPT_TXT = True   # also write '<video name>.txt' (plain-text transcript) next to the .srt
PARAGRAPH_GAP_MS = 2000       # start a new transcript paragraph after a pause this long...
PARAGRAPH_MAX_CHARS = 500     # ...or once a paragraph reaches roughly this many characters

# Resolution caps offered for playlists (and as a reference for naming)
RESOLUTION_TIERS = [
    (4320, "8K"),
    (2160, "4K"),
    (1440, "2K"),
    (1080, "1080p"),
    (720, "720p"),
    (480, "480p"),
    (360, "360p"),
]

HEIGHT_NICKNAMES = {4320: "8K", 2160: "4K", 1440: "2K", 1080: "Full HD"}

# What to download
MODE_VIDEO = "video"        # HEVC MP4 only
MODE_CAPTIONS = "captions"  # English .srt (+ .txt transcript) only, no video
MODE_BOTH = "both"          # HEVC MP4 + .srt (+ .txt transcript)


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------
def check_ffmpeg(need_encoders=True):
    """
    Makes sure FFmpeg exists. When video will be encoded (need_encoders=True), also checks
    that it includes the x265 and MP3 encoders. Captions-only mode just needs FFmpeg itself,
    because yt-dlp uses it to convert captions to .srt.
    """
    if not shutil.which("ffmpeg"):
        print("❌ FFmpeg was not found on your PATH. Install it and try again.")
        return False

    if not need_encoders:
        return True

    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True,
        )
    except Exception as e:
        print(f"❌ Could not query FFmpeg encoders: {e}")
        return False

    missing = [enc for enc in ("libx265", "libmp3lame") if enc not in result.stdout]
    if missing:
        print(f"❌ Your FFmpeg build is missing required encoder(s): {', '.join(missing)}")
        print("   Install a full FFmpeg build (most official/brew/apt builds include them).")
        return False
    return True


# ---------------------------------------------------------------------------
# User prompts
# ---------------------------------------------------------------------------
def get_valid_directory():
    """Prompts the user for a download folder and ensures it exists."""
    while True:
        directory = input("\nEnter target directory to save files (Leave blank for current folder): ").strip()

        if not directory:
            return "."  # Current directory

        # Clean up path and expand user home directory symbols like ~
        directory = os.path.abspath(os.path.expanduser(directory))

        try:
            if not os.path.exists(directory):
                os.makedirs(directory)
                print(f"📁 Created folder: {directory}")
            return directory
        except Exception as e:
            print(f"❌ Invalid directory or permission denied. Error: {e}. Please try again.")


def label_for_height(height):
    nickname = HEIGHT_NICKNAMES.get(height)
    return f"{height}p ({nickname})" if nickname else f"{height}p"


def get_valid_resolution(heights, is_playlist):
    """
    Prompts the user for a maximum video resolution.
    Returns an int height cap, or None for 'best available'.

    - Single video: shows the resolutions that video actually offers.
    - Playlist: shows standard tiers; each track uses the best resolution
      available at or below the chosen cap.
    """
    options = [(None, "Best available")]

    if is_playlist or not heights:
        options += [(h, f"{label_for_height(h)} or best below it") for h, _ in RESOLUTION_TIERS]
    else:
        options += [(h, label_for_height(h)) for h in heights]

    print("\nSelect your desired video resolution:")
    if is_playlist:
        print("(Each track downloads at the chosen resolution, or the best one it has below it.)")
    for i, (_, text) in enumerate(options, start=1):
        print(f"{i}. {text}")

    while True:
        choice = input(f"Enter choice (1-{len(options)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][0]
        print(f"❌ Invalid input. Please enter a number between 1 and {len(options)}.")


def get_download_mode():
    """Asks whether to download the video, the English captions (.srt), or both."""
    print("\nWhat would you like to download?")
    print("1. Video only (HEVC/x265 MP4)")
    print("2. Captions only (English .srt + .txt transcript, no video)")
    print("3. Both video and captions")

    modes = {'1': MODE_VIDEO, '2': MODE_CAPTIONS, '3': MODE_BOTH}
    while True:
        choice = input("Enter choice (1-3): ").strip()
        if choice in modes:
            return modes[choice]
        print("❌ Invalid input. Please enter 1, 2 or 3.")


def get_valid_bitrate():
    """Prompts the user for an MP3 audio bitrate and validates the input."""
    print("\nSelect your desired MP3 audio quality (bitrate):")
    print("1. 128 kbps (Standard quality / smaller file)")
    print("2. 192 kbps (High quality - Recommended)")
    print("3. 256 kbps (Very high quality)")
    print("4. 320 kbps (Highest quality / larger file)")
    print("5. Custom bitrate")

    while True:
        choice = input("Enter choice (1-5) or directly enter a value (e.g., 256): ").strip()

        if choice == '1':
            return '128'
        elif choice == '2':
            return '192'
        elif choice == '3':
            return '256'
        elif choice == '4':
            return '320'
        elif choice == '5':
            custom = input("Enter custom bitrate in kbps (e.g., 160): ").strip()
            if custom.isdigit():
                return custom
        elif choice.isdigit():
            return choice

        print("❌ Invalid input. Please enter a number between 1-5 or a valid numeric bitrate.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sanitize_folder_name(name):
    """Strips characters that are unsafe for folder/file names across OSes."""
    name = re.sub(r'[\\/:*?"<>|]', '', name).strip()
    return name or "Untitled Playlist"


def clean_metadata_modifier(info_dict):
    """
    Extracted data hook: Parses out Artist and Title metadata.
    If the artist's name appears inside the track title, it trims it out.
    """
    # Fallback to channel name if explicit track artist metadata doesn't exist
    artist = info_dict.get('artist') or info_dict.get('uploader') or "Unknown Artist"
    title = info_dict.get('track') or info_dict.get('title') or "Unknown Title"

    artist = artist.strip()
    title = title.strip()

    if artist and title:
        # Check if the artist name exists inside the title (case-insensitive)
        if artist.lower() in title.lower():
            # Match variations like "Artist - Title", "Artist-Title", "Artist: Title"
            pattern = re.compile(rf'\b{re.escape(artist)}\b\s*[\-\:]*\s*', re.IGNORECASE)
            cleaned_title = pattern.sub('', title).strip()

            if cleaned_title:
                title = cleaned_title

    # Inject parsed fields back into the info dictionary so yt-dlp uses them for naming & tagging
    info_dict['artist'] = artist
    info_dict['title'] = title
    return info_dict


def available_heights(info):
    """Returns the distinct video heights (highest first) that a single video offers."""
    heights = {
        f['height']
        for f in (info.get('formats') or [])
        if f.get('height') and f.get('vcodec') not in (None, 'none')
    }
    return sorted(heights, reverse=True)


def build_format_selector(max_height):
    """Builds a yt-dlp format string capped at the chosen resolution."""
    if max_height is None:
        return 'bestvideo+bestaudio/best'
    return f'bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]'


def probe_url(url):
    """Quick lookup to find out whether the URL is a playlist and what resolutions exist."""
    probe_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',  # don't fully resolve every playlist entry yet
    }
    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        return ydl.extract_info(url, download=False)


def build_ydl_opts(output_dir, max_height, mode=MODE_VIDEO):
    """
    Builds the shared yt-dlp options dict.
    The source streams are merged into a temporary MKV (which can hold any codec combo
    YouTube serves); it is then re-encoded to HEVC/x265 MP4 by encode_hevc_mp4().
    In captions-only mode nothing but the caption file is downloaded.
    """
    output_template = os.path.join(output_dir, '%(artist)s - %(title)s.%(ext)s')

    if mode == MODE_CAPTIONS:
        return {
            'skip_download': True,
            'format': 'best',                  # irrelevant (nothing is downloaded), but must resolve
            'ignore_no_formats_error': True,
            'outtmpl': output_template,
            'writesubtitles': True,            # manual captions, when the uploader provided them
            'writeautomaticsub': True,         # fall back to auto-generated captions
            'subtitleslangs': ['en.*'],        # en, en-US, en-GB, en-orig, ...
            'postprocessors': [
                {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt', 'when': 'before_dl'},
            ],
            'quiet': False,
            'ignoreerrors': True,
        }

    opts = {
        'format': build_format_selector(max_height),
        'outtmpl': output_template,
        'merge_output_format': 'mkv',
        'writethumbnail': False,
        'modify_chapters': False,
        'postprocessors': [
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            }
        ],
        'quiet': False,
        'ignoreerrors': True,
    }

    if mode == MODE_BOTH:
        opts.update({
            'writesubtitles': True,        # manual captions, when the uploader provided them
            'writeautomaticsub': True,     # fall back to auto-generated captions
            'subtitleslangs': ['en.*'],    # en, en-US, en-GB, en-orig, ...
        })
        opts['postprocessors'].append(
            {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt', 'when': 'before_dl'}
        )

    return opts


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def encode_hevc_mp4(source_path, audio_kbps):
    """
    Re-encodes the downloaded file to an MP4 with x265 (HEVC) video and MP3 audio,
    then removes the temporary source file. Returns the final file path.
    """
    base = os.path.splitext(source_path)[0]
    final_path = base + '.mp4'
    temp_path = base + '.hevc-temp.mp4'

    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-stats',
        '-i', source_path,
        '-map', '0:v:0', '-map', '0:a:0?',
        '-map_metadata', '0',
        '-c:v', 'libx265', '-crf', HEVC_CRF, '-preset', HEVC_PRESET,
        '-tag:v', 'hvc1',                      # makes HEVC-in-MP4 playable on Apple devices
        '-c:a', 'libmp3lame', '-b:a', f'{audio_kbps}k', '-ac', '2',
        '-movflags', '+faststart',
        temp_path,
    ]

    print(f"🎞️  Encoding to HEVC/x265 (CRF {HEVC_CRF}, preset {HEVC_PRESET}) + MP3 {audio_kbps}kbps... this can take a while.")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise RuntimeError("FFmpeg failed while encoding the video.")

    if os.path.exists(source_path) and os.path.abspath(source_path) != os.path.abspath(final_path):
        os.remove(source_path)
    os.replace(temp_path, final_path)
    return final_path


def locate_downloaded_file(ydl, info):
    """Finds the file yt-dlp just wrote for this video."""
    downloads = info.get('requested_downloads') or []
    if downloads and downloads[0].get('filepath') and os.path.exists(downloads[0]['filepath']):
        return downloads[0]['filepath']

    # Fallback: derive it from the output template
    base = os.path.splitext(ydl.prepare_filename(info))[0]
    for ext in ('.mkv', '.mp4', '.webm'):
        if os.path.exists(base + ext):
            return base + ext
    return None


# ---------------------------------------------------------------------------
# Download flow
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Caption cleanup
# ---------------------------------------------------------------------------
_TIME_RE = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)')
_TAG_RE = re.compile(r'<[^>]+>')


def _ts_to_ms(ts):
    h, m, sec, frac = _TIME_RE.match(ts.strip()).groups()
    return ((int(h) * 60 + int(m)) * 60 + int(sec)) * 1000 + int(frac.ljust(3, '0')[:3])


def _ms_to_ts(ms):
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    sec, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def parse_srt(path):
    """Reads an .srt into a list of {'start': ms, 'end': ms, 'lines': [text lines]}."""
    with open(path, encoding='utf-8-sig') as f:
        content = f.read().replace('\r\n', '\n')

    cues = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.split('\n')
        timing_idx = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if timing_idx is None:
            continue

        start_raw, end_raw = lines[timing_idx].split('-->')
        text_lines = []
        for line in lines[timing_idx + 1:]:
            line = html.unescape(_TAG_RE.sub('', line)).strip()
            if line:
                text_lines.append(line)

        cues.append({
            'start': _ts_to_ms(start_raw.split()[0]),
            'end': _ts_to_ms(end_raw.split()[0]),
            'lines': text_lines,
        })
    return cues


def looks_rolling(cues):
    """
    YouTube auto-captions use a 'rolling' style where each cue repeats the previous cue's
    last line. Manual captions don't, so they are left untouched.
    """
    pairs = overlaps = 0
    for prev, cur in zip(cues, cues[1:]):
        if prev['lines'] and cur['lines']:
            pairs += 1
            if set(prev['lines']) & set(cur['lines']):
                overlaps += 1
    return pairs > 0 and overlaps / pairs >= 0.3


def dedupe_rolling_cues(cues):
    """
    Keeps each caption line only the first time it appears, and extends that cue so it stays
    on screen as long as the line was visible in the original rolling cues.
    """
    cleaned = []
    prev_lines = []
    owner = {}  # line text -> index of the cleaned cue that holds it

    for cue in cues:
        lines = cue['lines']
        if not lines:
            prev_lines = []  # screen was cleared; anything that follows is new
            continue

        new_lines = []
        for line in lines:
            if line in prev_lines:
                idx = owner.get(line)
                # Only extend when the cues are back-to-back, not across a long silence
                if idx is not None and cue['start'] - cleaned[idx]['end'] <= 500:
                    cleaned[idx]['end'] = max(cleaned[idx]['end'], cue['end'])
            else:
                new_lines.append(line)

        if new_lines:
            cleaned.append({'start': cue['start'], 'end': cue['end'], 'lines': new_lines})
            for line in new_lines:
                owner[line] = len(cleaned) - 1
        prev_lines = lines

    # Stop each cue where the next one begins so nothing overlaps
    for current, nxt in zip(cleaned, cleaned[1:]):
        if nxt['start'] > current['start'] and current['end'] > nxt['start']:
            current['end'] = nxt['start']

    return cleaned


def write_srt(cues, path):
    with open(path, 'w', encoding='utf-8') as f:
        for i, cue in enumerate([c for c in cues if c['lines']], start=1):
            f.write(f"{i}\n{_ms_to_ts(cue['start'])} --> {_ms_to_ts(cue['end'])}\n")
            f.write("\n".join(cue['lines']) + "\n\n")


def write_transcript(cues, path):
    """Writes the caption text as wrapped plain-text paragraphs, with no timestamps."""
    paragraphs, current, length, last_end = [], [], 0, None

    for cue in cues:
        if not cue['lines']:
            continue
        text = ' '.join(cue['lines'])
        paused = last_end is not None and cue['start'] - last_end >= PARAGRAPH_GAP_MS
        if current and (paused or length >= PARAGRAPH_MAX_CHARS):
            paragraphs.append(' '.join(current))
            current, length = [], 0
        current.append(text)
        length += len(text) + 1
        last_end = cue['end']

    if current:
        paragraphs.append(' '.join(current))

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(textwrap.fill(re.sub(r'\s+', ' ', p), width=100) for p in paragraphs) + '\n')


def postprocess_captions(srt_path):
    """De-duplicates rolling auto-captions in the .srt and writes a matching plain-text transcript."""
    cues = parse_srt(srt_path)
    if not any(c['lines'] for c in cues):
        return

    if looks_rolling(cues):
        cues = dedupe_rolling_cues(cues)
        write_srt(cues, srt_path)
        print("🧹 Removed repeated lines from auto-generated captions.")

    if WRITE_TRANSCRIPT_TXT:
        txt_path = os.path.splitext(srt_path)[0] + '.txt'
        write_transcript(cues, txt_path)
        print(f"📝 Transcript saved: {txt_path}")


def rename_caption_to_match_video(source_path):
    """
    yt-dlp saves captions as '<name>.en.srt' (or '.en-orig.srt', '.en-US.srt', ...).
    This renames the best English caption to '<name>.srt' so it exactly matches the
    video's filename, and removes any extra English variants. Returns the caption path or None.
    """
    base = os.path.splitext(source_path)[0]
    candidates = sorted(glob.glob(glob.escape(base) + '.en*.srt'))
    if not candidates:
        print("⚠️ No English captions were available for this video.")
        return None

    # Prefer '.en.srt', then '.en-orig.srt', otherwise take the first variant found
    chosen = candidates[0]
    for lang in ('en', 'en-orig', 'en-US', 'en-GB'):
        if f"{base}.{lang}.srt" in candidates:
            chosen = f"{base}.{lang}.srt"
            break

    target = base + '.srt'
    os.replace(chosen, target)
    for extra in candidates:
        if extra != chosen and os.path.exists(extra):
            os.remove(extra)

    print(f"💬 Captions saved: {target}")
    postprocess_captions(target)
    return target


def download_single_video(ydl, info, audio_kbps, mode=MODE_VIDEO):
    """
    Cleans metadata, then (depending on mode) downloads the video via yt-dlp and encodes it to
    HEVC MP4, and/or saves the English captions. Returns the main output path, or None.
    """
    cleaned_info = clean_metadata_modifier(info)
    ydl.process_info(cleaned_info)

    if mode == MODE_CAPTIONS:
        # Nothing was downloaded besides captions; prepare_filename gives the would-be video name
        caption_path = rename_caption_to_match_video(ydl.prepare_filename(cleaned_info))
        if caption_path:
            print(f"✅ Saved: {caption_path}")
        return caption_path

    source_path = locate_downloaded_file(ydl, cleaned_info)
    if not source_path:
        raise RuntimeError("Download finished but the output file could not be found.")

    # Do this before encoding: source_path and the final .mp4 share the same base name
    if mode == MODE_BOTH:
        try:
            rename_caption_to_match_video(source_path)
        except Exception as e:
            print(f"⚠️ Could not finalize captions: {e}")

    final_path = encode_hevc_mp4(source_path, audio_kbps)
    print(f"✅ Saved: {final_path}")
    return final_path


def download_playlist(ydl, info, audio_kbps, base_output_dir, mode=MODE_VIDEO):
    """
    Iterates through every video in a playlist, downloading and encoding each one
    (or saving just its captions, depending on mode).
    Creates a subfolder named after the playlist so everything stays organized together.
    """
    entries = [e for e in info.get('entries', []) if e]  # Skip unavailable/private entries
    total = len(entries)

    if total == 0:
        print("⚠️ No downloadable entries were found in this playlist.")
        return

    playlist_title = sanitize_folder_name(info.get('title') or "Untitled Playlist")
    playlist_dir = os.path.join(base_output_dir, playlist_title)
    os.makedirs(playlist_dir, exist_ok=True)

    print(f"\n📃 Playlist detected: \"{playlist_title}\" ({total} video(s))")
    print(f"📁 Saving to: {playlist_dir}")

    # Point this download session's output template at the playlist subfolder
    ydl.params['outtmpl']['default'] = os.path.join(playlist_dir, '%(artist)s - %(title)s.%(ext)s')

    success_count = 0
    for index, entry in enumerate(entries, start=1):
        entry_title = entry.get('title') or entry.get('id') or "Unknown"
        print(f"\n[{index}/{total}] Processing: {entry_title}")
        try:
            if download_single_video(ydl, entry, audio_kbps, mode):
                success_count += 1
        except Exception as e:
            print(f"❌ Skipped \"{entry_title}\" due to an error: {e}")
            continue

    print(f"\n🎉 Playlist download complete! {success_count}/{total} item(s) saved to: {playlist_dir}")


def download_youtube(youtube_url, mode, max_height, audio_kbps, output_dir):
    ydl_opts = build_ydl_opts(output_dir, max_height, mode)

    if mode == MODE_CAPTIONS:
        summary = "English captions only"
    else:
        res_text = "best available" if max_height is None else f"up to {max_height}p"
        summary = f"{res_text}, MP3 {audio_kbps}kbps" + (" + captions" if mode == MODE_BOTH else "")

    try:
        print(f"\nFetching metadata ({summary})... Please wait.")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

            if info is None:
                print("❌ Could not retrieve any information for that URL.")
                return

            if 'entries' in info:
                # A playlist URL returns a top-level dict with an 'entries' list
                download_playlist(ydl, info, audio_kbps, output_dir, mode)
            else:
                print("Downloading... Please wait." if mode != MODE_CAPTIONS else "Fetching captions... Please wait.")
                if download_single_video(ydl, info, audio_kbps, mode):
                    print(f"🎉 Download complete! Saved to: {output_dir}")
    except Exception as e:
        print(f"❌ An error occurred: {e}")


if __name__ == "__main__":
    url = input("Enter YouTube Video or Playlist URL: ").strip()
    if not url:
        print("❌ URL cannot be empty.")
        raise SystemExit(1)

    download_mode = get_download_mode()

    if not check_ffmpeg(need_encoders=(download_mode != MODE_CAPTIONS)):
        raise SystemExit(1)

    try:
        print("\n🔎 Checking available formats...")
        probe_info = probe_url(url)
    except Exception as e:
        print(f"❌ Could not read that URL: {e}")
        raise SystemExit(1)

    if probe_info is None:
        print("❌ Could not retrieve any information for that URL.")
        raise SystemExit(1)

    output_folder = get_valid_directory()

    max_height, kbps = None, None
    if download_mode != MODE_CAPTIONS:
        is_playlist = 'entries' in probe_info
        heights = [] if is_playlist else available_heights(probe_info)
        max_height = get_valid_resolution(heights, is_playlist)
        kbps = get_valid_bitrate()

    download_youtube(url, download_mode, max_height, kbps, output_folder)
