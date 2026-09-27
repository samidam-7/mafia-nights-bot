from __future__ import annotations

import random
from collections import Counter
from typing import Any


ROLES = {
    "mafia": "🔪 سفاح",
    "detective": "🔍 كونان",
    "doctor": "👨‍⚕️ طبيب",
    "wizard": "🧙 ساحر",
    "guard": "🛡️ حارس",
    "hunter": "🏹 صياد",
    "clown": "🤡 مهرج",
    "leader": "👑 زعيم",
    "citizen": "👨‍🌾 مواطن",
}

LEVELS = [
    (0, "مبتدئ"),
    (5, "ساكن المدينة"),
    (15, "حارس الظالم"),
    (30, "محقق المدينة"),
    (50, "أسطورة مدينة الظالم"),
]

CHARACTER_NAMES = [
    "الظل الأسود",
    "العين الصامتة",
    "حارس الليل",
    "الغريب المقنع",
    "صوت الأزقة",
    "الرجل المجهول",
    "آخر الناجين",
    "سيد الأسرار",
    "الشبح القديم",
    "ابن المدينة",
]

ACTION_ROLES = {
    "kill": "mafia",
    "check": "detective",
    "revive": "doctor",
    "curse": "wizard",
    "protect": "guard",
}


def get_level(points: int) -> str:
    level = LEVELS[0][1]
    for required, name in LEVELS:
        if points >= required:
            level = name
    return level


def new_game(chat_id: int) -> dict[str, Any]:
    return {
        "chat_id": str(chat_id),
        "players": {},
        "alive": [],
        "dead": [],
        "roles": {},
        "started": False,
        "phase": "waiting",
        "night": 0,
        "day": 0,
        "votes": {},
        "history": [],
        "winner": None,
        "message_ids": [],
        "used_actions": {},
        "night_actions": {},
        "active_curses": [],
        "cursed_next_night": [],
        "protected_target": None,
        "doctor_used": False,
        "wizard_used": False,
        "guard_used": False,
        "leader_used": False,
        "pending_hunter": None,
        "hunter_turn_id": 0,
        "vote_round": 0,
        "vote_finalizing": False,
        "player_stats": {},
        "finished": False,
    }


def new_player(user: Any) -> dict[str, Any]:
    return {
        "id": int(user.id),
        "name": user.first_name or "لاعب",
        "username": getattr(user, "username", None),
        "alive": True,
        "role": None,
        "character": None,
    }


def get_roles_for_players(count: int) -> list[str]:
    if count < 3 or count > 20:
        raise ValueError("عدد اللاعبين يجب أن يكون بين 3 و20")

    if count == 3:
        roles = ["mafia", "detective", "citizen"]
    elif count == 4:
        roles = ["mafia", "detective", "doctor"]
    elif count == 5:
        roles = ["mafia", "mafia", "detective", "doctor"]
    elif 6 <= count <= 8:
        roles = ["mafia", "mafia", "detective", "doctor", "leader"]
    elif 9 <= count <= 11:
        roles = [
            "mafia",
            "mafia",
            "detective",
            "detective",
            "doctor",
            "wizard",
            "leader",
        ]
    elif 12 <= count <= 15:
        roles = [
            "mafia",
            "mafia",
            "mafia",
            "detective",
            "detective",
            "doctor",
            "wizard",
            "hunter",
            "leader",
        ]
    else:
        roles = [
            "mafia",
            "mafia",
            "mafia",
            "detective",
            "detective",
            "detective",
            "doctor",
            "wizard",
            "guard",
            "hunter",
            "clown",
            "leader",
        ]

    roles.extend(["citizen"] * (count - len(roles)))
    random.shuffle(roles)
    return roles


def assign_roles(game: dict[str, Any]) -> None:
    player_ids = list(game["players"])
    roles = get_roles_for_players(len(player_ids))
    random.shuffle(player_ids)

    game["alive"] = player_ids.copy()
    game["dead"] = []
    game["roles"] = {}
    game["player_stats"] = {
        player_id: {
            "checks": 0,
            "kills": 0,
            "saves": 0,
            "protections": 0,
            "votes": 0,
        }
        for player_id in player_ids
    }

    for index, player_id in enumerate(player_ids):
        player = game["players"][player_id]
        role = roles[index]
        player["role"] = role
        player["alive"] = True
        player["character"] = (
            CHARACTER_NAMES[index]
            if index < len(CHARACTER_NAMES)
            else f"ساكن المدينة {index + 1}"
        )
        game["roles"][player_id] = role


def is_alive(game: dict[str, Any], user_id: str | int) -> bool:
    return str(user_id) in game.get("alive", [])


def validate_action(
    game: dict[str, Any],
    actor_id: str | int,
    action: str,
    target_id: str | int,
) -> tuple[bool, str]:
    actor_id = str(actor_id)
    target_id = str(target_id)

    if not game.get("started"):
        return False, "اللعبة غير فعالة."
    if game.get("phase") != "night":
        return False, "هذه القدرة متاحة أثناء الليل فقط."
    if not is_alive(game, actor_id):
        return False, "أنت خارج اللعبة."

    actor = game["players"].get(actor_id)
    target = game["players"].get(target_id)
    expected_role = ACTION_ROLES.get(action)

    if not actor or not target or not expected_role:
        return False, "القرار غير صالح."
    if actor.get("role") != expected_role:
        return False, "هذه القدرة ليست من دورك."
    if actor_id in game.setdefault("used_actions", {}):
        return False, "استخدمت قدرتك هذه الليلة مسبقًا."

    if action in {"kill", "check", "curse"} and target_id == actor_id:
        return False, "لا يمكنك اختيار نفسك."
    if action in {"kill", "check", "curse", "protect"} and not is_alive(
        game, target_id
    ):
        return False, "هذا اللاعب ليس حيًا."
    if action == "revive" and target_id not in game.get("dead", []):
        return False, "لا يمكن إحياء هذا اللاعب."
    if action == "revive" and game.get("doctor_used"):
        return False, "استخدم الطبيب قدرته مسبقًا."
    if action == "curse" and game.get("wizard_used"):
        return False, "استخدم الساحر قدرته مسبقًا."
    if action == "protect" and game.get("guard_used"):
        return False, "استخدم الحارس قدرته مسبقًا."

    return True, ""


