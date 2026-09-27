from __future__ import annotations

import asyncio
import html
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import game_engine as engine
from config import Settings, load_settings
from storage import JsonStorage


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mafia-nights-bot")

settings: Settings = load_settings()
storage = JsonStorage(settings.data_file)
saved_state = storage.load()
players: dict[str, dict[str, Any]] = saved_state.get("players", {})
games: dict[str, dict[str, Any]] = saved_state.get("active_games", {})

game_tasks: dict[str, asyncio.Task[Any]] = {}
flag_games: dict[str, dict[str, Any]] = {}
flag_tasks: dict[str, asyncio.Task[Any]] = {}

GAME_TITLE = "🕯️ مدينة الظالم | مافيا"
FLAG_EMOJIS = [
    "🇦🇪",
    "🇪🇬",
    "🇸🇦",
    "🇯🇴",
    "🇱🇧",
    "🇸🇾",
    "🇮🇶",
    "🇰🇼",
    "🇶🇦",
    "🇧🇭",
    "🇴🇲",
    "🇾🇪",
    "🇲🇦",
    "🇩🇿",
    "🇹🇳",
    "🇱🇾",
    "🇵🇸",
    "🇹🇷",
    "🇫🇷",
    "🇩🇪",
    "🇮🇹",
    "🇪🇸",
    "🇬🇧",
    "🇺🇸",
    "🇨🇦",
    "🇯🇵",
    "🇰🇷",
    "🇨🇳",
    "🇮🇳",
    "🇧🇷",
    "🇦🇷",
    "🇷🇺",
    "🇬🇷",
    "🇵🇹",
    "🇳🇱",
    "🇸🇪",
    "🇳🇴",
    "🇫🇮",
    "🇨🇭",
]

GAME_INTRO_TEXT = (
    f"{GAME_TITLE}\n\n"
    "مدينة مظلمة يعيش فيها الأبرياء بين جدران تخفي أسرارًا.\n"
    "في النهار يبحث الجميع عن الحقيقة، وفي الليل تتحرك الأيدي الخفية.\n\n"
    "👥 الحد الأدنى: 3 لاعبين\n"
    f"👥 الحد الأعلى: {settings.max_players} لاعبًا\n\n"
    "اضغط انضمام للدخول إلى المدينة."
)

MAFIA_EXPLANATION_TEXT = (
    f"{GAME_TITLE} — دليل اللعبة\n\n"
    "اللعبة مقسمة إلى ليل ونهار. أثناء الليل يستخدم أصحاب الأدوار "
    "قدراتهم عبر الخاص، وأثناء النهار يناقش الجميع ثم يصوتون سرًا "
    "على اللاعب المشتبه به.\n\n"
    "🎭 الأدوار:\n"
    "🔪 السفاح: يختار ضحية كل ليلة. إذا كان هناك أكثر من سفاح، "
    "يبقى آخر اختيار صحيح هو قرار القتل، كما في النسخة الأصلية.\n"
    "🔍 كونان: يكشف دور لاعب واحد كل ليلة.\n"
    "👨‍⚕️ الطبيب: يحيي لاعبًا ميتًا مرة واحدة طوال اللعبة.\n"
    "🧙 الساحر: يعطل قدرة لاعب لليلة التالية مرة واحدة.\n"
    "🛡️ الحارس: يحمي لاعبًا من قتل السفاح مرة واحدة.\n"
    "🏹 الصياد: عند خروجه يختار لاعبًا حيًا لينتقم منه.\n"
    "🤡 المهرج: يفوز وحده إذا أخرجته المدينة بالتصويت.\n"
    "👑 الزعيم: يطرد لاعبًا بالرد على رسالته بكلمة «طرد» مرة واحدة.\n"
    "👨‍🌾 المواطن: لا يملك قدرة خاصة، ويعتمد على الملاحظة والتصويت.\n\n"
    "🏆 الفوز:\n"
    "• يفوز السفاحون عندما يصبح عددهم مساويًا أو أكبر من أهل المدينة.\n"
    "• يفوز أهل المدينة عند خروج جميع السفاحين.\n"
    "• يفوز المهرج وحده إذا خرج بالتصويت."
)


def game_for(chat_id: int | str) -> dict[str, Any] | None:
    return games.get(str(chat_id))


def player_profile(user: Any) -> dict[str, Any]:
    user_id = str(user.id)
    if user_id not in players:
        players[user_id] = {
            "name": user.first_name or "لاعب",
            "username": getattr(user, "username", None),
            "games": 0,
            "wins": 0,
            "losses": 0,
            "points": 0,
            "win_streak": 0,
            "achievements": [],
        }
    else:
        players[user_id]["name"] = user.first_name or players[user_id].get(
            "name", "لاعب"
        )
        players[user_id]["username"] = getattr(user, "username", None)
    return players[user_id]


async def persist() -> None:
    await storage.save({"players": players, "active_games": games})


def mention(user_id: str | int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(str(name))}</a>'


def is_group(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})


