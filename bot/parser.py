from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from config import CONFIG, logger
import asyncio
import os
import tempfile
from collections import defaultdict
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio, FSInputFile, BufferedInputFile
from datetime import datetime, timezone, timedelta
import re
import random
import socket
import aiohttp

class Parser:
    def __init__(self):
        # Основные параметры
        self.api_id = CONFIG['telegram']['api_id']
        self.api_hash = CONFIG['telegram']['api_hash']
        self.phone = CONFIG['telegram']['phone']
        self.client = None
        self.bot = None
        self.last_message_ids = {}
        self.temp_dir = tempfile.mkdtemp(prefix="telethon_media_")
        self.processed_album_ids = set()
        self.start_time = datetime.now(timezone.utc)
        
        # Кэширование информации о каналах
        self.channel_cache = {}  # username -> is_channel
        
        # Отслеживание активности каналов
        self.channel_activity = {}  # channel_id -> {last_post_date, check_interval}
        self.default_interval = CONFIG['settings']['parse_interval']
        self.low_activity_interval = self.default_interval * 6  # в 6 раз реже проверяем неактивные каналы
        
        # Параметры для экспоненциального backoff
        self.max_retries = 10
        self.base_retry_delay = 5  # начальная задержка 5 секунд
        self.max_retry_delay = 300  # максимальная задержка 5 минут
        self.connection_attempts = 0
        
        logger.info(f"Парсер инициализирован, время запуска: {self.start_time}")
        
    def set_bot(self, bot):
        self.bot = bot
        logger.info("Привязан экземпляр бота к парсеру")
        
    async def initialize_channel_activity(self):
        """Инициализирует отслеживание активности каналов"""
        for channel_id in CONFIG['channels']['source']:
            try:
                # Получаем последнее сообщение канала
                history = await self.client(GetHistoryRequest(
                    peer=channel_id,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=1,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))
                
                if history.messages:
                    last_message = history.messages[0]
                    # Сохраняем дату последнего сообщения и устанавливаем интервал проверки
                    last_post_date = last_message.date
                    
                    # Определяем интервал проверки на основе активности
                    now = datetime.now(timezone.utc)
                    days_since_last_post = (now - last_post_date).days
                    
                    if days_since_last_post > 3:
                        # Неактивный канал - проверяем реже
                        check_interval = self.low_activity_interval
                        logger.info(f"Канал {channel_id} неактивен {days_since_last_post} дней, интервал: {check_interval} сек")
                    else:
                        # Активный канал - проверяем чаще
                        check_interval = self.default_interval
                        logger.info(f"Канал {channel_id} активен, последний пост: {last_post_date}, интервал: {check_interval} сек")
                    
                    self.channel_activity[channel_id] = {
                        'last_post_date': last_post_date,
                        'check_interval': check_interval,
                        'next_check': now
                    }
                else:
                    # Если нет сообщений, устанавливаем долгий интервал
                    self.channel_activity[channel_id] = {
                        'last_post_date': datetime.now(timezone.utc) - timedelta(days=10),
                        'check_interval': self.low_activity_interval,
                        'next_check': datetime.now(timezone.utc)
                    }
                    logger.info(f"Канал {channel_id} пуст, установлен долгий интервал проверки")
                    
                # Небольшая задержка для избежания флуда
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ошибка при инициализации активности канала {channel_id}: {e}")
                # Устанавливаем значения по умолчанию
                self.channel_activity[channel_id] = {
                    'last_post_date': datetime.now(timezone.utc),
                    'check_interval': self.default_interval,
                    'next_check': datetime.now(timezone.utc)
                }
    
    async def is_channel(self, username):
        """Проверяет, является ли username каналом с кэшированием результата"""
        if username in self.channel_cache:
            return self.channel_cache[username]
            
        try:
            entity = await self.client.get_entity(username)
            from telethon.tl.types import Channel
            result = isinstance(entity, Channel)
            self.channel_cache[username] = result
            return result
        except Exception as e:
            logger.warning(f"Ошибка при проверке {username}: {e}")
            return False  # Если не удалось проверить, предполагаем, что это не канал
    
    async def filter_telegram_links_precise(self, text):
        """Точная фильтрация ссылок на каналы с проверкой через API"""
        if not text:
            return text
            
        # Удаляем прямые ссылки на каналы и приглашения
        text = re.sub(
            r'https?://(?:t(?:elegram)?\.me|telegram\.dog)/(?:joinchat/|\+)?[a-zA-Z0-9_\-]+',
            '[ссылка удалена]',
            text
        )
        
        # Находим все @упоминания
        mentions = re.findall(r'@([a-zA-Z0-9_]+)', text)
        
        # Проверяем каждое упоминание через API
        for mention in mentions:
            if await self.is_channel(mention):
                text = text.replace(f'@{mention}', '[канал удален]')
        
        return text
    
    async def connect_with_retry(self):
        """Подключение к Telegram API с автоматическими повторными попытками"""
        self.connection_attempts = 0
        
        while self.connection_attempts < self.max_retries:
            try:
                # Создаем клиент с номером телефона
                session_name = self.phone
                self.client = TelegramClient(session_name, self.api_id, self.api_hash)
                
                # Попытка подключения
                logger.info(f"Попытка подключения к Telegram API ({self.connection_attempts + 1}/{self.max_retries})")
                await self.client.start(phone=self.phone)
                
                if await self.client.is_user_authorized():
                    logger.info("Telethon успешно авторизован")
                    self.connection_attempts = 0  # Сбрасываем счетчик при успехе
                    return True
                else:
                    logger.error("Не удалось авторизоваться. Проверьте телефон и код подтверждения")
                    return False
                    
            except (socket.timeout, socket.error, ConnectionError, aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
                self.connection_attempts += 1
                
                # Вычисляем задержку с экспоненциальным увеличением и случайным jitter
                delay = min(
                    self.base_retry_delay * (2 ** (self.connection_attempts - 1)) + random.uniform(0, 1),
                    self.max_retry_delay
                )
                
                logger.warning(f"Ошибка подключения: {e}. Повторная попытка через {delay:.1f} сек "
                              f"(попытка {self.connection_attempts}/{self.max_retries})")
                
                # Если клиент был создан, пытаемся корректно отключиться
                if self.client:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                
                if self.connection_attempts >= self.max_retries:
                    logger.error(f"Достигнут лимит попыток подключения ({self.max_retries})")
                    return False
                
                # Ждем перед следующей попыткой
                await asyncio.sleep(delay)
            
            except Exception as e:
                logger.error(f"Неожиданная ошибка при подключении: {e}")
                return False
        
        return False
    
    async def api_request_with_retry(self, request_func, *args, **kwargs):
        """Выполняет API запрос с автоматическими повторными попытками при ошибках сети"""
        retries = 0
        
        while retries < self.max_retries:
            try:
                # Выполняем запрос
                return await request_func(*args, **kwargs)
                
            except (socket.timeout, socket.error, ConnectionError, aiohttp.ClientError, 
                    OSError, asyncio.TimeoutError, asyncio.exceptions.TimeoutError) as e:
                retries += 1
                
                # Вычисляем задержку с экспоненциальным увеличением
                delay = min(
                    self.base_retry_delay * (2 ** (retries - 1)) + random.uniform(0, 1),
                    self.max_retry_delay
                )
                
                logger.warning(f"Ошибка сети при выполнении запроса: {e}. "
                              f"Повторная попытка через {delay:.1f} сек (попытка {retries}/{self.max_retries})")
                
                if retries >= self.max_retries:
                    logger.error(f"Достигнут лимит попыток запроса ({self.max_retries})")
                    raise
                
                # Ждем перед следующей попыткой
                await asyncio.sleep(delay)
                
                # Если клиент отключился из-за ошибки, переподключаемся
                if not self.client.is_connected():
                    logger.info("Клиент отключен, выполняем переподключение...")
                    if not await self.connect_with_retry():
                        logger.error("Не удалось переподключиться")
                        raise
            
            except Exception as e:
                # Другие ошибки пробрасываем дальше
                logger.error(f"Неожиданная ошибка при выполнении запроса: {e}")
                raise
        
        raise Exception(f"Не удалось выполнить запрос после {self.max_retries} попыток")
    
    async def parse_messages(self):
        try:
            # Подключаемся с системой повторных попыток
            if not await self.connect_with_retry():
                logger.error("Не удалось подключиться к Telegram API, парсинг невозможен")
                return
            
            # Получаем диалоги и инициализируем каналы
            logger.info("Получение диалогов для обнаружения каналов...")
            
            try:
                await self.api_request_with_retry(self.client.get_dialogs)
                await self.initialize_channel_activity()
                await self.initialize_last_messages()
            except Exception as e:
                logger.error(f"Ошибка при инициализации: {e}")
                return
            
            # Основной цикл парсинга
            while True:
                if not self.bot:
                    logger.warning("Бот не установлен в парсере, пропускаем итерацию")
                    await asyncio.sleep(10)
                    continue
                
                # Проверка подключения к Telegram
                if not self.client.is_connected():
                    logger.warning("Обнаружен разрыв соединения, переподключение...")
                    if not await self.connect_with_retry():
                        logger.error("Не удалось переподключиться, ожидание...")
                        await asyncio.sleep(60)  # Ждем минуту перед следующей попыткой
                        continue
                
                now = datetime.now(timezone.utc)
                channels_to_check = []
                
                # Выбираем каналы для проверки в текущей итерации
                for channel_id, activity in self.channel_activity.items():
                    if now >= activity['next_check']:
                        channels_to_check.append(channel_id)
                
                logger.info(f"Проверка {len(channels_to_check)} из {len(self.channel_activity)} каналов")
                
                # Проверяем выбранные каналы
                for channel_id in channels_to_check:
                    try:
                        # Задержка для избежания flood wait
                        await asyncio.sleep(0.5)
                        
                        # Получаем историю сообщений с автоматическими повторными попытками
                        history = await self.api_request_with_retry(
                            self.client,
                            GetHistoryRequest(
                                peer=channel_id,
                                offset_id=0,
                                offset_date=None,
                                add_offset=0,
                                limit=20,
                                max_id=0,
                                min_id=0,
                                hash=0
                            )
                        )
                        
                        # Обновляем дату активности канала
                        if history.messages:
                            last_message_date = history.messages[0].date
                            days_since_last_post = (now - last_message_date).days
                            
                            # Адаптивно регулируем интервал проверки
                            if days_since_last_post > 3:
                                new_interval = self.low_activity_interval
                            else:
                                new_interval = self.default_interval
                                
                            # Обновляем информацию о канале
                            self.channel_activity[channel_id] = {
                                'last_post_date': last_message_date,
                                'check_interval': new_interval,
                                'next_check': now + timedelta(seconds=new_interval)
                            }
                            
                            # Словарь для группировки сообщений в альбомы
                            albums = defaultdict(list)
                            
                            # Обрабатываем сообщения канала
                            for message in history.messages:
                                # Пропускаем сообщения старше времени запуска
                                if message.date < self.start_time:
                                    continue
                                    
                                # Пропускаем уже обработанные
                                if channel_id in self.last_message_ids and message.id <= self.last_message_ids[channel_id]:
                                    continue
                                    
                                # Обновляем последний обработанный ID
                                if channel_id not in self.last_message_ids or message.id > self.last_message_ids[channel_id]:
                                    self.last_message_ids[channel_id] = message.id
                                
                                # Фильтруем сообщения по ключевым словам
                                if not self.filter_message(message.message or ""):
                                    continue
                                    
                                # Группируем в альбомы
                                if hasattr(message, 'grouped_id') and message.grouped_id:
                                    albums[message.grouped_id].append(message)
                                else:
                                    # Одиночное сообщение
                                    await self.process_single_message(channel_id, message)
                            
                            # Обрабатываем альбомы
                            for grouped_id, messages in albums.items():
                                if grouped_id in self.processed_album_ids:
                                    continue
                                self.processed_album_ids.add(grouped_id)
                                await self.process_album(channel_id, messages)
                        else:
                            # Если канал пуст, увеличиваем интервал проверки
                            self.channel_activity[channel_id] = {
                                'last_post_date': now - timedelta(days=10),
                                'check_interval': self.low_activity_interval,
                                'next_check': now + timedelta(seconds=self.low_activity_interval)
                            }
                            
                    except Exception as e:
                        logger.error(f"Ошибка при парсинге канала {channel_id}: {e}")
                        # Даже при ошибке обновляем время следующей проверки
                        if channel_id in self.channel_activity:
                            self.channel_activity[channel_id]['next_check'] = now + timedelta(seconds=self.default_interval)
                
                # Интервал между циклами проверки
                await asyncio.sleep(10)
                
        except asyncio.CancelledError:
            logger.info("Задача парсера отменена")
            if self.client and self.client.is_connected():
                await self.client.disconnect()
        except Exception as e:
            logger.error(f"Критическая ошибка в парсере: {e}")
            if self.client and self.client.is_connected():
                await self.client.disconnect()

    async def initialize_last_messages(self):
        """Инициализация: запоминаем ID последних сообщений для всех каналов"""
        logger.info("Инициализация: получение ID последних сообщений")
        for channel_id in CONFIG['channels']['source']:
            try:
                history = await self.client(GetHistoryRequest(
                    peer=channel_id,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=1,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))
                
                if history.messages:
                    last_message = history.messages[0]
                    self.last_message_ids[channel_id] = last_message.id
                    logger.info(f"Канал {channel_id}: последнее сообщение ID = {last_message.id}, дата = {last_message.date}")
            except Exception as e:
                logger.error(f"Ошибка при инициализации канала {channel_id}: {e}")

    def filter_message(self, text):
        if not text:
            return False
            
        text = text.lower()
        
        # Фильтрация по ключевым словам
        if not CONFIG['filters']['include']:
            has_include = True
        else:
            has_include = any(kw.lower() in text for kw in CONFIG['filters']['include'])
            
        has_exclude = any(kw.lower() in text for kw in CONFIG['filters']['exclude'])
        
        return has_include and not has_exclude

    async def download_media_with_retry(self, media, path):
        """Скачивает медиа с повторными попытками при ошибках сети"""
        retries = 0
        
        while retries < self.max_retries:
            try:
                return await self.client.download_media(media, file=path)
            except (socket.timeout, ConnectionError, OSError, asyncio.TimeoutError) as e:
                retries += 1
                
                delay = min(
                    self.base_retry_delay * (2 ** (retries - 1)) + random.uniform(0, 1),
                    self.max_retry_delay
                )
                
                logger.warning(f"Ошибка при скачивании медиа: {e}. "
                              f"Повторная попытка через {delay:.1f} сек (попытка {retries}/{self.max_retries})")
                
                if retries >= self.max_retries:
                    logger.error(f"Не удалось скачать медиа после {self.max_retries} попыток")
                    raise
                
                await asyncio.sleep(delay)
                
                # Если клиент отключился из-за ошибки, переподключаемся
                if not self.client.is_connected():
                    if not await self.connect_with_retry():
                        raise ConnectionError("Не удалось переподключиться для скачивания медиа")
        
        raise Exception(f"Не удалось скачать медиа после {self.max_retries} попыток")

    async def process_album(self, source_id, messages):
        """Обрабатывает альбом сообщений с фильтрацией каналов"""
        if not self.bot or not messages:
            return
            
        for channel_id in CONFIG['channels']['target']:
            try:
                media_group = []
                media_files = []
                
                # Берем подпись из первого сообщения и фильтруем ссылки
                caption = messages[0].message if messages and hasattr(messages[0], 'message') else ""
                filtered_caption = await self.filter_telegram_links_precise(caption)
                
                for message in messages:
                    if not hasattr(message, 'media') or not message.media:
                        continue
                        
                    # Скачиваем медиа с поддержкой переподключений
                    try:
                        media_path = await self.download_media_with_retry(
                            message.media,
                            os.path.join(self.temp_dir, "")
                        )
                        media_files.append(media_path)
                        
                        # Определяем тип медиа
                        if media_path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            media = InputMediaPhoto(
                                media=FSInputFile(media_path),
                                caption=filtered_caption if len(media_group) == 0 else None
                            )
                            media_group.append(media)
                            
                        elif media_path.endswith(('.mp4', '.avi', '.mov', '.mkv')):
                            media = InputMediaVideo(
                                media=FSInputFile(media_path),
                                caption=filtered_caption if len(media_group) == 0 else None
                            )
                            media_group.append(media)
                            
                        elif media_path.endswith(('.mp3', '.ogg', '.m4a', '.wav')):
                            media = InputMediaAudio(
                                media=FSInputFile(media_path),
                                caption=filtered_caption if len(media_group) == 0 else None
                            )
                            media_group.append(media)
                            
                        else:
                            media = InputMediaDocument(
                                media=FSInputFile(media_path),
                                caption=filtered_caption if len(media_group) == 0 else None
                            )
                            media_group.append(media)
                        
                    except Exception as e:
                        logger.error(f"Не удалось скачать медиа для альбома: {e}")
                        continue
                
                # Отправляем группу, если есть медиа
                if media_group:
                    await self.bot.send_media_group(
                        chat_id=channel_id,
                        media=media_group
                    )
                    logger.info(f"Альбом с {len(media_group)} медиа из {source_id} отправлен в {channel_id}")
                
                # Удаляем временные файлы
                for file_path in media_files:
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.warning(f"Не удалось удалить файл {file_path}: {e}")
                        
            except Exception as e:
                logger.error(f"Ошибка отправки альбома в {channel_id}: {e}")

    async def process_single_message(self, source_id, message):
        """Обрабатывает одиночное сообщение с фильтрацией каналов"""
        if not self.bot:
            logger.error("Не установлен экземпляр бота для отправки сообщений")
            return
            
        for channel_id in CONFIG['channels']['target']:
            try:
                # Получаем и фильтруем текст сообщения
                caption = message.message or ""
                filtered_caption = await self.filter_telegram_links_precise(caption)
                
                # Обрабатываем сообщение в зависимости от типа медиа
                if hasattr(message, 'media') and message.media:
                    try:
                        # Скачиваем медиа с поддержкой переподключений
                        media_path = await self.download_media_with_retry(
                            message.media, 
                            os.path.join(self.temp_dir, "")
                        )
                        
                        # Определяем тип медиа и отправляем с отфильтрованным текстом
                        if media_path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            # Фото
                            await self.bot.send_photo(
                                chat_id=channel_id,
                                photo=FSInputFile(media_path),
                                caption=filtered_caption
                            )
                            
                        elif media_path.endswith(('.mp4', '.avi', '.mov', '.mkv')):
                            # Видео
                            await self.bot.send_video(
                                chat_id=channel_id,
                                video=FSInputFile(media_path),
                                caption=filtered_caption
                            )
                            
                        elif media_path.endswith(('.mp3', '.ogg', '.m4a', '.wav')):
                            # Аудио
                            await self.bot.send_audio(
                                chat_id=channel_id,
                                audio=FSInputFile(media_path),
                                caption=filtered_caption
                            )
                            
                        elif media_path.endswith('.gif'):
                            # Анимация/GIF
                            await self.bot.send_animation(
                                chat_id=channel_id,
                                animation=FSInputFile(media_path),
                                caption=filtered_caption
                            )
                            
                        elif media_path.endswith(('.tgs')):
                            # Стикер
                            await self.bot.send_sticker(
                                chat_id=channel_id,
                                sticker=FSInputFile(media_path)
                            )
                            # Если есть подпись, отправим ее отдельно
                            if filtered_caption:
                                await self.bot.send_message(
                                    chat_id=channel_id,
                                    text=filtered_caption
                                )
                                
                        else:
                            # Документ (любой другой тип файла)
                            await self.bot.send_document(
                                chat_id=channel_id,
                                document=FSInputFile(media_path),
                                caption=filtered_caption
                            )
                        
                        # Удаляем временный файл
                        try:
                            os.remove(media_path)
                        except:
                            pass
                            
                    except Exception as e:
                        logger.error(f"Не удалось скачать медиа для сообщения: {e}")
                        # Отправляем хотя бы текст, если не удалось скачать медиа
                        if filtered_caption:
                            await self.bot.send_message(
                                chat_id=channel_id,
                                text=f"Не удалось скачать медиа: {e}\n\n{filtered_caption}",
                                parse_mode='HTML'
                            )
                        continue
                            
                elif hasattr(message, 'poll'):
                    # Опрос
                    from aiogram.types import PollType
                    
                    await self.bot.send_poll(
                        chat_id=channel_id,
                        question=message.poll.question,
                        options=[answer.text for answer in message.poll.answers],
                        is_anonymous=message.poll.public_voters,
                        type=PollType.QUIZ if message.poll.quiz else PollType.REGULAR,
                        allows_multiple_answers=message.poll.multiple_choice
                    )
                    
                elif hasattr(message, 'message') and message.message:
                    # Просто текст с отфильтрованными ссылками
                    await self.bot.send_message(
                        chat_id=channel_id,
                        text=filtered_caption,
                        parse_mode='HTML'
                    )
                    
                else:
                    # Если тип сообщения не определен
                    logger.warning(f"Неизвестный тип сообщения: {type(message)}")
                    
                logger.info(f"Сообщение из {source_id} скопировано в {channel_id}")
            except Exception as e:
                logger.error(f"Ошибка копирования в {channel_id}: {e}")
    
    def __del__(self):
        """Очистка при уничтожении объекта"""
        # Удаляем временную директорию при завершении
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass 