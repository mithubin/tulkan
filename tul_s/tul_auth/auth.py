import os
import jwt
import bcrypt
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, redirect, make_response

SECRET = os.environ.get('TUL_SECRET')
if not SECRET:
    # Kein unsicherer Default mehr — ein stillschweigend akzeptierter Platzhalter-Key würde
    # JWT-Fälschung für alle tul-Container ermöglichen. Fund Code-Review 2026-07-12.
    raise RuntimeError('TUL_SECRET environment variable must be set')
ALGO = 'HS256'
EXPIRE_DAYS = 30
COOKIE = 'tul_token'


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({'sub': user_id, 'exp': exp}, SECRET, algorithm=ALGO)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGO])
        return payload.get('sub')
    except Exception:
        return None


def _get_raw_token():
    t = request.cookies.get(COOKIE)
    if not t:
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            t = auth[7:]
    return t


def get_current_user():
    """Returns user dict or None."""
    token = _get_raw_token()
    if not token:
        return None
    user_id = decode_token(token)
    if not user_id:
        return None
    from .db import get_conn
    try:
        with get_conn() as conn:
            row = conn.execute(
                'SELECT id, name, email, global_role FROM users WHERE id=?', (user_id,)
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def is_json_request() -> bool:
    accept = request.headers.get('Accept', '')
    ct = request.headers.get('Content-Type', '')
    xhr = request.headers.get('X-Requested-With', '')
    return ('application/json' in accept or 'application/json' in ct
            or xhr == 'XMLHttpRequest')


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            if is_json_request():
                return jsonify({'error': 'Not authenticated'}), 401
            return redirect('/?next=' + request.path)
        request.tul_user = user
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Not authenticated'}), 401
        if user.get('global_role') != 'admin':
            return jsonify({'error': 'Admin required'}), 403
        request.tul_user = user
        return f(*args, **kwargs)
    return decorated


def promote_admin_on_startup():
    email = os.environ.get('ADMIN_EMAIL', '').lower().strip()
    if not email:
        return
    try:
        from .db import get_conn
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET global_role='admin' WHERE email=? AND global_role!='admin'",
                (email,)
            )
    except Exception:
        pass


def set_token_cookie(response, token: str):
    response.set_cookie(
        COOKIE, token,
        max_age=EXPIRE_DAYS * 86400,
        httponly=True,
        samesite='Lax',
        path='/'
    )
    return response


def clear_token_cookie(response):
    response.delete_cookie(COOKIE, path='/')
    return response
