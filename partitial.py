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
        try:
            return await retry_with_backoff(
                lambda: self.client.download_media(media, file=path),
                max_attempts=self.max_retries,
                base_delay=self.base_retry_delay,
                max_delay=self.max_retry_delay,
                log_prefix="Скачивание медиа"
            )
        except RetryError as e:
            logger.error(f"Не удалось скачать медиа после {e.attempts_made} попыток: {e.original_error}")
            
            # Записываем ошибку в монитор
            if self.monitor:
                self.monitor.record_error(f"Ошибка при скачивании медиа: {e.original_error}")
                
                # Если клиент отключился из-за ошибки, переподключаемся
                if not self.client.is_connected():
                    await self.connect_with_retry()
        
            raise

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
        # Обеспечиваем корректное завершение работы
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(self._cleanup_resources())
        else:
            try:
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except:
                pass 

    async def _fetch_channel_messages(self, entity, last_message_id):
        """Получает новые сообщения из канала с учетом последнего обработанного ID"""
        try:
            # Проверяем, нет ли активной блокировки FloodWait
            if await self.check_flood_wait():
                logger.warning(f"Пропуск получения сообщений из канала {entity.id} из-за активной блокировки FloodWait")
                return []
                
            # Получаем историю сообщений с учетом ограничений скорости
            history = await self.rate_limited_request(
                self.client.get_messages,
                entity=entity,
                limit=30,  # Уменьшаем лимит для более эффективной обработки
                min_id=last_message_id  # Получаем только сообщения новее last_message_id
            )
            
            if not history:
                return []
                
            # Фильтруем сообщения, которые старше времени запуска
            return [msg for msg in history if msg.date >= self.start_time]
            
        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(f"FloodWait при получении сообщений канала {entity.id}: {wait_seconds} сек")
            self.set_flood_wait(wait_seconds)
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений из канала {entity.id}: {e}")
            logger.exception(e)
            return []
            
    async def _process_new_messages(self, channel_id, messages):
        """Обрабатывает новые сообщения из канала"""
        if not messages:
            return 0
            
        # Сортируем сообщения по ID (от старых к новым)
        messages.sort(key=lambda msg: msg.id)
        
        # Словарь для группировки сообщений в альбомы
        albums = defaultdict(list)
        processed_count = 0
        
        # Проходим по всем сообщениям
        for message in messages:
            try:
                # Фильтруем сообщения по ключевым словам
                if not self.filter_message(message.message or ""):
                    continue
                    
                # Обновляем последний обработанный ID
                self.storage.set_last_message_id(channel_id, message.id)
                
                # Группируем в альбомы, если есть grouped_id
                if hasattr(message, 'grouped_id') and message.grouped_id:
                    if not self.storage.is_album_processed(message.grouped_id):
                        albums[message.grouped_id].append(message)
                else:
                    # Одиночное сообщение
                    await self.process_single_message(channel_id, message)
                    
                # Инкрементируем счетчик обработанных сообщений
                self.storage.increment_messages_count()
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения {message.id} из канала {channel_id}: {e}")
                logger.exception(e)
        
        # Обрабатываем альбомы после обработки всех сообщений
        for grouped_id, album_messages in albums.items():
            try:
                if self.storage.is_album_processed(grouped_id):
                    continue
                    
                await self.process_album(channel_id, album_messages)
                self.storage.mark_album_processed(grouped_id)
                
            except Exception as e:
                logger.error(f"Ошибка при обработке альбома {grouped_id} из канала {channel_id}: {e}")
                logger.exception(e)
        
        return processed_count
        
    def _process_monitoring_timeout(self):
        """Обработчик таймаута монитора активности"""
        logger.critical("Обнаружен таймаут активности парсера (180 секунд без обновления)!")
        
        # Записываем ошибку в основной монитор
        if self.monitor:
            self.monitor.record_error(
                "Критическая ошибка: обнаружен таймаут активности парсера (180 секунд)",
                is_critical=True
            )

    async def check_messages(self):
        """Проверяет новые сообщения во всех каналах"""
        try:
            logger.info("Проверка новых сообщений в каналах")
            
            # Получаем список каналов для проверки на основе их активности
            channels_to_check = self._get_channels_to_check()
            
            if not channels_to_check:
                logger.info("Нет каналов для проверки в текущей итерации")
                return
                
            logger.info(f"Запланировано проверить {len(channels_to_check)} каналов")
            
            # Ограничиваем количество каналов для проверки за один раз
            max_channels_per_batch = self.config.get('parser', {}).get('max_channels_per_batch', 20)  # Увеличиваем до 20
            
            # Если каналов слишком много, обрабатываем их частями
            if len(channels_to_check) > max_channels_per_batch:
                logger.info(f"Слишком много каналов ({len(channels_to_check)}), ограничиваем до {max_channels_per_batch}")
                # Перемешиваем список каналов для равномерной проверки
                random.shuffle(channels_to_check)
                channels_to_check = channels_to_check[:max_channels_per_batch]
            
            # Создаем семафор для ограничения числа одновременных запросов
            semaphore = asyncio.Semaphore(min(self.max_concurrent_requests, 10))  # Не более 10 одновременных запросов
            
            # Оборачиваем каждый вызов в корутину с семафором
            async def check_channel_with_semaphore(channel):
                async with semaphore:
                    try:
                        # Добавляем небольшую случайную задержку для распределения нагрузки
                        await asyncio.sleep(random.uniform(0.1, 0.3))  # Уменьшаем задержку
                        return await self._check_channel_messages(channel)
                    except FloodWaitError as e:
                        # Обрабатываем FloodWait ошибки
                        wait_seconds = e.seconds
                        self.set_flood_wait(wait_seconds)
                        logger.warning(f"FloodWait при проверке канала {channel}: {wait_seconds} сек")
                        return False
                    except Exception as e:
                        logger.error(f"Ошибка при проверке канала {channel}: {e}")
                        logger.exception(e)
                        return False
            
            # Запускаем параллельную обработку каналов
            start_time = time.time()
            tasks = [check_channel_with_semaphore(channel) for channel in channels_to_check]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Проверяем результаты
            success_count = sum(1 for r in results if r is True)
            error_count = sum(1 for r in results if isinstance(r, Exception) or r is False)
            
            # Сохраняем состояние
            self.storage.state["processed_albums"] = list(self.processed_album_ids)
            self.storage.save_state()
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            logger.info(f"Проверка всех каналов завершена. Успешно: {success_count}, с ошибками: {error_count}. Время: {elapsed_time:.2f} сек.")
            
        except Exception as e:
            logger.error(f"Ошибка при проверке сообщений: {e}")
            logger.exception(e)
