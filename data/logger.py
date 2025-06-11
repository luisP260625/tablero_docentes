import os
import pandas as pd
from datetime import datetime

LOG_FILE = "data/bitacora.csv"

def registrar_acceso(usuario):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{usuario},{fecha}\n")

def contar_accesos(usuario):
    if not os.path.exists(LOG_FILE):
        return 0
    df = pd.read_csv(LOG_FILE, names=["Usuario", "Fecha"])
    return df[df["Usuario"] == usuario].shape[0]

def obtener_bitacora():
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame(columns=["Usuario", "Accesos", "Fechas"])

    df = pd.read_csv(LOG_FILE, names=["Usuario", "Fecha"])
    df["Fecha"] = pd.to_datetime(df["Fecha"])

    resumen = df.groupby("Usuario").agg({
        "Fecha": [("Accesos", "count"), ("Fechas", lambda x: x.dt.strftime("%Y-%m-%d").tolist())]
    }).reset_index()
    resumen.columns = ["Usuario", "Accesos", "Fechas"]
    return resumen
