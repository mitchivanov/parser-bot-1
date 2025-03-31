from aiogram import Router, types, F
from aiogram.filters import Command
from config import ADMINS, SOURCE_CHATS, TARGET_CHANNELS, INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, PARSE_INTERVAL, logger

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "🤖 Бот-фильтр для пересылки сообщений\n\n"
        "Команды:\n"
        "/help - справка по работе бота\n"
        "/stats - статистика работы (только для админов)"
    )

@router.message(Command("help"))
async def help_cmd(message: types.Message):
    help_text = (
        "🔧 <b>Справка по работе бота:</b>\n\n"
        "Автоматически пересылает сообщения из указанных каналов "
        "в целевые каналы с фильтрацией по ключевым словам\n\n"
        "<b>Требования:</b>\n"
        "- Бот должен быть админом в целевых каналах\n"
        "- Настройки фильтров задаются в конфиге"
    )
    await message.answer(help_text)

@router.message(Command("stats"), F.from_user.id.in_(ADMINS))
async def stats_cmd(message: types.Message):
    await message.answer(
        "📊 <b>Статистика работы бота:</b>\n\n"
        f"🔹 Отслеживаемые каналы: {len(SOURCE_CHATS)}\n"
        f"🔸 Целевые каналы: {len(TARGET_CHANNELS)}\n" 
        f"🔹 Ключевые слова включения: {', '.join(INCLUDE_KEYWORDS)}\n"
        f"🔸 Ключевые слова исключения: {', '.join(EXCLUDE_KEYWORDS)}\n"
        f"🔄 Интервал проверки: {PARSE_INTERVAL} сек."
    ) 