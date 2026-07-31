import asyncio
import hashlib
import hmac
import logging
import os
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
import uvicorn

from config import (
    BOT_TOKEN, TELEGRAM_USER_ID, WEBAPP_HOST, WEBAPP_PORT,
    WEBAPP_LOCAL_TOKEN, BOT_USERNAME, SESSION_MAX_AGE_DAYS,
)
import db
import ai

logger = logging.getLogger(__name__)

app = FastAPI(title="Chert Vacancy Bot — Mini App")

_INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.html")
_LOGIN_PATH = os.path.join(os.path.dirname(__file__), "login.html")

SESSION_COOKIE = "vb_session"
SESSION_MAX_AGE = SESSION_MAX_AGE_DAYS * 24 * 3600

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


# ── Telegram initData (Mini App) ──────────────────────────────────────────────

def _verify_init_data(init_data: str) -> int | None:
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    parsed.pop("signature", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        logger.warning("initData HMAC mismatch: got=%s calc=%s", received_hash[:12], calc_hash[:12])
        return None
    try:
        import json as _json
        return _json.loads(parsed.get("user", "{}")).get("id")
    except Exception:
        return None


# ── Telegram Login Widget verification ────────────────────────────────────────

def _verify_login_widget(params: dict) -> int | None:
    """https://core.telegram.org/widgets/login#checking-authorization"""
    received_hash = params.pop("hash", None)
    if not received_hash:
        return None
    auth_date = int(params.get("auth_date", 0))
    if abs(time.time() - auth_date) > 86400:  # 24 часа — по документации
        logger.warning("Login widget: auth_date старше 24 часов")
        return None
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        logger.warning("Login widget HMAC mismatch")
        return None
    try:
        return int(params.get("id"))
    except (TypeError, ValueError):
        return None


# ── Session cookies (stateless, подписанные BOT_TOKEN) ────────────────────────

def _issue_session_token(user_id: int) -> str:
    exp = int(time.time()) + SESSION_MAX_AGE
    payload = f"{user_id}.{exp}"
    sig = hmac.new(BOT_TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def _verify_session_token(token: str) -> int | None:
    if not token:
        return None
    try:
        user_id_s, exp_s, sig = token.split(".")
        payload = f"{user_id_s}.{exp_s}"
        expected = hmac.new(BOT_TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_s) < int(time.time()):
            return None
        return int(user_id_s)
    except (ValueError, TypeError):
        return None


# ── Auth ──────────────────────────────────────────────────────────────────────

def _is_via_cloudflare(request: Request) -> bool:
    return bool(
        request.headers.get("Cf-Connecting-Ip")
        or request.headers.get("Cf-Ray")
        or request.headers.get("X-Forwarded-For")
    )


def _check_auth(request: Request) -> None:
    """4 пути авторизации, любой валидный = OK.

    1. Telegram Mini App: X-Telegram-Init-Data (HMAC).
    2. Cookie сессии, установленная после Telegram Login Widget.
    3. Секретный WEBAPP_LOCAL_TOKEN (для curl из своих скриптов).
    4. Прямой localhost без cloudflared (только для разработки).
    """
    # 1. Mini App
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        user_id = _verify_init_data(init_data)
        if user_id == TELEGRAM_USER_ID:
            return
        raise HTTPException(status_code=403, detail="init_data invalid")

    # 2. Cookie session (Telegram Login)
    session = request.cookies.get(SESSION_COOKIE, "")
    session_user = _verify_session_token(session)
    if session_user == TELEGRAM_USER_ID:
        return

    # 3. Local API token
    token = request.headers.get("X-Auth-Token", "") or request.query_params.get("token", "")
    if WEBAPP_LOCAL_TOKEN and hmac.compare_digest(token, WEBAPP_LOCAL_TOKEN):
        return

    # 4. Прямой localhost для dev
    via_cf = _is_via_cloudflare(request)
    client_host = request.client.host if request.client else ""
    if not via_cf and client_host in ("127.0.0.1", "localhost", "::1"):
        return

    logger.warning("Auth denied: client=%s via_cf=%s has_init=%s has_session=%s has_token=%s",
                   client_host, via_cf, bool(init_data), bool(session), bool(token))
    raise HTTPException(status_code=401, detail="unauthorized")


def _requires_login(request: Request) -> bool:
    """Есть ли валидная сессия в браузере (для HTML-редиректов)."""
    session = request.cookies.get(SESSION_COOKIE, "")
    return _verify_session_token(session) != TELEGRAM_USER_ID


# ── HTML routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def index(request: Request):
    # Если не Mini App и нет валидной сессии — редирект на /login
    if not request.headers.get("X-Telegram-Init-Data"):
        # проверяем всё, кроме initData (index обычный GET без header)
        session = request.cookies.get(SESSION_COOKIE, "")
        session_ok = _verify_session_token(session) == TELEGRAM_USER_ID
        local_ok = not _is_via_cloudflare(request) and \
                   (request.client.host if request.client else "") in ("127.0.0.1", "localhost", "::1")
        if not session_ok and not local_ok:
            return RedirectResponse(url="/login", status_code=302)
    return FileResponse(_INDEX_PATH, headers=_NO_CACHE)


@app.get("/vacancy/{vid}")
async def vacancy_page(vid: str, request: Request):
    if not request.headers.get("X-Telegram-Init-Data"):
        session = request.cookies.get(SESSION_COOKIE, "")
        session_ok = _verify_session_token(session) == TELEGRAM_USER_ID
        local_ok = not _is_via_cloudflare(request) and \
                   (request.client.host if request.client else "") in ("127.0.0.1", "localhost", "::1")
        if not session_ok and not local_ok:
            return RedirectResponse(url=f"/login?next=/vacancy/{vid}", status_code=302)
    return FileResponse(_INDEX_PATH, headers=_NO_CACHE)


@app.get("/login")
async def login_page():
    return FileResponse(_LOGIN_PATH, headers=_NO_CACHE)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Telegram Login Widget с data-auth-url=/auth/callback шлёт сюда
    query-параметры {id, first_name, username, photo_url, auth_date, hash}."""
    params = dict(request.query_params)
    next_url = params.pop("next", "/")
    if not next_url.startswith("/"):
        next_url = "/"

    user_id = _verify_login_widget(params)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Telegram login verification failed")
    if user_id != TELEGRAM_USER_ID:
        logger.warning("Login widget: wrong user_id=%s (expected %s)", user_id, TELEGRAM_USER_ID)
        raise HTTPException(status_code=403, detail="access denied")

    token = _issue_session_token(user_id)
    resp = RedirectResponse(url=next_url, status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    logger.info("Session issued for user_id=%s, next=%s", user_id, next_url)
    return resp


@app.post("/auth/logout")
async def logout():
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ── API ───────────────────────────────────────────────────────────────────────

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


# ── Config для клиента ────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config():
    """Публичный endpoint — не требует auth (нужен на /login)."""
    return {"bot_username": BOT_USERNAME}


async def run_server() -> None:
    config = uvicorn.Config(
        app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning",
        access_log=False,
        forwarded_allow_ips="*",  # доверяем X-Forwarded-* от nginx
        proxy_headers=True,
    )
    server = uvicorn.Server(config)
    await server.serve()
