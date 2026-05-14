"""
Авторизация TeacherFactory.

Дизайн:
  - Аккаунты хранятся в `~/.teacherfactory/auth/users.json` (вне репо,
    права 0o600 на POSIX). Пароли — argon2id, никогда в plain.
  - Роли: admin / user. Админ управляет пользователями через UI.
  - При первом запуске генерируется случайный пароль для admin и
    однократно печатается в stdout + в файл `admin_bootstrap.txt`
    рядом с users.json. Этот файл нужно прочитать и удалить.
  - Bruteforce-защита: in-memory rate limit (5 неудач → блок 15 минут на
    логин по этому имени). Сбрасывается перезапуском сервера.
  - Идле-таймаут сессии 60 мин, абсолютный 12 ч. Никаких куки/JWT —
    state живёт в `st.session_state` (per-tab).
  - Аудит: append-only лог в `auth.log` (логины, неудачи, смены пароля,
    создание/удаление пользователей). Никаких паролей в логах.

ВАЖНО: код НЕ использует .env, конфиги или Streamlit secrets для хранения
паролей. Всё — argon2id-хеши на диске.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import string
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from teacherfactory.paths import AUTH_DIR, AUTH_LOG, USERS_FILE

log = logging.getLogger(__name__)

# Argon2id с параметрами по умолчанию argon2-cffi (RFC 9106 разумные значения):
# time_cost=3, memory_cost=64 MiB, parallelism=4, hash_len=32, salt_len=16.
_HASHER = PasswordHasher()

# Идле- и абсолютный таймауты сессии.
_IDLE_TIMEOUT_SEC = 60 * 60
_ABS_TIMEOUT_SEC = 12 * 60 * 60

# Bruteforce: 5 неудач → лок на 15 мин.
_MAX_FAILED = 5
_LOCKOUT_SEC = 15 * 60

# In-memory счётчик неудачных попыток: {username_lower: (count, locked_until_epoch)}.
# Перезапуск сервера сбрасывает — приемлемо, т.к. требует доступа к хосту.
_failed: dict[str, tuple[int, float]] = {}
_failed_lock = threading.Lock()

# Один глобальный лок при записи users.json — Streamlit многопоточный.
_io_lock = threading.Lock()


# ─── Модель ───────────────────────────────────────────────────────────────────


@dataclass
class User:
    username: str
    password_hash: str
    role: str = "user"  # "admin" | "user"
    created_at: str = ""
    last_login: str = ""
    must_change_password: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "password_hash": self.password_hash,
            "role": self.role,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "must_change_password": self.must_change_password,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        return cls(
            username=data["username"],
            password_hash=data["password_hash"],
            role=data.get("role", "user"),
            created_at=data.get("created_at", ""),
            last_login=data.get("last_login", ""),
            must_change_password=bool(data.get("must_change_password", False)),
        )


@dataclass
class UsersDB:
    users: dict[str, User] = field(default_factory=dict)  # ключ — username.lower()

    def get(self, username: str) -> User | None:
        return self.users.get(username.lower())

    def add(self, user: User) -> None:
        self.users[user.username.lower()] = user

    def remove(self, username: str) -> bool:
        return self.users.pop(username.lower(), None) is not None

    def list_all(self) -> list[User]:
        return sorted(self.users.values(), key=lambda u: u.username.lower())


# ─── Хранилище ────────────────────────────────────────────────────────────────


def _ensure_dir() -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    # Закрываем директорию для остальных пользователей машины.
    try:
        os.chmod(AUTH_DIR, 0o700)
    except (OSError, NotImplementedError):
        pass  # Windows: chmod ограничен, но дефолт NTFS уже user-scope.


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except (OSError, NotImplementedError):
        pass


def load_users() -> UsersDB:
    if not USERS_FILE.exists():
        return UsersDB()
    try:
        raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("Не удалось прочитать users.json: %s", e)
        raise RuntimeError("Файл пользователей повреждён. Восстанови из резервной копии.") from e
    db = UsersDB()
    for item in raw.get("users", []):
        u = User.from_dict(item)
        db.add(u)
    return db


def save_users(db: UsersDB) -> None:
    _ensure_dir()
    payload = {"users": [u.to_dict() for u in db.list_all()], "version": 1}
    tmp = USERS_FILE.with_suffix(".json.tmp")
    with _io_lock:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        _restrict(tmp)
        # Атомарный replace — старый файл не теряется при сбое записи.
        os.replace(tmp, USERS_FILE)
        _restrict(USERS_FILE)


# ─── Пароли ───────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _HASHER.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> str | None:
    """Возвращает текст ошибки или None, если пароль допустим."""
    if len(password) < 12:
        return "Минимум 12 символов."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return "Пароль должен содержать минимум 3 из 4 категорий: строчные, заглавные, цифры, спецсимволы."
    return None


def generate_password(length: int = 20) -> str:
    """Криптостойкий пароль из букв+цифр+символов."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+?"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if validate_password_strength(pwd) is None:
            return pwd


