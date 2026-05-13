import json
import bcchapi
from datetime import datetime, timedelta
import os

UF_SERIE = "F073.UFF.PRE.Z.D"
USD_SERIE = "F073.TCO.PRE.Z.D"
UTM_SERIE = "F073.UTR.PRE.Z.M"

usr = os.getenv("BCCH_USER")
pwd = os.getenv("BCCH_PASS")

JSON_PATH = "data/cl-finance.json"


# ---------------------------
# UTIL: FETCH BCCH
# ---------------------------
def fetch_last(siete, series_id, days_back=30):
    hoy = datetime.today()
    desde = (hoy - timedelta(days=days_back)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")

    df = siete.cuadro(
        series=[series_id],
        nombres=["value"],
        desde=desde,
        hasta=hasta
    ).dropna()

    last_date = df.index[-1]
    last_value = float(df["value"].iloc[-1])

    return last_date.strftime("%Y-%m-%d"), last_value


# ---------------------------
# LOAD JSON
# ---------------------------
def load_json():
    if not os.path.exists(JSON_PATH):
        return {
            "country": "CL",
            "currency": "CLP",
            "rates_history": []
        }

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------
# UPSERT HISTORY
# ---------------------------
def upsert(history, new_entry):
    data = {item["date"]: item for item in history}
    data[new_entry["date"]] = new_entry
    return sorted(data.values(), key=lambda x: x["date"], reverse=True)


# ---------------------------
# GET VALUE N DAYS AGO (relative to base_date)
# ---------------------------
def get_value_days(history, base_date, days, key):
    base = datetime.strptime(base_date, "%Y-%m-%d")
    target = base - timedelta(days=days)

    best = None

    for r in history:
        d = datetime.strptime(r["date"], "%Y-%m-%d")

        if d <= target:
            if not best or d > datetime.strptime(best["date"], "%Y-%m-%d"):
                best = r

    if not best:
        return None, None

    return best.get(key), best["date"]


# ---------------------------
# VARIATION CALC
# ---------------------------
def variation(latest, past):
    if past is None or past == 0:
        return None
    return ((latest - past) / past) * 100


# ---------------------------
# MAIN
# ---------------------------
def main():
    bcch = bcchapi.Siete(usr=usr, pwd=pwd)

    uf_date, uf = fetch_last(bcch, UF_SERIE, days_back=60)
    usd_date, usd = fetch_last(bcch, USD_SERIE, days_back=60)
    utm_date, utm = fetch_last(bcch, UTM_SERIE, days_back=400)

    # Fecha principal del JSON (lo más reciente disponible)
    latest_date = max(uf_date, usd_date, utm_date)

    # ---------------------------
    # LOAD + UPSERT HISTORY
    # ---------------------------
    data = load_json()
    history = data.get("rates_history", [])

    # Guardamos por fecha de UF (porque UF es diaria y define el historial diario)
    # Si mañana cambia solo el USD pero UF no, igual el historial seguirá ordenado por UF.
    new_entry = {
        "date": uf_date,
        "uf": uf,
        "usd": usd,
        "utm": utm
    }

    history = upsert(history, new_entry)

    # ---------------------------
    # BUILD VARIATIONS (with real base date)
    # ---------------------------
    def build_variations(key, base_date, latest_value):
        v7, d7 = get_value_days(history, base_date, 7, key)
        v30, d30 = get_value_days(history, base_date, 30, key)
        v60, d60 = get_value_days(history, base_date, 60, key)

        return {
            "7d": {
                "value": v7,
                "pct": variation(latest_value, v7),
                "date": d7
            },
            "30d": {
                "value": v30,
                "pct": variation(latest_value, v30),
                "date": d30
            },
            "60d": {
                "value": v60,
                "pct": variation(latest_value, v60),
                "date": d60
            }
        }

    # ---------------------------
    # LATEST FORMAT (with per-indicator date)
    # ---------------------------
    latest = {
        "date": latest_date,

        "uf": uf,
        "usd": usd,
        "utm": utm,

        "dates": {
            "uf": uf_date,
            "usd": usd_date,
            "utm": utm_date
        },

        "variations": {
            "uf": build_variations("uf", uf_date, uf),
            "usd": build_variations("usd", usd_date, usd),
            "utm": build_variations("utm", utm_date, utm)
        }
    }

    output = {
        "country": "CL",
        "currency": "CLP",
        "rates_history": history,
        "latest": latest
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("OK actualizado")


if __name__ == "__main__":
    main()