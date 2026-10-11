---
name: threadlore-chat-intelligence
version: 1.0.0
description: |
  Local-first chat intelligence agent skill for searching, retrieving, and synthesizing Discord conversation archives over a 90-day rolling window using SQLite FTS5 with BM25 ranking, Hermes LLM, and ElevenLabs voice output.
author: ThreadLore
license: MIT
tags:
  - discord
  - search
  - fts5
  - bm25
  - rag
  - chat-intelligence
  - voice-call
  - hermes
tools:
  - name: query_vault
    description: Standalone retrieval and synthesis script that searches the 90-day SQLite FTS5 Discord vault with BM25 ranking and optional LLM synthesis.
    path: scripts/query_vault.py
    interpreter: python
    parameters:
      query:
        type: string
        description: Search term or full-text query to match against author, timestamp, or message body.
        required: true
      channel:
        type: string
        description: Discord channel ID to restrict results to.
        required: false
      days:
        type: integer
        default: 90
        description: Rolling history window in days (default: 90).
        required: false
      limit:
        type: integer
        default: 20
        description: Maximum number of retrieved messages (default: 20).
        required: false
      synthesize:
        type: boolean
        default: false
        description: Whether to run Nous Hermes LLM synthesis on retrieved messages to answer an executive query.
        required: false
      format:
        type: string
        enum: ["json", "markdown", "table"]
        default: "markdown"
        description: Output presentation format.
        required: false
---

# ThreadLore Chat Intelligence Skill

ThreadLore enables AI agents and local developers to inspect, search, and synthesize conversations exported from Discord channels across a rolling 90-day window.

## Capabilities

1. **Deterministic BM25 Full-Text Search**:
   Queries an external content SQLite FTS5 virtual table (`messages_fts`) linked directly to the primary `messages` table. Results are ranked by BM25 relevance score and filtered by `messages.timestamp >= datetime('now', '-90 days')`.

2. **Grounded Context Synthesis**:
   Synthesizes engineering decisions, incident post-mortems, team discussions, and status updates directly from retrieved conversation threads using Nous Research Hermes 3 or Gemma.

3. **Multi-Channel & Multi-Author Filtering**:
   Narrows search queries across `#dev-core`, `#research-hermes`, `#operations`, `#product`, or custom Discord channels.

4. **Zero-Cloud Local Privacy**:
   All database operations run against local `backend/data/chat_vault.db`. No Discord data leaves the user's workstation.

5. **Zero-Bot Ingestion Standard**:
   Agents and users do NOT need Discord bot tokens or server admin approval. Discord conversations can be ingested via direct JSON exports from DiscordChatExporter GUI/CLI, user account tokens, or GDPR data packages.

---

## Initializing Discord Context Without a Bot

If the agent needs to ingest Discord messages on behalf of a non-admin user:
1. **Direct JSON**: Ingest exported channel JSON files via `backend.exporter.parse_discord_dict(data)`.
2. **User Account Token**: Run `python backend/bin/cli_runner.py export -t <user_token> -c <channel_id> -o export.json --after <date>`. No bot invite or guild admin privileges required.
3. **Sample Data**: Call `seed_sample_data()` for immediate offline testing.

---

## Standalone Script Usage (`scripts/query_vault.py`)

Agents and automated workflows can execute `query_vault.py` directly without running the FastAPI server.

### Basic Search (Markdown Output)

```bash
python skill/scripts/query_vault.py --query "Hermes 3" --days 90 --limit 10
```

### Channel-Specific Query with JSON Output

```bash
python skill/scripts/query_vault.py --query "deployment rollback" --channel "operations" --format json
```

### Retrieval + Generative Synthesis (RAG)

```bash
python skill/scripts/query_vault.py \
  --query "What was decided about the release date?" \
  --synthesize \
  --model "hermes3" \
  --base-url "http://localhost:11434/v1"
```

---

## Database Architecture

- **Primary Storage**: `messages (id TEXT PRIMARY KEY, channel_id TEXT, author TEXT, timestamp TEXT, content TEXT)`
- **Full-Text Index**: `messages_fts USING fts5(author, timestamp, content, content='messages', content_rowid='rowid')`
- **Synchronization**: Automated rowid triggers (`messages_ai`, `messages_ad`, `messages_au`) and batch rebuilds (`INSERT INTO messages_fts(messages_fts) VALUES('rebuild')`).

---

## Agent Invocation Guidelines

When acting on behalf of the user:
- Formulate targeted keyword queries (e.g. `"sqlite fts5"`, `"release date"`, `"incident"`) rather than conversational sentences for the initial FTS5 search.
- When summarizing retrieved threads, always cite the **Author**, **Channel**, and **Timestamp** to maintain strict provenance.
- For voice synthesis prompts, keep outputs concise (2-4 spoken sentences) and avoid markdown markup, URLs, and code fences.
