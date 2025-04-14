from telethon import TelegramClient, events
from config import Config
import asyncio
import os
import time
from logger import logger
from telethon.tl.functions.messages import GetHistoryRequest
import random
from dotenv import load_dotenv
import re
from telethon.errors import FloodWaitError

class Parser:
    def __init__(self):
        self.user_client = None
        self.bot_client = None
        self._sources_cache = None
        self._last_update = 0
        self._auth_code = None
        self._auth_event = asyncio.Event()
        self.last_ids = {}
        self.running = False
        self.code_received = None
        self.user_auth_event = asyncio.Event()
        
        # Создаем директорию для временных файлов
        if not os.path.exists("temp_media"):
            os.makedirs("temp_media")
            logger.info("Создана директория для временных файлов")
        
        # Создаем директорию для сессий
        if not os.path.exists("data"):
            os.makedirs("data")
            logger.info("Создана директория для сессий")
        
        # ИСПРАВЛЯЕМ ИНИЦИАЛИЗАЦИЮ БОТА
        self.bot_client = TelegramClient(
            'data/bot_session', 
            Config.API_ID, 
            Config.API_HASH
        )  # УДАЛЕН СИНХРОННЫЙ .start()

    async def start(self):
        # Проверяем сначала, есть ли уже существующая сессия
        session_file = os.path.join("data", Config.SESSION_NAME + ".session")
        session_exists = os.path.exists(session_file) and os.path.getsize(session_file) > 0
        
        attempts = 0  # Счётчик попыток авторизации
        max_attempts = 2  # Максимум 2 ретрая
        
        while attempts <= max_attempts:
            try:
                # Инициализация клиентов
                self.user_client = TelegramClient(
                    "data/" + Config.SESSION_NAME,
                    Config.API_ID,
                    Config.API_HASH
                )
                
                # Если файл сессии уже существует, пытаемся использовать его напрямую
                if session_exists:
                    logger.info("Найдена существующая сессия, пропускаем авторизацию")
                    try:
                        await self.user_client.connect()
                        if await self.user_client.is_user_authorized():
                            logger.info("Пользователь успешно авторизован из существующей сессии")
                            await self._run_monitoring()
                            return
                    except Exception as e:
                        logger.error(f"Ошибка при использовании существующей сессии: {str(e)}")
                
                # Подключаем пользовательский клиент
                await self.user_client.connect()
                
                # Подключаем клиент бота - правильный порядок: сначала connect, потом start
                await self.bot_client.connect()
                
                # Проверка бота перед его использованием
                if Config.BOT_TOKEN:
                    await self.bot_client.start(bot_token=Config.BOT_TOKEN)
                    logger.info("✅ Бот авторизован успешно")
                else:
                    logger.warning("⚠️ Токен бота не настроен!")
                
                # Проверяем статус авторизации пользователя
                if not await self.user_client.is_user_authorized():
                    logger.info("Пользователь не авторизован. Пытаемся выполнить вход.")
                    await self._handle_authentication()
                else:
                    logger.info("Пользователь уже авторизован.")
                
                logger.info("✅ Авторизация успешна")
                
                await self._run_monitoring()
                return
                
            except Exception as e:
                attempts += 1
                logger.error(f"Попытка {attempts}/{max_attempts} провалена: {str(e)}")
                
                if attempts >= max_attempts:
                    logger.critical("❌ Достигнут лимит попыток. Аварийная остановка.")
                    raise
                
                # Ждём перед повторной попыткой
                await asyncio.sleep(10)

    async def _run_monitoring(self):
        logger.info("Запускаем периодический опрос каналов")
        last_ids = {}  # Храним ID последнего обработанного сообщения для каждого канала
        
        while True:
            sources = self._get_sources()
            logger.info(f"Начинаем опрос {len(sources)} каналов")
            
            # Параллельный опрос каналов
            tasks = []
            for chat in sources:
                tasks.append(self._process_chat(chat, last_ids))
            
            # Выполняем задачи параллельно с ограничением на количество одновременных запросов
            for i in range(0, len(tasks), 5):  # 5 параллельных запросов за раз
                await asyncio.gather(*tasks[i:i+5])
                await asyncio.sleep(random.uniform(0.5, 1.5))  # Задержка между группами
            
            logger.info("Цикл опроса завершен, ждем перед следующим...")
            await asyncio.sleep(30)  # Уменьшил интервал опроса до 30 секунд

    async def _process_chat(self, chat, last_ids):
        try:
            # Получаем последние сообщения
            history = await self.user_client(GetHistoryRequest(
                peer=chat,
                limit=20,
                offset_id=last_ids.get(chat, 0),
                offset_date=None,
                add_offset=0,
                max_id=0,
                min_id=0,
                hash=0
            ))
            
            if history.messages:
                last_ids[chat] = history.messages[0].id  # Обновляем ID последнего сообщения
                logger.info(f"Получено {len(history.messages)} новых сообщений из канала: {chat}")
                for msg in reversed(history.messages):
                    chat_title = chat if isinstance(chat, str) else f"Chat ID: {chat.id}"
                    logger.info(f"===== ОБРАБОТКА СООБЩЕНИЯ {msg.id} =====")
                    
                    # СОБИРАЕМ ВЕСЬ ТЕКСТ ИЗ ВСЕХ БЛЯТЬ ИСТОЧНИКОВ
                    message_text = []
                    
                    # 1. Обычный текст сообщения
                    if hasattr(msg, 'message') and msg.message:
                        message_text.append(msg.message)
                    
                    # 2. Текст из атрибута text (legacy)
                    if hasattr(msg, 'text') and msg.text:
                        message_text.append(msg.text)
                    
                    # 3. Подпись к медиа
                    if hasattr(msg, 'caption') and msg.caption:
                        message_text.append(msg.caption)
                    
                    # 4. Собираем все тексты из медиа объекта
                    if hasattr(msg, 'media') and msg.media:
                        # Логируем тип медиа для отладки
                        media_type = type(msg.media).__name__
                        logger.info(f"Медиа тип: {media_type}")
                        
                        # Подпись к медиа объекту
                        if hasattr(msg.media, 'caption') and msg.media.caption:
                            message_text.append(msg.media.caption)
                        
                        # Документы могут содержать атрибут message
                        if hasattr(msg.media, 'message') and msg.media.message:
                            message_text.append(msg.media.message)
                    
                    # Собираем все тексты в одну строку
                    full_text = " ".join(message_text).strip()
                    
                    # Проверяем сообщение
                    if self._validate_message(full_text):
                        logger.info(f"✅✅✅ Сообщение {msg.id} ПРОШЛО фильтрацию, пересылаем!")
                        await self._forward_message(msg, chat_title)
                    else:
                        logger.info(f"❌❌❌ Сообщение {msg.id} отклонено фильтрами!")
            else:
                logger.debug(f"Нет новых сообщений в канале: {chat}")
            
        except Exception as e:
            logger.error(f"Ошибка при опросе канала {chat}: {str(e)}")
            if "chat is inaccessible" in str(e).lower():
                logger.warning(f"Канал {chat} недоступен. Убедитесь, что аккаунт имеет доступ.")
        
        # Случайная задержка между запросами для избежания ограничений Telegram
        await asyncio.sleep(random.uniform(0.2, 0.5))  # Уменьшил задержку между запросами

    def _get_sources(self):
        current_time = time.time()
        if current_time - self._last_update > 300 or not self._sources_cache:  # 5 минут кеш
            self._sources_cache = self._load_sources()
            self._last_update = current_time
            logger.info(f"Источники обновлены. Загружено {len(self._sources_cache)} каналов/групп")
        return self._sources_cache

    def _load_sources(self):
        try:
            with open(Config.SOURCES_FILE, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.critical(f"Файл источников {Config.SOURCES_FILE} не найден")
            return []

    def _validate_message(self, text):
        """РАДИКАЛЬНО упрощенная проверка сообщений"""
        if not text:
            logger.info("❌ Пустое сообщение, отклоняем")
            return False
        
        # Преобразуем всё в нижний регистр для единообразия
        text = str(text).lower()
        
        # ОБЯЗАТЕЛЬНЫЙ ВОТ ЭТОТ БЛОК - ВЫВОДИМ ТЕКСТ, КОТОРЫЙ ПРОВЕРЯЕМ
        logger.info(f"📝 ТЕКСТ: '{text}'")
        logger.info(f"🔍 KEYWORDS: {Config.KEYWORDS}")
        
        # ПРОСТАЯ проверка ключевых слов - присутствует ли ХОТЯ БЫ ОДНО
        for keyword in Config.KEYWORDS:
            if keyword.lower() in text:
                logger.info(f"✅ НАЙДЕНО ключевое слово: '{keyword}'")
                
                # Проверяем стоп-слова только если нашли ключевое слово
                if Config.STOP_WORDS:
                    for stop_word in Config.STOP_WORDS:
                        if stop_word.lower() in text:
                            logger.info(f"❌ НАЙДЕНО стоп-слово: '{stop_word}'")
                            return False
                
                # Если нет стоп-слов - пропускаем сообщение
                return True
        
        # Ключевые слова не найдены
        logger.info("❌ НЕ найдено ни одного ключевого слова")
        return False
        
    async def _forward_message(self, message, source_chat_title=""):
        """Метод КОПИРУЕТ содержимое сообщения и создает НОВОЕ сообщение в целевом канале"""
        for target in Config.TARGET_CHANNELS:
            try:
                # Получаем текст сообщения
                message_text = ""
                if hasattr(message, 'message') and message.message:
                    message_text = message.message
                elif hasattr(message, 'text') and message.text:
                    message_text = message.text
                
                # Дополняем информацией об источнике
                full_text = f"{message_text}\n\n💬 Источник: {source_chat_title}"
                
                logger.info(f"Создаем новое сообщение для {target}: '{full_text[:100]}...'")
                
                # Если есть медиа, скачиваем его
                if hasattr(message, 'media') and message.media:
                    try:
                        # Определяем тип медиа для лучшей обработки
                        media_type = type(message.media).__name__
                        logger.info(f"Обрабатываем медиа типа {media_type}")
                        
                        # Вместо скачивания файла на диск, сначала скачиваем его в память
                        media_data = await self.user_client.download_media(message, bytes)
                        
                        if not media_data:
                            logger.error(f"Не удалось скачать медиа в память, объект bytes пустой")
                            raise ValueError("Медиа не может быть скачано в память")
                        
                        logger.info(f"Медиа успешно скачано в память, размер: {len(media_data)} байт")
                        
                        # Создаем временный файл и записываем в него содержимое
                        file_extension = ".jpg"  # По умолчанию
                        
                        # Определяем расширение файла по типу медиа
                        if hasattr(message.media, 'document') and hasattr(message.media.document, 'mime_type'):
                            mime_type = message.media.document.mime_type
                            logger.info(f"MIME-тип медиа: {mime_type}")
                            
                            if 'video' in mime_type:
                                file_extension = ".mp4"
                            elif 'audio' in mime_type:
                                file_extension = ".mp3"
                            elif 'image/png' in mime_type:
                                file_extension = ".png"
                            elif 'image/webp' in mime_type:
                                file_extension = ".webp"
                            elif 'image/gif' in mime_type:
                                file_extension = ".gif"
                        
                        # Создаем уникальное имя файла для записи
                        temp_file_name = f"temp_media/media_{message.id}_{int(time.time())}_{random.randint(1000, 9999)}{file_extension}"
                        
                        # Записываем байты в файл
                        with open(temp_file_name, 'wb') as f:
                            f.write(media_data)
                        
                        logger.info(f"Медиа сохранено во временный файл: {temp_file_name}")
                        
                        # Проверяем существование файла
                        if not os.path.exists(temp_file_name):
                            raise FileNotFoundError(f"Не удалось создать файл {temp_file_name}")
                        
                        # Теперь отправляем файл
                        await self.bot_client.send_file(
                            entity=int(target),
                            file=temp_file_name,
                            caption=full_text[:1024],  # Ограничение Telegram на длину caption
                            parse_mode='html'
                        )
                        
                        logger.info(f"✅ Сообщение с медиа отправлено в {target}")
                        
                        # Удаляем временный файл
                        if os.path.exists(temp_file_name):
                            os.remove(temp_file_name)
                            logger.info(f"Временный файл {temp_file_name} удален")
                    
                    except Exception as e:
                        logger.error(f"Ошибка при работе с медиа: {str(e)}")
                        logger.exception(e)  # Добавляем полный стек-трейс для отладки
                        
                        # Отправляем хотя бы текст, если медиа не удалось
                        await self.bot_client.send_message(
                            entity=int(target),
                            message=f"⚠️ ОШИБКА С МЕДИА ⚠️\n\n{full_text}",
                            parse_mode='html'
                        )
                else:
                    # Отправляем текстовое сообщение
                    await self.bot_client.send_message(
                        entity=int(target),
                        message=full_text,
                        parse_mode='html'
                    )
                    logger.info(f"✅ Текстовое сообщение отправлено в {target}")
                
            except Exception as e:
                logger.error(f"Общая ошибка при отправке в {target}: {str(e)}")
                logger.error(f"Тип сообщения: {type(message).__name__}")
                logger.exception(e)  # Добавляем стектрейс для отладки

    async def _handle_authentication(self):
        try:
            # Проверяем, что бот подключен для отправки кода
            if not self.bot_client.is_connected():
                await self.bot_client.connect()
            
            if not Config.BOT_TOKEN:
                logger.error("BOT_TOKEN не указан в конфигурации. Невозможно запросить код.")
                raise ValueError("BOT_TOKEN не указан в конфигурации.")
            
            # Очищаем сессию бота для надежности
            await self.bot_client.disconnect()
            await self.bot_client.connect()
            await self.bot_client.start(bot_token=Config.BOT_TOKEN)
            logger.info("✅ Бот переподключен для авторизации")
            
            # ВАЖНО: сбрасываем состояние авторизации
            self._auth_code = None
            self._auth_event.clear()
            
            # Отправляем запрос кода на телефон
            await self.user_client.send_code_request(Config.PHONE)
            logger.info(f"Код отправлен на номер {Config.PHONE}")
            
            # Настраиваем обработчик для получения кода от администратора
            admin_user_id = int(os.getenv('ADMIN_USER_ID', '0').strip())
            if not admin_user_id:
                logger.error("ADMIN_USER_ID не указан в .env. Невозможно запросить код.")
                raise ValueError("ADMIN_USER_ID не указан в переменных окружения.")
            
            # Настраиваем обработчик входящих сообщений от администратора
            @self.bot_client.on(events.NewMessage(from_users=[admin_user_id]))
            async def handle_admin_message(event):
                message_text = event.message.text.strip()
                logger.info(f"ПОЛУЧЕН КОД ОТ АДМИНИСТРАТОРА: {message_text}")
                self._auth_code = message_text
                self._auth_event.set()  # Сигнализируем, что код получен
            
            # Отправляем несколько запросов кода администратору для надежности
            admin_message = f"""
⚠️ ТРЕБУЕТСЯ КОД АВТОРИЗАЦИИ! ⚠️
            
Пожалуйста, отправьте код из SMS на номер {Config.PHONE}.
Код можно ввести в течение 120 секунд.
            
Просто введите только цифры кода, без дополнительного текста.
"""
            
            for _ in range(3):  # Отправляем 3 запроса с интервалом
                await self.bot_client.send_message(
                    entity=admin_user_id,
                    message=admin_message
                )
                await asyncio.sleep(2)  # Небольшая пауза между сообщениями
            
            logger.info(f"Запрос кода отправлен администратору с ID {admin_user_id}")
            
            # Ожидаем код от администратора с таймаутом
            logger.info("Ожидаем код авторизации от администратора...")
            try:
                # Ждем с таймаутом
                await asyncio.wait_for(self._auth_event.wait(), timeout=120)
            except asyncio.TimeoutError:
                logger.error("⌛ Время ожидания кода истекло (120 секунд)")
                raise ValueError("Тайм-аут при ожидании кода авторизации")
            
            if not self._auth_code:
                logger.error("Код не получен от администратора.")
                raise ValueError("Код авторизации не получен.")
            
            # Проверяем, что код содержит только цифры
            code = re.sub(r'\D', '', self._auth_code)
            logger.info(f"Используем код для авторизации: {code}")
            
            # Авторизуемся с полученным кодом
            await self.user_client.sign_in(
                phone=Config.PHONE,
                code=code,
                password=os.getenv('TG_PASSWORD') or None  # Для 2FA, если включено
            )
            logger.info("✅ Авторизация пользователя успешна")
            
        except Exception as e:
            logger.error(f"КРИТИЧЕСКИЙ СБОЙ АВТОРИЗАЦИИ: {str(e)}")
            logger.exception(e)  # Добавляем полный стектрейс для отладки
            raise

    async def init_client(self):
        """Безопасный метод для инициализации клиентов"""
        try:
            # Подключаем пользовательский клиент, если настроен
            if self.user_client and not self.user_client.is_connected():
                await self.user_client.connect()
                logger.info("Пользовательский клиент подключен успешно")
            
            # Подключаем бота, если настроен токен
            if self.bot_client and not self.bot_client.is_connected():
                await self.bot_client.connect()
                
                if Config.BOT_TOKEN:
                    await self.bot_client.start(bot_token=Config.BOT_TOKEN)
                    logger.info("Бот клиент авторизован успешно")
            
        except FloodWaitError as e:
            logger.error(f"Требуется ожидание: {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            return await self.init_client()  # Рекурсивно пробуем снова после ожидания
        
        except Exception as e:
            logger.error(f"Ошибка при инициализации клиентов: {str(e)}")
            raise
        
        return True

    async def check_connection(self):
        # Исправляем метод для проверки соединения
        if self.bot_client:
            return self.bot_client.is_connected()
        return False

if __name__ == "__main__":
    parser = Parser()
    asyncio.run(parser.start())