"""
Хранилище устройств с тремя взаимозаменяемыми бэкендами.

Выбор бэкенда — по переменным окружения (их удобно задавать через
Streamlit secrets, см. app.py и README):

  • Postgres  — если задан DATABASE_URL (Supabase / Neon / любой Postgres)
  • Firestore — если заданы FIREBASE_PROJECT_ID и FIREBASE_API_KEY
  • SQLite    — иначе (локальный файл devices.db), для запуска на одной машине

Можно форсировать явно: DB_BACKEND = postgres | firebase | sqlite

У всех бэкендов одинаковый набор методов:
    init(), register(phone, name), update_location(phone, lat, lon, acc),
    list(), get(phone), request_ring(phone), clear_ring(phone), remove(phone)
Поле устройства — словарь:
    phone, name, lat, lon, accuracy, updated_at (unix), ring (0/1)
"""

import os
import time
from pathlib import Path
from urllib.parse import quote


# ─────────────────────────────────────────────────────────────────────────────
# SQLite
# ─────────────────────────────────────────────────────────────────────────────
class SQLiteStorage:
    name = "SQLite (локально)"

    def __init__(self, path=None):
        import sqlite3  # noqa
        self.sqlite3 = sqlite3
        self.path = str(path or Path(__file__).parent / "devices.db")

    def _conn(self):
        conn = self.sqlite3.connect(self.path)
        conn.row_factory = self.sqlite3.Row
        return conn

    def init(self):
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS devices (
                    phone TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL,
                    accuracy REAL, updated_at REAL, ring INTEGER DEFAULT 0)"""
            )

    def register(self, phone, name=""):
        with self._conn() as c:
            row = c.execute("SELECT phone FROM devices WHERE phone=?", (phone,)).fetchone()
            if row:
                if name:
                    c.execute("UPDATE devices SET name=? WHERE phone=?", (name, phone))
            else:
                c.execute(
                    "INSERT INTO devices (phone,name,updated_at,ring) VALUES (?,?,?,0)",
                    (phone, name or phone, time.time()),
                )

    def update_location(self, phone, lat, lon, accuracy=None):
        with self._conn() as c:
            c.execute(
                """INSERT INTO devices (phone,name,lat,lon,accuracy,updated_at,ring)
                   VALUES (?,?,?,?,?,?,0)
                   ON CONFLICT(phone) DO UPDATE SET
                     lat=excluded.lat, lon=excluded.lon,
                     accuracy=excluded.accuracy, updated_at=excluded.updated_at""",
                (phone, phone, lat, lon, accuracy, time.time()),
            )

    def list(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM devices ORDER BY updated_at DESC").fetchall()]

    def get(self, phone):
        with self._conn() as c:
            r = c.execute("SELECT * FROM devices WHERE phone=?", (phone,)).fetchone()
            return dict(r) if r else None

    def request_ring(self, phone):
        with self._conn() as c:
            c.execute("UPDATE devices SET ring=1 WHERE phone=?", (phone,))

    def clear_ring(self, phone):
        with self._conn() as c:
            c.execute("UPDATE devices SET ring=0 WHERE phone=?", (phone,))

    def remove(self, phone):
        with self._conn() as c:
            c.execute("DELETE FROM devices WHERE phone=?", (phone,))


# ─────────────────────────────────────────────────────────────────────────────
# Postgres (Supabase, Neon, любой управляемый Postgres)
# ─────────────────────────────────────────────────────────────────────────────
class PostgresStorage:
    name = "Postgres (облако)"

    def __init__(self, dsn):
        import psycopg2  # noqa
        import psycopg2.extras  # noqa
        self.psycopg2 = psycopg2
        self.extras = psycopg2.extras
        self.dsn = dsn

    def _conn(self):
        return self.psycopg2.connect(self.dsn)

    def init(self):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS devices (
                    phone TEXT PRIMARY KEY, name TEXT, lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION, accuracy DOUBLE PRECISION,
                    updated_at DOUBLE PRECISION, ring INTEGER DEFAULT 0)"""
            )
            conn.commit()

    def register(self, phone, name=""):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO devices (phone,name,updated_at,ring)
                   VALUES (%s,%s,%s,0)
                   ON CONFLICT (phone) DO UPDATE SET
                     name = CASE WHEN %s <> '' THEN EXCLUDED.name ELSE devices.name END""",
                (phone, name or phone, time.time(), name or ""),
            )
            conn.commit()

    def update_location(self, phone, lat, lon, accuracy=None):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO devices (phone,name,lat,lon,accuracy,updated_at,ring)
                   VALUES (%s,%s,%s,%s,%s,%s,0)
                   ON CONFLICT (phone) DO UPDATE SET
                     lat=EXCLUDED.lat, lon=EXCLUDED.lon,
                     accuracy=EXCLUDED.accuracy, updated_at=EXCLUDED.updated_at""",
                (phone, phone, lat, lon, accuracy, time.time()),
            )
            conn.commit()

    def list(self):
        with self._conn() as conn, conn.cursor(cursor_factory=self.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM devices ORDER BY updated_at DESC NULLS LAST")
            return [dict(r) for r in cur.fetchall()]

    def get(self, phone):
        with self._conn() as conn, conn.cursor(cursor_factory=self.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM devices WHERE phone=%s", (phone,))
            r = cur.fetchone()
            return dict(r) if r else None

    def request_ring(self, phone):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE devices SET ring=1 WHERE phone=%s", (phone,))
            conn.commit()

    def clear_ring(self, phone):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE devices SET ring=0 WHERE phone=%s", (phone,))
            conn.commit()

    def remove(self, phone):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM devices WHERE phone=%s", (phone,))
            conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Firestore (REST API — без тяжёлого SDK, нужен project id + web api key)
# ─────────────────────────────────────────────────────────────────────────────
class FirestoreStorage:
    name = "Firebase Firestore (облако)"

    def __init__(self, project_id, api_key):
        import requests  # noqa
        self.requests = requests
        self.project_id = project_id
        self.api_key = api_key
        self.base = (f"https://firestore.googleapis.com/v1/projects/"
                     f"{project_id}/databases/(default)/documents")

    # --- кодирование типов Firestore ---
    @staticmethod
    def _to_fields(d):
        fields = {}
        for k, v in d.items():
            if v is None:
                fields[k] = {"nullValue": None}
            elif isinstance(v, bool):
                fields[k] = {"booleanValue": v}
            elif isinstance(v, int):
                fields[k] = {"integerValue": str(v)}
            elif isinstance(v, float):
                fields[k] = {"doubleValue": v}
            else:
                fields[k] = {"stringValue": str(v)}
        return {"fields": fields}

    @staticmethod
    def _from_doc(doc):
        out = {}
        for k, v in (doc.get("fields") or {}).items():
            if "integerValue" in v:
                out[k] = int(v["integerValue"])
            elif "doubleValue" in v:
                out[k] = float(v["doubleValue"])
            elif "booleanValue" in v:
                out[k] = bool(v["booleanValue"])
            elif "nullValue" in v:
                out[k] = None
            else:
                out[k] = v.get("stringValue")
        return out

    def _doc_url(self, phone, mask_fields=None):
        url = f"{self.base}/devices/{quote(phone, safe='')}?key={self.api_key}"
        if mask_fields:
            url += "".join(f"&updateMask.fieldPaths={f}" for f in mask_fields)
        return url

    def init(self):
        # В Firestore схема не нужна. Проверим доступность проекта.
        self.requests.get(f"{self.base}/devices?key={self.api_key}&pageSize=1", timeout=15)

    def _patch(self, phone, data):
        # PATCH с updateMask обновляет только переданные поля, не затирая остальные
        self.requests.patch(
            self._doc_url(phone, mask_fields=list(data.keys())),
            json=self._to_fields(data), timeout=15,
        )

    def register(self, phone, name=""):
        cur = self.get(phone)
        if cur is None:
            self._patch(phone, {"phone": phone, "name": name or phone,
                                "updated_at": time.time(), "ring": 0})
        elif name:
            self._patch(phone, {"name": name})

    def update_location(self, phone, lat, lon, accuracy=None):
        self._patch(phone, {
            "phone": phone, "lat": float(lat), "lon": float(lon),
            "accuracy": float(accuracy) if accuracy is not None else 0.0,
            "updated_at": time.time(),
        })

    def list(self):
        r = self.requests.get(f"{self.base}/devices?key={self.api_key}&pageSize=300", timeout=15)
        docs = (r.json() or {}).get("documents", [])
        items = [self._from_doc(d) for d in docs]
        items.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
        return items

    def get(self, phone):
        r = self.requests.get(self._doc_url(phone), timeout=15)
        if r.status_code == 200:
            return self._from_doc(r.json())
        return None

    def request_ring(self, phone):
        self._patch(phone, {"ring": 1})

    def clear_ring(self, phone):
        self._patch(phone, {"ring": 0})

    def remove(self, phone):
        self.requests.delete(self._doc_url(phone), timeout=15)


# ─────────────────────────────────────────────────────────────────────────────
# Автовыбор бэкенда
# ─────────────────────────────────────────────────────────────────────────────
_storage = None


def get_storage():
    global _storage
    if _storage is not None:
        return _storage

    backend = (os.environ.get("DB_BACKEND") or "").strip().lower()
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    fb_project = os.environ.get("FIREBASE_PROJECT_ID")
    fb_key = os.environ.get("FIREBASE_API_KEY")

    if not backend:
        if dsn:
            backend = "postgres"
        elif fb_project and fb_key:
            backend = "firebase"
        else:
            backend = "sqlite"

    if backend == "postgres":
        if not dsn:
            raise RuntimeError("DB_BACKEND=postgres, но DATABASE_URL не задан")
        _storage = PostgresStorage(dsn)
    elif backend == "firebase":
        if not (fb_project and fb_key):
            raise RuntimeError("DB_BACKEND=firebase, но FIREBASE_PROJECT_ID/FIREBASE_API_KEY не заданы")
        _storage = FirestoreStorage(fb_project, fb_key)
    else:
        _storage = SQLiteStorage()

    _storage.init()
    return _storage
