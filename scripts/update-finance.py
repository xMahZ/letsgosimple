import json
import bcchapi
from datetime import datetime, timedelta
import pytz
import os
import sys

# ---------------------------
# SERIES BCCH
# ---------------------------
UF_SERIE  = "F073.UFF.PRE.Z.D"
USD_SERIE = "F073.TCO.PRE.Z.D"
UTM_SERIE = "F073.UTR.PRE.Z.M"

usr = os.getenv("BCCH_USER")
pwd = os.getenv("BCCH_PASS")

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "src", "data", "cl-finance.json")

TZ = pytz.timezone("America/Santiago")


# ---------------------------
# UTIL: HORA CHILE
# ---------------------------
def now_chile():
    return datetime.now(TZ)


# ---------------------------
# UTIL: ES DÍA HÁBIL
# ---------------------------
def is_business_day(dt):
    return dt.weekday() < 5  # lunes=0 ... viernes=4


# ---------------------------
# LOAD / SAVE JSON
# ---------------------------
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"country": "CL", "currency": "CLP", "rates_history": [], "latest": {}}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------
# UTIL: UPSERT HISTÓRICO
# Solo escribe si el campo estaba en 0 o no existía.
# Nunca sobreescribe un valor real con 0.
# ---------------------------
def upsert(history, new_entry):
    index = {item["date"]: item for item in history}

    date = new_entry["date"]
    existing = index.get(date, {})

    merged = {
        "date": date,
        "uf":  new_entry["uf"]  if new_entry.get("uf",  0) != 0 else existing.get("uf",  0),
        "usd": new_entry["usd"] if new_entry.get("usd", 0) != 0 else existing.get("usd", 0),
        "utm": new_entry["utm"] if new_entry.get("utm", 0) != 0 else existing.get("utm", 0),
    }

    index[date] = merged
    return sorted(index.values(), key=lambda x: x["date"], reverse=True)


# ---------------------------
# UTIL: VALOR N DÍAS ATRÁS
# ---------------------------
def get_value_days_ago(history, base_date, days, key):
    base   = datetime.strptime(base_date, "%Y-%m-%d")
    target = base - timedelta(days=days)
    best   = None

    for r in history:
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        if d <= target:
            if best is None or d > datetime.strptime(best["date"], "%Y-%m-%d"):
                best = r

    if not best:
        return None, None

    val = best.get(key)
    if not val or val == 0:
        return None, None

    return val, best["date"]


# ---------------------------
# UTIL: VARIACIÓN %
# ---------------------------
def variation(latest, past):
    if past is None or past == 0:
        return None
    return round(((latest - past) / past) * 100, 6)


# ---------------------------
# UTIL: FETCH SERIE BCCH (rango)
# ---------------------------
def fetch_serie(siete, series_id, desde, hasta):
    df = siete.cuadro(
        series=[series_id],
        nombres=["value"],
        desde=desde,
        hasta=hasta
    ).dropna()
    return df


# ---------------------------
# JOB 1 — 10:05
# Actualiza serie UF + UTM en histórico
# Trae todos los días desde el último registrado hasta hoy
# ---------------------------
def job_update_uf_utm():
    print("=== JOB 1: Actualizar serie UF + UTM ===")

    data    = load_json()
    history = data.get("rates_history", [])

    # Determinar desde qué fecha pedir
    if history:
        last_date = max(r["date"] for r in history)
        desde = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        desde = "2026-01-01"

    hasta = (now_chile() + timedelta(days=10)).strftime("%Y-%m-%d")  # UF publica días futuros

    if desde > hasta:
        print("UF/UTM: histórico al día, nada que agregar.")
        save_json(data)
        return

    print(f"Pidiendo UF desde {desde} hasta {hasta}")

    bcch   = bcchapi.Siete(usr=usr, pwd=pwd)
    df_uf  = fetch_serie(bcch, UF_SERIE,  desde, hasta)
    df_utm = fetch_serie(bcch, UTM_SERIE, "2025-01-01", hasta)  # UTM mensual, traemos largo

    # Indexar UTM por fecha para lookup fácil
    utm_by_date = {}
    for idx, row in df_utm.iterrows():
        utm_by_date[idx.strftime("%Y-%m-%d")] = float(row["value"])

    # Función para obtener UTM vigente en una fecha (último valor <= fecha)
    def get_utm_for_date(date_str):
        target = datetime.strptime(date_str, "%Y-%m-%d")
        best_date = None
        best_val  = 0
        for d_str, val in utm_by_date.items():
            d = datetime.strptime(d_str, "%Y-%m-%d")
            if d <= target:
                if best_date is None or d > best_date:
                    best_date = d
                    best_val  = val
        return best_val

    nuevos = 0
    for idx, row in df_uf.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        utm_val  = get_utm_for_date(date_str)

        entry = {
            "date": date_str,
            "uf":   round(float(row["value"]), 2),
            "usd":  0,
            "utm":  utm_val
        }
        history = upsert(history, entry)
        nuevos += 1

    print(f"UF/UTM: {nuevos} días procesados.")
    data["rates_history"] = history
    save_json(data)
    print("JOB 1 OK")


