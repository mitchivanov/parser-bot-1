import json
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Инициализация логгера
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

def load_sources_from_file(file_path="sources.txt"):
    """Загружает источники из текстового файла"""
    sources = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith('#'):  # Пропускаем пустые строки и комментарии
                    # Преобразуем ссылки в формат, понятный Telegram
                    if url.startswith('https://t.me/'):
                        # Извлекаем username или invite_link
                        path = url.replace('https://t.me/', '')
                        if path.startswith('+'):  # Частный канал с invite ссылкой
                            sources.append(url)  # Добавляем полную ссылку
                        else:  # Публичный канал
                            sources.append(path)  # Добавляем только username
        
        logger.info(f"Загружено {len(sources)} источников из файла {file_path}")
        return sources
    except Exception as e:
        logger.error(f"Ошибка при загрузке источников из файла {file_path}: {e}")
        return []

def load_config():
    # Поиск config.json в разных местах
    possible_paths = [
        Path("config.json"),
        Path("bot/config.json"),
        Path(os.path.dirname(os.path.abspath(__file__)) + "/config.json")
    ]
    
    config_path = None
    for path in possible_paths:
        if path.exists():
            config_path = path
            break
            
    if not config_path:
        logger.critical("Отсутствует config.json! Проверьте пути: %s", possible_paths)
        raise FileNotFoundError("Не найден файл конфигурации")
    
    logger.info(f"Загружена конфигурация из {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Дополняем конфиг источниками из файла, если опция включена
    if config.get('use_sources_file', False):
        sources_file = config.get('sources_file', 'sources.txt')
        file_sources = load_sources_from_file(sources_file)
        
        # Объединяем источники из файла с источниками из конфига
        if file_sources:
            if 'channels' not in config:
                config['channels'] = {}
            
            if 'source' not in config['channels']:
                config['channels']['source'] = []
                
            # Добавляем новые источники, избегая дублирования
            for source in file_sources:
                if source not in config['channels']['source']:
                    config['channels']['source'].append(source)
                    
            logger.info(f"Итоговое количество источников: {len(config['channels']['source'])}")
    
    return config

CONFIG = load_config()

# Telegram API
API_ID = CONFIG['telegram']['api_id']
API_HASH = CONFIG['telegram']['api_hash']
BOT_TOKEN = CONFIG['telegram']['bot_token']

# Channels configuration
SOURCE_CHATS = CONFIG['channels']['source']
TARGET_CHANNELS = CONFIG['channels']['target']

# Filters
INCLUDE_KEYWORDS = CONFIG['filters']['include']
EXCLUDE_KEYWORDS = CONFIG['filters']['exclude']

# Settings
ADMINS = CONFIG['settings']['admins']
RATE_LIMIT = CONFIG['settings']['rate_limit']
PARSE_INTERVAL = CONFIG['settings']['parse_interval']

# Инициализация объектов бота и диспетчера
def setup_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    return bot, dp 