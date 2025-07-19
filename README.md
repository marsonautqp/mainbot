# Исправление ошибки AttributeError: 'Client' object has no attribute 'idle'

## Проблема
При запуске Telegram бота на Pyrogram 2.0.106 возникала ошибка:
```
AttributeError: 'Client' object has no attribute 'idle'
```

## Причина
В Pyrogram версии 2.x метод `idle()` был удален из API. Этот метод использовался для поддержания бота в активном состоянии.

## Решение
1. **Заменен метод `idle()`** на использование `asyncio.Event()` для ожидания сигнала остановки
2. **Добавлены обработчики сигналов** для корректного завершения работы (SIGINT, SIGTERM)
3. **Улучшена обработка ошибок** с более информативными сообщениями
4. **Добавлены try-catch блоки** для предотвращения неконтролируемого завершения

## Основные изменения в коде:

### Было:
```python
await app.start()
await app.idle()  # Эта строка вызывала ошибку
```

### Стало:
```python
await app.start()

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
await stop_event.wait()
```

## Дополнительные улучшения:
- Добавлена обработка ошибок в `init_spam_client()`
- Улучшена функция `refresh_cache()` с обработкой исключений
- Добавлен graceful shutdown для корректного завершения работы бота

## Установка зависимостей:
```bash
pip install pyrogram telethon
```

## Запуск:
```bash
python3 mainbot.py
```

Теперь бот корректно запускается и работает без ошибок, связанных с отсутствующим методом `idle()`.