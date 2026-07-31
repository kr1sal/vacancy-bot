# Deploy на VPS с Caddy

Предполагается: Ubuntu/Debian VPS, [Caddy](https://caddyserver.com/) уже установлен и работает.

## Пошагово

### 1. DNS
В панели регистратора `kr1sal.com` — добавь A-запись:
```
jobs   A   <IP_ТВОЕГО_VPS>
```
Проверь: `dig +short jobs.kr1sal.com` — должен вернуть IP VPS.

### 2. BotFather /setdomain
Иначе Telegram Login Widget работать не будет.
1. [@BotFather](https://t.me/BotFather) → `/setdomain`
2. Выбери бота (`kr1salvacancy_bot`)
3. Введи домен без `https://`: `jobs.kr1sal.com`

### 3. Установка на VPS
```bash
# на VPS под root или через sudo
apt install -y git
git clone https://github.com/kr1sal/vacancy-bot.git /tmp/vb
sudo bash /tmp/vb/deploy/install.sh
```

Что делает `install.sh`:
- Ставит `python3-venv`, `git`
- Создаёт системного пользователя `vacancy`
- Клонирует репо в `/opt/vacancy-bot`, поднимает venv, ставит зависимости
- Копирует `.env.example → .env` (chmod 600, owner: vacancy)
- Регистрирует и включает systemd unit `vacancy-bot.service`

Web-сервер скрипт **не трогает** — у тебя уже свой Caddy.

### 4. Заполни `.env`
```bash
sudo -u vacancy nano /opt/vacancy-bot/.env
```

Обязательные (с ротированными ключами):
```env
BOT_TOKEN=... (новый, после /revoke)
TELEGRAM_USER_ID=твой_id
BOT_USERNAME=kr1salvacancy_bot
OPENROUTER_API_KEY=sk-or-v1-... (новый)
WEBAPP_PUBLIC_URL=https://jobs.kr1sal.com
```

Опциональные (по желанию):
- `GMAIL_USER` / `GMAIL_APP_PASSWORD` — для Gmail-парсера
- `VACANCY_STOPWORDS` — стоп-слова, чтобы срезать senior-only
- `WEBAPP_LOCAL_TOKEN` — секрет для curl из своих скриптов

### 5. Caddy — добавь блок
Скопируй из `deploy/Caddyfile.snippet`:
```caddyfile
jobs.kr1sal.com {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8080 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
    log {
        output file /var/log/caddy/jobs.kr1sal.com.log
        format console
    }
}
```

Вставь в `/etc/caddy/Caddyfile` (после существующих блоков), затем:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy сам получит Let's Encrypt cert для нового субдомена — ничего дополнительно не нужно.

### 6. Запуск
```bash
sudo systemctl start vacancy-bot
sudo journalctl -u vacancy-bot -f
```

Ждёшь строку `Chert Vacancy Bot started` — значит бот работает.

### 7. Проверка
- Открой `https://jobs.kr1sal.com/` в браузере (не в Telegram)
- Должно редиректнуть на `/login` → виджет Telegram → авторизация → редирект на `/`
- Внутри Telegram: `/start` у бота → кнопка «📱 Открыть приложение» → Mini App должна открыться без логина (у Telegram есть initData)

## Обновление после `git push`
```bash
cd /opt/vacancy-bot
sudo -u vacancy git pull --ff-only
sudo -u vacancy .venv/bin/pip install -r requirements.txt
sudo systemctl restart vacancy-bot
```

## Диагностика

**Логи бота:**
```bash
sudo journalctl -u vacancy-bot -n 100 -f
# или
sudo tail -f /var/log/vacancy-bot.log
```

**Логи Caddy:**
```bash
sudo tail -f /var/log/caddy/jobs.kr1sal.com.log
sudo journalctl -u caddy -n 50
```

**Проверить что бот отвечает изнутри VPS:**
```bash
curl -sI http://127.0.0.1:8080/ | head -3
```

**Проверить внешний доступ:**
```bash
curl -sI https://jobs.kr1sal.com/ | head -3
```

## SSH reverse tunnel (альтернатива — бот у себя на PC)

Если хочешь запускать бота на своей машине, а VPS использовать только как HTTPS-прокси:

**На VPS:** только Caddy-блок из шага 5 (без установки бота).

**На локальной машине:**
```powershell
ssh -N -R 8080:127.0.0.1:8080 root@kr1sal.com
```

Работает пока SSH-сессия открыта. Для persistent — [autossh](https://www.harding.motd.ca/autossh/) как systemd-unit.
