import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)

class HealthMonitor:
    """Монитор работоспособности парсера"""
    
    def __init__(
        self,
        notify_func: Callable[[int, str], Any],
        admin_ids: List[int],
        heartbeat_interval: int = 60,
        error_report_interval: int = 300,
        critical_error_notification_delay: int = 10
    ):
        """
        Инициализирует монитор работоспособности.
        
        Args:
            notify_func: Функция для отправки уведомлений (chat_id, text)
            admin_ids: Список ID администраторов для уведомлений
            heartbeat_interval: Интервал проверки работоспособности в секундах
            error_report_interval: Минимальный интервал между отправкой отчетов об ошибках
            critical_error_notification_delay: Задержка перед отправкой уведомления о критической ошибке
        """
        self.notify_func = notify_func
        self.admin_ids = admin_ids
        self.heartbeat_interval = heartbeat_interval
        self.error_report_interval = error_report_interval
        self.critical_error_delay = critical_error_notification_delay
        
        # Время последнего обновления heartbeat
        self.last_heartbeat = time.time()
        
        # Время последней отправки отчета об ошибках
        self.last_error_report = 0
        
        # Счетчики ошибок
        self.errors = []
        self.critical_errors = []
        
        # Флаг работы монитора
        self.is_running = False
        
    async def start_monitoring(self):
        """Запускает мониторинг работоспособности"""
        if self.is_running:
            logger.warning("Монитор уже запущен")
            return
            
        self.is_running = True
        self.last_heartbeat = time.time()
        
        logger.info("Запущен мониторинг работоспособности")
        
        # Запускаем фоновую задачу мониторинга
        asyncio.create_task(self._monitoring_loop())
        
    async def stop_monitoring(self):
        """Останавливает мониторинг работоспособности"""
        if not self.is_running:
            return
            
        self.is_running = False
        logger.info("Мониторинг работоспособности остановлен")
        
    def update_heartbeat(self):
        """Обновляет время последней активности"""
        self.last_heartbeat = time.time()
        
    def record_error(self, error_message: str, is_critical: bool = False):
        """
        Записывает ошибку для последующего анализа и уведомления.
        
        Args:
            error_message: Текст ошибки
            is_critical: Является ли ошибка критической
        """
        timestamp = datetime.now(timezone.utc)
        error_record = {
            "message": error_message,
            "timestamp": timestamp,
            "reported": False
        }
        
        if is_critical:
            self.critical_errors.append(error_record)
            
            # Отправляем уведомление о критической ошибке с небольшой задержкой
            asyncio.create_task(self._notify_critical_error(error_record, self.critical_error_delay))
        else:
            self.errors.append(error_record)
            
        # Ограничиваем размер списков ошибок
        if len(self.errors) > 100:
            self.errors = self.errors[-100:]
            
        if len(self.critical_errors) > 20:
            self.critical_errors = self.critical_errors[-20:]
    
    async def _notify_critical_error(self, error: Dict[str, Any], delay: int):
        """
        Отправляет уведомление о критической ошибке.
        
        Args:
            error: Запись об ошибке
            delay: Задержка перед отправкой уведомления в секундах
        """
        # Ждем указанное время перед отправкой уведомления
        await asyncio.sleep(delay)
        
        # Проверяем, что монитор все еще работает
        if not self.is_running:
            return
            
        # Формируем сообщение
        message = (
            f"⚠️ <b>КРИТИЧЕСКАЯ ОШИБКА ПАРСЕРА:</b>\n\n"
            f"{error['message']}\n\n"
            f"🕒 Время: {error['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        
        # Отправляем уведомление всем администраторам
        for admin_id in self.admin_ids:
            try:
                await self.notify_func(admin_id, message)
                logger.info(f"Отправлено уведомление о критической ошибке администратору {admin_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")
        
        # Помечаем ошибку как отправленную
        error["reported"] = True
    
    async def _monitoring_loop(self):
        """Основной цикл мониторинга"""
        while self.is_running:
            try:
                # Проверяем время с последнего обновления heartbeat
                current_time = time.time()
                time_since_heartbeat = current_time - self.last_heartbeat
                
                # Если прошло слишком много времени, регистрируем ошибку
                if time_since_heartbeat > self.heartbeat_interval * 3:
                    self.record_error(
                        f"Парсер не отвечает в течение {int(time_since_heartbeat)} секунд",
                        is_critical=True
                    )
                
                # Проверяем, не нужно ли отправить отчет об ошибках
                if self.errors and current_time - self.last_error_report > self.error_report_interval:
                    await self._send_error_report()
                
                # Ожидаем перед следующей проверкой
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                logger.info("Задача мониторинга отменена")
                break
                
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _send_error_report(self):
        """Отправляет отчет о накопленных ошибках администраторам"""
        # Получаем неотправленные ошибки
        unreported_errors = [e for e in self.errors if not e["reported"]]
        
        if not unreported_errors:
            return
            
        # Формируем отчет
        now = datetime.now(timezone.utc)
        report = (
            f"📊 <b>Отчет об ошибках парсера</b>\n\n"
            f"Период: {(now - timedelta(seconds=self.error_report_interval)).strftime('%H:%M:%S')} - "
            f"{now.strftime('%H:%M:%S')} UTC\n\n"
        )
        
        # Добавляем информацию о каждой ошибке (максимум 5)
        for i, error in enumerate(unreported_errors[:5]):
            time_str = error["timestamp"].strftime("%H:%M:%S")
            report += f"{i+1}. [{time_str}] {error['message']}\n\n"
            
        # Если ошибок больше 5, добавляем информацию об остальных
        if len(unreported_errors) > 5:
            report += f"... и еще {len(unreported_errors) - 5} ошибок за этот период."
        
        # Отправляем отчет администраторам
        for admin_id in self.admin_ids:
            try:
                await self.notify_func(admin_id, report)
            except Exception as e:
                logger.error(f"Не удалось отправить отчет об ошибках администратору {admin_id}: {e}")
        
        # Помечаем ошибки как отправленные
        for error in unreported_errors:
            error["reported"] = True
            
        # Обновляем время последней отправки отчета
        self.last_error_report = time.time() 