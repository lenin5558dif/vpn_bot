import asyncio
import logging
import os
import tempfile
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types.input_file import FSInputFile

from app.config import get_settings
from app.schemas import RequestStatus
from bot.alerts import AlertManager
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
alerts = AlertManager(bot=bot, backend=backend, admin_ids=ADMIN_IDS, settings=settings)

AMNEZIAWG_INSTRUCTION = (
    "📱 <b>Как подключиться:</b>\n\n"
    "1. Скачай приложение <b>AmneziaWG</b>:\n"
    '   • <a href="https://apps.apple.com/app/amneziawg/id1600529900">iOS — App Store</a>\n'
    '   • <a href="https://play.google.com/store/apps/details?id=org.amnezia.awg">Android — Google Play</a>\n\n'
    "2. Открой приложение → нажми <b>«+»</b> → <b>«Импорт из файла»</b>\n"
    "3. Выбери полученный .conf файл\n"
    "4. Включи VPN переключателем\n\n"
    "Возникли проблемы? Напишите администратору."
)

REQUEST_STATUS_TEXT = {
    "new": "⏳ Заявка на рассмотрении — ожидай ответа администратора",
    "approved": "✅ Заявка одобрена — конфиг был отправлен тебе в чат",
    "rejected": "❌ Заявка отклонена — свяжись с администратором",
}

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


class AdminSearch(StatesGroup):
    waiting_query = State()


# ─── Клиентские команды ──────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    tg_id = message.from_user.id

    try:
        user = await backend.get_user_by_tg_id(tg_id)
        if user:
            reqs = await backend.get_requests_by_user_id(user["id"])
            if reqs:
                latest = sorted(reqs, key=lambda r: r.get("id", 0), reverse=True)[0]
                status = latest.get("status", "")
                status_text = REQUEST_STATUS_TEXT.get(status, status)
                if status == "new":
                    await message.answer(
                        f"У тебя уже есть активная заявка.\n{status_text}\n\n"
                        "Хочешь подать новую? — /newrequest"
                    )
                    return
                elif status == "approved":
                    await message.answer(
                        f"{status_text}.\n\n"
                        "Если потерял конфиг — напиши администратору.\n"
                        "Подать новую заявку: /newrequest"
                    )
                    return
    except Exception as exc:
        logger.warning("Could not check existing requests for tg_id=%s: %s", tg_id, exc)

    await message.answer("Привет! Введи, пожалуйста, своё имя и фамилию.")
    await state.set_state(RequestAccess.waiting_name)


@dp.message(Command("newrequest"))
async def cmd_newrequest(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Введи своё имя и фамилию.")
    await state.set_state(RequestAccess.waiting_name)


@dp.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user:
        return
    tg_id = message.from_user.id
    try:
        user = await backend.get_user_by_tg_id(tg_id)
        if not user:
            await message.answer("Заявок не найдено. Напишите /start чтобы подать заявку.")
            return
        reqs = await backend.get_requests_by_user_id(user["id"])
        if not reqs:
            await message.answer("Заявок не найдено. Напишите /start чтобы подать заявку.")
            return
        latest = sorted(reqs, key=lambda r: r.get("id", 0), reverse=True)[0]
        status = latest.get("status", "unknown")
        status_text = REQUEST_STATUS_TEXT.get(status, status)
        await message.answer(f"Статус твоей заявки:\n{status_text}")
    except Exception as exc:
        logger.error("Status check failed for tg_id=%s: %s", tg_id, exc)
        await message.answer("Не удалось получить статус. Попробуй позже.")


# ─── FSM: сбор данных заявки ─────────────────────────────────────────────────

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
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]]
    )
    await message.answer(
        "Комментарий (опционально). Если нечего добавить — нажми «Пропустить».",
        reply_markup=kb,
    )
    await state.set_state(RequestAccess.waiting_comment)


