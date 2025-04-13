from bot.config import setup_bot, logger, CONFIG
from bot.handlers import commands
from bot.handlers import message_handler
from bot.middleware.rate_limit import RateLimitingMiddleware
from bot.parser import Parser
from bot.data.storage import ParserStateStorage
from bot.utils.monitoring import HealthMonitor
from telethon.sync import TelegramClient
import asyncio
import signal
import sys
import os
import traceback
import shutil

# Проверка и создание необходимых директорий
def ensure_directories():
    """Проверяет наличие необходимых директорий и создает их при необходимости"""
    # Директория для сессий
    session_dir = CONFIG.get('session_dir', 'sessions')
    os.makedirs(session_dir, exist_ok=True)
    logger.info(f"Используется директория для сессий: {session_dir}")
    
    # Проверка прав доступа
    try:
        test_file = os.path.join(session_dir, '.test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        logger.info(f"Проверка прав доступа к {session_dir} пройдена успешно")
    except Exception as e:
        logger.error(f"Ошибка прав доступа к директории {session_dir}: {e}")

# Глобальные переменные для хранения объектов
bot = None
dp = None
parser = None
parser_task = None

# Обработчики сигналов для корректного завершения
async def shutdown(signal_type=None):
    """Корректно завершает работу бота и освобождает ресурсы"""
    global bot, parser, parser_task
    
    logger.info(f"Получен сигнал завершения{f' {signal_type}' if signal_type else ''}, начинаем остановку...")
    
    # Отменяем задачу парсера если она существует
    if parser_task:
        logger.info("Отменяем задачу парсера...")
        parser_task.cancel()
        try:
            await parser_task
        except asyncio.CancelledError:
            logger.info("Задача парсера успешно отменена")
        except Exception as e:
            logger.error(f"Ошибка при отмене задачи парсера: {e}")
    
    # Останавливаем парсер если он существует
    if parser:
        try:
            await parser._cleanup_resources()
            logger.info("Очистка ресурсов парсера...")
        except Exception as e:
            logger.error(f"Ошибка при очистке ресурсов парсера: {e}")
    
    # Закрываем сессию бота
    if bot:
        logger.info("Закрываем сессию бота...")
        try:
            await bot.session.close()
            logger.info("Сессия бота закрыта")
        except Exception as e:
            logger.error(f"Ошибка при закрытии сессии бота: {e}")
    
    # Завершаем работу event loop
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Отменяем {len(tasks)} оставшихся задач...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("Завершение работы...")

def register_signal_handlers():
    """Регистрирует обработчики сигналов для корректного завершения"""
    try:
        # На Unix/Linux системах
        for sig_name in ('SIGINT', 'SIGTERM'):
            if hasattr(signal, sig_name):
                asyncio.get_event_loop().add_signal_handler(
                    getattr(signal, sig_name),
                    lambda: asyncio.create_task(shutdown(sig_name))
                )
                logger.info(f"Зарегистрирован обработчик для {sig_name}")
    except (NotImplementedError, AttributeError) as e:
        # На Windows
        logger.warning(f"Не удалось зарегистрировать обработчики сигналов: {e}")
        
        # Для Windows обрабатываем Ctrl+C вручную
        signal.signal(signal.SIGINT, lambda signum, frame: 
            asyncio.create_task(shutdown('SIGINT')))

def setup_error_handling():
    """Настраивает глобальный обработчик исключений для логирования"""
    def excepthook(exctype, value, tb):
        # Логируем непойманные исключения
        traceback_text = ''.join(traceback.format_exception(exctype, value, tb))
        logger.critical(f"Непойманное исключение:\n{traceback_text}")
        # Вызываем стандартный обработчик
        sys.__excepthook__(exctype, value, tb)
    
    # Устанавливаем глобальный обработчик исключений
    sys.excepthook = excepthook

def clean_session():
    """Удаляет предыдущую сессию Telethon для принудительной авторизации"""
    session_dir = CONFIG.get('session_dir', 'sessions')
    phone = CONFIG['telegram']['phone']
    session_path = os.path.join(session_dir, phone)
    
    # Удаляем файл сессии если он существует
    if os.path.exists(f"{session_path}.session"):
        try:
            os.remove(f"{session_path}.session")
            logger.info(f"Удален файл сессии {session_path}.session для принудительной авторизации")
        except Exception as e:
            logger.error(f"Не удалось удалить файл сессии: {e}")
    
    # Удаляем файл состояния, если он существует
    state_file = "parser_state.json"
    if os.path.exists(state_file):
        try:
            os.remove(state_file)
            logger.info(f"Удален файл состояния {state_file}")
        except Exception as e:
            logger.error(f"Не удалось удалить файл состояния: {e}")

async def main():
    global bot, dp, parser, parser_task
    
    # Настраиваем обработку ошибок и сигналов
    setup_error_handling()
    register_signal_handlers()
    
    # Проверяем и создаем необходимые директории
    ensure_directories()
    
    # Удаляем предыдущие сессии для принудительной авторизации
    clean_session()

    try:
        # Запуск aiogram
        bot, dp = setup_bot()
        
        # Сохраняем ссылку на диспетчер в объекте бота для доступа из парсера
        bot.dispatcher = dp
        
        # Регистрация middleware
        dp.message.middleware(RateLimitingMiddleware())
        
        # Подключение хэндлеров
        dp.include_router(commands.router)
        dp.include_router(message_handler.router)
        
        # Запускаем опрос сообщений ботом
        logger.info("Запуск обработки сообщений ботом")
        polling_task = asyncio.create_task(dp.start_polling(bot))
        
        # Добавляем значительную задержку для инициализации бота и получения кода авторизации
        await asyncio.sleep(3)
        logger.info("Бот запущен и готов получать сообщения")
        
        # Отправляем сообщение администратору с просьбой подготовить код из SMS
        for admin_id in CONFIG['settings']['admins']:
            try:
                await bot.send_message(
                    chat_id=admin_id, 
                    text=f"🔄 Бот запущен и готов к работе!\n\n"
                         f"⚠️ Для авторизации парсера нужен код из SMS на номер {CONFIG['telegram']['phone']}.\n\n"
                         f"Пожалуйста, будьте готовы отправить код, когда парсер его запросит."
                )
                logger.info(f"Отправлено предварительное уведомление администратору {admin_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить начальное сообщение админу {admin_id}: {e}")
        
        # Дополнительная задержка перед запуском парсера
        await asyncio.sleep(3)

        # Инициализируем клиент Telethon
        session_path = CONFIG.get('session_path', os.path.join(CONFIG.get('session_dir', 'sessions'), CONFIG['telegram']['phone']))
        client = TelegramClient(
            session_path,
            CONFIG['telegram']['api_id'],
            CONFIG['telegram']['api_hash']
        )
        
        # Инициализируем хранилище
        storage = ParserStateStorage(storage_file="parser_state.json")
        
        # Инициализируем монитор
        monitor = HealthMonitor(
            notify_func=None,  # Будет установлен позже в парсере
            admin_ids=CONFIG['settings']['admins']
        )

        # Теперь создаем парсер и связываем с ботом
        logger.info("Инициализация парсера Telegram")
        parser = Parser(client, storage, CONFIG, monitor)
        parser.set_bot(bot)
        
        # Подключаемся к Telegram API перед запуском задачи парсера
        logger.info("Подключение к API Telegram...")
        if not await parser.connect_with_retry():
            logger.critical("Не удалось авторизоваться в Telegram. Остановка работы.")
            return
        
        # Запуск фоновой задачи парсера
        logger.info("Запуск задачи парсера")
        parser_task = asyncio.create_task(parser.run())
        
        # Ждем завершения основной задачи или исключения
        await polling_task
        
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}")
        logger.critical(f"Стек вызовов: {traceback.format_exc()}")
    finally:
        # Корректное завершение работы
        await shutdown()

if __name__ == "__main__":
    # Отключаем вывод отладочной информации
    if os.name == 'posix':  # Linux/Mac
        sys.stderr = open('/dev/null', 'w')
    else:  # Windows
        sys.stderr = open('nul', 'w')
    
    asyncio.run(main())
        
# Эта функция используется как точка входа при установке через pip
def run():
    """Точка входа для запуска как установленный пакет"""
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.critical(f"Фатальная ошибка в основном потоке: {e}")
        sys.exit(1) 