# ---------------------------
# JOB 2 — 17:35
# Escribe el dólar observado del día siguiente en el histórico
# Si no hay publicación (finde/feriado), hereda el último valor conocido
# ---------------------------
def job_update_dolar():
    print("=== JOB 2: Actualizar dólar observado ===")

    now = now_chile()

    # Guardar en el día siguiente (el dólar observado publicado hoy rige mañana)
    tomorrow     = now + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    data    = load_json()
    history = data.get("rates_history", [])

    bcch = bcchapi.Siete(usr=usr, pwd=pwd)

    usd_value = None
    usd_date  = None

    if is_business_day(now):
        # Intentar traer el valor publicado hoy
        hoy_str   = now.strftime("%Y-%m-%d")
        try:
            df = fetch_serie(bcch, USD_SERIE, hoy_str, hoy_str)
            if not df.empty:
                usd_value = round(float(df["value"].iloc[-1]), 2)
                usd_date  = hoy_str
                print(f"Dólar obtenido: {usd_value} (publicado {usd_date})")
        except Exception as e:
            print(f"No se pudo obtener dólar de hoy: {e}")

    # Si no hay valor (finde, feriado o falló la API), heredar el último conocido
    if usd_value is None:
        for r in history:
            if r.get("usd", 0) != 0:
                usd_value = r["usd"]
                usd_date  = r["date"]
                print(f"Dólar heredado desde {usd_date}: {usd_value}")
                break

    if usd_value is None:
        print("No hay valor de dólar disponible, abortando JOB 2.")
        return

    # Escribir en el día siguiente
    entry = {
        "date": tomorrow_str,
        "uf":   0,
        "usd":  usd_value,
        "utm":  0
    }
    history = upsert(history, entry)
    print(f"Dólar {usd_value} escrito en {tomorrow_str}")

    data["rates_history"] = history
    save_json(data)
    print("JOB 2 OK")


# ---------------------------
# JOB 3 — 00:05
# Recalcula latest con los valores del día de hoy
# ---------------------------
def job_update_latest():
    print("=== JOB 3: Recalcular latest ===")

    now      = now_chile()
    hoy_str  = now.strftime("%Y-%m-%d")

    data    = load_json()
    history = data.get("rates_history", [])

    # Buscar el registro de hoy en el histórico
    today_entry = next((r for r in history if r["date"] == hoy_str), None)

    if not today_entry:
        print(f"No hay entrada para {hoy_str} en el histórico. Abortando JOB 3.")
        return

    uf  = today_entry.get("uf",  0)
    usd = today_entry.get("usd", 0)
    utm = today_entry.get("utm", 0)

    # Si algún valor es 0, intentar heredar del día anterior más cercano
    if usd == 0:
        for r in history:
            if r["date"] < hoy_str and r.get("usd", 0) != 0:
                usd = r["usd"]
                print(f"USD heredado desde {r['date']}")
                break

    if utm == 0:
        for r in history:
            if r["date"] <= hoy_str and r.get("utm", 0) != 0:
                utm = r["utm"]
                print(f"UTM heredado desde {r['date']}")
                break

    # ---------------------------
    # VARIACIONES
    # ---------------------------
    def build_variations(key, base_date, latest_value):
        if not latest_value or latest_value == 0:
            return {
                "7d":  {"value": None, "pct": None, "date": None},
                "30d": {"value": None, "pct": None, "date": None},
                "60d": {"value": None, "pct": None, "date": None},
            }

        v7,  d7  = get_value_days_ago(history, base_date, 7,  key)
        v30, d30 = get_value_days_ago(history, base_date, 30, key)
        v60, d60 = get_value_days_ago(history, base_date, 60, key)

        return {
            "7d":  {"value": v7,  "pct": variation(latest_value, v7),  "date": d7},
            "30d": {"value": v30, "pct": variation(latest_value, v30), "date": d30},
            "60d": {"value": v60, "pct": variation(latest_value, v60), "date": d60},
        }

    latest = {
        "date": hoy_str,
        "uf":   uf,
        "usd":  usd,
        "utm":  utm,
        "dates": {
            "uf":  hoy_str,
            "usd": hoy_str,
            "utm": hoy_str,
        },
        "variations": {
            "uf":  build_variations("uf",  hoy_str, uf),
            "usd": build_variations("usd", hoy_str, usd),
            "utm": build_variations("utm", hoy_str, utm),
        }
    }

    data["latest"] = latest
    save_json(data)
    print(f"Latest actualizado: UF={uf} USD={usd} UTM={utm}")
    print("JOB 3 OK")


# ---------------------------
# ENTRYPOINT
# Uso: python update-finance.py [job1|job2|job3]
# Sin argumento: corre los 3 en orden
# ---------------------------
if __name__ == "__main__":

    job = sys.argv[1] if len(sys.argv) > 1 else "all"

    if job == "job1":
        job_update_uf_utm()
    elif job == "job2":
        job_update_dolar()
    elif job == "job3":
        job_update_latest()
    elif job == "all":
        job_update_uf_utm()
        job_update_dolar()
        job_update_latest()
    else:
        print(f"Job desconocido: {job}. Usa job1, job2, job3 o all.")
        sys.exit(1)