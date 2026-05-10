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


def get_last_value(siete, series_id, days_back=60):
    hoy = datetime.today()
    desde = (hoy - timedelta(days=days_back)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")

    df = siete.cuadro(
        series=[series_id],
        nombres=["value"],
        desde=desde,
        hasta=hasta
    )

    df = df.dropna()
    last_date = df.index[-1]
    last_value = float(df["value"].iloc[-1])

    return last_date.strftime("%Y-%m-%d"), last_value


def load_existing():
    if not os.path.exists(JSON_PATH):
        return []

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("rates_history", [])


def main():
    siete = bcchapi.Siete(usr=usr, pwd=pwd)

    uf_date, uf_value = get_last_value(siete, UF_SERIE, days_back=30)
    usd_date, usd_value = get_last_value(siete, USD_SERIE, days_back=30)
    utm_date, utm_value = get_last_value(siete, UTM_SERIE, days_back=400)

    # Fecha más reciente entre las 3
    latest_date = max(uf_date, usd_date, utm_date)

    latest_entry = {
        "date": latest_date,
        "uf": uf_value,
        "utm": utm_value,
        "usd": usd_value
    }

    history = load_existing()

    # Insertar el nuevo día arriba
    history.insert(0, latest_entry)

    # Eliminar duplicados por fecha (mantener el más reciente)
    seen = set()
    cleaned_history = []
    for item in history:
        d = item.get("date")
        if d and d not in seen:
            cleaned_history.append(item)
            seen.add(d)

    # Mantener solo 7 días
    cleaned_history = cleaned_history[:7]

    output = {
        "country": "CL",
        "currency": "CLP",
        "rates_history": cleaned_history,
        "latest": cleaned_history[0]
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("Actualizado OK:")
    print(output)


if __name__ == "__main__":
    main()