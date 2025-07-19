import logging
from logging.handlers import TimedRotatingFileHandler
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from spam_client import SpamClient
import asyncio
import signal
from telethon import TelegramClient
from telethon.errors import FloodWaitError
import time
from collections import deque
from typing import Deque
from datetime import datetime
from functools import lru_cache

# Настройка логирования с ротацией логов (новое)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Создаём обработчик, который меняет файл логов каждый день и хранит 7 копий
log_handler = TimedRotatingFileHandler("bot.log", when="D", interval=1, backupCount=7)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# Если нужен вывод и в консоль, можно добавить еще один StreamHandler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# Глобальная блокировка для доступа к базе данных (если требуется, например, для get_dialogs)
db_lock = asyncio.Lock()  # Новое: блокировка для синхронного доступа

# Функция кэширования. Оборачиваем вызов к базе с блокировкой
@lru_cache(maxsize=1)
async def get_cached_chats(spam):
    async with db_lock:  # Новое: синхронизация доступа к базе
        return await spam.get_dialogs()

# Фоновая задача для обновления кэша каждые 5 минут
async def refresh_cache():
    # Ждем 30 секунд перед первым обновлением кэша
    await asyncio.sleep(30)
    
    while True:
        try:
            async with SpamClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH) as spam:
                get_cached_chats.cache_clear()  # Очистка старого кэша
                await get_cached_chats(spam)      # Обновление кэша
                print("Кэш чатов обновлен успешно")
        except Exception as e:
            print(f"Ошибка при обновлении кэша: {e}")
        
        await asyncio.sleep(300)  # Обновляем кэш каждые 5 минут

# Logging is already configured above with TimedRotatingFileHandler

# Конфигурация
API_ID = '27734380'
API_HASH = '3597d2e2c267893d2652185f39d6f0af'
BOT_TOKEN = '7859990877:AAFDnFwvmVT5D-cAl_wkeq1hvlb3tVZ6GKs'

SPAM_API_ID = 29720193
SPAM_API_HASH = '75c623435b41e476192f723eafd53645'
SPAM_SESSION = 'spam_account12'

client = TelegramClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH, system_version='4.16.30-vxCUSTOM')

class RateLimiter:
    def __init__(self, rate_limit: int, period: float):
        self.rate_limit = rate_limit
        self.period = period
        self.timestamps: Deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] > self.period:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.rate_limit:
                sleep_time = self.period - (now - self.timestamps[0])
                await asyncio.sleep(sleep_time)
                now = time.monotonic()
                self.timestamps.popleft()
            self.timestamps.append(now)

# Глобальные переменные для состояния
rate_limiter = RateLimiter(rate_limit=10, period=60)
spam_task = None
is_spamming: bool = False  # Явная инициализация
sent_messages_count: int = 0

app = Client("admin_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

message_timestamps = []
rate_limit_lock = asyncio.Lock()

LOG_CHANNEL_ID = -1002547352191

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сколько чатов в базе", callback_data="chats_count")],
        [InlineKeyboardButton("Начать рассылку", callback_data="start_spam")],
        [InlineKeyboardButton("Статистика", callback_data="stats")]
    ])

async def error_handler(func, _client, message):
    try:
        await func(_client, message)
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await message.reply(f"Произошла ошибка: {str(e)}")

@app.on_message(filters.command("start"))
async def start(_client: Client, message: Message):
    await message.reply(
        "Добро пожаловать! Выберите действие:",
        reply_markup=get_main_menu()
    )

