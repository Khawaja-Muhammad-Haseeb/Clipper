"""Paths and settings. Values come from backend/.env (see .env.example)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]     # backend/
PROJECT_ROOT = BACKEND_DIR.parent                      # repo root
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "out"      # built UI served by the API

load_dotenv(BACKEND_DIR / ".env")

# ---- Data folders -----------------------------------------------------------
DATA_DIR = Path(os.getenv("CLIPPER_DATA_DIR") or PROJECT_ROOT / "data").resolve()
DOWNLOADS_DIR = DATA_DIR / "downloads"   # source videos (temporary: deleted after clipping)
UPLOADS_DIR = DOWNLOADS_DIR / "uploads"  # files uploaded through the UI (temporary too)
WORK_DIR = DATA_DIR / "work"             # kept: transcript, clip picks, source info per video
CLIPS_DIR = DATA_DIR / "clips"           # kept: clip_XX.mp4 + clip_XX.json (Instagram + YouTube metadata)
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"  # background videos for the background / split layouts

# ---- Transcription ----------------------------------------------------------
# "groq" = free Groq Whisper API (fast); "local" = faster-whisper on the CPU (unlimited, slow)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TRANSCRIBE = os.getenv("TRANSCRIBE", "groq" if GROQ_API_KEY else "local").lower()
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "small")

# ---- LLM (any OpenAI-compatible endpoint) -----------------------------------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# Comma-separated; the next model is tried when one is rate-limited or fails.
LLM_MODELS = [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()]

# ---- End screen -------------------------------------------------------------
OUTRO_HANDLE = os.getenv("OUTRO_HANDLE", "")  # e.g. "@myclips", shown above "Follow for more"

# ---- API server -------------------------------------------------------------
API_HOST = os.getenv("CLIPPER_HOST", "127.0.0.1")
API_PORT = int(os.getenv("CLIPPER_PORT", "8000"))
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


# Windows consoles default to cp1252; don't crash on emoji in titles / descriptions.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
