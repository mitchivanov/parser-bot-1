import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Any, Optional

logger = logging.getLogger(__name__)

class ParserStateStorage:
    """Хранилище состояния парсера с поддержкой сохранения в файл"""
    
    def __init__(self, storage_file="parser_state.json"):
        """
        Инициализирует хранилище состояния
        
        Args:
            storage_file: Путь к файлу для сохранения состояния
        """
        self.storage_file = storage_file
        self.state = {
            "last_message_ids": {},      # channel_id -> last_processed_id
            "processed_albums": set(),   # set of grouped_ids
            "channel_activity": {},      # channel_id -> activity_info
            "last_save": None,           # время последнего сохранения
            "last_error": None,          # информация о последней ошибке
            "stats": {                   # статистика работы
                "messages_processed": 0,
                "albums_processed": 0,
                "errors_count": 0,
                "start_time": datetime.now(timezone.utc).isoformat()
            }
        }
        self._load_state()
        
    def _load_state(self):
        """Загружает состояние из файла"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                    
                    # Обновляем состояние из файла
                    self.state.update(loaded_state)
                    
                    # Конвертируем processed_albums из списка в множество
                    if isinstance(self.state["processed_albums"], list):
                        self.state["processed_albums"] = set(self.state["processed_albums"])
                        
                    logger.info(f"Состояние загружено из {self.storage_file}")
            else:
                logger.info(f"Файл состояния {self.storage_file} не найден, создаем новый")
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
            
    def save_state(self):
        """Сохраняет текущее состояние в файл"""
        try:
            # Обновляем время последнего сохранения
            self.state["last_save"] = datetime.now(timezone.utc).isoformat()
            
            # Конвертируем множество в список для сериализации
            state_to_save = self.state.copy()
            state_to_save["processed_albums"] = list(self.state["processed_albums"])
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(state_to_save, f, ensure_ascii=False, indent=2)
                
            logger.debug(f"Состояние сохранено в {self.storage_file}")
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния: {e}")
            
    def get_last_message_id(self, channel_id):
        """Возвращает ID последнего обработанного сообщения для канала"""
        return self.state["last_message_ids"].get(str(channel_id), 0)
        
    def set_last_message_id(self, channel_id, message_id):
        """Устанавливает ID последнего обработанного сообщения для канала"""
        channel_id_str = str(channel_id)
        current_id = self.state["last_message_ids"].get(channel_id_str, 0)
        
        # Обновляем только если новый ID больше текущего
        if message_id > current_id:
            self.state["last_message_ids"][channel_id_str] = message_id
            
    def mark_album_processed(self, grouped_id):
        """Отмечает альбом как обработанный"""
        self.state["processed_albums"].add(grouped_id)
        self.state["stats"]["albums_processed"] += 1
        
    def is_album_processed(self, grouped_id):
        """Проверяет, был ли альбом уже обработан"""
        return grouped_id in self.state["processed_albums"]
        
    def update_channel_activity(self, channel_id, activity_data):
        """Обновляет информацию об активности канала"""
        channel_id_str = str(channel_id)
        
        # Преобразуем datetime объекты в строки для сериализации
        serializable_data = {}
        for key, value in activity_data.items():
            if isinstance(value, datetime):
                serializable_data[key] = value.isoformat()
            else:
                serializable_data[key] = value
                
        self.state["channel_activity"][channel_id_str] = serializable_data
        
    def get_channel_activity(self, channel_id):
        """Возвращает информацию об активности канала"""
        return self.state["channel_activity"].get(str(channel_id))
        
    def increment_messages_count(self):
        """Увеличивает счетчик обработанных сообщений"""
        self.state["stats"]["messages_processed"] += 1
        
    def record_error(self, error_info):
        """Записывает информацию об ошибке"""
        self.state["last_error"] = {
            "message": str(error_info),
            "time": datetime.now(timezone.utc).isoformat()
        }
        self.state["stats"]["errors_count"] += 1
        
    def get_stats(self):
        """Возвращает статистику работы парсера"""
        stats = self.state["stats"].copy()
        
        # Добавляем информацию о времени работы
        if "start_time" in stats:
            try:
                start_time = datetime.fromisoformat(stats["start_time"])
                uptime_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
                stats["uptime_hours"] = round(uptime_seconds / 3600, 2)
            except:
                stats["uptime_hours"] = 0
                
        return stats 