@app.on_callback_query()
async def handle_callback(_client: Client, callback_query: CallbackQuery):
    global is_spamming, spam_task, sent_messages_count

    data = callback_query.data
    await callback_query.answer()

    if data == "chats_count":
        # Новое: Сразу отправляем сообщение о загрузке
        loading_msg = await callback_query.message.edit_text("Загрузка данных, пожалуйста подождите...")
        try:
            async with SpamClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH) as spam:
                # Получаем данные из кэша (обновляются фоновой задачей)
                dialogs = await get_cached_chats(spam)
                chats = [d for d in dialogs if d.is_group]
                # Обновляем сообщение результатом
                await loading_msg.edit_text(
                    f"В базе {len(chats)} чатов",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Назад", callback_data="back")]
                    ])
                )
        except Exception as e:
            await handle_error(e, callback_query.message)

    elif data == "start_spam":
        try:
            async with SpamClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH) as spam:
                saved_messages = await spam.get_messages("me", limit=1)
                preview_text = "📝 Сообщение для рассылки:\n\n"
                if not saved_messages:
                    preview_text += "⚠️ В Избранном нет сообщений!"
                else:
                    msg = saved_messages[0]
                    media_info = ""
                    if msg.media:
                        if msg.photo:
                            media_info = "📷 Фото"
                        elif msg.video:
                            media_info = "🎥 Видео"
                        elif msg.document:
                            media_info = "📄 Документ"
                        elif msg.audio:
                            media_info = "🎵 Аудио"
                        else:
                            media_info = "📁 Медиафайл"
                    text_content = msg.text or msg.caption or ""
                    if text_content:
                        preview_text += f"{text_content[:500]}{'...' if len(text_content) > 500 else ''}\n\n"
                    if media_info:
                        preview_text += f"Тип вложения: {media_info}"
                    else:
                        preview_text += "Текст без вложений"
                await callback_query.message.edit_text(
                    f"Вы уверены, что хотите начать рассылку?\n\n"
                    f"{preview_text}\n\n"
                    "Убедитесь, что это правильное сообщение!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("ДА, НАЧАТЬ", callback_data="confirm_spam")],
                        [InlineKeyboardButton("ОТМЕНА", callback_data="back")]
                    ])
                )
        except Exception as e:
            await callback_query.message.edit_text(
                f"❌ Ошибка при получении сообщения: {str(e)}",
                reply_markup=get_main_menu()
            )

    elif data == "confirm_spam":
        if is_spamming:
            return await callback_query.message.edit_text("Рассылка уже запущена!")
        is_spamming = True
        sent_messages_count = 0
        await callback_query.message.edit_text(
            "Начинаю рассылку...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Закончить рассылку", callback_data="stop_spam")]
            ])
        )
        spam_task = asyncio.create_task(run_spam(_client, callback_query.message))

    elif data == "stop_spam":
        is_spamming = False
        if spam_task:
            spam_task.cancel()
        await callback_query.message.edit_text(
            "Рассылка завершена!",
            reply_markup=get_main_menu()
        )

    elif data == "stats":
        await callback_query.message.edit_text(
            f"Количество отправленных сообщений: {sent_messages_count}",
            reply_markup=get_main_menu()
        )

    elif data == "back":
        await callback_query.message.edit_text(
            "Главное меню:",
            reply_markup=get_main_menu()
        )

async def rate_limit_check():
    while True:
        async with rate_limit_lock:
            now = time.monotonic()
            valid_timestamps = [t for t in message_timestamps if now - t < 60]
            message_timestamps[:] = valid_timestamps
            if len(valid_timestamps) < 10:
                message_timestamps.append(now)
                return
            else:
                sleep_time = 60 - (now - valid_timestamps[0])
        logger.info(f"Лимит отправки достигнут. Ожидание {sleep_time:.2f} секунд")
        await asyncio.sleep(sleep_time)

async def log_to_channel(chat, action: str, retries=3):
    for attempt in range(retries):
        try:
            chat_title = getattr(chat, 'title', f"ID: {chat.id}")
            log_text = (
                f"**{action}**\n"
                f"Чат: {chat_title}\n"
                f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            await app.send_message(LOG_CHANNEL_ID, log_text)
            break
        except Exception as e:
            if attempt == retries - 1:
                logger.error(f"Не удалось отправить лог: {e}")
            await asyncio.sleep(5)

async def run_spam(_client: Client, message: Message):
    global sent_messages_count, is_spamming
    async with SpamClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH) as spam:
        saved_messages = await spam.get_messages("me", limit=1)
        if not saved_messages:
            await message.reply("В Избранном нет сообщений!")
            return
        msg = saved_messages[0]
        dialogs = await get_cached_chats(spam)
        chats = [d for d in dialogs if d.is_group]

        async def send_message_to_chat(chat):
            global sent_messages_count
            try:
                await rate_limiter.acquire()
                await msg.forward_to(chat.id)
                sent_messages_count += 1
                logger.info(f"Сообщение отправлено в {chat.id}")
                await log_to_channel(chat, "Сообщение отправлено")
                
                # Monitor chat for activity and resend if needed
                last_check_time = time.monotonic()
                while is_spamming:
                    await asyncio.sleep(10)  # Check every 10 seconds instead of 5
                    current_time = time.monotonic()
                    
                    # Only check for new messages every 60 seconds to avoid spam
                    if current_time - last_check_time >= 60:
                        try:
                            messages = await spam.get_messages(chat.id, limit=40)
                            new_messages = sum(1 for m in messages if not m.out and m.date.timestamp() > last_check_time)
                            if new_messages >= 10:  # Reduced threshold to avoid excessive spam
                                await rate_limiter.acquire()
                                await msg.forward_to(chat.id)
                                sent_messages_count += 1
                                logger.info(f"Повторная отправка в {chat.id}")
                                await log_to_channel(chat, "Повторная отправка")
                                last_check_time = current_time
                        except Exception as e:
                            logger.error(f"Ошибка при проверке сообщений в чате {chat.id}: {e}")
                            break  # Exit the loop if we can't check messages
            except FloodWaitError as e:
                logger.warning(f"Флуд-контроль в чате {chat.id}: ждем {e.seconds} сек.")
                await asyncio.sleep(e.seconds)
                await send_message_to_chat(chat)
            except Exception as e:
                error_str = str(e)
                if "USER_BANNED_IN_CHANNEL" in error_str or "The account has been banned" in error_str or "не имеет права писать" in error_str:
                    logger.error(f"Аккаунт забанен или не может писать в чате {chat.id}. Выполняется автовыход.")
                    try:
                        await spam.leave_chat(chat.id)
                        logger.info(f"Успешно вышли из чата {chat.id}")
                    except Exception as ex:
                        logger.error(f"Ошибка при выходе из чата {chat.id}: {str(ex)}")
                    return
                else:
                    logger.error(f"Ошибка в чате {chat.id}: {error_str}")
                    await handle_error(e, message)

        tasks = [asyncio.create_task(send_message_to_chat(chat)) for chat in chats]
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("Spam task was cancelled")
            # Cancel all remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for all tasks to complete cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            is_spamming = False

