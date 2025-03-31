from config import setup_bot, logger, CONFIG
from handlers import commands
from handlers import message_handler
from middleware.rate_limit import RateLimitingMiddleware
from parser import Parser
import asyncio

async def main():
    # Запуск aiogram
    bot, dp = setup_bot()
    
    # Запуск парсера Telethon и связывание с ботом
    parser = Parser()
    parser.set_bot(bot)
    
    # Запуск фоновой задачи парсера
    parser_task = asyncio.create_task(parser.parse_messages())
    
    # Регистрация middleware
    dp.message.middleware(RateLimitingMiddleware())
    
    # Подключение хэндлеров
    dp.include_router(commands.router)
    dp.include_router(message_handler.router)
    
    try:
        logger.info("Бот запущен с конфигурацией")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.critical("Критическая ошибка: %s", e)
    finally:
        # Отменяем задачу парсера при завершении
        parser_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main()) 