async def is_admin(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type not in {
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    }:
        return False
    try:
        member = await chat.get_member(user.id)
    except TelegramError:
        return False
    return member.status in {"administrator", "creator"}


async def safe_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> Any | None:
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramError as exc:
        logger.warning("send_message failed for %s: %s", chat_id, exc)
        return None


async def send_flavor_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_ref: str,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> Any | None:
    if video_ref:
        try:
            if os.path.isfile(video_ref):
                with open(video_ref, "rb") as video_file:
                    return await context.bot.send_video(
                        chat_id=chat_id,
                        video=video_file,
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
            return await context.bot.send_video(
                chat_id=chat_id,
                video=video_ref,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramError as exc:
            logger.warning("video send failed, falling back to text: %s", exc)

    return await safe_send(
        context,
        chat_id,
        caption,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def safe_edit_text(query: Any, text: str, **kwargs: Any) -> None:
    try:
        await query.edit_message_text(text=text, **kwargs)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.debug("edit text failed: %s", exc)
    except TelegramError as exc:
        logger.debug("edit text failed: %s", exc)


async def edit_lobby(
    query: Any, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    try:
        if query.message and query.message.video:
            await query.edit_message_caption(
                caption=text,
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
            )
    except TelegramError:
        # A video fallback becomes a text message, so edit the correct type.
        await safe_edit_text(query, text, reply_markup=keyboard)


def remember(game: dict[str, Any], message: Any | None) -> None:
    if message is not None and getattr(message, "message_id", None):
        game.setdefault("message_ids", []).append(message.message_id)


async def clear_game_messages(
    chat_id: int | str,
    context: ContextTypes.DEFAULT_TYPE,
    game: dict[str, Any],
) -> None:
    for message_id in game.get("message_ids", []):
        try:
            await context.bot.delete_message(
                chat_id=int(chat_id),
                message_id=message_id,
            )
        except TelegramError:
            pass
    game["message_ids"] = []


PERMISSION_FIELDS = (
    "can_send_messages",
    "can_send_audios",
    "can_send_documents",
    "can_send_photos",
    "can_send_videos",
    "can_send_video_notes",
    "can_send_voice_notes",
    "can_send_polls",
    "can_send_other_messages",
    "can_add_web_page_previews",
)


def member_permissions(member: Any) -> dict[str, bool | None]:
    return {
        field: getattr(member, field, None)
        for field in PERMISSION_FIELDS
        if getattr(member, field, None) is not None
    }


async def mute_game_players(
    chat_id: int,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game["original_permissions"] = {}
    for user_id in list(game.get("players", {})):
        try:
            member = await context.bot.get_chat_member(chat_id, int(user_id))
            if member.status in {"administrator", "creator", "left", "kicked"}:
                continue
            game["original_permissions"][user_id] = member_permissions(member)
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=int(user_id),
                permissions=ChatPermissions(can_send_messages=False),
            )
        except TelegramError as exc:
            logger.warning("could not mute %s in %s: %s", user_id, chat_id, exc)


async def restore_game_players(
    chat_id: int,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    saved = game.pop("original_permissions", {})
    for user_id in list(game.get("players", {})):
        try:
            member = await context.bot.get_chat_member(chat_id, int(user_id))
            if member.status in {"administrator", "creator", "left", "kicked"}:
                continue
            permissions = saved.get(user_id)
            if permissions is None:
                permissions = {
                    "can_send_messages": True,
                    "can_send_audios": True,
                    "can_send_documents": True,
                    "can_send_photos": True,
                    "can_send_videos": True,
                    "can_send_video_notes": True,
                    "can_send_voice_notes": True,
                    "can_send_polls": True,
                    "can_send_other_messages": True,
                    "can_add_web_page_previews": True,
                }
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=int(user_id),
                permissions=ChatPermissions(**permissions),
            )
        except TelegramError as exc:
            logger.warning("could not unmute %s in %s: %s", user_id, chat_id, exc)


def role_description(game: dict[str, Any], player_id: str) -> str:
    player = game["players"][player_id]
    role = player.get("role")
    text = (
        f"{GAME_TITLE}\n\n"
        f"🎭 اسمك بين الناس: {player.get('character', 'مجهول')}\n"
        f"👑 حقيقتك الخفية: {engine.ROLES.get(role, 'غير معروف')}\n\n"
    )

    descriptions = {
        "mafia": "اختر لاعبًا حيًا لقتله كل ليلة.",
        "detective": "اكشف حقيقة لاعب واحد كل ليلة.",
        "doctor": "أحيِ لاعبًا ميتًا مرة واحدة طوال اللعبة.",
        "wizard": "عطّل قدرة لاعب لليلة القادمة مرة واحدة.",
        "guard": "احمِ لاعبًا من قتل السفاح مرة واحدة.",
        "hunter": "عند خروجك، اختر لاعبًا حيًا للانتقام منه.",
        "clown": "إذا أخرجتك المدينة بالتصويت، تفوز وحدك.",
        "leader": "بالرد على رسالة لاعب بكلمة «طرد»، يمكنك إخراجه مرة واحدة.",
        "citizen": "لا تملك قدرة خاصة. راقب، ناقش، وصوّت بذكاء.",
    }
    text += descriptions.get(role, "")

    if role == "mafia":
        partners = [
            game["players"][other]["name"]
            for other in game["players"]
            if other != player_id and game["players"][other].get("role") == "mafia"
        ]
        if partners:
            text += "\n\n🖤 رفاقك في الظلام:\n" + "\n".join(
                f"• {name}" for name in partners
            )
    return text


async def send_role_messages(
    chat_id: int,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    failed: list[str] = []
    for player_id in game["players"]:
        message = await safe_send(
            context,
            int(player_id),
            role_description(game, player_id),
        )
        if message is None:
            failed.append(game["players"][player_id]["name"])

    if failed:
        warning = await safe_send(
            context,
            chat_id,
            "⚠️ لم أستطع إرسال الدور على الخاص لبعض اللاعبين. "
            "يجب عليهم فتح البوت والضغط على /start قبل بدء الجولة:\n"
            + "، ".join(failed),
        )
        remember(game, warning)


def action_keyboard(game: dict[str, Any], actor_id: str) -> InlineKeyboardMarkup:
    role = game["players"][actor_id].get("role")
    action = next((key for key, value in engine.ACTION_ROLES.items() if value == role), None)
    targets: list[str] = []

    if action in {"kill", "check", "curse"}:
        targets = [pid for pid in game["alive"] if pid != actor_id]
    elif action == "protect":
        targets = list(game["alive"])
    elif action == "revive":
        targets = list(game["dead"])

    buttons = [
        [
            InlineKeyboardButton(
                game["players"][target]["name"],
                callback_data=(
                    f"mact:{game['chat_id']}:{game['night']}:{action}:{target}"
                ),
            )
        ]
        for target in targets
    ]
    return InlineKeyboardMarkup(buttons)


async def send_night_actions(
    chat_id: int,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    for player_id in list(game.get("alive", [])):
        player = game["players"].get(player_id)
        if not player or player.get("role") not in engine.ACTION_ROLES.values():
            continue
        if player_id in game.get("active_curses", []):
            await safe_send(
                context,
                int(player_id),
                "🧙 لعنة الساحر عطّلت قدرتك هذه الليلة.",
            )
            continue

        keyboard = action_keyboard(game, player_id)
        if not keyboard.inline_keyboard:
            continue
        await send_flavor_message(
            context,
            int(player_id),
            settings.video_night_action,
            "🌑 استيقظت المدينة في الظلام...\n\n"
            "اختر قرارك السري قبل شروق الشمس.",
            reply_markup=keyboard,
        )


async def start_night(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = game_for(chat_id)
    if not game or not game.get("started"):
        return

    game["phase"] = "night"
    game["night"] += 1
    game["used_actions"] = {}
    game["night_actions"] = {}
    game["protected_target"] = None
    game["active_curses"] = game.pop("cursed_next_night", [])

    await mute_game_players(chat_id, game, context)
    message = await send_flavor_message(
        context,
        chat_id,
        settings.video_night,
        f"🌑 『 الليلة {game['night']} 』\n\n"
        "انطفأت الأنوار وساد الصمت. لا يستطيع المشاركون إرسال أي شيء "
        "في المجموعة حتى يبدأ النهار.",
        parse_mode="HTML",
    )
    remember(game, message)
    await send_night_actions(chat_id, game, context)
    await persist()


async def send_hunter_buttons(
    chat_id: int,
    hunter_id: str,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    targets = [pid for pid in game.get("alive", []) if pid != hunter_id]
    if not targets:
        return

    game["pending_hunter"] = hunter_id
    game["hunter_turn_id"] += 1
    buttons = [
        [
            InlineKeyboardButton(
                game["players"][target]["name"],
                callback_data=(
                    f"revenge:{chat_id}:{game['hunter_turn_id']}:{target}"
                ),
            )
        ]
        for target in targets
    ]
    await safe_send(
        context,
        int(hunter_id),
        "🏹 قبل أن يخفت صوتك، اختر لاعبًا حيًا ينتقم معك:",
        InlineKeyboardMarkup(buttons),
    )


async def wait_for_hunter(
    chat_id: int,
    game: dict[str, Any],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not game.get("pending_hunter"):
        return
    await asyncio.sleep(settings.hunter_seconds)
    if game.get("pending_hunter"):
        hunter_id = game["pending_hunter"]
        game["pending_hunter"] = None
        await safe_send(
            context,
            chat_id,
            f"🏹 انتهت مهلة انتقام الصياد "
            f"({html.escape(game['players'][hunter_id]['name'])}).",
        )
        await persist()


async def resolve_night(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = game_for(chat_id)
    if not game or not game.get("started"):
        return

    await restore_game_players(chat_id, game, context)
    game["phase"] = "day"
    game["day"] += 1
    killed = engine.resolve_night(game)

    if killed:
        player = game["players"][killed]
        message = await send_flavor_message(
            context,
            chat_id,
            settings.video_day,
            f"☀️ 『 اليوم {game['day']} 』\n\n"
            f"⚰️ وُجد بلا حراك: {mention(killed, player['name'])}\n"
            f"🎭 حقيقته: {engine.ROLES[player['role']]}",
            parse_mode="HTML",
        )
        remember(game, message)
        if player.get("role") == "hunter":
            await send_hunter_buttons(chat_id, killed, game, context)
            await wait_for_hunter(chat_id, game, context)
    else:
        message = await send_flavor_message(
            context,
            chat_id,
            settings.video_day,
            f"☀️ 『 اليوم {game['day']} 』\n\n"
            "أشرقت الشمس ولم يسقط أحد هذه الليلة.",
        )
        remember(game, message)

    await persist()


async def handle_elimination(
    chat_id: int,
    player_id: str,
    reason: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    game = game_for(chat_id)
    if not game or not engine.eliminate_player(game, player_id, reason):
        return False

    player = game["players"][player_id]
    message = await safe_send(
        context,
        chat_id,
        "⚖️ أُغلقت بوابة المدينة...\n\n"
        f"⚰️ اللاعب: {mention(player_id, player['name'])}\n"
        f"🎭 الحقيقة: {engine.ROLES[player['role']]}",
        parse_mode="HTML",
    )
    remember(game, message)

    if engine.check_clown_win(game, player_id, reason):
        await finish_game(chat_id, context, "clown")
        return True

    if player.get("role") == "hunter":
        await send_hunter_buttons(chat_id, player_id, game, context)
        await wait_for_hunter(chat_id, game, context)

    winner = engine.check_winner(game)
    if winner:
        await finish_game(chat_id, context, winner)
        return True

    await persist()
    return False


async def begin_voting(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = game_for(chat_id)
    if not game or not game.get("started"):
        return

    game["phase"] = "discussion"
    game["votes"] = {}
    game["vote_finalizing"] = False
    discussion = await safe_send(
        context,
        chat_id,
        "🗣️ أمامكم دقيقة للنقاش. بعد انتهاء النقاش سيصل التصويت "
        "السري إلى الخاص.",
    )
    remember(game, discussion)
    await asyncio.sleep(settings.discussion_seconds)
    if not game.get("started"):
        return

    game["phase"] = "vote"
    game["vote_round"] += 1
    round_id = game["vote_round"]
    for voter_id in list(game.get("alive", [])):
        buttons = [
            [
                InlineKeyboardButton(
                    game["players"][target_id]["name"],
                    callback_data=f"vote:{chat_id}:{round_id}:{target_id}",
                )
            ]
            for target_id in game["alive"]
            if target_id != voter_id
        ]
        buttons.append(
            [
                InlineKeyboardButton(
                    "🤷 امتناع عن التصويت",
                    callback_data=f"vote:{chat_id}:{round_id}:abstain",
                )
            ]
        )
        await safe_send(
            context,
            int(voter_id),
            "🗳️ حان وقت التصويت السري. اختر لاعبًا أو امتنع.",
            InlineKeyboardMarkup(buttons),
        )

    vote_message = await send_flavor_message(
        context,
        chat_id,
        settings.video_vote,
        "🗳️ بدأ التصويت السري. تظهر النتيجة بعد انتهاء المهلة.",
    )
    remember(game, vote_message)
    await persist()
    await asyncio.sleep(settings.voting_seconds)
    await finish_voting(chat_id, context)


async def finish_voting(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = game_for(chat_id)
    if not game or game.get("phase") != "vote":
        return
    if game.get("vote_finalizing"):
        return
    game["vote_finalizing"] = True

    result = engine.calculate_votes(game)
    if result is None:
        game["phase"] = "between_rounds"
        await safe_send(
            context,
            chat_id,
            "🕯️ لم يحصل أي لاعب على أصوات كافية. بقي الجميع هذه الليلة.",
        )
        game["votes"] = {}
        game["vote_finalizing"] = False
        await persist()
        return

    if result == "tie":
        game["phase"] = "between_rounds"
        await safe_send(
            context,
            chat_id,
            "🗳️ تساوت الأصوات، ولن يخرج أحد هذه المرة.",
        )
        game["votes"] = {}
        game["vote_finalizing"] = False
        await persist()
        return

    player = game["players"][result]
    count = sum(1 for target in game["votes"].values() if target == result)
    message = await safe_send(
        context,
        chat_id,
        f"⚖️ اتفقت المدينة على {mention(result, player['name'])} "
        f"بـ {count} صوت.",
        parse_mode="HTML",
    )
    remember(game, message)
    await asyncio.sleep(3)
    await handle_elimination(chat_id, result, "vote", context)
    if game.get("started"):
        game["phase"] = "between_rounds"
    game["votes"] = {}
    game["vote_finalizing"] = False
    await persist()


async def game_loop(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    try:
        while True:
            game = game_for(chat_id)
            if not game or not game.get("started"):
                return

            winner = engine.check_winner(game)
            if winner:
                await finish_game(chat_id, context, winner)
                return

            await start_night(chat_id, context)
            await asyncio.sleep(settings.night_seconds)
            game = game_for(chat_id)
            if not game or not game.get("started"):
                return

            await resolve_night(chat_id, context)
            game = game_for(chat_id)
            if not game or not game.get("started"):
                return

            winner = engine.check_winner(game)
            if winner:
                await finish_game(chat_id, context, winner)
                return

            await begin_voting(chat_id, context)
    except asyncio.CancelledError:
        logger.info("game task cancelled for %s", chat_id)
        raise
    except Exception:
        logger.exception("game loop crashed for %s", chat_id)
        game = game_for(chat_id)
        if game:
            game["started"] = False
            game["phase"] = "error"
            await persist()


def keyboard_for_lobby() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧑‍🤝‍🧑 انضمام", callback_data="join_game")],
            [InlineKeyboardButton("▶️ بدء اللعبة", callback_data="start_game")],
        ]
    )


async def mafia_start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not is_group(update):
        await update.message.reply_text("ابدأ اللعبة داخل مجموعة.")
        return
    if not await is_admin(update):
        await update.message.reply_text("🛡️ بدء اللعبة متاح للأدمن فقط.")
        return

    chat_id = update.effective_chat.id
    current = game_for(chat_id)
    if current and current.get("started"):
        await update.message.reply_text("🕯️ توجد لعبة قائمة حاليًا.")
        return

    game = engine.new_game(chat_id)
    games[str(chat_id)] = game
    message = await send_flavor_message(
        context,
        chat_id,
        settings.video_join,
        GAME_INTRO_TEXT,
        reply_markup=keyboard_for_lobby(),
    )
    remember(game, message)
    await persist()


async def join_game_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    chat_id = query.message.chat.id
    game = game_for(chat_id)
    user = query.from_user

    if not game or game.get("started"):
        await query.answer("لا توجد مدينة مفتوحة للانضمام.", show_alert=True)
        return
    if str(user.id) in game["players"]:
        await query.answer("أنت منضم مسبقًا.", show_alert=True)
        return
    if len(game["players"]) >= settings.max_players:
        await query.answer("اكتمل عدد اللاعبين.", show_alert=True)
        return

    player_profile(user)
    game["players"][str(user.id)] = engine.new_player(user)
    updated = (
        GAME_INTRO_TEXT
        + "\n\n━━━━━━━━━━━━━━\n\n"
        + f"👥 عدد المنضمين: {len(game['players'])}\n"
        + "بانتظار بقية السكان..."
    )
    await edit_lobby(query, updated, keyboard_for_lobby())
    await query.answer("تم انضمامك إلى المدينة.")
    await persist()


async def start_game_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    chat_id = query.message.chat.id
    game = game_for(chat_id)

    if not game:
        await query.answer("لا توجد مدينة مفتوحة.", show_alert=True)
        return
    if not await is_admin(update):
        await query.answer("بدء الجولة للأدمن فقط.", show_alert=True)
        return
    if len(game["players"]) < 3:
        await query.answer("تحتاج المدينة إلى 3 لاعبين على الأقل.", show_alert=True)
        return
    if game.get("started"):
        await query.answer("بدأت اللعبة مسبقًا.", show_alert=True)
        return

    game["started"] = True
    game["finished"] = False
    game["phase"] = "night"
    engine.assign_roles(game)
    await persist()
    await safe_edit_text(
        query,
        f"{GAME_TITLE}\n\n"
        "أُغلقت أبواب المدينة وبدأت القصة.\n"
        "سأرسل الأدوار على الخاص، ثم يبدأ الليل الأول.",
    )
    await send_role_messages(chat_id, game, context)

    old_task = game_tasks.get(str(chat_id))
    if old_task and not old_task.done():
        old_task.cancel()
    game_tasks[str(chat_id)] = asyncio.create_task(game_loop(chat_id, context))


async def action_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    query = update.callback_query
    if len(parts) != 5:
        await query.answer("زر غير صالح.", show_alert=True)
        return
    _, chat_id, night_text, action, target_id = parts
    game = game_for(chat_id)
    actor_id = str(query.from_user.id)

    if not game:
        await query.answer("انتهت اللعبة.", show_alert=True)
        return
    try:
        night = int(night_text)
    except ValueError:
        await query.answer("زر غير صالح.", show_alert=True)
        return
    if night != game.get("night"):
        await query.answer("انتهى وقت هذا الزر.", show_alert=True)
        return

    success, message, extra = engine.submit_action(
        game, actor_id, action, target_id
    )
    if not success:
        await query.answer(message, show_alert=True)
        return

    await query.answer("تم تسجيل القرار.")
    if action == "check" and extra:
        await safe_edit_text(
            query,
            f"🔍 نتيجة التحقيق:\n\n"
            f"👤 اللاعب: {html.escape(game['players'][target_id]['name'])}\n"
            f"🎭 الحقيقة: {extra}",
        )
    else:
        await safe_edit_text(query, f"✅ {message}")
    await persist()


async def vote_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    query = update.callback_query
    if len(parts) != 4:
        await query.answer("زر غير صالح.", show_alert=True)
        return
    _, chat_id, round_text, target_id = parts
    game = game_for(chat_id)
    voter_id = str(query.from_user.id)

    if not game or not game.get("started"):
        await query.answer("انتهت اللعبة.", show_alert=True)
        return
    if game.get("phase") != "vote":
        await query.answer("انتهى وقت التصويت.", show_alert=True)
        return
    if str(game.get("vote_round")) != round_text:
        await query.answer("هذا التصويت قديم.", show_alert=True)
        return
    if voter_id not in game.get("alive", []):
        await query.answer("اللاعبون الخارجون لا يصوتون.", show_alert=True)
        return
    if voter_id in game.get("votes", {}):
        await query.answer("صوّتَ مسبقًا.", show_alert=True)
        return
    if target_id != "abstain" and target_id not in game.get("alive", []):
        await query.answer("هذا اللاعب لم يعد موجودًا.", show_alert=True)
        return
    if target_id == voter_id:
        await query.answer("لا يمكنك التصويت لنفسك.", show_alert=True)
        return

    game["votes"][voter_id] = target_id
    game["player_stats"][voter_id]["votes"] += 1
    await query.answer("تم تسجيل صوتك.")
    await safe_edit_text(query, "🗳️ تم تسجيل قرارك سرًا.")
    await persist()

    if all(player_id in game["votes"] for player_id in game["alive"]):
        asyncio.create_task(finish_voting(int(chat_id), context))


async def revenge_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    query = update.callback_query
    if len(parts) != 4:
        await query.answer("زر غير صالح.", show_alert=True)
        return
    _, chat_id, turn_text, target_id = parts
    game = game_for(chat_id)
    hunter_id = str(query.from_user.id)

    if not game or game.get("pending_hunter") != hunter_id:
        await query.answer("لم يعد هذا القرار متاحًا.", show_alert=True)
        return
    if str(game.get("hunter_turn_id")) != turn_text:
        await query.answer("انتهى وقت الانتقام.", show_alert=True)
        return
    if not engine.eliminate_player(game, target_id, "hunter"):
        await query.answer("هذا اللاعب لم يعد حيًا.", show_alert=True)
        return

    game["pending_hunter"] = None
    game["player_stats"][hunter_id]["kills"] += 1
    await query.answer("تم تنفيذ الانتقام.")
    await safe_edit_text(query, "🏹 تم تنفيذ انتقامك الأخير.")
    target = game["players"][target_id]
    message = await safe_send(
        context,
        int(chat_id),
        f"🏹 انتقم الصياد وأخذ معه لاعبًا من سكان المدينة.\n\n"
        f"⚰️ الضحية: {mention(target_id, target['name'])}\n"
        f"🎭 الحقيقة: {engine.ROLES[target['role']]}",
        parse_mode="HTML",
    )
    remember(game, message)
    winner = engine.check_winner(game)
    if winner:
        await finish_game(int(chat_id), context, winner)
    else:
        await persist()


async def leader_kick_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.message
    if not message or not message.reply_to_message:
        return
    chat_id = update.effective_chat.id
    game = game_for(chat_id)
    leader_id = str(update.effective_user.id)
    if not game or not game.get("started"):
        return
    if game["players"].get(leader_id, {}).get("role") != "leader":
        return
    if game.get("leader_used"):
        await message.reply_text("👑 استخدمت صلاحية الزعيم مسبقًا.")
        return

    target_user = message.reply_to_message.from_user
    target_id = str(target_user.id)
    if target_id not in game.get("alive", []):
        await message.reply_text("هذا اللاعب ليس بين الأحياء.")
        return

    game["leader_used"] = True
    await handle_elimination(chat_id, target_id, "leader", context)
    await persist()


async def finish_game(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    winner: str,
) -> None:
    game = game_for(chat_id)
    if not game or game.get("finished"):
        return

    game["finished"] = True
    game["started"] = False
    game["phase"] = "finished"
    game["winner"] = winner
    await restore_game_players(chat_id, game, context)

    winners, losers = engine.game_winners(game, winner)
    for player_id in game["players"]:
        profile = players.get(player_id)
        if not profile:
            continue
        profile["games"] = profile.get("games", 0) + 1
        if player_id in winners:
            profile["wins"] = profile.get("wins", 0) + 1
            profile["points"] = profile.get("points", 0) + 1
            profile["win_streak"] = profile.get("win_streak", 0) + 1
        elif player_id in losers:
            profile["losses"] = profile.get("losses", 0) + 1
            profile["win_streak"] = 0

        achievements = profile.setdefault("achievements", [])
        if profile["wins"] >= 10 and "🏆 سيد الانتصارات" not in achievements:
            achievements.append("🏆 سيد الانتصارات")
        if profile["win_streak"] >= 5 and "🔥 سلسلة لا تنكسر" not in achievements:
            achievements.append("🔥 سلسلة لا تنكسر")
        if profile["points"] >= 50 and "🕯️ أسطورة مدينة الظالم" not in achievements:
            achievements.append("🕯️ أسطورة مدينة الظالم")

    winner_text = {
        "mafia": "🔪 السفاحون",
        "citizens": "👨‍🌾 أهل المدينة",
        "clown": "🤡 المهرج",
    }.get(winner, winner)
    video_ref = {
        "mafia": settings.video_mafia_win,
        "citizens": settings.video_citizens_win,
        "clown": settings.video_clown_win,
    }.get(winner, "")

    await clear_game_messages(chat_id, context, game)
    await send_flavor_message(
        context,
        chat_id,
        video_ref,
        f"🏆 انتهت القصة.\n\nالفائز: {winner_text}\n\n"
        f"👑 أفضل لاعب: {engine.best_player(game)}",
    )
    await persist()


async def end_game_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not is_group(update):
        return
    if not await is_admin(update):
        await update.message.reply_text("🛡️ إنهاء اللعبة للأدمن فقط.")
        return
    chat_id = str(update.effective_chat.id)
    game = games.get(chat_id)
    if not game:
        await update.message.reply_text("لا توجد لعبة مفتوحة.")
        return

    task = game_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
    game["started"] = False
    game["phase"] = "closed"
    await restore_game_players(int(chat_id), game, context)
    await clear_game_messages(int(chat_id), context, game)
    games.pop(chat_id, None)
    await update.message.reply_text("🕯️ تم إغلاق لعبة مدينة الظالم.")
    await persist()


async def member_left(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat_id = update.effective_chat.id
    game = game_for(chat_id)
    left_member = update.message.left_chat_member
    if not game or not left_member:
        return
    player_id = str(left_member.id)
    if not game.get("started"):
        game["players"].pop(player_id, None)
        await persist()
        return
    if player_id in game.get("alive", []):
        engine.eliminate_player(game, player_id, "left")
        await safe_send(
            context,
            chat_id,
            f"🚪 غادر {html.escape(left_member.first_name or 'لاعب')} اللعبة.",
        )
        winner = engine.check_winner(game)
        if winner:
            await finish_game(chat_id, context, winner)
        else:
            await persist()


async def profile_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    profile = player_profile(update.effective_user)
    achievements = profile.get("achievements", [])
    achievement_text = (
        "\n".join(f"🏅 {item}" for item in achievements)
        if achievements
        else "لا توجد إنجازات بعد."
    )
    await update.message.reply_text(
        f"{GAME_TITLE}\n\n"
        "👤 ملف اللاعب\n\n"
        f"الاسم: {profile['name']}\n"
        f"⭐ المستوى: {engine.get_level(profile['points'])}\n"
        f"🔥 النقاط: {profile['points']}\n\n"
        f"🎮 الألعاب: {profile['games']}\n"
        f"🏆 الانتصارات: {profile['wins']}\n"
        f"💀 الخسائر: {profile['losses']}\n"
        f"🔥 سلسلة الانتصارات: {profile['win_streak']}\n\n"
        f"🎖️ الإنجازات:\n{achievement_text}"
    )
    await persist()


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    profile = player_profile(update.effective_user)
    games_count = profile["games"]
    percentage = round(profile["wins"] / games_count * 100, 1) if games_count else 0
    await update.message.reply_text(
        f"📊 إحصائيات {profile['name']}\n\n"
        f"🎮 المباريات: {games_count}\n"
        f"🏆 الفوز: {profile['wins']}\n"
        f"💀 الخسارة: {profile['losses']}\n"
        f"📈 نسبة الفوز: {percentage}%"
    )


async def leaderboard_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    ranking = sorted(
        players.values(),
        key=lambda item: item.get("points", 0),
        reverse=True,
    )[:10]
    if not ranking:
        await update.message.reply_text("لا توجد إحصائيات بعد.")
        return
    lines = ["🏆 ترتيب مدينة الظالم\n"]
    for index, profile in enumerate(ranking, start=1):
        lines.append(
            f"{index}. {profile.get('name', 'لاعب')} — "
            f"⭐ {profile.get('points', 0)} نقطة"
        )
    await update.message.reply_text("\n".join(lines))


async def mafia_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await is_admin(update):
        await update.message.reply_text("🛡️ الحالة للأدمن فقط.")
        return
    game = game_for(update.effective_chat.id)
    if not game:
        await update.message.reply_text("لا توجد مدينة مفتوحة.")
        return
    await update.message.reply_text(
        f"{GAME_TITLE}\n\n"
        f"👥 اللاعبون: {len(game['players'])}\n"
        f"💚 الأحياء: {len(game['alive'])}\n"
        f"⚰️ الخارجون: {len(game['dead'])}\n"
        f"⏳ المرحلة: {game['phase']}\n"
        f"🌙 الليلة: {game['night']}\n"
        f"☀️ اليوم: {game['day']}"
    )


async def bot_start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text(
        f"أهلًا بك في {GAME_TITLE}.\n\n"
        "افتح هذا البوت واضغط /start حتى تصلك أدوار اللعبة وأزرارها على الخاص."
    )


async def mafia_explanation_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text(MAFIA_EXPLANATION_TEXT)


async def video_id_extractor(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    file_id = update.message.video.file_id
    await update.message.reply_text(
        "🎬 تم استلام الفيديو.\n\n"
        f"file_id:\n`{file_id}`",
        parse_mode="Markdown",
    )


async def unknown_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text("الأمر غير معروف. استخدم «المافيا لعبة شرح».")


# ------------------------------ Flags game ------------------------------


def flag_game_for(chat_id: int | str) -> dict[str, Any] | None:
    return flag_games.get(str(chat_id))


async def flags_start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not is_group(update):
        return
    if not await is_admin(update):
        await update.message.reply_text("🚩 بدء لعبة الأعلام للأدمن فقط.")
        return
    chat_id = str(update.effective_chat.id)
    current = flag_game_for(chat_id)
    if current and current.get("started"):
        await update.message.reply_text("🚩 توجد جولة أعلام قائمة.")
        return

    flag_games[chat_id] = {
        "started": False,
        "players": {},
        "flags": {},
        "alive": [],
        "turn_order": [],
        "current_turn": 0,
        "turn_id": 0,
        "current_chooser": None,
    }
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧑‍🤝‍🧑 انضمام", callback_data="flags_join")],
            [InlineKeyboardButton("▶️ بدء اللعبة", callback_data="flags_launch")],
        ]
    )
    await update.message.reply_text(
        "🚩 لعبة الأعلام\n\n"
        "كل لاعب يحصل على علم مجهول، وفي كل دور يختار لاعبًا لإقصائه.\n"
        "الحد الأدنى للبدء: 3 لاعبين.",
        reply_markup=keyboard,
    )


async def flags_join_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    chat_id = str(query.message.chat.id)
    game = flag_game_for(chat_id)
    user = query.from_user
    if not game or game.get("started"):
        await query.answer("لا توجد جولة مفتوحة.", show_alert=True)
        return
    user_id = str(user.id)
    if user_id in game["players"]:
        await query.answer("أنت منضم مسبقًا.", show_alert=True)
        return
    game["players"][user_id] = {"name": user.first_name or "لاعب"}
    await query.answer("تم انضمامك.")
    await safe_edit_text(
        query,
        "🚩 لعبة الأعلام\n\n"
        f"👥 عدد المنضمين: {len(game['players'])}\n\n"
        "اضغط انضمام أو ابدأ الجولة إذا كنت أدمن.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🧑‍🤝‍🧑 انضمام", callback_data="flags_join"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "▶️ بدء اللعبة", callback_data="flags_launch"
                    )
                ],
            ]
        ),
    )


async def flags_launch_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    chat_id = str(query.message.chat.id)
    game = flag_game_for(chat_id)
    if not await is_admin(update):
        await query.answer("الأدمن فقط يبدأ الجولة.", show_alert=True)
        return
    if not game or game.get("started"):
        await query.answer("لا توجد جولة قابلة للبدء.", show_alert=True)
        return
    if len(game["players"]) < 3:
        await query.answer("تحتاج الجولة إلى 3 لاعبين.", show_alert=True)
        return

    player_ids = list(game["players"])
    flags = FLAG_EMOJIS.copy()
    random.shuffle(flags)
    game["flags"] = {
        player_id: flags[index % len(flags)]
        for index, player_id in enumerate(player_ids)
    }
    random.shuffle(player_ids)
    game["turn_order"] = player_ids
    game["alive"] = player_ids.copy()
    game["started"] = True
    game["current_turn"] = 0
    game["turn_id"] = 0
    await query.answer("بدأت الجولة.")
    await safe_edit_text(query, "🚩 اكتملت الأقدار وبدأت لعبة الأعلام.")
    await send_flag_turn(chat_id, context)


async def send_flag_turn(
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = flag_game_for(chat_id)
    if not game or not game.get("started"):
        return
    if len(game["alive"]) <= 1:
        await finish_flags_game(chat_id, context)
        return

    order = game["turn_order"]
    for _ in range(len(order)):
        index = game["current_turn"] % len(order)
        chooser_id = order[index]
        game["current_turn"] = index
        if chooser_id in game["alive"]:
            break
        game["current_turn"] += 1
    else:
        await finish_flags_game(chat_id, context)
        return

    game["turn_id"] += 1
    turn_id = game["turn_id"]
    game["current_chooser"] = chooser_id
    buttons = [
        [
            InlineKeyboardButton(
                game["flags"][target_id],
                callback_data=f"flagpick:{chat_id}:{turn_id}:{target_id}",
            )
        ]
        for target_id in game["alive"]
        if target_id != chooser_id
    ]
    await safe_send(
        context,
        int(chat_id),
        f"🚩 دور {html.escape(game['players'][chooser_id]['name'])}\n\n"
        "اختر علمًا خلال الوقت المحدد، وصاحب العلم المختار سيخرج.",
        InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    old_task = flag_tasks.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()
    flag_tasks[chat_id] = asyncio.create_task(
        flag_turn_timeout(chat_id, chooser_id, turn_id, context)
    )


async def flag_turn_timeout(
    chat_id: str,
    chooser_id: str,
    turn_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    try:
        await asyncio.sleep(settings.flag_turn_seconds)
        game = flag_game_for(chat_id)
        if not game or not game.get("started"):
            return
        if game.get("turn_id") != turn_id:
            return
        if chooser_id in game.get("alive", []):
            game["alive"].remove(chooser_id)
        game["current_turn"] += 1
        await safe_send(
            context,
            int(chat_id),
            f"⏳ لم يختر {html.escape(game['players'][chooser_id]['name'])} "
            "في الوقت المحدد، فخرج من الجولة.",
            parse_mode="HTML",
        )
        await send_flag_turn(chat_id, context)
    except asyncio.CancelledError:
        return


async def flags_pick_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parts: list[str],
) -> None:
    query = update.callback_query
    if len(parts) != 4:
        await query.answer("زر غير صالح.", show_alert=True)
        return
    _, chat_id, turn_text, target_id = parts
    game = flag_game_for(chat_id)
    chooser_id = str(query.from_user.id)
    if not game or not game.get("started"):
        await query.answer("انتهت الجولة.", show_alert=True)
        return
    if str(game.get("turn_id")) != turn_text:
        await query.answer("انتهى وقت هذا الدور.", show_alert=True)
        return
    if game.get("current_chooser") != chooser_id:
        await query.answer("ليس دورك.", show_alert=True)
        return
    if target_id not in game.get("alive", []) or target_id == chooser_id:
        await query.answer("اختيار غير صالح.", show_alert=True)
        return

    game["alive"].remove(target_id)
    game["current_turn"] += 1
    task = flag_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
    await query.answer("تم اختيار العلم.")
    await safe_edit_text(query, "🚩 تم تسجيل اختيارك.")
    await safe_send(
        context,
        int(chat_id),
        f"🚩 أُقصي {html.escape(game['players'][target_id]['name'])} "
        "من الجولة.",
        parse_mode="HTML",
    )
    await send_flag_turn(chat_id, context)


async def finish_flags_game(
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    game = flag_game_for(chat_id)
    if not game:
        return
    game["started"] = False
    if not game.get("alive"):
        await safe_send(context, int(chat_id), "🚩 انتهت الجولة بلا فائز.")
        return
    winner_id = game["alive"][0]
    winner = game["players"][winner_id]["name"]
    await safe_send(
        context,
        int(chat_id),
        f"🏆 فاز في لعبة الأعلام: {mention(winner_id, winner)}",
        parse_mode="HTML",
    )


async def flags_end_game_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await is_admin(update):
        await update.message.reply_text("🚩 إنهاء لعبة الأعلام للأدمن فقط.")
        return
    chat_id = str(update.effective_chat.id)
    game = flag_game_for(chat_id)
    if not game:
        await update.message.reply_text("لا توجد جولة أعلام.")
        return
    game["started"] = False
    task = flag_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
    await update.message.reply_text("🚩 تم إنهاء جولة الأعلام.")


async def shaden_question_dispatcher(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    text = update.message.text or ""
    if re.search(r"(مين|من).{0,4}(أنشأك|برمجك|طورك|صنعك|عملك)", text):
        await update.message.reply_text(
            "🕯️ أنا شادن، بوت مدينة الظالم الذي صممه سامي."
        )
    else:
        await update.message.reply_text(
            "🕯️ أنا مشغول بحراسة المدينة وترتيب أسرارها 😅"
        )


async def button_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    data = update.callback_query.data or ""
    parts = data.split(":")

    if data == "join_game":
        await join_game_callback(update, context)
    elif data == "start_game":
        await start_game_callback(update, context)
    elif data == "flags_join":
        await flags_join_callback(update, context)
    elif data == "flags_launch":
        await flags_launch_callback(update, context)
    elif parts[0] == "mact":
        await action_callback(update, context, parts)
    elif parts[0] == "vote":
        await vote_callback(update, context, parts)
    elif parts[0] == "revenge":
        await revenge_callback(update, context, parts)
    elif parts[0] == "flagpick":
        await flags_pick_callback(update, context, parts)
    else:
        await update.callback_query.answer(
            "🕯️ هذا الزر لم يعد صالحًا.", show_alert=True
        )


async def autosave_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await persist()
        except Exception:
            logger.exception("autosave failed")


async def post_init(application: Application) -> None:
    application.create_task(autosave_loop(), name="autosave")
    # Resume persisted games at the next safe round after a restart.
    for chat_id, game in list(games.items()):
        if game.get("started"):
            game["phase"] = "between_rounds"
            game["pending_hunter"] = None
            game_tasks[chat_id] = application.create_task(
                game_loop(int(chat_id), application),
                name=f"game-{chat_id}",
            )


def setup_handlers(application: Application) -> None:
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^المافيا$"), mafia_start_command)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^المافيا لعبة انهاء$"),
            end_game_command,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^(اعلام|الأعلام)$"),
            flags_start_command,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^(اعلام لعبة انهاء|العالم لعبة انهاء)$"),
            flags_end_game_command,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^المافيا حالة$"),
            mafia_status_command,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^المافيا ترتيب$"),
            leaderboard_command,
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^ملفي$"), profile_command)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^احصائياتي$"),
            stats_command,
        )
    )
    application.add_handler(CallbackQueryHandler(button_router))
    application.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, member_left)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^طرد$") & filters.REPLY,
            leader_kick_command,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^شادن"),
            shaden_question_dispatcher,
        )
    )
    application.add_handler(CommandHandler("start", bot_start_command))
    application.add_handler(MessageHandler(filters.VIDEO, video_id_extractor))
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^المافيا لعبة شرح$"),
            mafia_explanation_command,
        )
    )
    application.add_handler(
        MessageHandler(filters.COMMAND, unknown_command)
    )


def main() -> None:
    if not settings.token:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add it to Replit Secrets or the environment."
        )

    application = (
        Application.builder()
        .token(settings.token)
        .post_init(post_init)
        .build()
    )
    setup_handlers(application)
    logger.info("Shaden Mafia Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()