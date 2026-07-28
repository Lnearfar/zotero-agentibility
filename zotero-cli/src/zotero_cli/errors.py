from __future__ import annotations

from typing import Any


class CliError(Exception):
    def __init__(self, code: str, message: str, *, details: Any = None, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.exit_code = exit_code