# ─── Rate limit ───────────────────────────────────────────────────────────────


def _is_locked(username: str) -> tuple[bool, float]:
    """Возвращает (locked, seconds_remaining)."""
    key = username.lower()
    with _failed_lock:
        info = _failed.get(key)
        if not info:
            return False, 0.0
        count, locked_until = info
        if locked_until > time.time():
            return True, locked_until - time.time()
        if locked_until and locked_until <= time.time():
            # Лок истёк — сбрасываем счётчик.
            _failed.pop(key, None)
        return False, 0.0


def _record_failure(username: str) -> None:
    key = username.lower()
    with _failed_lock:
        count, _ = _failed.get(key, (0, 0.0))
        count += 1
        locked_until = time.time() + _LOCKOUT_SEC if count >= _MAX_FAILED else 0.0
        _failed[key] = (count, locked_until)


def _clear_failures(username: str) -> None:
    with _failed_lock:
        _failed.pop(username.lower(), None)


# ─── Аудит ────────────────────────────────────────────────────────────────────


def _audit(event: str, **fields: Any) -> None:
    """Append-only JSON-lines в auth.log. Никогда не пишет пароли/хеши."""
    _ensure_dir()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **{k: v for k, v in fields.items() if k not in ("password", "password_hash")},
    }
    try:
        with AUTH_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        _restrict(AUTH_LOG)
    except OSError as e:
        log.warning("Не удалось записать auth.log: %s", e)


# ─── Bootstrap ────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bootstrap_admin_if_needed() -> str | None:
    """
    Если в users.json нет ни одного админа — создать admin с
    криптостойким случайным паролем. Пароль печатается в stdout и
    записывается одноразовый файл `admin_bootstrap.txt`.

    Возвращает текст для отображения в UI (если bootstrap произошёл) — но
    самый надёжный путь — терминал, потому что в UI пароль никто не должен
    «увидеть случайно».
    """
    _ensure_dir()
    db = load_users()
    if any(u.role == "admin" for u in db.list_all()):
        return None

    password = generate_password()
    admin = User(
        username="admin",
        password_hash=hash_password(password),
        role="admin",
        created_at=_now(),
        must_change_password=True,
    )
    db.add(admin)
    save_users(db)

    bootstrap_file = AUTH_DIR / "admin_bootstrap.txt"
    bootstrap_file.write_text(
        f"# Сгенерированный пароль admin (сменить при первом входе!)\n"
        f"username: admin\npassword: {password}\n"
        f"# Удали этот файл после прочтения.\n",
        encoding="utf-8",
    )
    _restrict(bootstrap_file)
    msg = (
        f"=== TeacherFactory: создан admin аккаунт ===\n"
        f"  username: admin\n  password: {password}\n"
        f"  (пароль также сохранён в {bootstrap_file})\n"
        f"  УДАЛИ файл после входа и СМЕНИ пароль.\n"
        f"============================================"
    )
    print(msg)
    _audit("admin_bootstrap", username="admin")
    return msg


# ─── Аутентификация ───────────────────────────────────────────────────────────


def authenticate(username: str, password: str) -> User | None:
    """Проверяет логин/пароль с учётом rate limit. None при неудаче."""
    locked, remaining = _is_locked(username)
    if locked:
        _audit("login_locked", username=username, remaining_sec=int(remaining))
        return None

    db = load_users()
    user = db.get(username)
    # Защита от user enumeration: всегда выполняем verify, даже если
    # пользователя нет — берём фейковый хеш с теми же параметрами.
    if user is None:
        # Постоянное время: верифицируем против заведомо неверного хеша.
        verify_password(_DUMMY_HASH, password)
        _record_failure(username)
        _audit("login_failed", username=username, reason="no_such_user")
        return None

    if not verify_password(user.password_hash, password):
        _record_failure(username)
        _audit("login_failed", username=username, reason="bad_password")
        return None

    # Успех. Обновим хеш при необходимости (изменились параметры argon2).
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login = _now()
    save_users(db)
    _clear_failures(username)
    _audit("login_ok", username=username, role=user.role)
    return user


