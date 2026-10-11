#!/usr/bin/env python3
"""
ThreadLore - Agent Skill Standalone Vault Query & Synthesis Tool
Complies with Agent Skill Open Standard.
Queries SQLite FTS5 database, ranks results with BM25, and optionally synthesizes answers via Hermes LLM.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from backend.db import get_vault_stats, search_90_days
except ImportError:
    # Standalone fallback if package structure is run independently
    from db import get_vault_stats, search_90_days


def format_table(rows: List[Dict[str, Any]]) -> str:
    """Formats rows as a clean ASCII/Unicode table."""
    if not rows:
        return "No matching records found in the 90-day archive."

    headers = ["Author", "Channel", "Timestamp (UTC)", "BM25 Rank", "Message Snippet"]
    col_widths = [16, 16, 20, 10, 50]

    # Header line
    header_str = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    sep_str = "-+-".join("-" * w for w in col_widths)

    out = [header_str, sep_str]
    for r in rows:
        author = (r.get("author") or "Unknown")[:16].ljust(16)
        channel = f"#{r.get('channel_id') or ''}"[:16].ljust(16)
        ts = (r.get("timestamp") or "")[:19].replace("T", " ").ljust(20)
        rank = str(r.get("rank", 0.0))[:10].ljust(10)
        content = (r.get("content") or "").replace("\n", " ")[:48]
        if len(r.get("content", "")) > 48:
            content += ".."
        content = content.ljust(50)
        out.append(f"{author} | {channel} | {ts} | {rank} | {content}")

    return "\n".join(out)


def format_markdown(rows: List[Dict[str, Any]], query: str) -> str:
    """Formats results as structured Markdown."""
    if not rows:
        return f"### ThreadLore Search: `{query}`\n\n*No messages found matching this query in the 90-day window.*"

    out = [f"### ThreadLore Search: `{query}` ({len(rows)} results)\n"]
    for i, r in enumerate(rows, 1):
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        ch = r.get("channel_id", "unknown")
        author = r.get("author", "unknown")
        rank = r.get("rank", 0.0)
        content = r.get("content", "")
        out.append(f"**{i}. {author}** in `#{ch}` at `{ts} UTC` *(BM25: {rank})*")
        out.append(f"> {content}\n")

    return "\n".join(out)


def run_llm_synthesis(
    query: str,
    records: List[Dict[str, Any]],
    base_url: str = "http://localhost:11434/v1",
    model: str = "hermes3",
    api_key: str = "ollama",
) -> str:
    """Executes Hermes LLM synthesis on retrieved records."""
    if not records:
        return "No messages were retrieved from the 90-day vault, so no synthesis could be generated."

    context_lines = []
    for r in records:
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        ch = r.get("channel_id", "unknown")
        author = r.get("author", "unknown")
        content = r.get("content", "")
        context_lines.append(f"[{ts}] #{ch} | {author}: {content}")

    rag_text = "\n".join(context_lines)

    prompt = (
        f"You are ThreadLore, an expert AI analyst powered by Nous Hermes 3.\n"
        f"Synthesize an executive summary answering the user query based ONLY on the provided 90-day Discord archive.\n\n"
        f"User Query: {query}\n\n"
        f"Retrieved Discord Messages:\n{rag_text}\n\n"
        f"Format your response with key takeaways, quoting authors and dates when relevant."
    )

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are ThreadLore powered by Nous Hermes 3."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        # Fallback offline synthesis
        lines = [f"**ThreadLore Local Synthesis (Offline Mode)**"]
        lines.append(f"Retrieved {len(records)} relevant messages from the 90-day archive:")
        for r in records[:5]:
            lines.append(f"- **{r.get('author')}** in `#{r.get('channel_id')}`: \"{r.get('content')}\"")
        lines.append(f"\n*(Note: LLM endpoint at {base_url} was unreachable: {e})*")
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ThreadLore - Agent Skill Vault Query")
    parser.add_argument("-q", "--query", required=True, help="Search query or keyword")
    parser.add_argument("-c", "--channel", default=None, help="Filter by channel ID")
    parser.add_argument("-d", "--days", type=int, default=90, help="History window in days (default: 90)")
    parser.add_argument("-l", "--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("-f", "--format", choices=["json", "markdown", "table"], default="markdown", help="Output format")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument("--synthesize", action="store_true", help="Generate Hermes LLM synthesis")
    parser.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"), help="LLM API base URL")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "hermes3"), help="LLM model identifier")
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY", "ollama"), help="LLM API Key")

    args = parser.parse_args()

    results = search_90_days(
        query=args.query,
        channel_id=args.channel,
        limit=args.limit,
        days=args.days,
        db_path=args.db,
    )

    if args.format == "json":
        output = json.dumps({"query": args.query, "count": len(results), "results": results}, indent=2)
        print(output)
    elif args.format == "table":
        print(format_table(results))
    else:
        print(format_markdown(results, args.query))

    if args.synthesize:
        print("\n" + "=" * 60)
        print("HERMES 3 SYNTHESIS")
        print("=" * 60 + "\n")
        synthesis = run_llm_synthesis(
            query=args.query,
            records=results,
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
        )
        print(synthesis)


if __name__ == "__main__":
    main()
