"""
ThreadSift - ElevenLabs Expressive Voice Integration Helper
Handles REST API calls to ElevenLabs Text-to-Speech (TTS), voice configurations,
and streaming audio response generation.
"""

import logging
import os
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("threadsift.voice")

# Default voice settings
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (expressive, natural)
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"      # Ultra-fast, low latency for real-time calls
FALLBACK_MODEL_ID = "eleven_monolingual_v1"

POPULAR_VOICES = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (Calm & Natural)", "category": "Conversational"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam (Deep & Confident)", "category": "Conversational"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella (Warm & Expressive)", "category": "Narration"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni (Crisp & Articulate)", "category": "Technical"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh (Youthful & Casual)", "category": "Conversational"},
    {"id": "VR6AewLTigWG4xiVioSm", "name": "Arnold (Authoritative)", "category": "Direct"},
]


class ElevenLabsService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("your_"))

    async def generate_speech(
        self,
        text: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> bytes:
        """
        Calls ElevenLabs TTS REST API to generate MP3 audio for the given text.
        Raises ValueError or httpx.HTTPStatusError on failure.
        """
        if not self.is_configured():
            raise ValueError("ElevenLabs API Key is not configured. Set ELEVENLABS_API_KEY in .env or settings.")

        target_voice = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
        target_model = model_id or os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID

        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Text cannot be empty for speech generation.")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{target_voice}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": clean_text,
            "model_id": target_model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "use_speaker_boost": True,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 404 and target_model != FALLBACK_MODEL_ID:
                # If turbo model isn't enabled for the tier, try fallback model
                payload["model_id"] = FALLBACK_MODEL_ID
                resp = await client.post(url, headers=headers, json=payload)

            resp.raise_for_status()
            return resp.content

    async def list_available_voices(self) -> List[Dict[str, Any]]:
        """
        Retrieves user's available custom and standard voices from ElevenLabs,
        or falls back to curated popular list if unauthorized.
        """
        if not self.is_configured():
            return POPULAR_VOICES

        try:
            url = "https://api.elevenlabs.io/v1/voices"
            headers = {"xi-api-key": self.api_key}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    voices = []
                    for v in data.get("voices", []):
                        voices.append({
                            "id": v.get("voice_id"),
                            "name": v.get("name"),
                            "category": v.get("category", "Custom"),
                        })
                    return voices if voices else POPULAR_VOICES
        except Exception as e:
            logger.warning(f"Could not fetch voices from ElevenLabs API: {e}")

        return POPULAR_VOICES
