import asyncio
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ================= РОЛИ (добавляй новые сюда) =================
ROLES = {
    "civilian":   {"name": "👤 Мирный житель",   "desc": "Ночью спишь, днём обсуждаешь и голосуешь. Вычисляй мафию логикой."},
    "don":        {"name": "👔 Дон",             "desc": "Главарь мафии. Ночью назначаешь жертву от лица мафии."},
    "mafia":      {"name": "👨 Мафия",           "desc": "Ночью помогаешь дону выбрать жертву. Днём ври и путай город."},
    "commissar":  {"name": "🕵️ Комиссар Каттани", "desc": "Ночью проверяешь игрока — мафия он или нет. Результат придёт в личку."},
    "sergeant":   {"name": "👮 Сержант",         "desc": "Напарник комиссара. Начинаешь проверки, если комиссар погиб."},
    "doctor":     {"name": "💉 Доктор",          "desc": "Ночью лечишь игрока. Если мафия выберет его — он выживет."},
    "maniac":     {"name": "🔪 Маньяк",          "desc": "Одиночка. Каждую ночь сам убиваешь. Побеждаешь, оставшись последним."},
    "lover":      {"name": "💃 Любовница",       "desc": "Ночью выбираешь игрока — его ночное действие отменяется."},
    "lawyer":     {"name": "👨‍⚖️ Адвокат",        "desc": "Ночью защищаешь игрока: если его проголосуют днём — он не умрёт."},
    "suicide":    {"name": "🤦 Самоубийца",      "desc": "Побеждаешь, если тебя выгнали голосованием. Провоцируй город!"},
    "beggar":     {"name": "🧙 Бомж",            "desc": "Ночью узнаёшь роль выбранного игрока."},
    "lucky":      {"name": "🤞 Счастливчик",     "desc": "Первая попытка убить тебя проваливается. Вторая — смертельна."},
    "kamikaze":   {"name": "💣 Камикадзе",       "desc": "Один раз за игру днём: /boom номер — взрываешь себя вместе с игроком."},
    "journalist": {"name": "📰 Журналист",       "desc": "Ночью узнаёшь роль выбранного игрока."},
    "bodyguard":  {"name": "🛡 Телохранитель",   "desc": "Ночью охраняешь игрока: если на него нападут — умрёшь вместо него."},
    "mayor":      {"name": "🏛 Мэр",             "desc": "Твой голос на голосовании считается за два."},
}

ROLE_TEAM = {
    "civilian": "city", "commissar": "city", "sergeant": "city",
    "doctor": "city", "lover": "city", "lawyer": "city", "lucky": "city",
    "kamikaze": "city", "journalist": "city", "bodyguard": "city",
    "mayor": "city", "beggar": "city", "suicide": "neutral",
    "don": "mafia", "mafia": "mafia", "maniac": "maniac",
}

ROLE_ACTION = {
    "don": "kill", "mafia": "kill", "maniac": "kill",
    "doctor": "heal", "commissar": "check", "sergeant": "check",
    "lover": "block", "lawyer": "protect", "bodyguard": "protect",
    "journalist": "spy", "beggar": "spy",
}

ACTION_TEXT = {
    "kill": "Выбери жертву 🔪",
    "heal": "Кого лечим этой ночью? 💉",
    "check": "Кого проверяем? 🕵️",
    "block": "Кого очаровываем? 💃",
    "protect": "Кого защищаем? 🛡",
    "spy": "Чью роль узнать? 📰",
}

games = {}  # chat_id -> состояние игры


