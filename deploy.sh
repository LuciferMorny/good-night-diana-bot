#!/bin/bash
set -e

CONTAINER_NAME="for_diana_bot"

echo "=== Загрузка адреса репозитория ==="
if [ ! -f ".deploy.secret" ]; then
    echo "Ошибка: файл .deploy.secret не найден."
    echo "Скопируй .deploy.secret.example, переименуй в .deploy.secret и заполни."
    exit 1
fi
source .deploy.secret

echo ""
echo "=== 1. Остановка программы (если запущена без Docker) ==="
pkill -f "python bot.py" 2>/dev/null && echo "Процесс остановлен." || echo "Процесс не был запущен."

echo ""
echo "=== 2. Остановка контейнера (если запущен) ==="
docker compose down 2>/dev/null && echo "Контейнер остановлен." || echo "Контейнер не был запущен."

echo ""
echo "=== 3. Скачивание изменений из репозитория ==="
git pull "$REPO_URL" main

echo ""
echo "=== 4. Подготовка файлов данных ==="
touch logs.txt
if [ ! -s state.json ]; then
    echo '{"message_index": 0, "song_index": 0}' > state.json
    echo "Создан state.json с начальными значениями."
fi
mkdir -p music

echo ""
echo "=== 5. Сборка и запуск нового контейнера ==="
docker compose build --no-cache
docker compose up -d

echo ""
echo "Готово! Бот запущен в контейнере '$CONTAINER_NAME'."
echo "Смотреть логи: docker logs -f $CONTAINER_NAME"
