---
name: telegram-send
description: Отправить пользователю файл или сообщение в его Telegram-бот. Use when the user asks to send, share, or deliver a file, archive, or text to Telegram.
---

Отправка идёт в единственный личный чат пользователя с ботом. Токен и чат берутся из `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`; если их нет в окружении, скрипт читает `~/.config/zsh/secrets.zsh`. Не выводи значения этих переменных.

1. Подготовь то, что нужно отправить. Каталог или несколько файлов сначала упакуй в один `.zip` вне рабочих файлов проекта и проверь его содержимое через `unzip -l`.
2. Отправь:
   - файл: `bash <skill-dir>/send.sh <path> [caption]`;
   - текст: `bash <skill-dir>/send.sh --text <message>`.
3. Готово, когда скрипт напечатал `sent, message_id=...`. При ошибке сообщи пользователю текст ошибки Telegram. Файлы больше 50 MB Bot API не принимает: предложи разбить архив (`zip -s 45m`) или другой способ передачи.
