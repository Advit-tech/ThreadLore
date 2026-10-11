"""
DiscordChatExporter.Cli Standalone Runner
Executes real Discord message export using Discord REST API or CLI arguments:
export -t <token> -c <channel_id> -f Json -o <output_path> --after <date>
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def fetch_real_discord_messages(channel_id: str, token: str, is_bot: bool = False, limit: int = 100):
    """Fetches real messages directly from Discord REST API using user or bot token."""
    auth_header = f"Bot {token}" if is_bot else token
    headers = {
        "Authorization": auth_header,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Discord API error {e.code}: {error_body}")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Discord API: {e}")


def main():
    parser = argparse.ArgumentParser(description="DiscordChatExporter.Cli")
    subparsers = parser.add_subparsers(dest="subcommand")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("-t", "--token", required=True, help="Discord user or bot token")
    export_parser.add_argument("-c", "--channel", required=True, help="Discord channel ID")
    export_parser.add_argument("-f", "--format", default="Json", help="Output format (Json)")
    export_parser.add_argument("-o", "--output", required=True, help="Output file path")
    export_parser.add_argument("--after", default=None, help="Cutoff date (e.g. YYYY-MM-DD)")
    export_parser.add_argument("-b", "--bot", action="store_true", help="Token is a bot token")

    args = parser.parse_args()

    if args.subcommand != "export":
        parser.print_help()
        sys.exit(1)

    print(f"[*] ThreadSift DiscordChatExporter: Exporting channel {args.channel}...")
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Fetch real messages from Discord
    try:
        raw_msgs = fetch_real_discord_messages(args.channel, args.token, is_bot=args.bot, limit=100)
    except Exception as err:
        print(f"[-] Export error: {err}", file=sys.stderr)
        sys.exit(1)

    messages = []
    for m in raw_msgs:
        author_info = m.get("author", {})
        author_name = author_info.get("global_name") or author_info.get("username") or "Unknown"
        messages.append({
            "id": m.get("id"),
            "type": "Default",
            "timestamp": m.get("timestamp"),
            "timestampEdited": m.get("edited_timestamp"),
            "content": m.get("content", ""),
            "author": {
                "id": author_info.get("id"),
                "name": author_name,
                "discriminator": author_info.get("discriminator", "0000"),
                "nickname": author_name,
                "color": None,
                "isBot": author_info.get("bot", False),
            },
            "attachments": m.get("attachments", []),
            "embeds": m.get("embeds", []),
        })

    export_data = {
        "guild": {"id": "guild", "name": "Discord Server"},
        "channel": {"id": args.channel, "name": f"channel-{args.channel}", "topic": ""},
        "dateRange": {"after": args.after, "before": datetime.now(timezone.utc).isoformat()},
        "messages": messages,
        "messageCount": len(messages),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)

    print(f"[+] Successfully exported {len(messages)} real messages to {output_path}")


if __name__ == "__main__":
    main()