# ================= ВСПОМОГАТЕЛЬНОЕ =================
def roles_keyboard() -> InlineKeyboardMarkup:
    keys = list(ROLES.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(text=ROLES[keys[i]]["name"], callback_data=f"role:{keys[i]}")]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(text=ROLES[keys[i + 1]]["name"],
                                            callback_data=f"role:{keys[i + 1]}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def player_kb(g, prefix, allow_self=True):
    rows, alive = [], []
    for idx, (uid, name) in enumerate(g["players"]):
        if uid in g["alive"] and (allow_self or uid != g.get("last_actor")):
            alive.append((idx + 1, uid, name))
    for i in range(0, len(alive), 2):
        rows.append([InlineKeyboardButton(
            text=f"{num}. {name}", callback_data=f"{prefix}:{uid}")
            for num, uid, name in alive[i:i + 2]])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def name_of(g, uid):
    for i, (u, n) in enumerate(g["players"]):
        if u == uid:
            return f"{i + 1}. {n}"
    return str(uid)


def build_roles(n):
    roles = ["commissar", "doctor"]
    if n >= 7:
        roles += ["don", "mafia"]
    else:
        roles.append("mafia")
    if n >= 8:
        roles.append("maniac")
    if n >= 9:
        roles.append("lover")
    if n >= 10:
        roles.append("bodyguard")
    roles += ["civilian"] * (n - len(roles))
    random.shuffle(roles)
    return roles


def night_actors(g):
    roles, alive = g["roles"], g["alive"]
    don_alive = any(roles[u] == "don" for u in alive)
    com_alive = any(roles[u] == "commissar" for u in alive)
    actors = []
    for uid in list(alive):
        r = roles[uid]
        if r == "mafia" and don_alive:
            continue
        if r == "sergeant" and com_alive:
            continue
        if r in ROLE_ACTION:
            actors.append(uid)
    return actors


def check_win(g):
    roles, alive = g["roles"], list(g["alive"])
    maf = [u for u in alive if roles[u] in ("don", "mafia")]
    maniacs = [u for u in alive if roles[u] == "maniac"]
    others = len(alive) - len(maf)
    if not maf and not maniacs:
        return "🌍 Победа города!"
    if len(maf) >= others:
        return "🩸 Победа мафии!"
    if not maf and len(alive) == len(maniacs) == 1:
        return "🔪 Победа маньяка!"
    return None


async def end_game(cid, reason):
    g = games.pop(cid, None)
    if not g:
        return
    reveal = "\n".join(f"{name_of(g, u)} — {ROLES[r]['name']}"
                       for u, r in g["roles"].items())
    await bot.send_message(cid, f"{reason}\n\n🎭 Роли игроков:\n{reveal}")
    await bot.send_message(cid, "Новая игра: /join → /start_game")


# ================= МЕНЮ РОЛЕЙ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🎭 Я бот для игры в Мафию!\n\n"
        "/roles — роли и описания\n"
        "/join — записаться на игру\n"
        "/start_game — начать (минимум 5 игроков)\n"
        "/night — начать ночь (после раздачи ролей)\n"
        "/resolve — подвести итог ночи (когда все походили)\n"
        "/list — список игроков с номерами\n"
        "/vote номер — проголосовать днём\n"
        "/boom номер — взрыв камикадзе\n"
        "/end — завершить игру"
    )


@dp.message(Command("roles"))
async def cmd_roles(message: Message):
    await message.answer("Нажми на роль, чтобы увидеть её описание:",
                         reply_markup=roles_keyboard())


@dp.callback_query(F.data.startswith("role:"))
async def show_role(cb: CallbackQuery):
    role = ROLES.get(cb.data.split(":")[1])
    if role:
        await cb.message.answer(f"<b>{role['name']}</b>\n\n{role['desc']}")
    await cb.answer()


# ================= СБОР ИГРОКОВ =================
@dp.message(Command("join"))
async def cmd_join(message: Message):
    g = games.setdefault(message.chat.id, {
        "players": [], "alive": set(), "roles": {}, "started": False,
        "phase": None, "actions": {}, "expected": set(), "votes": {},
        "shield": set(), "boom_used": False,
    })
    if g["started"]:
        await message.answer("Игра уже идёт.")
        return
    user = message.from_user
    if any(u == user.id for u, _ in g["players"]):
        await message.answer("Ты уже в списке 🙂")
        return
    g["players"].append((user.id, user.first_name))
    await message.answer(f"✅ {user.first_name} в игре! Игроков: {len(g['players'])}")


