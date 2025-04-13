from telethon import TelegramClient, events
from config import Config
import asyncio
import os
import time
from logger import logger

class Parser:
    def __init__(self):
        self.client = None
        self._sources_cache = None
        self._last_update = 0
        
    async def start(self):
        self.client = TelegramClient(
            Config.SESSION_NAME,
            Config.API_ID,
            Config.API_HASH
        )
        
        try:
            if not await self.client.is_user_authorized():
                await self._handle_authentication()
            
            logger.info("Сессия успешно инициализирована")
            await self._run_monitoring()
            
        except Exception as e:
            logger.error(f"Ошибка инициализации: {str(e)}")
            raise

    async def _run_monitoring(self):
        @self.client.on(events.NewMessage(chats=self._get_sources()))
        async def message_handler(event):
            try:
                if self._validate_message(event.message.text):
                    await self._forward_message(event.message)
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {str(e)}")

        logger.info("Мониторинг активирован")
        await self.client.run_until_disconnected()

    def _get_sources(self):
        current_time = time.time()
        if current_time - self._last_update > 300 or not self._sources_cache:  # 5 минут кеш
            self._sources_cache = self._load_sources()
            self._last_update = current_time
            logger.info("Источники обновлены")
        return self._sources_cache

    def _load_sources(self):
        try:
            with open(Config.SOURCES_FILE, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.critical(f"Файл источников {Config.SOURCES_FILE} не найден")
            return []

    def _validate_message(self, text):
        text = text.lower()
        
        if Config.KEYWORDS and not any(kw in text for kw in Config.KEYWORDS):
            return False
            
        if Config.STOP_WORDS and any(sw in text for sw in Config.STOP_WORDS):
            return False
            
        return True
        
    async def _forward_message(self, message):
        for target in Config.TARGET_CHANNELS:
            try:
                await self.client.send_message(
                    entity=target,
                    message=message
                )
                logger.debug(f"Сообщение отправлено в {target}")
            except Exception as e:
                logger.error(f"Ошибка отправки в {target}: {str(e)}")

    async def _handle_authentication(self):
        await self.client.send_code_request(Config.PHONE)
        
        if os.getenv('TG_CODE'):
            code = os.getenv('TG_CODE')
        else:
            code = input("Введите код из SMS: ")
        
        await self.client.sign_in(
            phone=Config.PHONE,
            code=code,
            password=os.getenv('TG_PASSWORD')  # Для 2FA
        )

if __name__ == "__main__":
    parser = Parser()
    asyncio.run(parser.start()) 