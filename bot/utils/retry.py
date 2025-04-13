import asyncio
import logging
import random
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)

class RetryError(Exception):
    """Исключение, возникающее при исчерпании повторных попыток"""
    
    def __init__(self, message: str, original_error: Exception, attempts_made: int):
        self.message = message
        self.original_error = original_error
        self.attempts_made = attempts_made
        super().__init__(message)

async def retry_with_backoff(
    func: Callable[[], Any],
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    factor: float = 2.0,
    jitter: bool = True,
    log_prefix: str = "Retry"
) -> Any:
    """
    Выполняет функцию с экспоненциальной задержкой между повторными попытками.
    
    Args:
        func: Функция для выполнения (должна быть корутиной или вызываемым объектом)
        max_attempts: Максимальное количество попыток
        base_delay: Начальная задержка в секундах
        max_delay: Максимальная задержка в секундах
        factor: Множитель для увеличения задержки
        jitter: Добавлять случайность в задержку
        log_prefix: Префикс для сообщений лога
        
    Returns:
        Результат выполнения функции
        
    Raises:
        RetryError: Если все попытки исчерпаны и функция не выполнена успешно
    """
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            # Вызываем функцию и обрабатываем как корутину
            result = func()
            # Проверяем, является ли результат корутиной
            if asyncio.iscoroutine(result):
                # Если это корутина, выполняем её
                return await result
            # Иначе просто возвращаем результат
            return result
            
        except Exception as e:
            last_exception = e
            
            # Если это последняя попытка, выбрасываем исключение
            if attempt == max_attempts:
                error_msg = f"{log_prefix}: исчерпаны все попытки ({max_attempts})"
                logger.error(error_msg)
                raise RetryError(error_msg, last_exception, attempt)
            
            # Вычисляем задержку
            delay = min(base_delay * (factor ** (attempt - 1)), max_delay)
            
            # Добавляем случайность для избежания синхронизированных запросов
            if jitter:
                delay = delay * (0.5 + random.random())
                
            logger.warning(f"{log_prefix}: попытка {attempt}/{max_attempts} не удалась: {e}, повтор через {delay:.2f} сек")
            
            # Ждем перед повторной попыткой
            await asyncio.sleep(delay)
    
    # Этот код не должен быть достигнут, но на всякий случай
    raise RetryError(f"{log_prefix}: неожиданный выход из цикла повторов", last_exception, max_attempts) 