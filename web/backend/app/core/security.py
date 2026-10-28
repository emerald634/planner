from threading import BoundedSemaphore

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
_hash_slots = BoundedSemaphore(2)


class HashCapacityExceeded(RuntimeError):
    pass


def hash_password(password: str) -> str:
    if not _hash_slots.acquire(blocking=False):
        raise HashCapacityExceeded("Проверка пароля занята. Повторите позднее.")
    try:
        return password_hash.hash(password)
    finally:
        _hash_slots.release()


def verify_password(password: str, hashed_password: str) -> bool:
    if not _hash_slots.acquire(blocking=False):
        raise HashCapacityExceeded("Проверка пароля занята. Повторите позднее.")
    try:
        return password_hash.verify(password, hashed_password)
    finally:
        _hash_slots.release()
