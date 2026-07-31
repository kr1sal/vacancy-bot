# Deploy на VPS

Ubuntu 22.04+ / Debian 12+, домен указывает A-записью на VPS.

## Быстрый старт

```bash
# на VPS под root
apt update && apt install -y git
git clone https://github.com/kr1sal/vacancy-bot.git /tmp/vb
sudo DOMAIN=bot.kr1sal.com bash /tmp/vb/deploy/install.sh
```

Скрипт установит python + nginx + certbot, создаст системного пользователя `vacancy`,
клонирует репо в `/opt/vacancy-bot`, поднимет venv, поставит зависимости, настроит
systemd-unit и nginx с Let's Encrypt HTTPS.

## После установки

1. Заполни `.env`:
   ```bash
   sudo nano /opt/vacancy-bot/.env
   ```
   Обязательные:
   - `BOT_TOKEN`, `TELEGRAM_USER_ID`, `OPENROUTER_API_KEY`
   - `WEBAPP_PUBLIC_URL=https://bot.kr1sal.com`
   - `BOT_USERNAME=Kr1saLVacancyBot` — без `@`, точное имя бота
2. Запусти:
   ```bash
   sudo systemctl start vacancy-bot
   sudo journalctl -u vacancy-bot -f
   ```

## Настройка Telegram Login Widget

Чтобы можно было заходить в Mini App из обычного браузера (не только из Telegram):

1. Открой [@BotFather](https://t.me/BotFather) → `/setdomain` → выбери бота
2. Введи домен **без** `https://`: `bot.kr1sal.com`
3. Открой `https://bot.kr1sal.com/` — должно редиректить на `/login`
4. Виджет «Log in with Telegram» → подтверждаешь → сессия сохраняется в
   HttpOnly cookie на 30 дней (настраивается `SESSION_MAX_AGE_DAYS`)

Session-токен подписан HMAC от `BOT_TOKEN`, stateless — сервер не хранит
сессии в БД. Внутри Telegram Mini App работает как раньше через initData.

## Обновление после git push

```bash
cd /opt/vacancy-bot
sudo -u vacancy git pull
sudo -u vacancy .venv/bin/pip install -r requirements.txt
sudo systemctl restart vacancy-bot
```

## SSH reverse tunnel (альтернатива, бот у себя на PC)

Если хочешь запускать бот локально, а VPS использовать только как HTTPS-прокси:

**На VPS:** установи только nginx + certbot по `deploy/nginx.conf`, без бота.

**На локальной машине** держи SSH-туннель:
```powershell
ssh -N -R 8080:127.0.0.1:8080 root@kr1sal.com
```

Работает пока сессия открыта. Для persistent-туннеля — [autossh](https://www.harding.motd.ca/autossh/).
