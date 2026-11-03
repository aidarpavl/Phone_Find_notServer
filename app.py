"""
Семейный локатор устройств — Streamlit.

Что это:
  • Устройства добавляются по номеру телефона (номер = идентификатор).
  • Каждое устройство САМО делится своим GPS, когда у него открыто приложение
    (режим «Моё устройство»). Это согласная модель, как в «Найти устройство»
    или семейных локаторах.
  • На карте 2GIS видно, где находятся добавленные устройства.
  • Кнопка «Подать сигнал» просит нужное устройство громко зазвонить,
    чтобы его можно было найти ещё и по звуку.

Чего тут НЕТ и быть не может:
  определения местоположения чужого телефона по одному лишь номеру без его
  участия — так не умеет ни один легальный инструмент.
"""

import os
import time
import streamlit as st

import db


def _load_db_config_from_secrets():
    """Пробрасываем настройки БД из Streamlit secrets в переменные окружения,
    чтобы storage.py сам выбрал бэкенд (Postgres / Firebase / SQLite)."""
    for key in ("DB_BACKEND", "DATABASE_URL", "POSTGRES_URL",
                "FIREBASE_PROJECT_ID", "FIREBASE_API_KEY"):
        try:
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
        except Exception:
            pass


_load_db_config_from_secrets()

# ── необязательные компоненты ────────────────────────────────────────────────
try:
    from streamlit_geolocation import streamlit_geolocation
    HAS_GEO = True
except Exception:
    HAS_GEO = False

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False


st.set_page_config(page_title="Локатор устройств", page_icon="📍", layout="wide")
db.init_db()


def fmt_age(updated_at):
    if not updated_at:
        return "нет данных"
    sec = int(time.time() - updated_at)
    if sec < 60:
        return f"{sec} сек назад"
    if sec < 3600:
        return f"{sec // 60} мин назад"
    if sec < 86400:
        return f"{sec // 3600} ч назад"
    return f"{sec // 86400} дн назад"


# ── карта ────────────────────────────────────────────────────────────────────
def render_2gis_map(devices, api_key, height=460):
    """Карта 2GIS MapGL с маркерами устройств. Нужен ключ 2GIS MapGL."""
    pts = [d for d in devices if d.get("lat") is not None and d.get("lon") is not None]
    if pts:
        center_lat = sum(d["lat"] for d in pts) / len(pts)
        center_lon = sum(d["lon"] for d in pts) / len(pts)
    else:
        center_lat, center_lon = 51.1605, 71.4704  # Астана по умолчанию

    markers_js = ",".join(
        f'{{lat:{d["lat"]},lon:{d["lon"]},label:{_json_str(d["name"])}}}'
        for d in pts
    )

    html = f"""
    <div id="map" style="width:100%;height:{height}px;border-radius:12px;overflow:hidden;"></div>
    <script src="https://mapgl.2gis.com/api/js/v1"></script>
    <script>
      const markers = [{markers_js}];
      const map = new mapgl.Map('map', {{
        center: [{center_lon}, {center_lat}],
        zoom: {13 if len(pts) <= 1 else 11},
        key: {_json_str(api_key)}
      }});
      markers.forEach(m => {{
        const mk = new mapgl.Marker(map, {{ coordinates: [m.lon, m.lat] }});
        const lbl = new mapgl.Label(map, {{
          coordinates: [m.lon, m.lat], text: m.label, fontSize: 13, color: '#111',
          haloRadius: 2, haloColor: '#fff', offset: [0, -42]
        }});
      }});
    </script>
    """
    st.components.v1.html(html, height=height + 10)


def render_leaflet_map(devices, height=460):
    """Запасная карта (OpenStreetMap) — если ключ 2GIS не указан."""
    pts = [d for d in devices if d.get("lat") is not None and d.get("lon") is not None]
    if pts:
        center_lat = sum(d["lat"] for d in pts) / len(pts)
        center_lon = sum(d["lon"] for d in pts) / len(pts)
    else:
        center_lat, center_lon = 51.1605, 71.4704

    markers_js = ",".join(
        f'{{lat:{d["lat"]},lon:{d["lon"]},label:{_json_str(d["name"])}}}'
        for d in pts
    )
    html = f"""
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <div id="map" style="width:100%;height:{height}px;border-radius:12px;"></div>
    <script>
      const markers = [{markers_js}];
      const map = L.map('map').setView([{center_lat},{center_lon}], {13 if len(pts) <= 1 else 11});
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
        {{maxZoom:19, attribution:'© OpenStreetMap'}}).addTo(map);
      markers.forEach(m => {{
        L.marker([m.lat, m.lon]).addTo(map).bindPopup(m.label);
      }});
    </script>
    """
    st.components.v1.html(html, height=height + 10)


def _json_str(s):
    import json
    return json.dumps(s if s is not None else "")


# ── звук сигнала ─────────────────────────────────────────────────────────────
def play_ring(seconds=6):
    """Громкий звук звонка через WebAudio (без аудиофайлов)."""
    html = f"""
    <script>
      (function() {{
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = new Ctx();
        const dur = {seconds};
        const start = ctx.currentTime;
        // чередуем два тона, как классический звонок
        for (let i = 0; i < dur * 2; i++) {{
          const t0 = start + i * 0.5;
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'square';
          osc.frequency.value = (i % 2 === 0) ? 880 : 660;
          gain.gain.setValueAtTime(0.0001, t0);
          gain.gain.exponentialRampToValueAtTime(0.6, t0 + 0.05);
          gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.45);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(t0); osc.stop(t0 + 0.5);
        }}
      }})();
    </script>
    <div style="padding:10px;background:#ffe9e9;border-radius:8px;color:#b00;font-weight:600;">
      🔔 Сигнал проигрывается… слушайте, где звонит телефон.
    </div>
    """
    st.components.v1.html(html, height=60)


