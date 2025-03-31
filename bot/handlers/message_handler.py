from aiogram import F, types, Router, Bot
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.utils.media_group import MediaGroupBuilder
from config import SOURCE_CHATS, TARGET_CHANNELS, INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, logger
from tenacity import retry, stop_after_attempt, wait_fixed

router = Router()

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