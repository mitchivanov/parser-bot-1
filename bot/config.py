import json
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Импортируем новый модуль для работы с каналами
try:
    from bot.utils.channel_utils import load_channels_from_file
except ImportError:
    # Для локального запуска
    try:
        from utils.channel_utils import load_channels_from_file
    except ImportError:
        # Если модуль вообще не найден
        def load_channels_from_file(file_path):
            """Заглушка для загрузки каналов из файла"""
            channels = []
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            channels.append(line)
            return channels

# Загрузка переменных окружения
load_dotenv("config.env")

# Инициализация логгера
logger = logging.getLogger(__name__)

# Настройка логирования
log_dir = os.getenv('LOG_DIR', 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'parser.log')

# Настройка обработчиков логирования
handlers = [
    logging.FileHandler(log_file, encoding='utf-8'),  # Вывод в файл
    logging.StreamHandler()  # Вывод в консоль
]

# Установка уровня логирования для лучшей диагностики
log_level = logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=handlers
)

# Отключаем лишние логи от библиотек
logging.getLogger('telethon').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)
logging.getLogger('aiogram').setLevel(logging.ERROR)
# Отключаем вывод импортов Python
logging.getLogger('importlib').setLevel(logging.CRITICAL)
logging.getLogger('asyncio').setLevel(logging.CRITICAL)

def load_sources_from_file(file_path="sources.txt"):
    """Загружает источники из текстового файла"""
    # Используем новую функцию из модуля channel_utils
    return load_channels_from_file(file_path)

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
    
    # Переопределение параметров из переменных окружения
    if os.getenv("TELEGRAM_API_ID"):
        config["telegram"]["api_id"] = int(os.getenv("TELEGRAM_API_ID"))
    
    if os.getenv("TELEGRAM_API_HASH"):
        config["telegram"]["api_hash"] = os.getenv("TELEGRAM_API_HASH")
    
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        config["telegram"]["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if os.getenv("TELEGRAM_PHONE"):
        config["telegram"]["phone"] = os.getenv("TELEGRAM_PHONE")
        
    if os.getenv("PARSE_INTERVAL"):
        config["settings"]["parse_interval"] = int(os.getenv("PARSE_INTERVAL"))
    
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
    
    # Настройка сессий для работы в Docker
    session_dir = os.getenv("SESSION_DIR", "sessions")
    os.makedirs(session_dir, exist_ok=True)
    config["session_dir"] = session_dir
    
    # Путь к сессии Telethon в Docker
    config["session_path"] = os.path.join(session_dir, config["telegram"]["phone"])
    
    return config

# Загружаем конфигурацию
CONFIG = load_config()

# Константы для удобства доступа
SOURCE_CHATS = CONFIG['channels']['source']
TARGET_CHANNELS = CONFIG['channels']['target']
INCLUDE_KEYWORDS = CONFIG['filters']['include']
EXCLUDE_KEYWORDS = CONFIG['filters']['exclude']
PARSE_INTERVAL = CONFIG['settings']['parse_interval']

# Telegram API
API_ID = CONFIG['telegram']['api_id']
API_HASH = CONFIG['telegram']['api_hash']
BOT_TOKEN = CONFIG['telegram']['bot_token']

# Settings
ADMINS = CONFIG['settings']['admins']
RATE_LIMIT = CONFIG['settings']['rate_limit']

# Инициализация объектов бота и диспетчера
def setup_bot():
    """Создает и настраивает объекты бота и диспетчера"""
    # Создаем бота с параметрами
    bot_settings = DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
    
    # Инициализируем бота
    bot = Bot(token=CONFIG['telegram']['bot_token'], default=bot_settings)
    
    # Инициализируем диспетчер
    dp = Dispatcher()
    
    logger.info("Инициализирован бот и диспетчер")
    return bot, dp 