# ── боковая панель ───────────────────────────────────────────────────────────
def _secret(key):
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


st.sidebar.title("📍 Локатор устройств")
api_key = st.sidebar.text_input(
    "Ключ 2GIS MapGL (необязательно)",
    value=_secret("DGIS_KEY"),
    type="password",
    help="Получить бесплатно: https://dev.2gis.ru/. Без ключа покажем карту OpenStreetMap.",
)
mode = st.sidebar.radio(
    "Режим",
    ["🔎 Искать устройства", "📲 Моё устройство (делюсь локацией)"],
)

st.sidebar.markdown("---")
st.sidebar.caption(f"🗄 Хранилище: **{db.active_backend_name()}**")
st.sidebar.caption(
    "Это согласная модель. Устройство видно на карте, только если на нём открыт "
    "режим «Моё устройство» и оно само делится GPS."
)


# ══════════════════════════════════════════════════════════════════════════════
# РЕЖИМ 1: ИСКАТЬ УСТРОЙСТВА
# ══════════════════════════════════════════════════════════════════════════════
if mode.startswith("🔎"):
    st.title("Поиск добавленных устройств")

    if HAS_AUTOREFRESH:
        st_autorefresh(interval=5000, key="finder_refresh")

    with st.expander("➕ Добавить устройство по номеру", expanded=False):
        c1, c2 = st.columns([2, 2])
        new_phone = c1.text_input("Номер телефона", placeholder="+7 701 234 56 78")
        new_name = c2.text_input("Имя (необязательно)", placeholder="Папа / Машина / Рабочий")
        if st.button("Добавить", type="primary"):
            if db.normalize_phone(new_phone):
                db.register_device(new_phone, new_name)
                st.success(f"Добавлено: {new_name or new_phone}. Теперь на этом телефоне "
                           f"нужно открыть приложение в режиме «Моё устройство».")
            else:
                st.error("Введите корректный номер.")

    devices = db.list_devices()

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Карта")
        if api_key:
            render_2gis_map(devices, api_key)
        else:
            st.info("Ключ 2GIS не указан — показана карта OpenStreetMap. "
                    "Добавьте ключ в боковой панели для карты 2GIS.")
            render_leaflet_map(devices)

    with right:
        st.subheader("Устройства")
        if not devices:
            st.caption("Пока ничего не добавлено.")
        for d in devices:
            with st.container(border=True):
                st.markdown(f"**{d['name']}**  \n`{d['phone']}`")
                if d["lat"] is not None:
                    st.caption(f"📍 {d['lat']:.5f}, {d['lon']:.5f} · "
                               f"±{int(d['accuracy'] or 0)} м · {fmt_age(d['updated_at'])}")
                else:
                    st.caption("Локация ещё не получена (устройство не делится GPS).")
                b1, b2 = st.columns(2)
                if b1.button("🔔 Подать сигнал", key=f"ring_{d['phone']}"):
                    db.request_ring(d["phone"])
                    st.toast(f"Запрошен сигнал на {d['name']}")
                if b2.button("🗑 Удалить", key=f"del_{d['phone']}"):
                    db.remove_device(d["phone"])
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# РЕЖИМ 2: МОЁ УСТРОЙСТВО
# ══════════════════════════════════════════════════════════════════════════════
else:
    st.title("Моё устройство")
    st.write("Открой эту страницу на телефоне, который хочешь сделать видимым на карте.")

    my_phone = st.text_input("Номер этого телефона", placeholder="+7 701 234 56 78")

    if HAS_AUTOREFRESH:
        st_autorefresh(interval=4000, key="device_refresh")

    if db.normalize_phone(my_phone):
        db.register_device(my_phone)

        st.markdown("#### 1. Поделиться местоположением")
        if HAS_GEO:
            loc = streamlit_geolocation()
            if loc and loc.get("latitude") is not None:
                db.update_location(my_phone, loc["latitude"], loc["longitude"],
                                   loc.get("accuracy"))
                st.success(f"Отправлено: {loc['latitude']:.5f}, {loc['longitude']:.5f} "
                           f"(±{int(loc.get('accuracy') or 0)} м)")
            else:
                st.info("Нажми на значок, чтобы разрешить доступ к геолокации.")
        else:
            st.warning("Компонент геолокации не установлен. "
                       "Установи: pip install streamlit-geolocation")

        st.markdown("#### 2. Звуковой сигнал")
        st.caption("Если кто-то запросит сигнал, этот телефон громко зазвонит. "
                   "Один раз нажми кнопку ниже, чтобы разрешить звук в браузере.")
        st.button("🔓 Разрешить звук")

        dev = db.get_device(my_phone)
        if dev and dev.get("ring"):
            play_ring()
            db.clear_ring(my_phone)

        st.markdown("---")
        if dev and dev.get("lat") is not None:
            st.caption(f"Последняя отправленная точка: {dev['lat']:.5f}, {dev['lon']:.5f} · "
                       f"{fmt_age(dev['updated_at'])}")
    else:
        st.info("Введите номер телефона, чтобы начать делиться местоположением.")
