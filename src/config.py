import os
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class Config:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PHONE = os.getenv("PHONE")
    SESSION_NAME = os.getenv("SESSION_NAME")
    SOURCES_FILE = os.getenv("SOURCES_FILE")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    @staticmethod
    def _parse_channels(value):
        """Парсит ID каналов из строки в список целых чисел"""
        if not value:
            return []
        return [int(id.strip()) for id in value.split(',') if id.strip()]
    
    @staticmethod
    def _parse_keywords(value):
        """Парсит ключевые слова из строки в список строк"""
        if not value:
            return []
        return [word.strip().lower() for word in value.split(',') if word.strip()]
    
    # ИСПРАВЛЕНО! Используем правильные функции
    KEYWORDS = _parse_keywords.__get__(None, staticmethod)(os.getenv('KEYWORDS', ''))
    STOP_WORDS = _parse_keywords.__get__(None, staticmethod)(os.getenv('STOP_WORDS', ''))
    TARGET_CHANNELS = _parse_channels.__get__(None, staticmethod)(os.getenv('TARGET_CHANNELS', ''))
    
    @classmethod
    def log_config(cls):
        logger.info(f"Загружены ключевые слова: {cls.KEYWORDS}")
        logger.info(f"Загружены стоп-слова: {cls.STOP_WORDS}")
        logger.info(f"Целевые каналы: {cls.TARGET_CHANNELS}")

# После загрузки конфигурации  
Config.log_config() 