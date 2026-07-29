import asyncio
import hashlib
import hmac
import logging
import os
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from config import BOT_TOKEN, TELEGRAM_USER_ID, WEBAPP_HOST, WEBAPP_PORT, WEBAPP_LOCAL_TOKEN
import db
import ai

logger = logging.getLogger(__name__)

app = FastAPI(title="Chert Vacancy Bot — Mini App")

_INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.html")


def _verify_init_data(init_data: str) -> int | None:
    """Проверяет подпись Telegram initData. Возвращает user_id или None.

    Согласно https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    data_check_string строится из всех полей кроме `hash` и `signature`, url-decoded,
    отсортированных по ключу, через '\\n'.
    """
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    parsed.pop("signature", None)  # новый параметр Telegram 2024+
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        logger.warning("initData HMAC mismatch: got=%s calc=%s fields=%s",
                       received_hash[:12], calc_hash[:12], sorted(parsed.keys()))
        return None
    user_field = parsed.get("user", "{}")
    try:
        import json as _json
        return _json.loads(user_field).get("id")
    except Exception:
        return None


def _is_via_cloudflare(request: Request) -> bool:
    """Cloudflared tunnel всегда ставит эти заголовки на прошедшие через него запросы."""
    return bool(
        request.headers.get("Cf-Connecting-Ip")
        or request.headers.get("Cf-Ray")
        or request.headers.get("X-Forwarded-For")
    )


def _check_auth(request: Request) -> None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    token = request.headers.get("X-Auth-Token", "") or request.query_params.get("token", "")
    via_cf = _is_via_cloudflare(request)
    client_host = request.client.host if request.client else ""

    # 1) Локальный прямой доступ (не через cloudflared) — разрешаем
    if not via_cf and client_host in ("127.0.0.1", "localhost", "::1"):
        return

    # 2) Telegram Mini App через cloudflared: initData обязательна
    if init_data:
        user_id = _verify_init_data(init_data)
        if user_id == TELEGRAM_USER_ID:
            return
        logger.warning("Auth failed: initData present but HMAC/user_id mismatch (client=%s, via_cf=%s)",
                       client_host, via_cf)
        raise HTTPException(status_code=403, detail="forbidden: init_data invalid")

    # 3) Внешний доступ по секретному токену
    if WEBAPP_LOCAL_TOKEN and hmac.compare_digest(token, WEBAPP_LOCAL_TOKEN):
        return

    logger.warning("Auth denied: no init_data, no valid token (client=%s, via_cf=%s, has_token=%s)",
                   client_host, via_cf, bool(token))
    raise HTTPException(status_code=403, detail="forbidden: no credentials")


@app.get("/")
async def index():
    return FileResponse(_INDEX_PATH)


@app.get("/api/counts")
async def api_counts(request: Request):
    _check_auth(request)
    return db.counts()


@app.get("/api/vacancies")
async def api_list(request: Request, filter: str = "all"):
    _check_auth(request)
    if filter not in ("all", "new", "viewed", "starred", "applied"):
        raise HTTPException(status_code=400, detail="invalid filter")
    return db.list_vacancies(filter)


@app.get("/api/vacancies/{vid}")
async def api_get(vid: str, request: Request):
    _check_auth(request)
    v = db.get_vacancy(vid)
    if not v:
        raise HTTPException(status_code=404, detail="not found")
    return v


@app.post("/api/vacancies/{vid}/view")
async def api_view(vid: str, request: Request):
    _check_auth(request)
    db.mark_viewed(vid)
    return {"ok": True}


@app.post("/api/vacancies/{vid}/star")
async def api_star(vid: str, request: Request):
    _check_auth(request)
    starred = db.toggle_star(vid)
    return {"ok": True, "starred": starred}


@app.post("/api/vacancies/{vid}/applied")
async def api_applied(vid: str, request: Request):
    _check_auth(request)
    applied = db.toggle_applied(vid)
    return {"ok": True, "applied": applied}


@app.post("/api/vacancies/{vid}/letter")
async def api_generate_letter(vid: str, request: Request):
    _check_auth(request)
    v = db.get_vacancy(vid)
    if not v:
        raise HTTPException(status_code=404, detail="not found")

    # optional body: {"feedback": "правки"} — если передано, регенерируем поверх кеша
    feedback = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            feedback = (body.get("feedback") or "").strip() or None
    except Exception:
        pass

    cached = db.get_letter(vid)
    if cached and not feedback:
        return {"letter": cached, "cached": True}

    try:
        letter = await asyncio.to_thread(
            ai.generate_cover_letter,
            v["title"], v["company"], v["description"] or "",
            cached if feedback else None,
            feedback,
        )
        db.save_letter(vid, letter)
        return {"letter": letter, "cached": False, "regenerated": bool(feedback)}
    except Exception as e:
        logger.exception("Letter generation failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


async def run_server() -> None:
    config = uvicorn.Config(
        app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()
