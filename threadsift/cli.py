from __future__ import annotations

import argparse

from .core import ThreadSift, load_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ThreadSift: local search with AI-style synthesis for chats/logs")
    parser.add_argument("query", help="What you want to find in chats/logs")
    parser.add_argument("files", nargs="+", help="Chat or log text files to index")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum number of highlights to include")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = load_records(args.files)
    app = ThreadSift(records)
    print(app.synthesize(args.query, top_k=args.top_k))


if __name__ == "__main__":
    main()
