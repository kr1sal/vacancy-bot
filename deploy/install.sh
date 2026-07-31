#!/usr/bin/env bash
# Устанавливает Chert Vacancy Bot на Ubuntu/Debian VPS.
# Не трогает web-сервер — предполагается, что у тебя уже настроен Caddy или nginx.
# После скрипта пропиши reverse-proxy на 127.0.0.1:8080 (см. deploy/Caddyfile.snippet).
#
#   sudo bash deploy/install.sh
#
# Опции через переменные окружения:
#   REPO_URL=https://github.com/kr1sal/vacancy-bot.git  — откуда клонить
#   APP_DIR=/opt/vacancy-bot                             — куда ставить

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/kr1sal/vacancy-bot.git}"
APP_DIR="${APP_DIR:-/opt/vacancy-bot}"
APP_USER="vacancy"

if [[ $EUID -ne 0 ]]; then
    echo "❌ Запусти под root: sudo bash $0"
    exit 1
fi

echo "==> 1. Пакеты Python (nginx / caddy — отдельно, не трогаем)"
apt update
apt install -y python3 python3-venv python3-pip git

echo "==> 2. Пользователь $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$APP_DIR" --shell /bin/bash "$APP_USER"
fi

echo "==> 3. Клон/обновление репо в $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
else
    cd "$APP_DIR" && sudo -u "$APP_USER" git pull --ff-only
fi

echo "==> 4. Виртуальное окружение + зависимости"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> 5. .env"
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo ""
    echo "   Дальше отредактируй $APP_DIR/.env — там пусто, кроме плейсхолдеров."
else
    chmod 600 "$APP_DIR/.env"
fi

echo "==> 6. systemd unit"
install -m 644 "$APP_DIR/deploy/vacancy-bot.service" /etc/systemd/system/vacancy-bot.service
touch /var/log/vacancy-bot.log
chown "$APP_USER:$APP_USER" /var/log/vacancy-bot.log
systemctl daemon-reload
systemctl enable vacancy-bot

echo ""
echo "✅ Python-часть готова. Что дальше:"
echo ""
echo "   1. Заполни .env:"
echo "        sudo -u $APP_USER nano $APP_DIR/.env"
echo "      Обязательные: BOT_TOKEN, TELEGRAM_USER_ID, OPENROUTER_API_KEY,"
echo "      BOT_USERNAME, WEBAPP_PUBLIC_URL=https://bot.kr1sal.com"
echo ""
echo "   2. Добавь в /etc/caddy/Caddyfile блок из deploy/Caddyfile.snippet,"
echo "      затем: sudo systemctl reload caddy"
echo ""
echo "   3. Запусти бота:"
echo "        sudo systemctl start vacancy-bot"
echo "        sudo journalctl -u vacancy-bot -f"
echo ""
echo "   4. У @BotFather: /setdomain -> выбери бота -> bot.kr1sal.com"
echo ""
echo "   5. Открой https://bot.kr1sal.com/ — редирект на /login, войди через Telegram."
