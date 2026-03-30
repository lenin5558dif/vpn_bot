import asyncio
import logging
import os
import tempfile
from typing import Optional
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types.input_file import FSInputFile

from app.config import get_settings
from app.schemas import RequestStatus
from bot.backend import BackendClient

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
if not settings.bot_token:
    raise RuntimeError("BOT_TOKEN not set")

bot = Bot(token=settings.bot_token)
dp = Dispatcher()
backend = BackendClient()
ADMIN_IDS = {int(x) for x in (settings.admin_ids or "").split(",") if x}

CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit_slug(text: str) -> str:
    slug_parts: list[str] = []
    for ch in text.lower():
        if ch in CYR_TO_LAT:
            slug_parts.append(CYR_TO_LAT[ch])
        elif re.match(r"[a-z0-9]", ch):
            slug_parts.append(ch)
        elif ch in (" ", "-", "_"):
            slug_parts.append("_")
    slug = "".join(slug_parts).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:50]


class RequestAccess(StatesGroup):
    waiting_name = State()
    waiting_contact = State()
    waiting_comment = State()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Привет! Введи, пожалуйста, своё имя и фамилию.")
    await state.set_state(RequestAccess.waiting_name)


@dp.message(RequestAccess.waiting_name)
async def handle_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return
    await state.update_data(name=message.text.strip()[:100])
    await message.answer("Оставь контакт для связи (телефон или email).")
    await state.set_state(RequestAccess.waiting_contact)


@dp.message(RequestAccess.waiting_contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return
    await state.update_data(contact=message.text.strip()[:200])
    await message.answer("Комментарий (опционально). Если нечего добавить, напиши 'нет'.")
    await state.set_state(RequestAccess.waiting_comment)


@dp.message(RequestAccess.waiting_comment)
async def handle_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return
    data = await state.get_data()
    comment = message.text.strip()[:500]
    if comment.lower() == "нет":
        comment = ""
    name = data.get("name")
    contact = data.get("contact")
    if not message.from_user:
        await message.answer("Не удалось определить отправителя.")
        return
    tg_id = message.from_user.id

    try:
        user = await backend.create_user({"name": name, "contact": contact, "tg_id": tg_id})
        req = await backend.create_request({"user_id": user["id"], "comment": comment})
    except Exception as exc:
        logger.error("Failed to create user/request: %s", exc)
        await message.answer("Ошибка при отправке заявки. Попробуй ещё раз.")
        return

    await message.answer("Заявка отправлена. Админ скоро её рассмотрит.")
    await state.clear()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Одобрить",
                    callback_data=f"approve:{req['id']}:{user['id']}:{tg_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отказать",
                    callback_data=f"reject:{req['id']}:{user['id']}:{tg_id}",
                )
            ],
        ]
    )
    text = f"Новая заявка #{req['id']}\nИмя: {name}\nКонтакт: {contact}\nКомментарий: {comment}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception as exc:
            logger.error("Failed to notify admin %s: %s", admin_id, exc)


async def _ensure_admin(callback: CallbackQuery) -> bool:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return False
    return True


@dp.callback_query(F.data.startswith("approve"))
async def approve_request(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    try:
        parts = callback.data.split(":")
        _, req_id_str, user_id_str, tg_id_str = parts
        req_id, user_id, tg_id = int(req_id_str), int(user_id_str), int(tg_id_str)
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    await backend.update_request(req_id, RequestStatus.approved)
    peer = await backend.create_peer(user_id)
    config_text = await backend.get_config(peer["id"])
    filename_slug = "user"
    try:
        user = await backend.get_user(user_id)
        filename_slug = translit_slug(user.get("name") or "")
        if not filename_slug:
            filename_slug = "user"
    except Exception as exc:
        logger.error("Failed to fetch user for filename: %s", exc)

    await bot.send_message(tg_id, "Доступ одобрен. Вот твой конфиг:")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".conf") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name
        input_file = FSInputFile(tmp_path, filename=f"VPN_{filename_slug}.conf")
        await bot.send_document(tg_id, input_file, caption="Импортируй файл в WireGuard")
    except Exception as exc:
        logger.error("Failed to send config file: %s", exc)

    if tmp_path and os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    await callback.answer("Одобрено")


@dp.callback_query(F.data.startswith("reject"))
async def reject_request(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    try:
        parts = callback.data.split(":")
        _, req_id_str, _, tg_id_str = parts
        req_id, tg_id = int(req_id_str), int(tg_id_str)
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
        return

    await backend.update_request(req_id, RequestStatus.rejected)
    await bot.send_message(tg_id, "К сожалению, доступ отклонён. Свяжитесь с админом для подробностей.")
    await callback.answer("Отказано")


@dp.message(Command("admin"))
async def admin_menu(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Новые заявки", callback_data="admin:req:new")],
            [InlineKeyboardButton(text="Все заявки", callback_data="admin:req:all")],
            [InlineKeyboardButton(text="Пиры", callback_data="admin:peers")],
            [InlineKeyboardButton(text="Пользователи", callback_data="admin:users")],
            [InlineKeyboardButton(text="Онлайн", callback_data="admin:online")],
            [InlineKeyboardButton(text="Трафик 24ч", callback_data="admin:traffic")],
            [InlineKeyboardButton(text="Топ трафик", callback_data="admin:top")],
            [InlineKeyboardButton(text="Сервер", callback_data="admin:server")],
            [InlineKeyboardButton(text="Health", callback_data="admin:health")],
        ]
    )
    await message.answer("Админ-меню:", reply_markup=kb)


