from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pandas as pd

# ✅ Ruta absoluta al CSV para evitar escribir en otro lugar por el "working directory"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = str((PROJECT_ROOT / "data" / "bitacora.csv").resolve())


def _ensure_log_folder() -> None:
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)


def _detect_format() -> int:
    """
    Detecta formato del CSV:
    - 3 columnas: Plantel,Usuario,FechaHora  -> retorna 3
    - 2 columnas: Usuario,FechaHora          -> retorna 2
    - no existe / vacío                      -> retorna 0
    """
    p = Path(LOG_FILE)
    if not p.exists() or p.stat().st_size == 0:
        return 0

    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            commas = line.count(",")
            if commas >= 2:
                return 3
            if commas == 1:
                return 2
            return 2
    return 0


def _migrar_2_a_3() -> None:
    """
    Migra bitácora vieja (Usuario,FechaHora) a nueva (Plantel,Usuario,FechaHora).
    Plantel queda vacío "" en los registros históricos.
    """
    p = Path(LOG_FILE)
    if not p.exists() or p.stat().st_size == 0:
        return

    df = pd.read_csv(LOG_FILE, header=None, dtype=str, engine="python").dropna(how="all")
    if df.empty or df.shape[1] < 2:
        return

    df = df.iloc[:, :2].copy()
    df.columns = ["Usuario", "FechaHora"]

    df_new = pd.DataFrame(
        {
            "Plantel": [""] * len(df),
            "Usuario": df["Usuario"].astype(str),
            "FechaHora": df["FechaHora"].astype(str),
        }
    )

    tmp = p.with_suffix(".tmp")
    df_new.to_csv(tmp, index=False, header=False, encoding="utf-8")
    tmp.replace(p)


def registrar_acceso(usuario: str, plantel: str | None = None) -> None:
    """
    Guarda un acceso en bitácora.
    Nuevo formato (sin header): Plantel,Usuario,YYYY-MM-DD HH:MM:SS

    ✅ Compatible:
      - registrar_acceso(usuario)
      - registrar_acceso(usuario, plantel)
    """
    _ensure_log_folder()

    fmt = _detect_format()
    if fmt == 2:
        _migrar_2_a_3()

    usuario_n = str(usuario).strip().upper()
    plantel_n = "GLOBAL" if plantel is None else str(plantel).strip()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{plantel_n},{usuario_n},{fecha}\n")


def contar_accesos(usuario: str) -> int:
    p = Path(LOG_FILE)
    if not p.exists() or p.stat().st_size == 0:
        return 0

    df = pd.read_csv(LOG_FILE, header=None, dtype=str, engine="python").dropna(how="all")
    if df.empty:
        return 0

    if df.shape[1] >= 3:
        df = df.iloc[:, :3].copy()
        df.columns = ["Plantel", "Usuario", "FechaHora"]
    else:
        df = df.iloc[:, :2].copy()
        df.columns = ["Usuario", "FechaHora"]

    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()
    u = str(usuario).strip().upper()
    return int((df["Usuario"] == u).sum())


def obtener_logs_detalle() -> pd.DataFrame:
    p = Path(LOG_FILE)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=["FechaHora", "Usuario", "Plantel"])

    df = pd.read_csv(LOG_FILE, header=None, dtype=str, engine="python").dropna(how="all")
    if df.empty:
        return pd.DataFrame(columns=["FechaHora", "Usuario", "Plantel"])

    if df.shape[1] >= 3:
        df = df.iloc[:, :3].copy()
        df.columns = ["Plantel", "Usuario", "FechaHora"]
    else:
        df = df.iloc[:, :2].copy()
        df.columns = ["Usuario", "FechaHora"]
        df["Plantel"] = ""

    df["Plantel"] = df["Plantel"].astype(str).fillna("").str.strip()
    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")

    df = df.dropna(subset=["Usuario", "FechaHora"]).sort_values("FechaHora", ascending=False)
    return df[["FechaHora", "Usuario", "Plantel"]]
