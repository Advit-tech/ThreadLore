# ThreadSift

Sift through messy chats and logs with local search and AI synthesis, especially for Discord and WhatsApp style exports.

## Quick start

```bash
python -m threadsift.cli "deploy failure" /path/to/chat.txt /path/to/log.txt --top-k 5
```

ThreadSift will:
- normalize common chat/log lines into searchable records,
- run local keyword search with ranking,
- produce an AI-style synthesis summary from top matches.
