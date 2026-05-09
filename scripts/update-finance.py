import json
import bcchapi
from datetime import datetime, timedelta
import os

UF_SERIE = "F073.UFF.PRE.Z.D"
USD_SERIE = "F073.TCO.PRE.Z.D"
UTM_SERIE = "F073.UTR.PRE.Z.M"

usr = os.getenv("BCCH_USER")
pwd = os.getenv("BCCH_PASS")

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


def main():
    siete = bcchapi.Siete(usr=usr, pwd=pwd)

    uf_date, uf_value = get_last_value(siete, UF_SERIE, days_back=30)
    usd_date, usd_value = get_last_value(siete, USD_SERIE, days_back=30)
    utm_date, utm_value = get_last_value(siete, UTM_SERIE, days_back=400)

    # Fecha más reciente entre las 3 (lo correcto)
    updated_at = max(uf_date, usd_date, utm_date)

    output = {
        "country": "CL",
        "currency": "CLP",
        "updated_at": updated_at,
        "rates": {
            "uf": {
                "name": "Unidad de Fomento",
                "symbol": "UF",
                "value_clp": uf_value
            },
            "utm": {
                "name": "Unidad Tributaria Mensual",
                "symbol": "UTM",
                "value_clp": utm_value
            },
            "usd": {
                "name": "Dólar Observado",
                "symbol": "USD",
                "value_clp": usd_value
            }
        }
    }

    with open("data/cl-finance.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("Actualizado OK:")
    print(output)


if __name__ == "__main__":
    main()