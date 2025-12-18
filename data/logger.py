# data/logger.py
import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

LOG_FILE = "data/bitacora.csv"
TZ_LOCAL = ZoneInfo("America/Mexico_City")


def registrar_acceso(usuario: str):
    """
    Guarda un acceso en bitácora con hora LOCAL de México (America/Mexico_City).
    Formato CSV: Usuario,YYYY-MM-DD HH:MM:SS
    """
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    usuario = str(usuario).strip().upper()
    fecha = datetime.now(TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{usuario},{fecha}\n")


def contar_accesos(usuario: str) -> int:
    """
    Cuenta cuántas veces aparece el usuario en la bitácora.
    """
    if not os.path.exists(LOG_FILE):
        return 0

    df = pd.read_csv(LOG_FILE, names=["Usuario", "Fecha"], dtype=str)
    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()

    u = str(usuario).strip().upper()
    return int((df["Usuario"] == u).sum())


def obtener_bitacora() -> pd.DataFrame:
    """
    Regresa un resumen por Usuario:
    - Usuario
    - Accesos
    - Fechas (lista de fechas YYYY-MM-DD por acceso)
    """
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame(columns=["Usuario", "Accesos", "Fechas"])

    df = pd.read_csv(LOG_FILE, names=["Usuario", "Fecha"], dtype=str)
    if df.empty:
        return pd.DataFrame(columns=["Usuario", "Accesos", "Fechas"])

    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()

    # Como ya guardamos hora local, parseamos "naive" (sin UTC)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

    # Limpieza básica
    df = df.dropna(subset=["Usuario"])
    df = df[df["Usuario"] != ""]

    resumen = (
        df.groupby("Usuario")
          .agg(
              Accesos=("Fecha", "count"),
              Fechas=("Fecha", lambda x: x.dt.strftime("%Y-%m-%d").tolist())
          )
          .reset_index()
          .sort_values(["Accesos", "Usuario"], ascending=[False, True])
    )

    return resumen


def obtener_logs_detalle() -> pd.DataFrame:
    """
    (Opcional) Si alguna vista necesita el log sin resumir:
    - Usuario
    - FechaHora (datetime)
    """
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame(columns=["Usuario", "FechaHora"])

    df = pd.read_csv(LOG_FILE, names=["Usuario", "FechaHora"], dtype=str)
    if df.empty:
        return pd.DataFrame(columns=["Usuario", "FechaHora"])

    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
    df = df.dropna(subset=["Usuario"]).sort_values("FechaHora", ascending=False)
    return df
