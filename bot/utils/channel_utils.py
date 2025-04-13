import os
import logging
from typing import List, Union, Optional
from telethon.tl.types import InputPeerChannel, InputPeerUser, InputPeerChat

logger = logging.getLogger(__name__)

def load_channels_from_file(file_path: str) -> List[str]:
    """Загружает список каналов из текстового файла.
    
    Args:
        file_path: Путь к файлу со списком каналов
        
    Returns:
        Список каналов
    """
    channels = []
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        channels.append(line)
            logger.info(f"Загружено {len(channels)} каналов из файла {file_path}")
        else:
            logger.warning(f"Файл со списком каналов не найден: {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке каналов из файла {file_path}: {e}")
    
    return channels

def get_all_source_channels() -> List[str]:
    """Получает полный список источников из конфигурации и файла sources.txt.
    
    Returns:
        Список идентификаторов каналов
    """
    from bot.config import CONFIG
    
    # Получаем каналы из конфигурации
    source_channels = set(CONFIG['channels']['source'])
    
    # Если включено использование файла с источниками
    if CONFIG.get('use_sources_file', False):
        sources_file = CONFIG.get('sources_file', 'sources.txt')
        
        # Загружаем каналы из файла
        file_channels = load_channels_from_file(sources_file)
        
        # Добавляем новые каналы в список
        for channel in file_channels:
            source_channels.add(channel)
    
    return list(source_channels)

async def resolve_channel_entity(client, channel_id: Union[str, int]) -> Optional[InputPeerChannel]:
    """Разрешает сущность канала по его идентификатору или имени.
    
    Args:
        client: Экземпляр клиента Telethon
        channel_id: Идентификатор или имя канала
        
    Returns:
        Объект InputPeerChannel или None, если канал не найден
    """
    try:
        # Преобразуем URL канала в username при необходимости
        if isinstance(channel_id, str) and channel_id.startswith('https://t.me/'):
            # Извлекаем username из URL
            parts = channel_id.strip('/').split('/')
            channel_id = parts[-1].lstrip('@')
            
            # Обрабатываем приватные ссылки (с +)
            if channel_id.startswith('+'):
                logger.warning(f"Приватная ссылка на канал не поддерживается напрямую: {channel_id}")
                return None
                
        # Получаем entity
        entity = await client.get_entity(channel_id)
        return entity
    except Exception as e:
        logger.error(f"Не удалось получить сущность для канала {channel_id}: {e}")
        return None 