# Clipper

Long video → Whisper transcript → open-source LLM picks the best moments → ffmpeg cuts them (snapped to sentence boundaries) → LLM writes captions → saved to `data/clips/`.

## Project layout

```
Clipper/
├── backend/                      Python package (CLI + API)
│   ├── pyproject.toml            dependencies and the `clipper` / `clipper-server` commands
│   ├── .env                      your keys and settings (from .env.example)
│   ├── scripts/                  one-off maintenance scripts
│   └── src/clipper/
│       ├── config.py             paths and settings from .env
│       ├── pipeline.py           download → transcribe → pick → captions → cut & save
│       ├── youtube.py            yt-dlp: channel search, video info, downloads
│       ├── transcribe.py         Whisper (Groq API or local faster-whisper)
│       ├── llm.py                OpenAI-compatible client, JSON parsing, model fallback
│       ├── analysis.py           LLM prompts: topic check, clip picking, captions
│       ├── media.py              ffmpeg: probe, audio extraction, cutting, layouts
│       ├── backgrounds.py        background videos: download, add, random picking
│       ├── outro.py              animated Follow / Subscribe end screens
│       ├── library.py            reads generated clips back from disk
│       ├── schemas.py            ClipOptions and LLM response models
│       ├── reporting.py          logging and per-stage progress
│       ├── errors.py, utils.py
│       ├── cli.py                `clipper` command
│       └── api/                  `clipper-server` (FastAPI)
│           ├── app.py            app factory, static mounts, entry point
│           ├── jobs.py           background job runner
│           ├── schemas.py        request bodies
│           └── routes/           system, search, jobs, library
├── frontend/                     Next.js UI (built to frontend/out, served by the API)
└── data/                         generated, gitignored
    ├── downloads/                source videos (temporary, deleted after clipping)
    ├── work/<video>/             transcript, clip picks, source info (kept, tiny)
    ├── clips/<video>/            clip_XX_<name>.mp4 + .json (Instagram + YouTube metadata)
    ├── backgrounds/              background videos (~2 min each) + .json source info
    └── outros/                   cached end screen animation frames
```

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\pip install -e backend
copy backend\.env.example backend\.env
cd frontend; npm install; npm run build; cd ..
```

Fill in `backend/.env`:

1. **GROQ_API_KEY**: free at https://console.groq.com/keys. Used for Whisper transcription (about 1 minute per hour of video).
   Without it, set `TRANSCRIBE=local` to transcribe on your own CPU (free and unlimited, but slow).
2. **LLM_API_KEY**: free at https://openrouter.ai/keys.
3. **LLM_MODEL**: run `.venv\Scripts\clipper --list-models`, pick 2–3 free models, comma-separated.

ffmpeg is bundled through `imageio-ffmpeg`; nothing else to install. Set `CLIPPER_DATA_DIR` in `.env` to store data somewhere other than `data/`.

## Web UI

```powershell
.venv\Scripts\clipper-server        # open http://127.0.0.1:8000
```

- **New job**: search a YouTuber and topic (or paste a link, file path or upload a file), set clip options, generate. Progress is shown for each stage: download, transcribe, pick clips, captions, cut.
- **Library** (`/#library`): every processed video with its clips, a player, Instagram and YouTube captions with copy buttons, transcript and download links.
- **Backgrounds** (`/#backgrounds`): download random free-to-use background videos, add one from a YouTube link or upload a file, preview and remove them.

Only one job runs at a time. Refreshing the page while a job runs picks its progress back up.

**Developing the UI:** run `clipper-server`, and in another terminal run `cd frontend; npm run dev`, then open http://localhost:3000. It hot-reloads and talks to the API on :8000. API docs: http://127.0.0.1:8000/docs.

## Command line

**Search mode:** give a YouTuber and a topic. It checks their latest videos, you pick one, and it gets clipped.
```powershell
.venv\Scripts\clipper                                          # asks for YouTuber + topic
.venv\Scripts\clipper --youtuber "Ali Abdaal" --topic "productivity"
.venv\Scripts\clipper --youtuber "@aliabdaal" --topic "money" --latest 10
```
If no video matches, you can switch YouTuber, change the topic, or inspect older videos.

