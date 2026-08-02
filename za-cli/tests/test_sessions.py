from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from za_cli import sessions


class SessionTests(unittest.TestCase):
    def test_sessions_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            sessions.create(config, "agent-a")
            sessions.create(config, "agent-b")
            state = sessions.load(config, "agent-a")
            state["collection"] = "COLLA123"
            sessions.save(config, state)
            self.assertEqual(sessions.load(config, "agent-a")["collection"], "COLLA123")
            self.assertIsNone(sessions.load(config, "agent-b")["collection"])
            self.assertEqual(sessions.session_path(config, "agent-a").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
