#!/usr/bin/env bash
# Установка Chert Vacancy Bot на Ubuntu/Debian VPS.
# Запусти под root или через sudo. Меняй DOMAIN на свой субдомен.
#
#   sudo DOMAIN=bot.kr1sal.com bash deploy/install.sh
#
# Требования: Ubuntu 22.04+ / Debian 12+, домен указывает A-записью на этот VPS.

set -euo pipefail

DOMAIN="${DOMAIN:?Задай DOMAIN=bot.example.com}"
REPO_URL="${REPO_URL:-https://github.com/kr1sal/vacancy-bot.git}"
APP_DIR="/opt/vacancy-bot"
APP_USER="vacancy"

echo "==> 1. Пакеты"
apt update
apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx

echo "==> 2. Пользователь $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$APP_DIR" --shell /bin/bash "$APP_USER"
fi

echo "==> 3. Клон репо в $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
else
    cd "$APP_DIR" && sudo -u "$APP_USER" git pull
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
    echo "  ⚠️  Отредактируй $APP_DIR/.env:"
    echo "     BOT_TOKEN, TELEGRAM_USER_ID, OPENROUTER_API_KEY"
    echo "     WEBAPP_PUBLIC_URL=https://$DOMAIN"
    echo ""
fi

echo "==> 6. systemd unit"
install -m 644 "$APP_DIR/deploy/vacancy-bot.service" /etc/systemd/system/vacancy-bot.service
touch /var/log/vacancy-bot.log
chown "$APP_USER:$APP_USER" /var/log/vacancy-bot.log
systemctl daemon-reload
systemctl enable vacancy-bot

echo "==> 7. nginx"
sed "s/bot\.kr1sal\.com/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" > "/etc/nginx/sites-available/$DOMAIN"
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
nginx -t
systemctl reload nginx

echo "==> 8. HTTPS через Let's Encrypt"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect

echo ""
echo "✅ Готово. Дальше:"
echo "   1. sudo nano $APP_DIR/.env       # заполни секреты"
echo "   2. sudo systemctl start vacancy-bot"
echo "   3. sudo journalctl -u vacancy-bot -f    # логи"
echo "   4. Открой https://$DOMAIN в браузере — должен показать Mini App"
