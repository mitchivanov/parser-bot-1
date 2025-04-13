from aiogram import Router, types, F
from aiogram.filters import Command
from bot.config import ADMINS, SOURCE_CHATS, TARGET_CHANNELS, INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, PARSE_INTERVAL, logger
import inspect
import asyncio
from datetime import datetime, timezone

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "🤖 Бот-фильтр для пересылки сообщений\n\n"
        "Команды:\n"
        "/help - справка по работе бота\n"
        "/stats - статистика работы (только для админов)\n"
        "/status <channel_id> - проверка статуса канала (только для админов)"
    )

@router.message(Command("help"))
async def help_cmd(message: types.Message):
    help_text = (
        "🔧 <b>Справка по работе бота:</b>\n\n"
        "Автоматически пересылает сообщения из указанных каналов "
        "в целевые каналы с фильтрацией по ключевым словам\n\n"
        "<b>Требования:</b>\n"
        "- Бот должен быть админом в целевых каналах\n"
        "- Настройки фильтров задаются в конфиге\n\n"
        "<b>Команды:</b>\n"
        "/stats - статистика работы\n"
        "/status <channel_id> - проверка статуса канала"
    )
    await message.answer(help_text)

@router.message(Command("stats"), F.from_user.id.in_(ADMINS))
async def stats_cmd(message: types.Message):
    # Получаем экземпляр парсера из main.py
    # Используем inspect для доступа к модулю main
    try:
        import sys
        main_module = sys.modules.get('bot.main') or sys.modules.get('main')
        if main_module and hasattr(main_module, 'parser') and main_module.parser:
            parser = main_module.parser
            
            # Получаем данные из хранилища состояния
            storage_stats = parser.storage.get_stats() if hasattr(parser, 'storage') else {}
            
            # Получаем информацию о времени работы
            uptime_hours = storage_stats.get('uptime_hours', 0)
            
            # Получаем счетчики обработанных сообщений
            messages_processed = storage_stats.get('messages_processed', 0)
            albums_processed = storage_stats.get('albums_processed', 0)
            errors_count = storage_stats.get('errors_count', 0)
            
            # Формируем расширенную статистику
            await message.answer(
                "📊 <b>Расширенная статистика работы бота:</b>\n\n"
                f"⏱ <b>Время работы:</b> {uptime_hours:.1f} часов\n\n"
                f"📨 <b>Обработано сообщений:</b> {messages_processed}\n"
                f"🖼 <b>Обработано альбомов:</b> {albums_processed}\n"
                f"⚠️ <b>Ошибок:</b> {errors_count}\n\n"
                f"📋 <b>Конфигурация:</b>\n"
                f"🔹 Отслеживаемые каналы: {len(SOURCE_CHATS)}\n"
                f"🔸 Целевые каналы: {len(TARGET_CHANNELS)}\n" 
                f"🔹 Ключевые слова включения: {', '.join(INCLUDE_KEYWORDS)}\n"
                f"🔸 Ключевые слова исключения: {', '.join(EXCLUDE_KEYWORDS)}\n"
                f"🔄 Интервал проверки: {PARSE_INTERVAL} сек.\n\n"
                f"🕒 Статистика сгенерирована: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
        else:
            # Если не удалось получить экземпляр парсера, отправляем базовую статистику
            await message.answer(
                "📊 <b>Базовая статистика работы бота:</b>\n\n"
                f"🔹 Отслеживаемые каналы: {len(SOURCE_CHATS)}\n"
                f"🔸 Целевые каналы: {len(TARGET_CHANNELS)}\n" 
                f"🔹 Ключевые слова включения: {', '.join(INCLUDE_KEYWORDS)}\n"
                f"🔸 Ключевые слова исключения: {', '.join(EXCLUDE_KEYWORDS)}\n"
                f"🔄 Интервал проверки: {PARSE_INTERVAL} сек."
            )
    except Exception as e:
        logger.error(f"Ошибка при формировании статистики: {e}")
        await message.answer(
            "⚠️ <b>Ошибка при получении расширенной статистики</b>\n\n"
            f"🔹 Отслеживаемые каналы: {len(SOURCE_CHATS)}\n"
            f"🔸 Целевые каналы: {len(TARGET_CHANNELS)}\n" 
            f"🔄 Интервал проверки: {PARSE_INTERVAL} сек."
        )

@router.message(Command("status"), F.from_user.id.in_(ADMINS))
async def channel_status_cmd(message: types.Message):
    """Проверяет статус канала по его ID"""
    # Получаем параметры команды
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        await message.answer("❌ Ошибка: укажите ID канала. Пример: /status 1234567890")
        return
        
    channel_id = args[0]
    
    try:
        # Преобразуем ID канала в число, если это число
        if channel_id.isdigit() or (channel_id.startswith('-') and channel_id[1:].isdigit()):
            channel_id = int(channel_id)
            
        # Получаем экземпляр парсера
        import sys
        main_module = sys.modules.get('bot.main') or sys.modules.get('main')
        
        if not main_module or not hasattr(main_module, 'parser') or not main_module.parser:
            await message.answer("❌ Не удалось получить доступ к парсеру")
            return
            
        parser = main_module.parser
        
        # Проверяем наличие канала в отслеживаемых
        if not channel_id in parser.channel_activity:
            await message.answer(
                f"❌ Канал {channel_id} не найден в списке отслеживаемых каналов.\n\n"
                "Возможно, канал еще не был инициализирован или указан неверный ID."
            )
            return
            
        # Получаем информацию о канале
        activity = parser.channel_activity[channel_id]
        last_processed_id = parser.storage.get_last_message_id(channel_id)
        
        # Преобразуем даты в строки, если это datetime объекты
        last_post_date = activity.get('last_post_date')
        if hasattr(last_post_date, 'strftime'):
            last_post_date = last_post_date.strftime('%Y-%m-%d %H:%M:%S UTC')
            
        next_check = activity.get('next_check')
        if hasattr(next_check, 'strftime'):
            next_check = next_check.strftime('%Y-%m-%d %H:%M:%S UTC')
            
        # Формируем статус канала
        status_text = (
            f"📋 <b>Статус канала {channel_id}:</b>\n\n"
            f"🔹 Последний пост: {last_post_date}\n"
            f"🔸 Последний обработанный ID: {last_processed_id}\n"
            f"🔹 Интервал проверки: {activity.get('check_interval')} сек\n"
            f"🔸 Следующая проверка: {next_check}\n\n"
            f"ℹ️ Статус запрошен: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        
        await message.answer(status_text)
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса канала {channel_id}: {e}")
        await message.answer(f"❌ Ошибка при получении статуса канала {channel_id}: {e}") 