def _format_requests(items: list[dict]) -> str:
    lines = []
    for r in items[:15]:
        lines.append(
            f"#{r.get('id')} user={r.get('user_id')} status={r.get('status')} created={r.get('created_at')}"
        )
    return "\n".join(lines) if lines else "Пусто"


def _format_peers(items: list[dict]) -> str:
    lines = []
    for p in items[:15]:
        lines.append(
            f"#{p.get('id')} user={p.get('user_id')} {p.get('address')} status={p.get('status')} speed={p.get('speed_limit_mbps')}mbit"
        )
    return "\n".join(lines) if lines else "Пусто"


def _format_users(items: list[dict]) -> str:
    lines = []
    for u in items[:15]:
        lines.append(f"#{u.get('id')} {u.get('name')} contact={u.get('contact')}")
    return "\n".join(lines) if lines else "Пусто"


ADMIN_MENU_ACTIONS = {
    "admin:req:new",
    "admin:req:all",
    "admin:peers",
    "admin:users",
    "admin:online",
    "admin:traffic",
    "admin:top",
    "admin:server",
    "admin:health",
}


@dp.callback_query(F.data.in_(ADMIN_MENU_ACTIONS))
async def admin_actions(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    action = callback.data
    if action == "admin:req:new":
        reqs = await backend.list_requests(status="new")
        await callback.message.answer(f"Новые заявки:\n{_format_requests(reqs)}")
    elif action == "admin:req:all":
        reqs = await backend.list_requests()
        await callback.message.answer(f"Все заявки:\n{_format_requests(reqs)}")
    elif action == "admin:peers":
        peers = await backend.list_peers()
        await callback.message.answer(f"Пиры (первые {min(len(peers), 20)}):")
        for p in peers[:20]:
            text = f"peer #{p.get('id')} user={p.get('user_id')} {p.get('address')} status={p.get('status')} speed={p.get('speed_limit_mbps')}mbit"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Отключить",
                            callback_data=f"admin:peer:{p.get('id')}:disabled",
                        ),
                        InlineKeyboardButton(
                            text="Активировать",
                            callback_data=f"admin:peer:{p.get('id')}:active",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="Забанить",
                            callback_data=f"admin:peer:{p.get('id')}:banned",
                        ),
                    ],
                ]
            )
            await callback.message.answer(text, reply_markup=kb)
    elif action == "admin:users":
        users = await backend.list_users()
        await callback.message.answer(f"Пользователи:\n{_format_users(users)}")
    elif action == "admin:online":
        data = await backend.get_online_peers()
        lines = [f"Онлайн: {data['online_count']}/{data['total']}"]
        for p in data.get("peers", []):
            ago = p["seconds_ago"]
            if ago < 60:
                ago_str = f"{ago} сек"
            else:
                ago_str = f"{ago // 60} мин"
            lines.append(f"  {p['name']} ({p['address']}) — {ago_str} назад")
        if not data.get("peers"):
            lines.append("  Никого нет")
        await callback.message.answer("\n".join(lines))
    elif action == "admin:traffic":
        items = await backend.get_traffic_summary(hours=24)
        lines = ["Трафик за 24ч:"]
        for item in items:
            rx_gb = item["rx"] / (1024 ** 3)
            tx_gb = item["tx"] / (1024 ** 3)
            name = item.get("name", f"user#{item['user_id']}")
            lines.append(f"  {name}: {rx_gb:.1f} GB / {tx_gb:.1f} GB")
        if len(items) == 0:
            lines.append("  Нет данных")
        await callback.message.answer("\n".join(lines))
    elif action == "admin:top":
        items = await backend.get_traffic_summary(hours=24)
        ranked = sorted(items, key=lambda x: x["rx"] + x["tx"], reverse=True)[:5]
        lines = ["Топ-5 за 24ч:"]
        for i, item in enumerate(ranked, 1):
            total_gb = (item["rx"] + item["tx"]) / (1024 ** 3)
            name = item.get("name", f"user#{item['user_id']}")
            lines.append(f"  {i}. {name} — {total_gb:.1f} GB")
        if not ranked:
            lines.append("  Нет данных")
        await callback.message.answer("\n".join(lines))
    elif action == "admin:server":
        stats = await backend.get_server_stats()
        text = (
            f"Сервер:\n"
            f"  CPU: {stats['cpu_pct']}% ({stats['cpu_cores']} core)\n"
            f"  RAM: {stats['ram_used_mb']}/{stats['ram_total_mb']} MB\n"
            f"  Disk: {stats['disk_used_gb']}/{stats['disk_total_gb']} GB\n"
            f"  Uptime: {stats['uptime']}\n"
            f"  Пиров: {stats['peers_total']}\n"
            f"  TrafficStat: {stats['trafficstat_rows']} строк"
        )
        await callback.message.answer(text)
    elif action == "admin:health":
        health = await backend.health()
        await callback.message.answer(f"Health: {health}")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin:peer:"))
async def admin_peer_update(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    logger.info("Admin %s clicked peer action: %s", callback.from_user.id, callback.data)
    try:
        _, _, peer_id_str, new_status = callback.data.split(":")
        peer_id = int(peer_id_str)
    except Exception:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    try:
        await backend.update_peer_status(peer_id, new_status)
        await callback.message.answer(f"Peer #{peer_id} -> {new_status}")
    except Exception as exc:
        logger.error("Failed to update peer %s: %s", peer_id, exc)
        await callback.message.answer(f"Ошибка обновления peer #{peer_id}")
    await callback.answer()


async def main() -> None:
    try:
        await dp.start_polling(bot)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
