#!/usr/bin/env python3
"""
ThreadLore - One-Click Application Startup Script
Initializes the database, checks configurations, and launches the FastAPI server.
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.db import get_vault_stats, init_db
from backend.exporter import find_exporter_cli


def print_banner(host: str, port: int):
    cli_path = find_exporter_cli()
    stats = get_vault_stats()
    cli_status = f"[OK] Found at {Path(cli_path).name}" if cli_path else "[!] Not found (Using built-in runner & sample seeder)"

    banner = fr"""
========================================================================
  _____ _                        _ _____ _  __ _   
 |_   _| |__  _ __ ___  __ _  __| / ____(_)/ _| |  
   | | | '_ \| '__/ _ \/ _` |/ _` \___ \| | |_| |_ 
   | | | | | | | |  __/ (_| | (_| |___) | |  _|  _|
   |_| |_| |_|_|  \___|\__,_|\__,_|_____/|_|_| |_|  
                                                   
  Local-First Discord Chat Intelligence & Voice Agent
  Agent Skill Open Standard Compliant | SQLite FTS5 Engine
========================================================================
  * Web Dashboard:       http://{host}:{port}
  * API Documentation:   http://{host}:{port}/docs
  * Chat Vault Database: backend/data/chat_vault.db
  * 90-Day Archive:      {stats['messages_90_days']} messages ({stats['total_messages']} total)
  * Discord Exporter:    {cli_status}
  * Agent Skill Spec:    skill/SKILL.md
  * Retrieval Tool:      skill/scripts/query_vault.py
========================================================================
"""
    print(banner)


def main():
    parser = argparse.ArgumentParser(description="ThreadLore - Local-First Chat Intelligence")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"), help="Host to bind server to")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8000)), help="Port to bind server to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")
    args = parser.parse_args()

    # 1. Initialize SQLite Database & FTS5
    init_db()

    # 2. Print System Diagnostic Banner
    print_banner(args.host, args.port)

    # 3. Open Browser (optional)
    if not args.no_browser:
        try:
            webbrowser.open(f"http://{args.host}:{args.port}")
        except Exception:
            pass

    # 4. Start Uvicorn Server
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