**Direct mode:** give a link or file.
```powershell
.venv\Scripts\clipper "https://www.youtube.com/watch?v=VIDEO_ID"
.venv\Scripts\clipper C:\path\to\video.mp4
```

| Flag | Default | Meaning |
|---|---|---|
| `--youtuber` | asks | Search mode: name, @handle or channel URL |
| `--topic` | asks | Search mode: what the video should be about |
| `--latest` | 5 | Search mode: how many recent videos to check per page |
| `--min-clips / --max-clips` | 5 / 7 | How many clips to ask for |
| `--min-len / --max-len` | 20 / 60 | Clip length in seconds |
| `--format` | `crop` | see **Formats** below |
| `--fresh` | off | Ask the LLM for new clips instead of reusing saved picks |
| `--no-end-screen` | off | Don't add Follow / Subscribe end screens |
| `--add-end-screens` | | Add end screens to existing clips that don't have them, and exit |
| `--keep-source` | off | Keep the downloaded source video instead of deleting it after clipping |
| `--list-models` | | List models at `LLM_BASE_URL` (free ones only, for OpenRouter) |
| `--download-backgrounds N` | | Download N random free-to-use background videos and exit |

## End screens

Each clip gets a 3 second animated end screen: the last frame freezes and darkens, a card pops in, a cursor clicks the button and it flips to the done state.

| Platform | Text | Button |
|---|---|---|
| Instagram | Follow for more | Follow → Following (blue) |
| YouTube | Subscribe for more | Subscribe → Subscribed (red) |

The clip is stored once, plus a small end piece per platform (`clip_XX_<name>.end_instagram.mp4`, `.end_youtube.mp4`). They are joined when you download a clip **for Instagram** or **for YouTube** in the Library, and later when uploading. Joining takes about a second because both are encoded identically (1080×1920, 30 fps, 48 kHz). The Library player plays the clip followed by the end screen of the tab that's open.

Set `OUTRO_HANDLE=@yourpage` in `backend/.env` to show your handle on the card. Not available for the `original` format.

## Formats

All formats except `original` produce a 1080×1920 (9:16) video for Shorts / Reels.

| Format | Layout |
|---|---|
| `crop` | Centre crop to 9:16. Cuts off the sides of a 16:9 video. |
| `blur` | Whole clip at full width, over a blurred copy of itself. |
| `background` | Whole clip at full width, centred over a random **blurred background video**. |
| `split` | Whole clip at full width in the top half (gaps filled with its own blur), random **background video** in the bottom half. |
| `original` | Unchanged aspect ratio. |

For `background` and `split`, every clip gets a different random background (no repeats until all have been used), starting at a random point and cut to exactly the clip's length. A background shorter than the clip loops. Background audio is muted.

Backgrounds live in `data/backgrounds/`. `clipper --download-backgrounds 12` (or the Backgrounds page) searches YouTube for gameplay / satisfying videos whose titles say *no copyright* / *free to use* and downloads a random 2 minute, 720p, video-only section of each. That label is the uploader's claim; check the source link if unsure.

## Output

```
data/clips/<video_title>/clip_01_<name>.mp4
data/clips/<video_title>/clip_01_<name>.json
```

One video file per clip, used for both platforms. The JSON holds:
- `instagram`: `caption`, `hashtags`, `full_caption`, `uploaded`
- `youtube`: `title`, `description`, `tags`, `hashtags`, `full_description`, `uploaded`
- timestamps, the exact transcript, hook, reason and source video info

Re-running a video replaces its clips.

### Source videos and re-clipping

The downloaded (or uploaded) source video is **deleted after clipping** unless you use `--keep-source` / "Keep source video". Your own local files passed by path are never deleted.

`data/work/<video_title>/` keeps `transcript.json`, `clip_picks.json` and `source.json` (a few KB). To get **different clips** from a video later, use **Make new clips** in the Library, or `clipper "<url>" --fresh`:

1. The saved transcript is reused (no transcription).
2. The LLM picks new clips and writes captions from the transcript.
3. Only then is the video downloaded again, cut, and deleted.

Uploaded files can't be re-downloaded, so upload them again to re-clip.

## API usage per video

1 transcription request plus **2 LLM requests** (one to pick clips, one for all captions). Search mode adds 1 LLM request per topic check. This fits easily in free tiers.
