from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(parsed, minimum)


@dataclass(frozen=True)
class Settings:
    token: str
    data_file: str
    night_seconds: int
    discussion_seconds: int
    voting_seconds: int
    hunter_seconds: int
    flag_turn_seconds: int
    max_players: int
    video_join: str
    video_night: str
    video_night_action: str
    video_day: str
    video_vote: str
    video_mafia_win: str
    video_citizens_win: str
    video_clown_win: str


def load_settings() -> Settings:
    return Settings(
        token=os.getenv("BOT_TOKEN", "").strip(),
        data_file=os.getenv("DATA_FILE", "data/shaden_mafia_data.json").strip(),
        night_seconds=_int_env("NIGHT_SECONDS", 60),
        discussion_seconds=_int_env("DISCUSSION_SECONDS", 60),
        voting_seconds=_int_env("VOTING_SECONDS", 60),
        hunter_seconds=_int_env("HUNTER_SECONDS", 30),
        flag_turn_seconds=_int_env("FLAG_TURN_SECONDS", 30),
        max_players=_int_env("MAX_PLAYERS", 20, minimum=3),
        video_join=os.getenv("VIDEO_JOIN", "").strip(),
        video_night=os.getenv("VIDEO_NIGHT", "").strip(),
        video_night_action=os.getenv("VIDEO_NIGHT_ACTION", "").strip(),
        video_day=os.getenv("VIDEO_DAY", "").strip(),
        video_vote=os.getenv("VIDEO_VOTE", "").strip(),
        video_mafia_win=os.getenv("VIDEO_MAFIA_WIN", "").strip(),
        video_citizens_win=os.getenv("VIDEO_CITIZENS_WIN", "").strip(),
        video_clown_win=os.getenv("VIDEO_CLOWN_WIN", "").strip(),
    )