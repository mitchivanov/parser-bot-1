from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Awaitable, Any
from config import RATE_LIMIT, logger
import time

class RateLimitingMiddleware(BaseMiddleware):
    def __init__(self):
        self.limit = RATE_LIMIT['max_requests']
        self.interval = RATE_LIMIT['period_seconds']
        self.user_calls = {}
        
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any]
    ) -> Any:
        if not event.from_user:
            return await handler(event, data)
            
        user_id = event.from_user.id
        
        if user_id not in self.user_calls:
            self.user_calls[user_id] = []
        
        now = time.time()
        # Очищаем устаревшие записи
        self.user_calls[user_id] = [
            t for t in self.user_calls[user_id] 
            if now - t < self.interval
        ]
        
        # Проверяем лимит
        if len(self.user_calls[user_id]) >= self.limit:
            logger.warning(f"Превышен лимит запросов для пользователя {user_id}")
            await event.answer("🚫 Слишком много запросов! Пожалуйста, подождите минуту.")
            return None
        
        # Добавляем текущий вызов
        self.user_calls[user_id].append(now)
        return await handler(event, data) 