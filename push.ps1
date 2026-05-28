# Скрипт для Windows: сохраняет изменения, собирает Docker-образ и пушит в Git.

if (-not (Test-Path ".deploy.secret")) {
    Write-Host "Ошибка: файл .deploy.secret не найден."
    Write-Host "Скопируй .deploy.secret.example, переименуй в .deploy.secret и заполни."
    exit 1
}

$REPO_URL = ""
Get-Content ".deploy.secret" | ForEach-Object {
    if ($_ -match "^REPO_URL=(.+)$") {
        $REPO_URL = $matches[1].Trim()
    }
}

if (-not $REPO_URL) {
    Write-Host "Ошибка: REPO_URL не найден в .deploy.secret"
    exit 1
}

Write-Host ""
Write-Host "=== 1. Сборка Docker-образа ==="
docker compose build
if (-not $?) { Write-Host "Ошибка сборки Docker!"; exit 1 }

Write-Host ""
Write-Host "=== 2. Сохранение изменений в Git ==="
git add .
$timestamp = Get-Date -Format "dd.MM.yyyy HH:mm"
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "update $timestamp"
} else {
    Write-Host "Нет новых изменений для коммита."
}

Write-Host ""
Write-Host "=== 3. Отправка в репозиторий ==="
git push $REPO_URL main
if (-not $?) { Write-Host "Ошибка при push!"; exit 1 }

Write-Host ""
Write-Host "Готово! Изменения отправлены в репозиторий."