# Фиксированный «болванчик» — argon2-хеш строки, которую никто не введёт.
# Используется чтобы verify имел постоянное время даже для отсутствующих юзеров.
_DUMMY_HASH = _HASHER.hash("not-a-real-password-" + secrets.token_hex(8))


# ─── Управление пользователями (admin) ────────────────────────────────────────


def create_user(username: str, password: str, role: str = "user") -> tuple[bool, str]:
    username = username.strip()
    if not username or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        return False, "Имя пользователя: только буквы/цифры/._- ."
    if len(username) > 64:
        return False, "Имя слишком длинное."
    if role not in ("admin", "user"):
        return False, "Недопустимая роль."
    err = validate_password_strength(password)
    if err:
        return False, err
    db = load_users()
    if db.get(username):
        return False, "Пользователь с таким именем уже существует."
    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            created_at=_now(),
            must_change_password=True,
        )
    )
    save_users(db)
    _audit("user_created", username=username, role=role)
    return True, "Пользователь создан."


def delete_user(username: str, actor: str) -> tuple[bool, str]:
    if username.lower() == actor.lower():
        return False, "Нельзя удалить собственный аккаунт."
    db = load_users()
    user = db.get(username)
    if not user:
        return False, "Нет такого пользователя."
    if user.role == "admin":
        admins = [u for u in db.list_all() if u.role == "admin"]
        if len(admins) <= 1:
            return False, "Нельзя удалить последнего администратора."
    db.remove(username)
    save_users(db)
    _audit("user_deleted", username=username, actor=actor)
    return True, "Пользователь удалён."


def change_password(username: str, new_password: str) -> tuple[bool, str]:
    err = validate_password_strength(new_password)
    if err:
        return False, err
    db = load_users()
    user = db.get(username)
    if not user:
        return False, "Нет такого пользователя."
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    save_users(db)
    _audit("password_changed", username=username)
    return True, "Пароль изменён."


def set_role(username: str, role: str, actor: str) -> tuple[bool, str]:
    if role not in ("admin", "user"):
        return False, "Недопустимая роль."
    db = load_users()
    user = db.get(username)
    if not user:
        return False, "Нет такого пользователя."
    if user.role == "admin" and role != "admin":
        admins = [u for u in db.list_all() if u.role == "admin"]
        if len(admins) <= 1:
            return False, "Нельзя разжаловать последнего администратора."
    user.role = role
    save_users(db)
    _audit("role_changed", username=username, new_role=role, actor=actor)
    return True, "Роль изменена."


# ─── Streamlit UI ─────────────────────────────────────────────────────────────


def _session_user() -> User | None:
    auth = st.session_state.get("_auth")
    if not auth:
        return None
    now = time.time()
    if now - auth["last_active"] > _IDLE_TIMEOUT_SEC:
        st.session_state.pop("_auth", None)
        return None
    if now - auth["login_at"] > _ABS_TIMEOUT_SEC:
        st.session_state.pop("_auth", None)
        return None
    auth["last_active"] = now
    # Возвращаем свежие данные из БД на случай смены роли/удаления.
    db = load_users()
    user = db.get(auth["username"])
    if not user:
        st.session_state.pop("_auth", None)
        return None
    return user


def _login_screen() -> None:
    st.title("🔐 Вход в TeacherFactory")
    st.caption("Введите имя пользователя и пароль.")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Имя пользователя", max_chars=64)
        password = st.text_input("Пароль", type="password", max_chars=256)
        submit = st.form_submit_button("Войти", use_container_width=True)

    if not submit:
        return

    if not username or not password:
        st.error("Введите имя пользователя и пароль.")
        return

    locked, remaining = _is_locked(username)
    if locked:
        st.error(f"Слишком много неудачных попыток. Подождите {int(remaining // 60) + 1} мин.")
        return

    user = authenticate(username, password)
    if not user:
        # Единая формулировка — не подсказываем, есть ли такой логин.
        st.error("Неверное имя пользователя или пароль.")
        return

    st.session_state["_auth"] = {
        "username": user.username,
        "role": user.role,
        "login_at": time.time(),
        "last_active": time.time(),
    }
    st.rerun()