@dp.message(Command("start_game"))
async def cmd_start_game(message: Message):
    g = games.get(message.chat.id)
    if not g or g["started"] or not g["players"]:
        await message.answer("Сначала собери игроков через /join.")
        return
    if len(g["players"]) < 5:
        await message.answer("Минимум 5 игроков.")
        return

    players = g["players"]
    g["started"] = True
    g["phase"] = "night1"
    g["alive"] = {uid for uid, _ in players}
    g["roles"] = {uid: r for (uid, _), r in zip(players, build_roles(len(players)))}
    g["votes"] = {}
    g["actions"] = {}
    g["shield"] = set()
    g["boom_used"] = False

    for uid, name in players:
        role = ROLES[g["roles"][uid]]
        try:
            await bot.send_message(
                uid,
                f"🎭 Твоя роль: <b>{role['name']}</b>\n\n{role['desc']}\n\n"
                "Список игроков — в чате (/list). Удачи!")
        except Exception:
            await message.answer(
                f"⚠️ Не смог написать {name} — пусть нажмёт /start у бота в личке.")

    await message.answer(
        "🎮 Игра началась! Роли разосланы в личку.\n"
        "Ведущий: когда все готовы — /night 🌙")


# ================= НОЧЬ =================
@dp.message(Command("night"))
async def cmd_night(message: Message):
    g = games.get(message.chat.id)
    if not g or not g["started"]:
        return
    g["phase"] = "night"
    g["actions"] = {}
    actors = night_actors(g)
    g["expected"] = set(actors)
    for uid in actors:
        act = ROLE_ACTION[g["roles"][uid]]
        try:
            await bot.send_message(uid, ACTION_TEXT[act],
                                   reply_markup=player_kb(g, "act"))
        except Exception:
            pass
    await message.answer(
        "🌙 Город засыпает. Активные роли ходят в личке.\n"
        "Ведущий: когда все походили — /resolve")


@dp.callback_query(F.data.startswith("act:"))
async def do_action(cb: CallbackQuery):
    target = int(cb.data.split(":")[1])
    uid = cb.from_user.id
    cid = None
    g = None
    for chat_id, game in games.items():
        if uid in game.get("expected", set()) and game["phase"] == "night":
            cid, g = chat_id, game
            break
    if g is None:
        await cb.answer("Сейчас не твой ход.")
        return

    role = g["roles"][uid]
    if ROLE_ACTION[role] == "kill" and ROLE_TEAM.get(g["roles"].get(target, "")) == "mafia":
        await cb.answer("Нельзя убить своего!")
        return

    g["actions"][uid] = target
    if ROLE_ACTION[role] in ("check", "spy"):
        try:
            await bot.send_message(uid, f"🕵️ Результат: {ROLES[g['roles'][target]]['name']}")
        except Exception:
            pass
    await cb.answer("Принято ✅")
    if set(g["actions"]) >= g["expected"]:
        await bot.send_message(cid, "✅ Все ночные роли сделали ход. Ведущий: /resolve")


@dp.message(Command("resolve"))
async def cmd_resolve(message: Message):
    g = games.get(message.chat.id)
    if g and g["phase"] in ("night", "night1"):
        await resolve_night(message.chat.id)


async def resolve_night(cid):
    g = games[cid]
    roles = g["roles"]

    # любовница отменяет действие своей цели
    lover_targets = {t for u, t in g["actions"].items() if roles.get(u) == "lover"}
    acts = {u: t for u, t in g["actions"].items() if t not in lover_targets}

    healed = next((t for u, t in acts.items() if roles.get(u) == "doctor"), None)
    guarded = next((t for u, t in acts.items() if roles.get(u) == "bodyguard"), None)
    kills = [t for u, t in acts.items()
             if roles.get(u) in ("don", "mafia", "maniac")]

    deaths = []
    guard_death = None

    for target in kills:
        if target not in g["alive"]:
            continue
        if target == healed:
            continue
        if target == guarded:
            for u, t in acts.items():
                if roles.get(u) == "bodyguard":
                    g["alive"].discard(u)
                    guard_death = name_of(g, u)
            continue
        if roles.get(target) == "lucky" and target not in g["shield"]:
            g["shield"].add(target)
            continue
        g["alive"].discard(target)
        deaths.append(name_of(g, target))

    parts = []
    if deaths:
        parts.append("☀️ Утро. Этой ночью город потерял: " + ", ".join(deaths))
    else:
        parts.append("☀️ Утро. Этой ночью все выжили 😴")
    if guard_death:
        parts.append(f"🛡 {guard_death} погиб, защищая того, кого охранял.")

    text = "\n\n".join(parts)
    result = check_win(g)
    if result:
        await end_game(cid, text + "\n\n" + result)
        return

    g["phase"] = "day"
    g["votes"] = {}
    await bot.send_message(
        cid,
        text + "\n\nОбсуждайте и голосуйте: /vote номер игрока.\n"
               "/list — список игроков. Камикадзе: /boom номер.")