@dp.callback_query(F.data == "skip_comment", RequestAccess.waiting_comment)
async def skip_comment(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await _submit_request(callback.message, state, comment="", tg_id=callback.from_user.id)
    await callback.answer()


@dp.message(RequestAccess.waiting_comment)
async def handle_comment(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовое сообщение.")
        return
    if not message.from_user:
        await message.answer("Не удалось определить отправителя.")
        return
    comment = message.text.strip()[:500]
    if comment.lower() == "нет":
        comment = ""
    await _submit_request(message, state, comment=comment, tg_id=message.from_user.id)


async def _submit_request(message: Message, state: FSMContext, comment: str, tg_id: int) -> None:
    data = await state.get_data()
    name = data.get("name")
    contact = data.get("contact")

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
            [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{req['id']}:{user['id']}:{tg_id}")],
            [InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject:{req['id']}:{user['id']}:{tg_id}")],
        ]
    )
    text = (
        f"📋 Новая заявка #{req['id']}\n"
        f"👤 Имя: {name}\n"
        f"📞 Контакт: {contact}\n"
        f"💬 Комментарий: {comment or '—'}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception as exc:
            logger.error("Failed to notify admin %s: %s", admin_id, exc)


# ─── Одобрение / отказ ───────────────────────────────────────────────────────

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

    try:
        existing_peers = [
            p for p in await backend.list_peers(user_id=user_id)
            if p.get("status") in {"active", "disabled"}
        ]
        peer = sorted(existing_peers, key=lambda p: p.get("id", 0), reverse=True)[0] if existing_peers else None
        if peer is None:
            peer = await backend.create_peer(user_id)
        elif peer.get("status") == "disabled":
            peer = await backend.update_peer_status(int(peer["id"]), "active")
        config_text = await backend.get_config(peer["id"])
    except Exception as exc:
        logger.error("Failed to provision VPN for request %s user %s: %s", req_id, user_id, exc)
        if callback.message:
            await callback.message.answer(
                f"Не удалось выдать VPN для заявки #{req_id}. Заявка не помечена одобренной."
            )
        await callback.answer("Ошибка выдачи", show_alert=True)
        return

    filename_slug = "user"
    try:
        user = await backend.get_user(user_id)
        filename_slug = translit_slug(user.get("name") or "") or "user"
    except Exception as exc:
        logger.error("Failed to fetch user for filename: %s", exc)

    tmp_path = None
    try:
        await bot.send_message(tg_id, "✅ Доступ одобрен! Вот твой конфиг:")
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".conf") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name
        input_file = FSInputFile(tmp_path, filename=f"VPN_{filename_slug}.conf")
        await bot.send_document(tg_id, input_file, caption="Импортируй файл в приложение AmneziaWG")
    except Exception as exc:
        logger.error("Failed to send config file: %s", exc)
        if callback.message:
            await callback.message.answer(
                f"Конфиг для заявки #{req_id} создан, но не отправлен пользователю. Статус не изменён."
            )
        await callback.answer("Ошибка отправки", show_alert=True)
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    try:
        await bot.send_message(tg_id, AMNEZIAWG_INSTRUCTION, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        logger.error("Failed to send instruction: %s", exc)

    try:
        await backend.update_request(req_id, RequestStatus.approved)
    except Exception as exc:
        logger.error("Failed to mark request %s approved after provisioning: %s", req_id, exc)
        if callback.message:
            await callback.message.answer(
                f"VPN для заявки #{req_id} выдан, но статус не обновился. Повторное одобрение переиспользует peer #{peer['id']}."
            )
        await callback.answer("Выдано, статус не обновлён", show_alert=True)
        return

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

    try:
        await backend.update_request(req_id, RequestStatus.rejected)
        await bot.send_message(tg_id, "К сожалению, доступ отклонён. Свяжитесь с админом для подробностей.")
        await callback.answer("Отказано")
    except Exception as exc:
        logger.error("Failed to reject request %s: %s", req_id, exc)
        await callback.answer("Ошибка отказа", show_alert=True)


# ─── Админ-меню ──────────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def admin_menu(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа")
        return
    await message.answer("Админ-меню:", reply_markup=_admin_menu_keyboard())


def _gb(value: int | float | None) -> float:
    return float(value or 0) / (1024 ** 3)


def _status_icon(status: str | None) -> str:
    return {"active": "🟢", "disabled": "🔴", "banned": "⛔", "pending": "⚪"}.get(status or "", "⚪")


def _admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users:0")],
            [InlineKeyboardButton(text="🔎 Поиск", callback_data="adm:srch")],
            [
                InlineKeyboardButton(text="🆕 Новые заявки", callback_data="admin:req:new"),
                InlineKeyboardButton(text="📋 Все заявки", callback_data="admin:req:all"),
            ],
            [
                InlineKeyboardButton(text="📊 Трафик", callback_data="admin:traffic"),
                InlineKeyboardButton(text="🖥 Сервер", callback_data="admin:server"),
            ],
            [
                InlineKeyboardButton(text="🧭 Диагностика", callback_data="adm:diag"),
                InlineKeyboardButton(text="❤️ Health", callback_data="admin:health"),
            ],
        ]
    )


def _user_list_keyboard(data: dict, query: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user in data.get("items", []):
        counts = user.get("peer_counts", {})
        active = counts.get("active", 0)
        total = counts.get("total", 0)
        label = f"👤 #{user.get('id')} {user.get('name')} · 🟢{active}/{total}"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"adm:u:{user.get('id')}")])

    offset = int(data.get("offset", 0) or 0)
    limit = int(data.get("limit", 8) or 8)
    total = int(data.get("total", 0) or 0)
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"adm:users:{max(0, offset - limit)}"))
    page = offset // limit + 1 if limit else 1
    pages = max(1, (total + limit - 1) // limit) if limit else 1
    nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="adm:noop"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"adm:users:{offset + limit}"))
    rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🔎 Поиск", callback_data="adm:srch"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="adm:menu"),
    ])
    if query:
        rows.append([InlineKeyboardButton(text="Сбросить поиск", callback_data="adm:reset")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_user_list(data: dict, query: str | None = None) -> str:
    total = int(data.get("total", 0) or 0)
    title = f"👥 Пользователи: {total}"
    if query:
        title += f"\n🔎 Поиск: {query}"
    lines = [title]
    if not data.get("items"):
        lines.append("\nНичего не найдено.")
        return "\n".join(lines)
    for user in data.get("items", []):
        counts = user.get("peer_counts", {})
        req = user.get("latest_request") or {}
        lines.append(
            "\n"
            f"#{user.get('id')} {user.get('name')}\n"
            f"📞 {user.get('contact') or '—'} · tg_id={user.get('tg_id') or '—'}\n"
            f"🔑 Пиры: 🟢{counts.get('active', 0)} 🔴{counts.get('disabled', 0)} "
            f"⛔{counts.get('banned', 0)} · 24ч {_gb(user.get('traffic_24h_bytes')):.1f} ГБ\n"
            f"📋 Заявка: {req.get('status', '—')}"
        )
    return "\n".join(lines)


async def _send_user_list(target: Message | CallbackQuery, offset: int = 0, query: str | None = None) -> None:
    try:
        data = await backend.admin_user_list(query=query, limit=8, offset=offset)
    except Exception as exc:
        logger.error("Failed to load admin user list: %s", exc)
        text = "Не удалось загрузить пользователей."
        kb = _admin_menu_keyboard()
    else:
        text = _format_user_list(data, query=query)
        kb = _user_list_keyboard(data, query=query)
    if isinstance(target, CallbackQuery):
        await _edit_or_answer(target, text, kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


def _user_card_keyboard(card: dict) -> InlineKeyboardMarkup:
    user = card.get("user", {})
    user_id = user.get("id")
    rows: list[list[InlineKeyboardButton]] = []
    for peer in card.get("peers", []):
        rows.append([
            InlineKeyboardButton(
                text=f"{_status_icon(peer.get('status'))} Peer #{peer.get('id')} · {peer.get('address')}",
                callback_data=f"adm:pc:{peer.get('id')}:{user_id}",
            )
        ])
    rows.extend([
        [
            InlineKeyboardButton(text="➕ Добавить устройство", callback_data=f"adm:add:{user_id}"),
            InlineKeyboardButton(text="📤 Конфиг", callback_data=f"adm:cfgu:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="🔴 Откл. все", callback_data=f"adm:ub:{user_id}:disabled"),
            InlineKeyboardButton(text="🟢 Вкл. все", callback_data=f"adm:ub:{user_id}:active"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:u:{user_id}"),
            InlineKeyboardButton(text="👥 Назад", callback_data="adm:back"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_user_card(card: dict) -> str:
    user = card.get("user", {})
    req = card.get("latest_request") or {}
    wg = card.get("wg", {})
    lines = [
        f"👤 {user.get('name')} · #{user.get('id')}",
        f"Telegram: {user.get('tg_id') or '—'}",
        f"Контакт: {user.get('contact') or '—'}",
        f"Заявка: {req.get('status', '—')} #{req.get('id', '—')}",
        f"WG: {'✅ доступен' if wg.get('available') else '⚠️ недоступен'}",
        f"Трафик 24ч: {_gb(card.get('traffic_24h_bytes')):.1f} ГБ",
        "",
        "Устройства:",
    ]
    peers = card.get("peers", [])
    if not peers:
        lines.append("  нет устройств")
    for peer in peers:
        traffic = peer.get("traffic_24h", {})
        online = "онлайн" if peer.get("online") else "оффлайн"
        wg_state = "WG есть" if peer.get("wg_present") else "WG нет"
        lines.append(
            f"{_status_icon(peer.get('status'))} #{peer.get('id')} · {peer.get('address')} · "
            f"{peer.get('speed_limit_mbps')} Мбит/с\n"
            f"   {online}, {wg_state}, handshake: {peer.get('last_handshake_at') or '—'}\n"
            f"   24ч ↓{_gb(traffic.get('rx')):.1f} / ↑{_gb(traffic.get('tx')):.1f} ГБ"
        )
    return "\n".join(lines)


async def _send_user_card(callback: CallbackQuery, user_id: int) -> None:
    try:
        card = await backend.admin_user_card(user_id)
    except Exception as exc:
        logger.error("Failed to load user card %s: %s", user_id, exc)
        await callback.answer("Не удалось загрузить карточку", show_alert=True)
        return
    await _edit_or_answer(callback, _format_user_card(card), _user_card_keyboard(card))
    await callback.answer()


def _peer_card_keyboard(peer: dict, user_id: int) -> InlineKeyboardMarkup:
    peer_id = peer.get("id")
    speed_buttons = [
        InlineKeyboardButton(text=str(speed), callback_data=f"adm:ps:{peer_id}:{user_id}:{speed}")
        for speed in (5, 10, 20, 50, 100, 0)
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Отключить", callback_data=f"adm:pa:{peer_id}:disabled"),
                InlineKeyboardButton(text="🟢 Включить", callback_data=f"adm:pa:{peer_id}:active"),
            ],
            speed_buttons[:3],
            speed_buttons[3:],
            [
                InlineKeyboardButton(text="📤 Отправить конфиг", callback_data=f"adm:cfg:{peer_id}:{user_id}"),
                InlineKeyboardButton(text="⛔ Бан…", callback_data=f"adm:ban?:{peer_id}:{user_id}"),
            ],
            [InlineKeyboardButton(text="← Карточка пользователя", callback_data=f"adm:u:{user_id}")],
        ]
    )
    return kb


def _format_peer_card(peer: dict) -> str:
    traffic = peer.get("traffic_24h", {})
    return (
        f"🔑 Peer #{peer.get('id')}\n"
        f"Статус: {_status_icon(peer.get('status'))} {peer.get('status')}\n"
        f"IP: {peer.get('address')}\n"
        f"Скорость: {peer.get('speed_limit_mbps')} Мбит/с\n"
        f"WG: {'есть' if peer.get('wg_present') else 'нет'} · allowed={peer.get('wg_allowed_ips') or '—'}\n"
        f"Онлайн: {'да' if peer.get('online') else 'нет'}\n"
        f"Handshake: {peer.get('last_handshake_at') or '—'}\n"
        f"Трафик 24ч: ↓{_gb(traffic.get('rx')):.1f} / ↑{_gb(traffic.get('tx')):.1f} ГБ"
    )


async def _send_peer_card(callback: CallbackQuery, peer_id: int, user_id: int) -> None:
    try:
        card = await backend.admin_user_card(user_id)
        peer = next((p for p in card.get("peers", []) if int(p.get("id")) == peer_id), None)
    except Exception as exc:
        logger.error("Failed to load peer card %s: %s", peer_id, exc)
        await callback.answer("Не удалось загрузить peer", show_alert=True)
        return
    if not peer:
        await callback.answer("Peer не найден", show_alert=True)
        return
    await _edit_or_answer(callback, _format_peer_card(peer), _peer_card_keyboard(peer, user_id))
    await callback.answer()


async def _edit_or_answer(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


async def _send_config_to_user(peer_id: int, user_id: int) -> None:
    card = await backend.admin_user_card(user_id)
    user = card.get("user", {})
    peer_ids = {int(peer["id"]) for peer in card.get("peers", []) if peer.get("id") is not None}
    if peer_id not in peer_ids:
        raise RuntimeError("Peer does not belong to target user")
    tg_id = user.get("tg_id")
    if not tg_id:
        raise RuntimeError("User has no tg_id")
    config_text = await backend.get_config(peer_id)
    filename_slug = translit_slug(user.get("name") or "") or "user"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".conf") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name
        input_file = FSInputFile(tmp_path, filename=f"VPN_{filename_slug}_peer_{peer_id}.conf")
        await bot.send_document(tg_id, input_file, caption="VPN-конфиг для AmneziaWG")
        await bot.send_message(tg_id, AMNEZIAWG_INSTRUCTION, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def _diagnostics_text() -> str:
    health = await backend.health()
    stats = await backend.get_server_stats()
    reconcile = await backend.reconcile_peers()
    counts = reconcile.get("counts", {})
    return (
        "🧭 Диагностика\n"
        f"Backend: {health.get('status')}\n"
        f"WireGuard: {health.get('checks', {}).get('wireguard', 'unknown')}\n"
        f"Disk: {stats.get('disk_used_pct', 0)}% "
        f"({stats.get('disk_used_gb', 0)}/{stats.get('disk_total_gb', 0)} GB)\n"
        f"Reconcile: {reconcile.get('status')}\n"
        f"  unknown WG: {counts.get('unknown_wg_peers', 0)}\n"
        f"  missing WG: {counts.get('missing_wg_peers', 0)}\n"
        f"  allowed_ips mismatch: {counts.get('allowed_ips_mismatch', 0)}\n"
        f"  disabled nonempty allowed_ips: {counts.get('disabled_with_allowed_ips', 0)}"
    )


@dp.callback_query(F.data.startswith("adm:"))
async def admin_card_actions(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    data = callback.data or ""
    try:
        parts = data.split(":")
        action = parts[1]
    except Exception:
        await callback.answer("Некорректный запрос", show_alert=True)
        return

    try:
        if action == "noop":
            await callback.answer()
        elif action == "menu":
            await state.clear()
            await _edit_or_answer(callback, "Админ-меню:", _admin_menu_keyboard())
            await callback.answer()
        elif action == "users":
            offset = int(parts[2]) if len(parts) > 2 else 0
            navigation = await state.get_data()
            query = navigation.get("admin_query")
            await state.update_data(admin_offset=offset)
            await _send_user_list(callback, offset=offset, query=query)
        elif action == "back":
            navigation = await state.get_data()
            await _send_user_list(
                callback,
                offset=int(navigation.get("admin_offset") or 0),
                query=navigation.get("admin_query"),
            )
        elif action == "reset":
            await state.clear()
            await _send_user_list(callback, offset=0)
        elif action == "srch":
            await state.set_state(AdminSearch.waiting_query)
            if callback.message:
                await callback.message.answer("Введите имя, контакт, user ID или Telegram ID для поиска.")
            await callback.answer()
        elif action == "u":
            await _send_user_card(callback, int(parts[2]))
        elif action == "pc":
            await _send_peer_card(callback, int(parts[2]), int(parts[3]))
        elif action == "pa":
            peer_id = int(parts[2])
            new_status = parts[3]
            peer = await backend.update_peer_status(peer_id, new_status)
            await _send_peer_card(callback, peer_id, int(peer["user_id"]))
        elif action == "ps":
            peer_id = int(parts[2])
            user_id = int(parts[3])
            speed = int(parts[4])
            await backend.update_peer_status(peer_id, "active", speed_limit_mbps=speed)
            await _send_peer_card(callback, peer_id, user_id)
        elif action == "ub":
            user_id = int(parts[2])
            new_status = parts[3]
            await backend.bulk_update_user_peers(user_id, new_status)
            await _send_user_card(callback, user_id)
        elif action == "add":
            user_id = int(parts[2])
            peer = await backend.create_peer(user_id)
            try:
                await _send_config_to_user(int(peer["id"]), user_id)
            except Exception as exc:
                logger.error("Failed to send config for new peer %s: %s", peer.get("id"), exc)
                if callback.message:
                    await callback.message.answer(f"Peer #{peer.get('id')} создан, но конфиг не отправлен.")
            await _send_user_card(callback, user_id)
        elif action == "cfg":
            peer_id = int(parts[2])
            user_id = int(parts[3])
            await _send_config_to_user(peer_id, user_id)
            await callback.answer("Конфиг отправлен")
        elif action == "cfgu":
            user_id = int(parts[2])
            card = await backend.admin_user_card(user_id)
            peers = [p for p in card.get("peers", []) if p.get("status") in {"active", "disabled"}]
            if not peers:
                await callback.answer("Нет peer для отправки", show_alert=True)
                return
            peer = sorted(peers, key=lambda p: p.get("id", 0), reverse=True)[0]
            await _send_config_to_user(int(peer["id"]), user_id)
            await callback.answer("Конфиг отправлен")
        elif action == "ban?":
            peer_id = int(parts[2])
            user_id = int(parts[3])
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⛔ Да, забанить", callback_data=f"adm:ban!:{peer_id}:{user_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"adm:pc:{peer_id}:{user_id}"),
            ]])
            await _edit_or_answer(
                callback,
                f"⚠️ Забанить peer #{peer_id}? Действие удалит peer из БД и WireGuard.",
                kb,
            )
            await callback.answer()
        elif action == "ban!":
            peer_id = int(parts[2])
            user_id = int(parts[3])
            await backend.update_peer_status(peer_id, "banned")
            await _send_user_card(callback, user_id)
        elif action == "diag":
            text = await _diagnostics_text()
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:diag"),
                InlineKeyboardButton(text="🏠 Меню", callback_data="adm:menu"),
            ]])
            await _edit_or_answer(callback, text, kb)
            await callback.answer()
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные", show_alert=True)
    except Exception as exc:
        logger.error("Admin card action failed for %s: %s", data, exc)
        await callback.answer("Ошибка действия", show_alert=True)


@dp.message(AdminSearch.waiting_query)
async def admin_search_query(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа")
        await state.clear()
        return
    query = (message.text or "").strip()[:100]
    await state.set_state(None)
    await state.update_data(admin_query=query, admin_offset=0)
    try:
        data = await backend.admin_user_list(query=query, limit=8, offset=0)
    except Exception as exc:
        logger.error("Admin search failed: %s", exc)
        await message.answer("Поиск временно недоступен.", reply_markup=_admin_menu_keyboard())
        return
    await message.answer(_format_user_list(data, query=query), reply_markup=_user_list_keyboard(data, query=query))


def _format_requests(items: list[dict]) -> str:
    if not items:
        return "Пусто"
    lines = []
    for r in items[:15]:
        lines.append(
            f"#{r.get('id')} user={r.get('user_id')} "
            f"status={r.get('status')} created={r.get('created_at')}"
        )
    return "\n".join(lines)


def _format_users(items: list[dict]) -> str:
    if not items:
        return "Пусто"
    lines = []
    for u in items[:15]:
        lines.append(f"#{u.get('id')} {u.get('name')} contact={u.get('contact')}")
    return "\n".join(lines)


async def _user_names() -> dict[int, str]:
    try:
        users = await backend.list_users()
    except Exception as exc:
        logger.error("Failed to fetch users for name map: %s", exc)
        return {}
    return {u.get("id"): u.get("name") for u in users}


ADMIN_MENU_ACTIONS = {
    "admin:req:new", "admin:req:all", "admin:peers", "admin:users",
    "admin:online", "admin:traffic", "admin:top", "admin:server", "admin:health",
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
        names = await _user_names()
        await callback.message.answer(f"Пиры ({min(len(peers), 20)} из {len(peers)}):")
        status_icon = {"active": "🟢", "disabled": "🔴", "banned": "⛔"}
        for p in peers[:20]:
            icon = status_icon.get(p.get("status", ""), "⚪")
            uid = p.get("user_id")
            uname = names.get(uid, f"user#{uid}")
            text = (
                f"{icon} {uname} · Peer #{p.get('id')} | {p.get('address')}\n"
                f"👤 user={uid} | ⚡ {p.get('speed_limit_mbps')} Мбит/с"
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔴 Откл.", callback_data=f"admin:peer:{p.get('id')}:disabled"),
                        InlineKeyboardButton(text="🟢 Вкл.", callback_data=f"admin:peer:{p.get('id')}:active"),
                    ],
                    [InlineKeyboardButton(text="⛔ Забанить", callback_data=f"admin:peer:ban_ask:{p.get('id')}")],
                ]
            )
            await callback.message.answer(text, reply_markup=kb)

    elif action == "admin:users":
        users = await backend.list_users()
        peers = await backend.list_peers()
        peers_by_user: dict[int, list[dict]] = {}
        for p in peers:
            peers_by_user.setdefault(p.get("user_id"), []).append(p)
        status_icon = {"active": "🟢", "disabled": "🔴", "banned": "⛔"}
        await callback.message.answer(f"Пользователи ({min(len(users), 20)} из {len(users)}):")
        for u in users[:20]:
            uid = u.get("id")
            user_peers = peers_by_user.get(uid, [])
            if user_peers:
                peer_summary = " ".join(
                    f"{status_icon.get(pp.get('status', ''), '⚪')}#{pp.get('id')}" for pp in user_peers
                )
            else:
                peer_summary = "нет пиров"
            text = (
                f"#{uid} {u.get('name')}\n"
                f"📞 {u.get('contact') or '—'}\n"
                f"🔑 {peer_summary}"
            )
            if user_peers:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="🔴 Откл. все", callback_data=f"admin:user:{uid}:disabled"),
                        InlineKeyboardButton(text="🟢 Вкл. все", callback_data=f"admin:user:{uid}:active"),
                    ]]
                )
                await callback.message.answer(text, reply_markup=kb)
            else:
                await callback.message.answer(text)

    elif action == "admin:online":
        data = await backend.get_online_peers()
        lines = [f"Онлайн: {data['online_count']}/{data['total']}"]
        for p in data.get("peers", []):
            ago = p["seconds_ago"]
            ago_str = f"{ago} сек" if ago < 60 else f"{ago // 60} мин"
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
            lines.append(f"  {name}: ↓{rx_gb:.1f} ГБ / ↑{tx_gb:.1f} ГБ")
        if not items:
            lines.append("  Нет данных")
        await callback.message.answer("\n".join(lines))

    elif action == "admin:top":
        items = await backend.get_traffic_summary(hours=24)
        ranked = sorted(items, key=lambda x: x["rx"] + x["tx"], reverse=True)[:5]
        lines = ["Топ-5 за 24ч:"]
        for i, item in enumerate(ranked, 1):
            total_gb = (item["rx"] + item["tx"]) / (1024 ** 3)
            name = item.get("name", f"user#{item['user_id']}")
            lines.append(f"  {i}. {name} — {total_gb:.1f} ГБ")
        if not ranked:
            lines.append("  Нет данных")
        await callback.message.answer("\n".join(lines))

    elif action == "admin:server":
        stats = await backend.get_server_stats()
        text = (
            f"Сервер:\n"
            f"  CPU: {stats['cpu_pct']}% ({stats['cpu_cores']} core)\n"
            f"  RAM: {stats['ram_used_mb']}/{stats['ram_total_mb']} MB\n"
            f"  Disk: {stats['disk_used_gb']}/{stats['disk_total_gb']} GB ({stats.get('disk_used_pct', 0)}%)\n"
            f"  Uptime: {stats['uptime']}\n"
            f"  Пиров: {stats['peers_total']}\n"
            f"  TrafficStat: {stats['trafficstat_rows']} строк"
        )
        await callback.message.answer(text)

    elif action == "admin:health":
        health = await backend.health()
        await callback.message.answer(f"Health: {health}")

    await callback.answer()


