from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_STATE: dict[str, Any] = {
    "players": {},
    "active_games": {},
}


class JsonStorage:
    """Small, atomic JSON store suitable for a single bot process."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    def _load_sync(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(DEFAULT_STATE)

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            # Never silently destroy a damaged save file.
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            return copy.deepcopy(DEFAULT_STATE)

        if not isinstance(data, dict):
            return copy.deepcopy(DEFAULT_STATE)

        data.setdefault("players", {})
        data.setdefault("active_games", {})
        return data

    def load(self) -> dict[str, Any]:
        return self._load_sync()

    def _save_sync(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    async def save(self, state: dict[str, Any]) -> None:
        snapshot = copy.deepcopy(state)
        async with self._lock:
            await asyncio.to_thread(self._save_sync, snapshot)