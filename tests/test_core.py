import tempfile
import unittest
from pathlib import Path

from threadsift.core import ThreadSift, load_records


class ThreadSiftTests(unittest.TestCase):
    def test_load_records_normalizes_common_chat_formats(self):
        text = "\n".join(
            [
                "[10/10/2026, 10:00] Alice: Build failed after deploy",
                "2026-10-10 10:05:00 bot: Retrying deploy",
                "Bob: Deploy completed",
                "",  # ignored
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.txt"
            path.write_text(text, encoding="utf-8")
            records = load_records([path])

        self.assertEqual(
            records,
            [
                "10/10/2026, 10:00 | Alice | Build failed after deploy",
                "2026-10-10 10:05:00 | bot | Retrying deploy",
                "Bob | Deploy completed",
            ],
        )

    def test_search_ranks_by_local_term_frequency(self):
        app = ThreadSift(
            [
                "Alice | build build failed",
                "bot | build started",
                "Bob | all green",
            ]
        )

        results = app.search("build")
        self.assertEqual([result.score for result in results], [2, 1])
        self.assertEqual(results[0].text, "Alice | build build failed")

    def test_synthesize_includes_focus_and_highlights(self):
        app = ThreadSift(["Alice | auth timeout", "Bob | fixed timeout issue"])
        synthesis = app.synthesize("timeout")

        self.assertIn("AI synthesis (local heuristic):", synthesis)
        self.assertIn("Focus: timeout", synthesis)
        self.assertIn("Highlights:", synthesis)


if __name__ == "__main__":
    unittest.main()
