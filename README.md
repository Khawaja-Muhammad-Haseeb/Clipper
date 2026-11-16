# Clipper

Long video → Whisper transcript → open-source LLM picks the best moments → ffmpeg cuts them (snapped to sentence boundaries) → LLM writes captions → saved to `insta_vid/` and `yt_vids/`.

## Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Fill in `.env` (template: `.env.example`):

1. **GROQ_API_KEY**: free at https://console.groq.com/keys. Used for Whisper transcription (about 1 minute per hour of video).
   Without it, set `TRANSCRIBE=local` to transcribe on your own CPU (free and unlimited, but slow).
2. **LLM_API_KEY**: free at https://openrouter.ai/keys.
3. **LLM_MODEL**: run `.venv\Scripts\python clipper.py --list-models`, pick 2–3 free models, comma-separated.

ffmpeg is bundled through `imageio-ffmpeg`; nothing else to install.

## Web UI

One-time setup: build the frontend (requires Node.js).
```powershell
cd frontend; npm install; npm run build; cd ..
```
Then start everything with one command and open http://127.0.0.1:8000:
```powershell
.venv\Scripts\python server.py
```

- **New job**: search a YouTuber and topic (or paste a link, file path or upload a file), set clip options, generate. Progress is shown for each stage: download, transcribe, pick clips, captions, cut.
- **Library** (`/#library`): every processed video with its clips, a player, Instagram and YouTube captions with copy buttons, transcript and download links.

Only one job runs at a time. Refreshing the page while a job runs picks its progress back up.

**Developing the UI:** run `server.py`, and in another terminal run `cd frontend; npm run dev`, then open http://localhost:3000. It hot-reloads and talks to the API on :8000.

## Command line

**Search mode:** give a YouTuber and a topic. It checks their latest videos, you pick one, and it gets clipped.
```powershell
.venv\Scripts\python clipper.py                                          # asks for YouTuber + topic
.venv\Scripts\python clipper.py --youtuber "Ali Abdaal" --topic "productivity"
.venv\Scripts\python clipper.py --youtuber "@aliabdaal" --topic "money" --latest 10
```
If no video matches, you can switch YouTuber, change the topic, or inspect older videos.

**Direct mode:** give a link or file.
```powershell
.venv\Scripts\python clipper.py "https://www.youtube.com/watch?v=VIDEO_ID"
.venv\Scripts\python clipper.py C:\path\to\video.mp4
```

| Flag | Default | Meaning |
|---|---|---|
| `--youtuber` | asks | Search mode: name, @handle or channel URL |
| `--topic` | asks | Search mode: what the video should be about |
| `--latest` | 5 | Search mode: how many recent videos to check per page |
| `--min-clips / --max-clips` | 5 / 7 | How many clips to ask for |
| `--min-len / --max-len` | 20 / 60 | Clip length in seconds |
| `--format` | `crop` | `crop` (9:16 centre crop), `blur` (full frame on blurred 9:16 background), `original` |
| `--fresh` | off | Ask the LLM for new clips instead of reusing saved picks |
| `--list-models` | | List models at `LLM_BASE_URL` (free ones only, for OpenRouter) |

## Output

```
insta_vid/<video_title>/clip_01_<name>.mp4  + .json   (caption, hashtags, full_caption)
yt_vids/<video_title>/clip_01_<name>.mp4    + .json   (title, description, tags, hashtags)
```

Each JSON also holds timestamps, the exact transcript, hook, source video info and `uploaded: false`.

`work/<video_title>/` caches `transcript.json` and `clip_picks.json`. Re-running a video skips transcription, and also skips clip picking unless you pass `--fresh`. You can hand-edit the clip times in `clip_picks.json`.

## API usage per video

1 transcription request plus **2 LLM requests** (one to pick clips, one for all captions). Search mode adds 1 LLM request per topic check. This fits easily in free tiers.
