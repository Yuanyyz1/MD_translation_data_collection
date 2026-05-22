from passlib.context import CryptContext
from starlette.requests import Request

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_USER_ID_KEY = "user_id"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def login_user(request: Request, user_id: int) -> None:
    request.session[SESSION_USER_ID_KEY] = user_id


def logout_user(request: Request) -> None:
    request.session.clear()


def get_user_id_from_session(request: Request) -> int | None:
    return request.session.get(SESSION_USER_ID_KEY)
