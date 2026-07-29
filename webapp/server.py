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
    """Проверяет подпись Telegram initData. Возвращает user_id или None."""
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    user_field = parsed.get("user", "{}")
    try:
        import json as _json
        return _json.loads(user_field).get("id")
    except Exception:
        return None


def _check_auth(request: Request) -> None:
    # 1) Основной путь — Telegram Mini App
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        user_id = _verify_init_data(init_data)
        if user_id == TELEGRAM_USER_ID:
            return
        raise HTTPException(status_code=403, detail="forbidden")

    # 2) Локальная разработка/curl: проверяем секретный токен из .env
    if WEBAPP_LOCAL_TOKEN:
        token = request.headers.get("X-Auth-Token", "")
        if hmac.compare_digest(token, WEBAPP_LOCAL_TOKEN):
            return

    raise HTTPException(status_code=403, detail="forbidden")


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
