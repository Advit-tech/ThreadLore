"""
ThreadLore - Local-First Chat Intelligence Dashboard
FastAPI Application, RAG Retrieval, Hermes LLM Inference, and Voice Loop Handlers.
"""

import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.db import (
    clear_database,
    get_connection,
    get_vault_stats,
    init_db,
    insert_messages,
    search_90_days,
)
from backend.exporter import (
    find_exporter_cli,
    parse_discord_dict,
    run_export,
    seed_sample_data,
)
from backend.voice import (
    DEFAULT_VOICE_ID,
    ElevenLabsService,
    POPULAR_VOICES,
)

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("threadlore")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# Runtime Configuration State
CONFIG = {
    "llm_base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
    "llm_model": os.getenv("LLM_MODEL", "hermes3"),
    "llm_api_key": os.getenv("LLM_API_KEY", "ollama"),
    "elevenlabs_api_key": os.getenv("ELEVENLABS_API_KEY", ""),
    "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup initialization and teardown."""
    logger.info("Initializing ThreadLore Chat Intelligence Engine...")
    init_db()
    yield
    logger.info("ThreadLore shutting down gracefully.")


app = FastAPI(
    title="ThreadLore",
    description="Local-first Discord chat intelligence dashboard with FTS5 search, Hermes LLM, and live voice calls.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for flexible local integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Request Models ---
class ExportRequest(BaseModel):
    channel_id: str = Field(..., description="Discord Channel ID to export")
    token: str = Field(..., description="Discord User or Bot authentication token")
    days: int = Field(90, ge=1, le=365, description="Days of history to export (cutoff)")
    bot_token: bool = Field(False, description="Whether token is a Discord Bot token")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message or prompt")
    channel_id: Optional[str] = Field(None, description="Optional channel filter for retrieval")
    history: Optional[List[Dict[str, str]]] = Field(None, description="Prior conversational turns")
    voice_mode: bool = Field(False, description="Optimize synthesis for spoken voice")


class VoiceCallRequest(BaseModel):
    transcript: str = Field(..., description="Transcribed user speech from Web Speech API")
    voice_id: Optional[str] = Field(None, description="ElevenLabs voice ID override")
    channel_id: Optional[str] = Field(None, description="Optional channel filter")


class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to convert to expressive speech")
    voice_id: Optional[str] = Field(None, description="ElevenLabs voice ID")


class SettingsUpdateRequest(BaseModel):
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None


# --- Helper Functions ---
async def check_llm_status() -> Dict[str, Any]:
    """Tests connectivity to the configured OpenAI-compatible LLM endpoint."""
    url = f"{CONFIG['llm_base_url']}/models"
    headers = {"Authorization": f"Bearer {CONFIG['llm_api_key']}"}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                models = [m.get("id") for m in resp.json().get("data", [])]
                return {"online": True, "models": models}
            return {"online": False, "status_code": resp.status_code, "error": resp.text[:120]}
    except Exception as e:
        return {"online": False, "error": str(e)}


def assemble_rag_context(retrieved_messages: List[Dict[str, Any]]) -> str:
    """Formats retrieved messages into a clean markdown context block for the LLM."""
    if not retrieved_messages:
        return "No specific past messages directly matched this query in the 90-day archive."

    lines = ["--- 90-DAY DISCORD CHAT VAULT ARCHIVE CONTEXT ---"]
    for msg in retrieved_messages:
        ts = msg.get("timestamp", "").replace("T", " ")[:19]
        ch = msg.get("channel_id", "unknown")
        author = msg.get("author", "unknown")
        content = msg.get("content", "")
        rank = msg.get("rank", "")
        lines.append(f"[{ts}] #{ch} | {author}: {content}")
    lines.append("--- END OF ARCHIVED CONTEXT ---")
    return "\n".join(lines)


async def call_hermes_llm(
    prompt: str,
    rag_context: str,
    history: Optional[List[Dict[str, str]]] = None,
    voice_mode: bool = False,
) -> str:
    """
    Calls OpenAI-compatible LLM endpoint (targeting Nous Research Hermes 3).
    Includes intelligent fallback synthesis if the local LLM server is not currently running.
    """
    system_instruction = (
        "You are ThreadLore, an expert AI chat intelligence assistant powered by Nous Research Hermes 3. "
        "You have direct access to a 90-day SQLite FTS5 conversation archive of team Discord channels.\n\n"
        "Instructions:\n"
        "1. Ground your answers directly in the provided 90-day Discord conversation context whenever relevant.\n"
        "2. When referencing decisions, bug fixes, or discussions, attribute them accurately to the author, channel, and timeframe.\n"
        "3. Maintain Hermes's sharp, insightful, and direct conversational tone.\n"
    )

    if voice_mode:
        system_instruction += (
            "\nVOICE MODE ACTIVE:\n"
            "- Speak naturally and concisely as if talking on a real-time voice call.\n"
            "- Keep answers to 2-4 spoken sentences.\n"
            "- DO NOT use markdown bullet points, bold asterisks, code blocks, or raw URLs, as your response will be read aloud via TTS."
        )
    else:
        system_instruction += (
            "\n- Format your response with clean markdown headings and quotes when helpful."
        )

    messages = [{"role": "system", "content": system_instruction}]

    # Include RAG context
    messages.append({
        "role": "user",
        "content": f"Relevant Context from 90-day vault:\n{rag_context}\n\nUser Question:\n{prompt}",
    })

    # Append recent chat history if provided
    if history:
        for turn in history[-4:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ["user", "assistant"]:
                messages.append({"role": role, "content": content})
        # Add prompt again if history was appended
        messages.append({"role": "user", "content": prompt})

    endpoint = f"{CONFIG['llm_base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {CONFIG['llm_api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CONFIG["llm_model"],
        "messages": messages,
        "temperature": 0.6 if voice_mode else 0.7,
        "max_tokens": 300 if voice_mode else 800,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
            else:
                logger.warning(f"LLM API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Could not reach LLM endpoint at {endpoint}: {e}")

    # Fallback Synthesis Mode (Ensures ThreadLore remains functional even without local LLM running)
    if "No specific past messages" in rag_context:
        if voice_mode:
            return "I searched the 90-day Discord archive, but couldn't find any messages matching that query. Could you try rephrasing or asking about a specific channel or team member?"
        return (
            "**ThreadLore Intelligent Search:**\n\n"
            "No matching messages were found in the 90-day Discord vault for your inquiry.\n\n"
            "> *Note: Local LLM endpoint is currently offline or unreachable at `"
            + CONFIG["llm_base_url"]
            + "`. Ensure Ollama, vLLM, or LM Studio is running, or configure a remote API in Settings.*"
        )

    # Synthesize from context directly
    context_lines = [l for l in rag_context.splitlines() if l.startswith("[")]
    top_items = context_lines[:4]
    
    if voice_mode:
        summary_voice = f"Based on recent Discord conversations, {len(top_items)} related messages were found. "
        first = top_items[0].split("|", 1)
        if len(first) > 1:
            summary_voice += f"For example, {first[1].strip()}"
        return summary_voice

    summary_md = (
        f"### ThreadLore Vault Synthesis\n\n"
        f"Retrieved **{len(context_lines)} relevant records** from the 90-day archive for your inquiry:\n\n"
    )
    for item in top_items:
        summary_md += f"- `{item}`\n"
    summary_md += (
        f"\n\n*(Synthesis generated via ThreadLore local FTS5 indexing. To enable generative Hermes 3 reasoning, connect an OpenAI-compatible endpoint at `{CONFIG['llm_base_url']}`)*"
    )
    return summary_md


# --- API Routes ---

@app.get("/api/status")
async def get_status():
    """Returns database vault statistics, exporter availability, and AI configurations."""
    vault_stats = get_vault_stats()
    cli_path = find_exporter_cli()
    llm_info = await check_llm_status()
    voice_service = ElevenLabsService(CONFIG["elevenlabs_api_key"])

    return {
        "status": "healthy",
        "app_name": "ThreadLore",
        "version": "1.0.0",
        "vault": vault_stats,
        "exporter": {
            "cli_found": bool(cli_path),
            "cli_path": cli_path,
        },
        "llm": {
            "base_url": CONFIG["llm_base_url"],
            "model": CONFIG["llm_model"],
            "online": llm_info.get("online", False),
            "details": llm_info,
        },
        "elevenlabs": {
            "configured": voice_service.is_configured(),
            "default_voice_id": CONFIG["elevenlabs_voice_id"],
            "popular_voices": POPULAR_VOICES,
        },
    }


@app.get("/api/search")
async def search_endpoint(
    q: str = Query("", description="Search keywords or FTS query"),
    channel_id: Optional[str] = Query(None, description="Filter by Discord channel"),
    limit: int = Query(30, ge=1, le=100, description="Max messages to return"),
    days: int = Query(90, ge=1, le=365, description="Search window in days"),
):
    """Full-text and BM25 ranked keyword search over 90-day conversation archive."""
    try:
        results = search_90_days(query=q, channel_id=channel_id, limit=limit, days=days)
        return {
            "query": q,
            "channel_id": channel_id,
            "days": days,
            "total_results": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export")
async def trigger_export(req: ExportRequest):
    """Executes DiscordChatExporter.Cli to export and ingest messages."""
    try:
        result = run_export(
            channel_id=req.channel_id,
            token=req.token,
            days=req.days,
            bot_token=req.bot_token,
        )
        return result
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-json")
async def upload_discord_json(file: UploadFile = File(...)):
    """
    Directly ingests an exported Discord JSON file.
    Compatible with DiscordChatExporter GUI, CLI, or Discord GDPR Data Package.
    NO BOT NEEDED! NO ADMIN RIGHTS NEEDED!
    """
    try:
        content_bytes = await file.read()
        raw_text = content_bytes.decode("utf-8")
        data = json.loads(raw_text)

        channel_fallback = file.filename.rsplit(".", 1)[0] if file.filename else "imported-channel"
        parsed_messages, meta = parse_discord_dict(data, channel_id_fallback=channel_fallback)
        inserted_count = insert_messages(parsed_messages)
        stats = get_vault_stats()

        return {
            "status": "success",
            "filename": file.filename,
            "parsed_messages": len(parsed_messages),
            "inserted_messages": inserted_count,
            "channel": meta.get("channel", {}).get("name") or channel_fallback,
            "meta": meta,
            "vault": stats,
        }
    except Exception as e:
        logger.error(f"Upload JSON parsing failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to process Discord JSON: {str(e)}")


@app.post("/api/ingest-json")
async def ingest_raw_json(data: Dict[str, Any]):
    """Directly ingests a JSON object representing Discord messages."""
    try:
        parsed_messages, meta = parse_discord_dict(data)
        inserted_count = insert_messages(parsed_messages)
        stats = get_vault_stats()
        return {
            "status": "success",
            "parsed_messages": len(parsed_messages),
            "inserted_messages": inserted_count,
            "meta": meta,
            "vault": stats,
        }
    except Exception as e:
        logger.error(f"Ingest JSON failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ingest-sample")
async def ingest_sample():
    """Populates the vault with realistic 90-day Discord conversation sample data."""
    count = seed_sample_data()
    stats = get_vault_stats()
    return {
        "status": "success",
        "seeded_messages": count,
        "vault": stats,
    }


@app.post("/api/clear-vault")
async def clear_vault():
    """Resets and clears the SQLite message vault."""
    clear_database()
    return {"status": "success", "message": "Chat vault cleared successfully"}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """RAG Chat completion using SQLite FTS5 context and Hermes LLM."""
    retrieved = search_90_days(query=req.message, channel_id=req.channel_id, limit=12, days=90)
    rag_context = assemble_rag_context(retrieved)
    response_text = await call_hermes_llm(
        prompt=req.message,
        rag_context=rag_context,
        history=req.history,
        voice_mode=req.voice_mode,
    )

    return {
        "response": response_text,
        "retrieved_context": retrieved,
        "model": CONFIG["llm_model"],
    }


@app.post("/api/voice/call-turn")
async def voice_call_turn(req: VoiceCallRequest):
    """
    Full Voice Call Loop:
    Browser Web Speech STT -> 90-day FTS5 Retrieval -> Hermes LLM -> ElevenLabs TTS.
    """
    retrieved = search_90_days(query=req.transcript, channel_id=req.channel_id, limit=8, days=90)
    rag_context = assemble_rag_context(retrieved)

    # Generate spoken voice response (natural, brief)
    response_text = await call_hermes_llm(
        prompt=req.transcript,
        rag_context=rag_context,
        voice_mode=True,
    )

    # Attempt ElevenLabs TTS synthesis
    voice_service = ElevenLabsService(CONFIG["elevenlabs_api_key"])
    audio_base64: Optional[str] = None
    used_elevenlabs = False
    voice_error = None

    if voice_service.is_configured():
        try:
            target_voice = req.voice_id or CONFIG["elevenlabs_voice_id"]
            audio_bytes = await voice_service.generate_speech(
                text=response_text,
                voice_id=target_voice,
            )
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            used_elevenlabs = True
        except Exception as e:
            logger.warning(f"ElevenLabs TTS failed: {e}")
            voice_error = str(e)

    return {
        "transcript": req.transcript,
        "response_text": response_text,
        "audio_base64": audio_base64,
        "used_elevenlabs": used_elevenlabs,
        "voice_error": voice_error,
        "retrieved_context": retrieved,
    }


@app.post("/api/voice/tts")
async def direct_tts(req: TTSRequest):
    """Generates direct MP3 audio stream for specified text using ElevenLabs."""
    voice_service = ElevenLabsService(CONFIG["elevenlabs_api_key"])
    if not voice_service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="ElevenLabs API key is not configured. Add ELEVENLABS_API_KEY in Settings.",
        )
    try:
        target_voice = req.voice_id or CONFIG["elevenlabs_voice_id"]
        audio_bytes = await voice_service.generate_speech(text=req.text, voice_id=target_voice)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/voice/voices")
async def get_voices():
    """Lists available ElevenLabs voices."""
    service = ElevenLabsService(CONFIG["elevenlabs_api_key"])
    voices = await service.list_available_voices()
    return {"voices": voices}


@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """Updates runtime configurations."""
    if req.llm_base_url is not None:
        CONFIG["llm_base_url"] = req.llm_base_url.rstrip("/")
    if req.llm_model is not None:
        CONFIG["llm_model"] = req.llm_model
    if req.llm_api_key is not None:
        CONFIG["llm_api_key"] = req.llm_api_key
    if req.elevenlabs_api_key is not None:
        CONFIG["elevenlabs_api_key"] = req.elevenlabs_api_key
    if req.elevenlabs_voice_id is not None:
        CONFIG["elevenlabs_voice_id"] = req.elevenlabs_voice_id

    llm_info = await check_llm_status()
    voice_service = ElevenLabsService(CONFIG["elevenlabs_api_key"])

    return {
        "status": "success",
        "settings": {
            "llm_base_url": CONFIG["llm_base_url"],
            "llm_model": CONFIG["llm_model"],
            "llm_online": llm_info.get("online", False),
            "elevenlabs_configured": voice_service.is_configured(),
            "elevenlabs_voice_id": CONFIG["elevenlabs_voice_id"],
        },
    }


# --- Static Files & Single Page Dashboard ---
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "ThreadLore API is running. Place index.html in frontend/"}
