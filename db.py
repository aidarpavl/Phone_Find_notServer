"""
Публичный интерфейс хранилища.

Реальная работа — в storage.py (SQLite / Postgres / Firestore, выбирается
автоматически по настройкам). Этот модуль оставляет прежние функции, чтобы
остальной код не менялся.
"""

import storage


def init_db():
    storage.get_storage()


def active_backend_name():
    try:
        return storage.get_storage().name
    except Exception as e:
        return f"ошибка: {e}"


def normalize_phone(phone: str) -> str:
    """Единый вид номера: только цифры и ведущий +."""
    phone = (phone or "").strip()
    keep = []
    for i, ch in enumerate(phone):
        if ch.isdigit():
            keep.append(ch)
        elif ch == "+" and i == 0:
            keep.append(ch)
    return "".join(keep)


def register_device(phone, name=""):
    phone = normalize_phone(phone)
    if phone:
        storage.get_storage().register(phone, name)


def update_location(phone, lat, lon, accuracy=None):
    phone = normalize_phone(phone)
    if phone:
        storage.get_storage().update_location(phone, lat, lon, accuracy)


def list_devices():
    return storage.get_storage().list()


def get_device(phone):
    phone = normalize_phone(phone)
    if not phone:
        return None
    return storage.get_storage().get(phone)


def request_ring(phone):
    phone = normalize_phone(phone)
    if phone:
        storage.get_storage().request_ring(phone)


def clear_ring(phone):
    phone = normalize_phone(phone)
    if phone:
        storage.get_storage().clear_ring(phone)


def remove_device(phone):
    phone = normalize_phone(phone)
    if phone:
        storage.get_storage().remove(phone)