def _force_password_change(user: User) -> None:
    st.title("🔑 Смена пароля")
    st.info("При первом входе нужно сменить пароль.")
    with st.form("change_pwd_form"):
        new1 = st.text_input("Новый пароль", type="password")
        new2 = st.text_input("Повторите пароль", type="password")
        submit = st.form_submit_button("Сменить пароль")
    if not submit:
        return
    if new1 != new2:
        st.error("Пароли не совпадают.")
        return
    ok, msg = change_password(user.username, new1)
    if not ok:
        st.error(msg)
        return
    st.success("Пароль изменён. Войдите заново.")
    st.session_state.pop("_auth", None)
    time.sleep(1)
    st.rerun()


def require_auth() -> User:
    """
    Гейт: если не авторизован — показывает экран входа и останавливает скрипт.
    Возвращает текущего User.
    """
    bootstrap_admin_if_needed()
    user = _session_user()
    if user is None:
        _login_screen()
        st.stop()
    if user.must_change_password:
        _force_password_change(user)
        st.stop()
    return user


def logout() -> None:
    auth = st.session_state.get("_auth")
    if auth:
        _audit("logout", username=auth["username"])
    st.session_state.pop("_auth", None)


def render_user_admin(current: User) -> None:
    """Админ-панель: список пользователей, создание, удаление, смена роли."""
    if current.role != "admin":
        st.error("Доступ только для администратора.")
        return

    st.subheader("Пользователи")
    db = load_users()
    users = db.list_all()

    for u in users:
        cols = st.columns([3, 1, 2, 2, 1])
        cols[0].write(f"**{u.username}**")
        cols[1].write(u.role)
        cols[2].caption(f"создан: {u.created_at[:10] if u.created_at else '—'}")
        cols[3].caption(f"вход: {u.last_login[:16] if u.last_login else '—'}")
        with cols[4]:
            if u.username.lower() != current.username.lower():
                if st.button("🗑", key=f"del_{u.username}", help="Удалить"):
                    ok, msg = delete_user(u.username, current.username)
                    (st.success if ok else st.error)(msg)
                    st.rerun()

    st.divider()
    with st.expander("➕ Создать пользователя"):
        with st.form("create_user", clear_on_submit=True):
            new_name = st.text_input("Имя пользователя")
            new_pwd = st.text_input("Пароль (мин 12 символов, 3 категории)", type="password")
            new_role = st.selectbox("Роль", ["user", "admin"])
            create = st.form_submit_button("Создать")
            if create:
                ok, msg = create_user(new_name, new_pwd, new_role)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.info("Передайте пароль пользователю по защищённому каналу. Он сменит его при первом входе.")

    with st.expander("🎲 Сгенерировать случайный пароль"):
        if st.button("Сгенерировать"):
            st.code(generate_password(), language=None)
            st.caption("Скопируй сейчас — после перезагрузки страницы он будет другим.")

    with st.expander("🔧 Сменить роль"):
        names = [u.username for u in users]
        target = st.selectbox("Пользователь", names, key="role_target")
        target_role = st.selectbox("Новая роль", ["user", "admin"], key="role_value")
        if st.button("Применить"):
            ok, msg = set_role(target, target_role, current.username)
            (st.success if ok else st.error)(msg)
            st.rerun()

    st.divider()
    with st.expander("🔑 Сменить собственный пароль"):
        with st.form("self_pwd"):
            old = st.text_input("Текущий пароль", type="password")
            new1 = st.text_input("Новый пароль", type="password")
            new2 = st.text_input("Повторите новый", type="password")
            submit = st.form_submit_button("Сменить")
            if submit:
                if new1 != new2:
                    st.error("Пароли не совпадают.")
                elif not authenticate(current.username, old):
                    st.error("Текущий пароль неверен.")
                else:
                    ok, msg = change_password(current.username, new1)
                    (st.success if ok else st.error)(msg)


__all__ = [
    "User",
    "authenticate",
    "bootstrap_admin_if_needed",
    "change_password",
    "create_user",
    "delete_user",
    "load_users",
    "logout",
    "render_user_admin",
    "require_auth",
    "set_role",
    "validate_password_strength",
]
