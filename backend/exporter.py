"""
ThreadSift - DiscordChatExporter Automation Wrapper
Executes DiscordChatExporter.Cli via subprocess, parses exported JSON,
and ingests messages into the local SQLite FTS5 database.
"""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.db import insert_messages

logger = logging.getLogger("threadsift.exporter")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_BIN_DIR = BASE_DIR / "bin"
DEFAULT_DATA_DIR = BASE_DIR / "data" / "exports"


def find_exporter_cli() -> Optional[str]:
    """
    Locates the DiscordChatExporter.Cli binary.
    Checks:
    1. Local backend/bin directory (.exe or unix binary or .cmd/.bat)
    2. System PATH
    3. Custom environment variable DISCORD_EXPORTER_PATH
    """
    env_path = os.getenv("DISCORD_EXPORTER_PATH")
    if env_path and Path(env_path).is_file():
        return str(Path(env_path).resolve())

    candidates = [
        DEFAULT_BIN_DIR / "DiscordChatExporter.Cli.exe",
        DEFAULT_BIN_DIR / "DiscordChatExporter.Cli",
        DEFAULT_BIN_DIR / "DiscordChatExporter.Cli.bat",
        DEFAULT_BIN_DIR / "DiscordChatExporter.Cli.cmd",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # Check system PATH
    for cmd_name in ["DiscordChatExporter.Cli", "DiscordChatExporter.Cli.exe", "discordchatexporter-cli"]:
        path_on_sys = shutil.which(cmd_name)
        if path_on_sys:
            return path_on_sys

    return None


def parse_discord_dict(data: Dict[str, Any], channel_id_fallback: str = "discord-channel") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parses a DiscordChatExporter dictionary structure into standardized ThreadSift messages.
    """
    meta = {
        "guild": data.get("guild", {}),
        "channel": data.get("channel", {}),
        "date_range": data.get("dateRange", {}),
        "exported_count": len(data.get("messages", [])),
    }

    channel_name = data.get("channel", {}).get("name") or channel_id_fallback
    channel_id = str(data.get("channel", {}).get("id") or channel_name)

    raw_messages = data.get("messages", [])
    parsed_messages: List[Dict[str, Any]] = []

    for msg in raw_messages:
        # Extract author name (prefer nickname if available)
        author_obj = msg.get("author", {})
        author_name = author_obj.get("nickname") or author_obj.get("name") or "Unknown"

        # Content may be text + attachments + embeds
        content = msg.get("content", "") or ""
        
        # If attachments or embeds exist, append brief descriptors
        attachments = msg.get("attachments", [])
        if attachments:
            att_names = [a.get("fileName", "attachment") for a in attachments]
            content += f" [Attached: {', '.join(att_names)}]"

        timestamp_str = msg.get("timestamp")
        if not timestamp_str:
            timestamp_str = datetime.now(timezone.utc).isoformat()

        # Format ISO timestamp if necessary
        try:
            # Normalize timestamp to ISO-8601
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            normalized_ts = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            normalized_ts = timestamp_str

        parsed_messages.append({
            "id": str(msg.get("id")),
            "channel_id": channel_id,
            "author": author_name,
            "timestamp": normalized_ts,
            "content": content.strip(),
        })

    return parsed_messages, meta


def parse_discord_json(file_path: Path, channel_id_fallback: str = "discord-channel") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parses a DiscordChatExporter JSON output file into standardized ThreadSift messages.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_discord_dict(data, channel_id_fallback=channel_id_fallback)



def run_export(
    channel_id: str,
    token: str,
    days: int = 90,
    bot_token: bool = False,
    output_dir: Optional[str] = None,
    custom_bin_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calculates cutoff date for `days` ago in ISO-8601 format,
    executes DiscordChatExporter.Cli via subprocess.run,
    and ingests messages into SQLite FTS5 database.
    """
    cli_path = custom_bin_path or find_exporter_cli()
    if not cli_path:
        raise FileNotFoundError(
            "DiscordChatExporter.Cli binary not found. "
            "Please place DiscordChatExporter.Cli.exe in backend/bin/ "
            "or set DISCORD_EXPORTER_PATH in .env, or use the sample seed generator."
        )

    out_folder = Path(output_dir) if output_dir else DEFAULT_DATA_DIR
    out_folder.mkdir(parents=True, exist_ok=True)

    timestamp_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = out_folder / f"export_{channel_id}_{timestamp_suffix}.json"

    # Calculate cutoff date
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    after_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    cmd = [
        cli_path,
        "export",
        "-t", token,
        "-c", channel_id,
        "-f", "Json",
        "-o", str(output_file.resolve()),
        "--after", after_str,
    ]

    if bot_token:
        cmd.extend(["-b", "true"])

    logger.info(f"Executing DiscordChatExporter: {' '.join(cmd[:4])} [REDACTED TOKEN] ...")

    # Run CLI
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or f"CLI exited with code {result.returncode}"
        logger.error(f"DiscordChatExporter error: {error_msg}")
        raise RuntimeError(f"DiscordChatExporter failed: {error_msg}")

    # Verify output file exists
    if not output_file.exists():
        # DiscordChatExporter might append channel name to output path if path was directory
        potential_files = list(out_folder.glob(f"*{channel_id}*.json"))
        if potential_files:
            output_file = sorted(potential_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]
        else:
            raise FileNotFoundError(f"Export file was not created at {output_file}")

    # Parse and insert messages
    parsed_messages, meta = parse_discord_json(output_file, channel_id_fallback=channel_id)
    inserted_count = insert_messages(parsed_messages)

    return {
        "status": "success",
        "channel_id": channel_id,
        "days": days,
        "cutoff_date": after_str,
        "exported_messages": len(parsed_messages),
        "inserted_messages": inserted_count,
        "file_path": str(output_file.resolve()),
        "meta": meta,
    }


def generate_sample_archive_data(days: int = 90) -> List[Dict[str, Any]]:
    """
    Generates a realistic 90-day archive of Discord conversation history across
    channels (#dev-core, #research-hermes, #operations, #product, #general)
    highlighting technical debates, release schedules, AI engineering, FTS5 benchmarks,
    and voice pipeline tuning.
    """
    now = datetime.now(timezone.utc)
    channels = [
        {"id": "dev-core", "name": "💻-dev-core"},
        {"id": "research-hermes", "name": "🧠-research-hermes"},
        {"id": "operations", "name": "🚀-operations"},
        {"id": "product", "name": "📋-product"},
        {"id": "general", "name": "💬-general"},
    ]

    authors = [
        "Nova_LeadArchitect",
        "Cipher_ML",
        "Elena_SysOps",
        "Kaelen_Backend",
        "Aria_VoiceAI",
        "Devin_QA",
        "Marcus_PM",
    ]

    sample_conversations = [
        # Channel: research-hermes
        ("research-hermes", "Cipher_ML", 2, "Just finished benchmarking Nous Hermes 3 on local Ollama / vLLM. The tool-calling latency is sub-250ms on our RTX 4090."),
        ("research-hermes", "Nova_LeadArchitect", 2, "That's huge. Does Hermes 3 follow strict JSON output schemas reliably during voice synthesis prompts?"),
        ("research-hermes", "Cipher_ML", 2, "Yes! We tested structured JSON prompts and voice-conversational brevity constraints. Hermes 3 maintains character without rambling."),
        ("research-hermes", "Aria_VoiceAI", 1, "We connected ElevenLabs turbo-v2.5 with Hermes 3. Average end-to-end voice latency from Speech-to-Text finish to first audio chunk is around 680ms!"),
        ("research-hermes", "Nova_LeadArchitect", 1, "That is within the threshold for a real-time conversational phone call experience. Excellent work."),
        
        # Channel: dev-core (FTS5 & SQLite)
        ("dev-core", "Kaelen_Backend", 4, "Refactored the SQLite FTS5 index. The external content table with `content='messages'` reduced DB file size by 42% compared to duplicating content columns."),
        ("dev-core", "Nova_LeadArchitect", 4, "Make sure we run `INSERT INTO messages_fts(messages_fts) VALUES('rebuild')` after batch ingests to ensure rowid mapping stays 100% aligned."),
        ("dev-core", "Kaelen_Backend", 3, "Confirmed. Also implemented BM25 rank scoring and snippet extraction with `<mark>` tags for full-text search highlights."),
        ("dev-core", "Devin_QA", 3, "Testing search queries with punctuation and symbols. Sanitization is catching unclosed quotes properly now without throwing sqlite3 syntax exceptions."),

        # Channel: operations
        ("operations", "Elena_SysOps", 7, "Deployment update: Production cluster upgrade scheduled for next Tuesday at 02:00 UTC. Zero-downtime rolling restart."),
        ("operations", "Marcus_PM", 7, "Will the DiscordChatExporter scheduled jobs be paused during the migration window?"),
        ("operations", "Elena_SysOps", 6, "Yes, we set a maintenance flag. Ingestion resumes automatically once the SQLite replica synchronizes."),
        ("operations", "Nova_LeadArchitect", 5, "Let's also retain local WAL checkpoints every 1,000 pages so read queries during export writes remain completely non-blocking."),

        # Channel: product
        ("product", "Marcus_PM", 12, "Customer feedback on the 90-day search retention: Users love finding lost engineering decisions from 2 months ago in under 15 milliseconds."),
        ("product", "Devin_QA", 11, "One request from power users: Can we filter search queries both by channel and by author simultaneously in the dashboard?"),
        ("product", "Kaelen_Backend", 10, "Already added! The `/api/search` endpoint accepts `channel_id`, `author`, `days`, and `limit` as optional query parameters."),
        ("product", "Marcus_PM", 9, "ThreadSift v1.0 release date is confirmed for the 25th. All documentation and Agent Skill Open Standard specs need to be finalized by Friday."),

        # Channel: dev-core (Audio & ElevenLabs)
        ("dev-core", "Aria_VoiceAI", 15, "Voice call mode update: Added fallback to browser Web Speech Synthesis if the ElevenLabs API key is absent or quota is exceeded."),
        ("dev-core", "Nova_LeadArchitect", 14, "Smart move. That ensures developers testing locally or offline can still test the interactive voice conversation loop."),
        ("dev-core", "Aria_VoiceAI", 14, "Browser Web Speech API captures speech with `webkitSpeechRecognition`, feeds text to Hermes 3 with 90-day Discord context, and speaks the response."),

        # Channel: research-hermes
        ("research-hermes", "Cipher_ML", 25, "Prompt engineering tip for Hermes 3: Adding `<thinking>` tags during complex retrieval queries helps it synthesize multi-author chat threads accurately."),
        ("research-hermes", "Nova_LeadArchitect", 24, "Agreed. For voice mode, we prompt it for natural, concise spoken speech without markdown links or bullet points."),

        # Channel: operations
        ("operations", "Elena_SysOps", 35, "Disk space alert resolved: The SQLite database with 150,000 archived Discord messages is only 48 MB thanks to WAL compression."),
        ("operations", "Kaelen_Backend", 34, "FTS5 indexes are remarkably lean. We can easily scale to 1 year archives if needed, but the 90-day rolling window is optimal for working memory."),

        # Channel: general
        ("general", "Marcus_PM", 45, "Team lunch celebrating the ThreadSift project milestone this Thursday at noon! Tacos are on engineering."),
        ("general", "Cipher_ML", 45, "Count me in! Celebrating sub-second RAG latency with extra guacamole."),
        ("general", "Aria_VoiceAI", 44, "Will be there. Can we demo the live voice agent ordering our tacos? 😄"),
        ("general", "Nova_LeadArchitect", 44, "Haha, only if Hermes 3 remembers that Elena is allergic to cilantro!"),

        # Channel: product
        ("product", "Marcus_PM", 60, "Quarterly review: Search queries over Discord history reduced duplicate support tickets by 63% across the engineering organization."),
        ("product", "Nova_LeadArchitect", 59, "The biggest win was finding deployment rollbacks and architectural decision records directly from past chat threads."),

        # Channel: dev-core
        ("dev-core", "Kaelen_Backend", 75, "Database schema migration v2 completed. Primary key deduplication using `INSERT OR IGNORE` ensures re-running exports is fully idempotent."),
        ("dev-core", "Devin_QA", 74, "Verified. Exporting the same Discord channel 5 times produces zero duplicate messages in the chat vault."),

        # Channel: research-hermes
        ("research-hermes", "Cipher_ML", 85, "Initial experimentation with Gemma 2 and Hermes 3 on local quantization: 4-bit AWQ provides almost identical retrieval synthesis quality with half the VRAM."),
        ("research-hermes", "Nova_LeadArchitect", 84, "That means ThreadSift can run locally on an 8GB laptop GPU or Apple Silicon unified memory with zero cloud dependencies."),
    ]

    messages: List[Dict[str, Any]] = []
    msg_id_counter = 100000

    for ch_id, author, days_ago, text in sample_conversations:
        msg_id_counter += 1
        msg_time = now - timedelta(days=days_ago, minutes=(msg_id_counter % 360), seconds=(msg_id_counter % 59))
        messages.append({
            "id": f"discord-msg-{msg_id_counter}",
            "channel_id": ch_id,
            "author": author,
            "timestamp": msg_time.isoformat(),
            "content": text,
        })

    return messages


def seed_sample_data(db_path: Optional[str] = None) -> int:
    """
    Populates the chat vault with a rich 90-day archive of sample Discord messages.
    """
    messages = generate_sample_archive_data(days=90)
    count = insert_messages(messages, db_path=db_path)
    logger.info(f"Seeded {count} sample messages into chat vault.")
    return count