def submit_action(
    game: dict[str, Any],
    actor_id: str | int,
    action: str,
    target_id: str | int,
) -> tuple[bool, str, str | None]:
    actor_id = str(actor_id)
    target_id = str(target_id)
    valid, error = validate_action(game, actor_id, action, target_id)
    if not valid:
        return False, error, None

    game.setdefault("used_actions", {})[actor_id] = {
        "action": action,
        "target": target_id,
        "night": game["night"],
    }

    stats = game.setdefault("player_stats", {}).setdefault(
        actor_id,
        {"checks": 0, "kills": 0, "saves": 0, "protections": 0, "votes": 0},
    )

    if action == "kill":
        # Keep the original behavior: a mafia selection is the current kill
        # decision, and the last valid mafia selection is resolved.
        game.setdefault("night_actions", {})["kill"] = target_id
        stats["kills"] += 1
        return True, "تم تسجيل قرارك بالقتل.", None

    if action == "check":
        stats["checks"] += 1
        role_name = ROLES[game["players"][target_id]["role"]]
        return True, "تم كشف حقيقة اللاعب.", role_name

    if action == "revive":
        game["dead"].remove(target_id)
        game["alive"].append(target_id)
        game["players"][target_id]["alive"] = True
        game["doctor_used"] = True
        stats["saves"] += 1
        return True, "تم إحياء اللاعب بنجاح.", None

    if action == "curse":
        game.setdefault("cursed_next_night", []).append(target_id)
        game["wizard_used"] = True
        return True, "تم تسجيل اللعنة لليلة القادمة.", None

    if action == "protect":
        game["protected_target"] = target_id
        game["guard_used"] = True
        stats["protections"] += 1
        return True, "تم تسجيل الحماية.", None

    return False, "القرار غير معروف.", None


def resolve_night(game: dict[str, Any]) -> str | None:
    target_id = game.get("night_actions", {}).get("kill")
    if not target_id or target_id not in game.get("alive", []):
        return None
    if target_id == game.get("protected_target"):
        return None

    game["alive"].remove(target_id)
    game["dead"].append(target_id)
    game["players"][target_id]["alive"] = False
    game.setdefault("history", []).append(
        {
            "event": "night_death",
            "player_id": target_id,
            "player": game["players"][target_id]["name"],
            "role": game["players"][target_id]["role"],
            "night": game["night"],
        }
    )
    return target_id


def eliminate_player(
    game: dict[str, Any], player_id: str | int, reason: str
) -> bool:
    player_id = str(player_id)
    if player_id not in game.get("alive", []):
        return False

    game["alive"].remove(player_id)
    game.setdefault("dead", []).append(player_id)
    game["players"][player_id]["alive"] = False
    game.setdefault("history", []).append(
        {
            "event": "elimination",
            "reason": reason,
            "player_id": player_id,
            "player": game["players"][player_id]["name"],
            "role": game["players"][player_id]["role"],
            "day": game.get("day", 0),
        }
    )
    return True


def check_clown_win(game: dict[str, Any], player_id: str | int, reason: str) -> bool:
    player_id = str(player_id)
    return (
        reason == "vote"
        and player_id in game.get("players", {})
        and game["players"][player_id].get("role") == "clown"
    )


def check_winner(game: dict[str, Any]) -> str | None:
    mafia_alive = 0
    town_alive = 0

    for player_id in game.get("alive", []):
        role = game["players"].get(player_id, {}).get("role")
        if role == "mafia":
            mafia_alive += 1
        elif role != "clown":
            town_alive += 1

    if mafia_alive == 0:
        return "citizens"
    if mafia_alive >= town_alive:
        return "mafia"
    return None


def calculate_votes(game: dict[str, Any]) -> str | None:
    counts = Counter(
        target
        for target in game.get("votes", {}).values()
        if target != "abstain" and target in game.get("alive", [])
    )
    if not counts:
        return None

    highest = max(counts.values())
    winners = [player_id for player_id, count in counts.items() if count == highest]
    return "tie" if len(winners) > 1 else winners[0]


def game_winners(game: dict[str, Any], winner: str) -> tuple[list[str], list[str]]:
    winners: list[str] = []
    losers: list[str] = []

    for player_id, player in game.get("players", {}).items():
        role = player.get("role")
        won = (
            role == "mafia"
            if winner == "mafia"
            else role not in {"mafia", "clown"}
            if winner == "citizens"
            else role == "clown"
        )
        (winners if won else losers).append(player_id)

    return winners, losers


def best_player(game: dict[str, Any]) -> str:
    if not game.get("players"):
        return "لا يوجد"

    def score(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        player_id, player = item
        stats = game.get("player_stats", {}).get(player_id, {})
        value = (
            stats.get("checks", 0)
            + stats.get("kills", 0)
            + stats.get("saves", 0)
            + stats.get("protections", 0)
            + stats.get("votes", 0)
        )
        if player_id in game.get("alive", []):
            value += 2
        return value, player.get("name", "")

    return max(game["players"].items(), key=score)[1].get("name", "لا يوجد")