from aiogram import F, types, Router, Bot
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.utils.media_group import MediaGroupBuilder
from bot.config import SOURCE_CHATS, TARGET_CHANNELS, INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, logger, ADMINS, CONFIG
from tenacity import retry, stop_after_attempt, wait_fixed
from aiogram.types import Message
import re

router = Router()

# Словарь для хранения кодов авторизации от админов
auth_codes = {}

async def check_admin(bot: Bot, channel_id: int) -> bool:
    try:
        admins = await bot.get_chat_administrators(channel_id)
        return any(admin.user.id == bot.id for admin in admins)
    except Exception as e:
        logger.error(f"Admin check error in {channel_id}: {e}")
        return False

def content_filter(message: types.Message) -> bool:
    # Получаем текст из сообщения или подписи к медиа
    text = (message.text or message.caption or "").lower()
    
    has_include = any(kw.lower() in text for kw in INCLUDE_KEYWORDS)
    has_exclude = any(kw.lower() in text for kw in EXCLUDE_KEYWORDS)
    
    return has_include and not has_exclude

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
async def safe_forward(message: types.Message, channel_id: int):
    await message.send_copy(channel_id)

async def forward_content(message: types.Message, bot: Bot, channel_id: int):
    try:
        if message.media_group_id:
            # Для медиа-групп требуется отдельная обработка
            album = MediaGroupBuilder()
            for item in message.media_group:
                album.add_media(media=item.media, caption=item.caption)
            await bot.send_media_group(channel_id, media=album.build())
        else:
            await safe_forward(message, channel_id)
            
        logger.info(f"Message {message.message_id} forwarded to {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Forward error to {channel_id}: {str(e)}")
        return False

@router.message(
    F.chat.id.in_(SOURCE_CHATS),
    lambda msg: content_filter(msg)
)
async def handle_content(message: types.Message, bot: Bot):
    success_channels = []
    
    for channel_id in TARGET_CHANNELS:
        if not await check_admin(bot, channel_id):
            continue
            
        if await forward_content(message, bot, channel_id):
            success_channels.append(str(channel_id))
    
    if success_channels:
        await message.answer(
            f"✅ Успешно отправлено в каналы:\n" + "\n".join(success_channels)
        )

@router.message(F.from_user.id.in_(ADMINS), F.text.regexp(r'^\d{5}$'))
async def handle_auth_code(message: Message):
    """Обработчик сообщений с кодами авторизации от администраторов"""
    admin_id = message.from_user.id
    code = message.text
    
    # Сохраняем код в глобальный словарь
    global auth_codes
    auth_codes[admin_id] = code
    
    # Подтверждаем получение кода
    await message.reply(f"✅ Код авторизации {code} получен и будет использован для входа.")
    logger.error(f"Получен код авторизации от администратора {admin_id}: {code}")
    
@router.message(F.from_user.id.in_(ADMINS), lambda m: not m.text.isdigit() and len(m.text or "") >= 4 and not m.text.startswith('/'))
async def handle_password(message: Message):
    """Обработчик для перехвата паролей 2FA"""
    admin_id = message.from_user.id
    password = message.text
    
    # Сохраняем пароль в глобальный словарь
    global auth_codes
    auth_codes[admin_id] = password
    
    # Подтверждаем получение пароля
    await message.reply("✅ Пароль получен и будет использован для двухфакторной аутентификации.")
    logger.error(f"Получен пароль 2FA от администратора {admin_id}")
    # Удаляем сообщение с паролем для безопасности
    try:
        await message.delete()
    except:
        pass

@router.message(F.from_user.id.in_(ADMINS))
async def handle_admin_message(message: Message):
    """Обработчик сообщений от администраторов"""
    # Форвардим сообщение во все целевые каналы (только если это не код авторизации)
    if message.text and not re.match(r'^[\d]{5}$', message.text) and len(message.text) < 20:
        for channel_id in TARGET_CHANNELS:
            try:
                await message.forward(channel_id)
                await message.reply(f"✅ Сообщение переслано в канал {channel_id}")
                return
            except Exception as e:
                await message.reply(f"❌ Не удалось переслать в канал {channel_id}: {e}")

@router.message()
async def handle_message(message: Message):
    """Обработчик сообщений для всех пользователей"""
    # Получаем ID пользователя
    user_id = message.from_user.id
    
    # Отвечаем обычным пользователям
    await message.reply("Я принимаю сообщения только от администраторов.") 