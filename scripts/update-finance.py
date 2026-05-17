import json
import bcchapi
from datetime import datetime, timedelta
import os
import sys
from zoneinfo import ZoneInfo

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

TZ = ZoneInfo("America/Santiago")


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

    bcch  = bcchapi.Siete(usr=usr, pwd=pwd)
    hasta = (now_chile() + timedelta(days=10)).strftime("%Y-%m-%d")

    # Traer UTM desde 2025 completo (mensual, liviano)
    df_utm = fetch_serie(bcch, UTM_SERIE, "2025-01-01", hasta)

    # Indexar UTM por fecha
    utm_by_date = {}
    for idx, row in df_utm.iterrows():
        utm_by_date[idx.strftime("%Y-%m-%d")] = float(row["value"])

    # Función para obtener UTM vigente en una fecha (último valor publicado <= fecha)
    def get_utm_for_date(date_str):
        target    = datetime.strptime(date_str, "%Y-%m-%d")
        best_date = None
        best_val  = 0
        for d_str, val in utm_by_date.items():
            d = datetime.strptime(d_str, "%Y-%m-%d")
            if d <= target:
                if best_date is None or d > best_date:
                    best_date = d
                    best_val  = val
        return best_val

    # ---------------------------
    # BACKFILL: rellenar utm=0 en histórico existente
    # ---------------------------
    backfilled = 0
    for r in history:
        if r.get("utm", 0) == 0:
            utm_val = get_utm_for_date(r["date"])
            if utm_val != 0:
                r["utm"] = utm_val
                backfilled += 1

    if backfilled:
        print(f"UTM backfill: {backfilled} dias rellenados en historico existente.")

    # ---------------------------
    # NUEVOS DÍAS: desde el último hasta hoy + 10
    # ---------------------------
    if history:
        last_date = max(r["date"] for r in history)
        desde     = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        desde = "2026-01-01"

    nuevos = 0
    if desde <= hasta:
        print(f"Pidiendo UF desde {desde} hasta {hasta}")
        df_uf = fetch_serie(bcch, UF_SERIE, desde, hasta)

        for idx, row in df_uf.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            entry    = {
                "date": date_str,
                "uf":   round(float(row["value"]), 2),
                "usd":  0,
                "utm":  get_utm_for_date(date_str)
            }
            history = upsert(history, entry)
            nuevos += 1

        print(f"UF: {nuevos} dias nuevos agregados.")
    else:
        print("UF: historico al dia, nada que agregar.")
        # Aunque no haya días nuevos, igual guardamos el backfill de UTM

    data["rates_history"] = history
    save_json(data)
    print("JOB 1 OK")


# ---------------------------
# JOB 2 — 17:35
# Escribe el dólar observado del día siguiente en el histórico
# Si no hay publicación (finde/feriado), hereda el último valor conocido
# ---------------------------
def job_update_dolar():
    print("=== JOB 2: Actualizar dolar observado ===")

    now          = now_chile()
    hoy_str      = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    data    = load_json()
    history = data.get("rates_history", [])

    bcch = bcchapi.Siete(usr=usr, pwd=pwd)

    # ---------------------------
    # BACKFILL: rellenar usd=0 en histórico existente (últimos 90 días)
    # ---------------------------
    dias_sin_usd = [r["date"] for r in history if r.get("usd", 0) == 0]

    if dias_sin_usd:
        fecha_min = min(dias_sin_usd)
        print(f"USD backfill: pidiendo desde {fecha_min} hasta {hoy_str}")
        try:
            df_hist = fetch_serie(bcch, USD_SERIE, fecha_min, hoy_str)

            # Construir mapa fecha -> valor
            usd_hist = {}
            for idx, row in df_hist.iterrows():
                usd_hist[idx.strftime("%Y-%m-%d")] = round(float(row["value"]), 2)

            # El BCCH devuelve el dólar con la fecha en que rige (no en que se publica)
            # Entonces history[date].usd = usd_hist[date] directamente
            # Si no hay dato exacto (finde/feriado), buscamos el día hábil anterior
            backfilled = 0
            for r in history:
                if r.get("usd", 0) == 0:
                    check_date = datetime.strptime(r["date"], "%Y-%m-%d")
                    for _ in range(5):
                        check_str = check_date.strftime("%Y-%m-%d")
                        if check_str in usd_hist:
                            r["usd"] = usd_hist[check_str]
                            backfilled += 1
                            break
                        check_date -= timedelta(days=1)

            print(f"USD backfill: {backfilled} dias rellenados.")
        except Exception as e:
            print(f"USD backfill error: {e}")

    # ---------------------------
    # HOY: obtener valor publicado hoy (rige mañana)
    # ---------------------------
    usd_value = None

    if is_business_day(now):
        try:
            df = fetch_serie(bcch, USD_SERIE, hoy_str, hoy_str)
            if not df.empty:
                usd_value = round(float(df["value"].iloc[-1]), 2)
                print(f"Dolar obtenido: {usd_value} (publicado {hoy_str}, rige {tomorrow_str})")
        except Exception as e:
            print(f"No se pudo obtener dolar de hoy: {e}")

    # Si no hay valor nuevo, heredar el último conocido
    if usd_value is None:
        for r in history:
            if r.get("usd", 0) != 0:
                usd_value = r["usd"]
                print(f"Dolar heredado desde {r['date']}: {usd_value}")
                break

    if usd_value is None:
        print("No hay valor de dolar disponible, abortando JOB 2.")
        return

    # Escribir en el día siguiente
    entry = {"date": tomorrow_str, "uf": 0, "usd": usd_value, "utm": 0}
    history = upsert(history, entry)
    print(f"Dolar {usd_value} escrito en {tomorrow_str}")

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