# ─── Бан с подтверждением (регистрируем ДО общего peer-хэндлера) ─────────────

@dp.callback_query(F.data.startswith("admin:peer:ban_ask:"))
async def admin_ban_ask(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    try:
        peer_id = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⛔ Да, забанить", callback_data=f"admin:peer:ban_ok:{peer_id}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"admin:peer:ban_cancel:{peer_id}"),
        ]]
    )
    await callback.message.answer(
        f"⚠️ Забанить peer #{peer_id}?\n"
        "Пользователь немедленно потеряет доступ. Действие необратимо.",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin:peer:ban_ok:"))
async def admin_ban_confirm(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    try:
        peer_id = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    try:
        await backend.update_peer_status(peer_id, "banned")
        await callback.message.answer(f"⛔ Peer #{peer_id} забанен.")
    except Exception as exc:
        logger.error("Failed to ban peer %s: %s", peer_id, exc)
        await callback.message.answer(f"Ошибка при бане peer #{peer_id}")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin:peer:ban_cancel:"))
async def admin_ban_cancel(callback: CallbackQuery) -> None:
    await callback.message.answer("Бан отменён.")
    await callback.answer()


# ─── Управление пирами (отключить / активировать) ────────────────────────────

@dp.callback_query(F.data.startswith("admin:peer:"))
async def admin_peer_update(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    logger.info("Admin %s peer action: %s", callback.from_user.id, callback.data)
    try:
        _, _, peer_id_str, new_status = callback.data.split(":")
        peer_id = int(peer_id_str)
    except Exception:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    try:
        await backend.update_peer_status(peer_id, new_status)
        icon = {"active": "🟢", "disabled": "🔴"}.get(new_status, "")
        await callback.message.answer(f"{icon} Peer #{peer_id} → {new_status}")
    except Exception as exc:
        logger.error("Failed to update peer %s: %s", peer_id, exc)
        await callback.message.answer(f"Ошибка обновления peer #{peer_id}")
    await callback.answer()


# ─── Массовое управление пирами пользователя (по имени) ──────────────────────

@dp.callback_query(F.data.startswith("admin:user:"))
async def admin_user_toggle(callback: CallbackQuery) -> None:
    if not await _ensure_admin(callback):
        return
    logger.info("Admin %s user action: %s", callback.from_user.id, callback.data)
    try:
        _, _, user_id_str, new_status = callback.data.split(":")
        user_id = int(user_id_str)
    except Exception:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    if new_status not in ("active", "disabled"):
        await callback.answer("Недопустимый статус", show_alert=True)
        return
    try:
        peers = await backend.list_peers(user_id=user_id)
        user_peers = [
            p for p in peers
            if p.get("user_id") == user_id and p.get("status") != "banned"
        ]
        if not user_peers:
            await callback.message.answer(f"У #{user_id} нет управляемых пиров (или все забанены).")
            await callback.answer()
            return
        ok = 0
        for p in user_peers:
            try:
                await backend.update_peer_status(p["id"], new_status)
                ok += 1
            except Exception as exc:
                logger.error("Failed to toggle peer %s: %s", p.get("id"), exc)
        icon = {"active": "🟢", "disabled": "🔴"}.get(new_status, "")
        await callback.message.answer(
            f"{icon} #{user_id}: {ok}/{len(user_peers)} пиров → {new_status}"
        )
    except Exception as exc:
        logger.error("Failed to toggle user %s peers: %s", user_id, exc)
        await callback.message.answer(f"Ошибка при обновлении пиров #{user_id}")
    await callback.answer()


async def main() -> None:
    try:
        alerts.start()
        await dp.start_polling(bot)
    finally:
        await alerts.stop()
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