async def handle_error(error: Exception, message: Message):
    logger.error(str(error))
    error_msg = str(error)
    async def delete_message_later(msg: Message):
        await asyncio.sleep(300)
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
    try:
        if "A wait of" in error_msg:
            sent_msg = await message.reply("Аккаунт временно заблокирован из-за флуда!")
            asyncio.create_task(delete_message_later(sent_msg))
        elif "USER_BANNED_IN_CHANNEL" in error_msg:
            sent_msg = await message.reply("Аккаунт забанен в одном из чатов!")
            asyncio.create_task(delete_message_later(sent_msg))
        elif "The account has been banned" in error_msg:
            sent_msg = await message.reply("Аккаунт полностью забанен в Telegram!")
            asyncio.create_task(delete_message_later(sent_msg))
        else:
            sent_msg = await message.reply(f"Произошла ошибка: {error_msg}")
            asyncio.create_task(delete_message_later(sent_msg))
    except Exception as ex:
        logger.error(f"Ошибка при отправке сообщения: {ex}")

async def init_spam_client():
    try:
        async with SpamClient(SPAM_SESSION, SPAM_API_ID, SPAM_API_HASH) as _:
            print("Рассыльный аккаунт авторизован!")
    except Exception as e:
        print(f"Ошибка при инициализации spam клиента: {e}")
        # Не прерываем выполнение, так как основной бот может работать без spam клиента

async def main():
    global app
    print("Бот запущен...")
    print(f"Тип объекта app в начале main(): {type(app)}")
    print(f"Есть ли метод idle(): {hasattr(app, 'idle')}")
    
    # Инициализируем spam client перед запуском бота
    await init_spam_client()
    
    # Запускаем фоновую задачу обновления кэша
    asyncio.create_task(refresh_cache())
    
    # Запускаем бота
    try:
        await app.start()
        print("Pyrogram бот запущен успешно!")
        print("Бот готов к работе. Нажмите Ctrl+C для остановки.")
        
        # В Pyrogram 2.x нет метода idle(), используем Event для ожидания
        stop_event = asyncio.Event()
        
        # Обработчик для graceful shutdown
        def signal_handler(signum, frame):
            print(f"\nПолучен сигнал {signum}. Останавливаем бота...")
            stop_event.set()
        
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Ожидаем сигнала остановки
        print("Бот работает. Для остановки нажмите Ctrl+C")
        await stop_event.wait()
            
    except KeyboardInterrupt:
        print("\nПолучен сигнал остановки. Завершаем работу...")
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
        print(f"Тип объекта app: {type(app)}")
        if hasattr(app, 'idle'):
            print("Метод idle() доступен")
        else:
            print("Метод idle() НЕ доступен - это нормально для Pyrogram 2.x")
        raise
    finally:
        try:
            if app.is_connected:
                await app.stop()
                print("Бот остановлен.")
        except Exception as e:
            print(f"Ошибка при остановке бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())
