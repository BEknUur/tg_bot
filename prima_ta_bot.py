"""
PRIMA TA — Telegram-бот для соглашения об использовании ИИ-агента
Требования: python-telegram-bot>=20.0, gspread, google-auth, python-dotenv
Установка: pip install python-telegram-bot gspread google-auth python-dotenv
"""

import logging
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import gspread
from google.oauth2.service_account import Credentials

# ─── Загрузка переменных окружения ───────────────────────────────────────────
load_dotenv()

BOT_TOKEN       = os.getenv("BOT_TOKEN")
AI_AGENT_LINK   = os.getenv("AI_AGENT_LINK")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS    = os.getenv("GOOGLE_CREDS_JSON", "credentials.json")
SUPPORT_PHONE   = os.getenv("SUPPORT_PHONE", "77784409882")

ALMATY_TZ = pytz.timezone("Asia/Almaty")

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Состояния ConversationHandler ───────────────────────────────────────────
STEP1, STEP2, STEP3, STEP4, STEP5_WAIT_NAME, STEP5_CONFIRM, DONE = range(7)

# ─── Тексты сообщений ────────────────────────────────────────────────────────
MSG = {
    STEP1: (
        "Привет\\!\n\n"
        "Прежде чем получить доступ к ИИ\\-агенту PRIMA TA, ознакомьтесь с "
        "условиями использования\\. Это займёт 2–3 минуты\\.\n\n"
        "*Что такое ИИ\\-агент PRIMA TA*\n\n"
        "Это образовательный инструмент для поддержки вашего обучения "
        "в рамках программы института\\.\n\n"
        "ИИ\\-агент:\n"
        "— не является терапевтом, супервизором или консультантом\n"
        "— не обладает клиническим мышлением\n"
        "— не принимает профессиональных решений\n"
        "— может содержать неточности в ответах\n\n"
        "Вы сохраняете полную ответственность за свои профессиональные решения\\."
    ),
    STEP2: (
        "*Что нельзя вводить в чат с ИИ*\n\n"
        "Запрещено вводить:\n"
        "— персональные данные клиентов\n"
        "— описания реальных кейсов, по которым можно идентифицировать человека\n"
        "— записи сессий и материалы супервизий\n"
        "— любые данные третьих лиц\n\n"
        "ИИ нельзя использовать для терапии или супервизии\\.\n\n"
        "_Это этическое требование, а не формальность\\._"
    ),
    STEP3: (
        "*Конфиденциальность*\n\n"
        "Всё, что вы получаете через ИИ\\-агента — материалы, структуры, "
        "комментарии — является интеллектуальной собственностью PRIMA TA\\.\n\n"
        "Вы обязуетесь:\n"
        "— не передавать ссылку доступа третьим лицам\n"
        "— не распространять материалы и ответы ИИ\n"
        "— не воспроизводить архитектуру инструмента\n"
        "— не создавать производные продукты на его основе\n\n"
        "Обязательства действуют бессрочно\\."
    ),
    STEP4: (
        "*О рисках использования ИИ*\n\n"
        "Пожалуйста, осознайте следующее:\n\n"
        "— ИИ может ошибаться\n"
        "— ИИ может создавать иллюзию понимания там, где его нет\n"
        "— есть риск переоценить достоверность ответов\n"
        "— есть риск избыточной зависимости от инструмента\n\n"
        "Критическое мышление остаётся за вами\\."
    ),
    STEP5_WAIT_NAME: (
        "*Подтверждение согласия*\n\n"
        "Пожалуйста, введите ваше ФИО — это необходимо для фиксации вашего согласия\\."
    ),
}

# ─── Кнопки ──────────────────────────────────────────────────────────────────
def kb_next(callback: str) -> InlineKeyboardMarkup:
    """Одна кнопка 'продолжить'."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("Продолжить →", callback_data=callback)]])

def kb_accept(callback: str) -> InlineKeyboardMarkup:
    """Одна кнопка 'принимаю'."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("Принимаю →", callback_data=callback)]])

def kb_aware(callback: str) -> InlineKeyboardMarkup:
    """Одна кнопка 'осознаю'."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("Осознаю →", callback_data=callback)]])

def kb_final() -> InlineKeyboardMarkup:
    """Две кнопки на шаге 5: перечитать / подтвердить."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Перечитать сначала", callback_data="restart")],
        [InlineKeyboardButton("Подтверждаю всё ✓",   callback_data="confirm_all")],
    ])

# ─── Хранение данных ─────────────────────────────────────────────────────────
def save_to_sheet(telegram_id: int, username: str, full_name: str) -> None:
    """Записывает согласие в Google Sheets."""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

        # Заголовки при первой записи
        if sheet.row_count == 0 or not sheet.cell(1, 1).value:
            sheet.append_row(["telegram_id", "username", "ФИО", "agreed_at", "steps"])

        now = datetime.now(ALMATY_TZ).strftime("%d.%m.%Y %H:%M")
        sheet.append_row([
            str(telegram_id),
            username or "—",
            full_name,
            now,
            "1,2,3,4,5",
        ])
        logger.info(f"Saved: {telegram_id} | {full_name} | {now}")
    except Exception as e:
        logger.error(f"Google Sheets error: {e}")