# ================= ДЕНЬ =================
@dp.message(Command("list"))
async def cmd_list(message: Message):
    g = games.get(message.chat.id)
    if not g or not g["started"]:
        return
    lines = []
    for i, (uid, name) in enumerate(g["players"]):
        status = "✅" if uid in g["alive"] else "☠️"
        lines.append(f"{i + 1}. {name} {status}")
    await message.answer("\n".join(lines))


@dp.message(Command("vote"))
async def cmd_vote(message: Message):
    g = games.get(message.chat.id)
    if not g or g["phase"] != "day":
        return
    try:
        num = int(message.text.removeprefix("/vote").strip()) - 1
    except (ValueError, IndexError):
        await message.answer("Формат: /vote номер (см. /list)")
        return
    if num < 0 or num >= len(g["players"]):
        await message.answer("Нет такого номера.")
        return
    target = g["players"][num][0]
    if target not in g["alive"]:
        await message.answer("Этот игрок уже мёртв.")
        return
    voter = message.from_user.id
    if voter not in g["alive"]:
        await message.answer("Мёртвые не голосуют 🙂")
        return
    weight = 2 if g["roles"][voter] == "mayor" else 1
    g["votes"][voter] = (target, weight)
    total = sum(w for _, w in g["votes"].values())
    await message.answer(
        f"Голос против {name_of(g, target)} принят (вес {weight}). "
        f"Голосов: {total} из {len(g['alive']) // 2 + 1} необходимых.")
    if total >= len(g["alive"]) // 2 + 1:
        await resolve_lynch(message.chat.id)


async def resolve_lynch(cid):
    g = games[cid]
    counts = {}
    for target, weight in g["votes"].values():
        counts[target] = counts.get(target, 0) + weight
    if not counts:
        return
    top = max(counts.values())
    candidates = [u for u, c in counts.items() if c == top]
    if len(candidates) > 1:
        await bot.send_message(cid, "🤝 Голоса разделились — никто не казнён. Ведущий: /night")
        return

    target = candidates[0]
    lawyer = next((t for u, t in g["actions"].items() if g["roles"].get(u) == "lawyer"), None)
    if target == lawyer:
        await bot.send_message(cid, f"⚖️ Адвокат спас {name_of(g, target)}! Город расходится. Ведущий: /night")
        return

    if g["roles"].get(target) == "suicide":
        g["alive"].discard(target)
        await end_game(cid, f"💪 {name_of(g, target)} изгнан... и оказался Самоубийцей. "
                            "🤦 Самоубийца побеждает!")
        return

    g["alive"].discard(target)
    result = check_win(g)
    if result:
        await end_game(cid, f"🏛 Город изгнал {name_of(g, target)}.\n\n{result}")
        return
    await bot.send_message(cid, f"🏛 Город изгнал {name_of(g, target)}. "
                                "Наступает новая ночь. Ведущий: /night")


@dp.message(Command("boom"))
async def cmd_boom(message: Message):
    g = games.get(message.chat.id)
    if not g or g["phase"] != "day" or g.get("boom_used"):
        return
    uid = message.from_user.id
    if uid not in g["alive"] or g["roles"][uid] != "kamikaze":
        return
    try:
        num = int(message.text.removeprefix("/boom").strip()) - 1
        target = g["players"][num][0]
    except (ValueError, IndexError):
        await message.answer("Формат: /boom номер (см. /list)")
        return
    g["boom_used"] = True
    for u in (uid, target):
        g["alive"].discard(u)
    result = check_win(g)
    if result:
        await end_game(message.chat.id, f"💣 Камикадзе взорвал {name_of(g, target)} "
                                        f"и себя!\n\n{result}")
    else:
        await bot.send_message(message.chat.id,
                               f"💣 БУМ! Погибли {name_of(g, uid)} и {name_of(g, target)}. "
                               "Ведущий: /night")


@dp.message(Command("end"))
async def cmd_end(message: Message):
    if message.chat.id in games:
        games.pop(message.chat.id)
        await message.answer("🏁 Игра завершена. Новая запись — /join")


# ================= ЗАПУСК =================
async def main():
    if not TOKEN:
        print("ОШИБКА: BOT_TOKEN не задан! Добавь переменную окружения BOT_TOKEN.")
        return
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
