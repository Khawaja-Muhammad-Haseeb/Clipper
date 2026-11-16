from fastapi import APIRouter

from clipper import config

router = APIRouter(tags=["system"])


@router.get("/config")
def get_config():
    return {
        "llm_models": config.LLM_MODELS,
        "llm_base_url": config.LLM_BASE_URL,
        "llm_key_set": bool(config.LLM_API_KEY),
        "transcribe": config.TRANSCRIBE,
        "groq_key_set": bool(config.GROQ_API_KEY),
    }