def already_agreed(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, проходил ли пользователь соглашение в этой сессии."""
    return context.user_data.get("agreed", False)

# ─── Обработчики шагов ───────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — начало или напоминание о прошлом согласии."""
    if already_agreed(context):
        date = context.user_data.get("agreed_at", "ранее")
        await update.message.reply_text(
            f"Вы уже прошли соглашение {date}\\.\n"
            "Ссылка на ИИ\\-агента была выслана ранее\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        MSG[STEP1],
        parse_mode="MarkdownV2",
        reply_markup=kb_next("to_step2"),
    )
    return STEP1


async def step1_to_step2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        MSG[STEP2],
        parse_mode="MarkdownV2",
        reply_markup=kb_accept("to_step3"),
    )
    return STEP2


async def step2_to_step3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        MSG[STEP3],
        parse_mode="MarkdownV2",
        reply_markup=kb_accept("to_step4"),
    )
    return STEP3


async def step3_to_step4(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        MSG[STEP4],
        parse_mode="MarkdownV2",
        reply_markup=kb_aware("to_step5"),
    )
    return STEP4


async def step4_to_step5(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        MSG[STEP5_WAIT_NAME],
        parse_mode="MarkdownV2",
    )
    return STEP5_WAIT_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает ФИО и показывает итоговое подтверждение."""
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text(
            "Пожалуйста, введите полное ФИО\\.",
            parse_mode="MarkdownV2",
        )
        return STEP5_WAIT_NAME

    context.user_data["full_name"] = name

    confirm_text = (
        f"Спасибо, *{name}*\\!\n\n"
        "Подтвердите, что вы:\n"
        "— ознакомились со всеми условиями\n"
        "— понимаете их содержание\n"
        "— принимаете их в полном объёме\n"
        "— берёте на себя ответственность за использование инструмента"
    )
    await update.message.reply_text(
        confirm_text,
        parse_mode="MarkdownV2",
        reply_markup=kb_final(),
    )
    return STEP5_CONFIRM


async def restart_from_step5(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка 'Перечитать сначала' — сброс и возврат на шаг 1."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text(
        MSG[STEP1],
        parse_mode="MarkdownV2",
        reply_markup=kb_next("to_step2"),
    )
    return STEP1


async def confirm_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальное подтверждение — выдача ссылки."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    full_name = context.user_data.get("full_name", "—")
    now = datetime.now(ALMATY_TZ).strftime("%d.%m.%Y %H:%M")

    # Сохраняем в Google Sheets
    save_to_sheet(user.id, user.username, full_name)

    # Фиксируем в user_data
    context.user_data["agreed"] = True
    context.user_data["agreed_at"] = now

    link = AI_AGENT_LINK or "https://example.com"
    # Экранируем символы для MarkdownV2
    safe_name = full_name.replace(".", "\\.").replace("-", "\\-").replace("_", "\\_")
    safe_date = now.replace(".", "\\.").replace("-", "\\-")
    safe_link = link.replace(".", "\\.").replace("-", "\\-").replace("_", "\\_").replace("~", "\\~")

    done_text = (
        "Ваше согласие зафиксировано\\.\n\n"
        f"Дата: {safe_date}\n"
        f"Участник: {safe_name}\n\n"
        f"Вот ваша ссылка на ИИ\\-агента:\n"
        f"👉 {safe_link}\n\n"
        "Если возникнут вопросы — напишите нам, мы рядом\\.\n\n"
        "_Отдел заботы PRIMA TA_"
    )

    support_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Написать в Telegram", url=f"https://t.me/+{SUPPORT_PHONE}")],
        [InlineKeyboardButton("📲 Написать в WhatsApp", url=f"https://wa.me/{SUPPORT_PHONE}")],
    ])

    await query.message.reply_text(done_text, parse_mode="MarkdownV2", reply_markup=support_kb)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог прерван\\. Напишите /start чтобы начать заново\\.", parse_mode="MarkdownV2")
    return ConversationHandler.END

# ─── Сборка приложения ───────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STEP1:           [CallbackQueryHandler(step1_to_step2,    pattern="^to_step2$")],
            STEP2:           [CallbackQueryHandler(step2_to_step3,    pattern="^to_step3$")],
            STEP3:           [CallbackQueryHandler(step3_to_step4,    pattern="^to_step4$")],
            STEP4:           [CallbackQueryHandler(step4_to_step5,    pattern="^to_step5$")],
            STEP5_WAIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            STEP5_CONFIRM:   [
                CallbackQueryHandler(restart_from_step5, pattern="^restart$"),
                CallbackQueryHandler(confirm_all,        pattern="^confirm_all$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)

    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
