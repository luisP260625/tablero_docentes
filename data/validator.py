# data/validator.py
from pathlib import Path
import pandas as pd
import streamlit as st
from config import EXCEL_FILE, SHEET_PLANTELES, SHEET_DATOS

__all__ = [
    "validar_usuario",
    "guard_plantel_or_stop",
    "plantel_has_data",
    "get_missing_planteles",
]

# --- Admin (ajusta si quieres) ---
ADMIN_USER = "admin"
ADMIN_PASS = "administrador*"

# Para invalidar cache si cambia el Excel en disco
def _excel_mtime() -> int:
    p = Path(EXCEL_FILE)
    return int(p.stat().st_mtime) if p.exists() else 0

# ---------- Carga/normalización ----------
@st.cache_data(ttl=600)
def _load_df(sheet: str, _v=_excel_mtime()) -> pd.DataFrame:
    df = pd.read_excel(EXCEL_FILE, sheet_name=sheet, dtype=str)
    # normaliza encabezados
    df.columns = [c.strip() for c in df.columns]
    return df

def _norm(s: str) -> str:
    return str(s or "").strip()

def _norm_user(s: str) -> str:
    return _norm(s).upper()

# ---------- Login ----------
@st.cache_data(ttl=600)
def _load_planteles_norm(_v=_excel_mtime()) -> pd.DataFrame:
    df = _load_df(SHEET_PLANTELES)
    # renombra columnas tolerando "Contraseña"/"Contrasena"
    cols = {c.lower(): c for c in df.columns}
    # nombre canónico:
    col_plantel = cols.get("plantel")
    col_usuario = cols.get("usuario")
    col_contra  = cols.get("contrasena") or cols.get("contraseña")

    if not (col_plantel and col_usuario and col_contra):
        raise ValueError(
            f"La hoja '{SHEET_PLANTELES}' debe tener columnas: "
            f"'Plantel', 'Usuario' y 'Contrasena'/'Contraseña'. "
            f"Encontradas: {list(df.columns)}"
        )

    df = df.rename(columns={
        col_plantel: "Plantel",
        col_usuario: "Usuario",
        col_contra:  "Contrasena",
    })

    # normaliza valores
    df["Plantel"]    = df["Plantel"].astype(str).str.strip()
    df["Usuario"]    = df["Usuario"].astype(str).str.strip().str.upper()
    df["Contrasena"] = df["Contrasena"].astype(str).str.strip()

    # rol (opcional)
    if "Rol" in df.columns:
        df["Rol"] = df["Rol"].astype(str).str.strip().str.lower()
    else:
        df["Rol"] = "usuario"
    return df

def validar_usuario(user: str, password: str):
    # admin hardcoded
    if _norm(user).lower() == ADMIN_USER and _norm(password) == ADMIN_PASS:
        return True, "ADMIN", True

    u = _norm_user(user)
    p = _norm(password)

    try:
        df = _load_planteles_norm()
    except Exception as e:
        st.error(f"No pude leer '{EXCEL_FILE}' / hoja '{SHEET_PLANTELES}': {e}")
        return False, None, False

    row = df[(df["Usuario"] == u) & (df["Contrasena"] == p)]
    if row.empty:
        return False, None, False

    plantel  = row.iloc[0]["Plantel"]
    es_admin = (row.iloc[0].get("Rol", "usuario") == "admin")
    return True, plantel, es_admin

# ---------- Guard y utilidades ----------
@st.cache_data(ttl=600)
def _planteles_sets(_v=_excel_mtime()):
    df_datos = _load_df(SHEET_DATOS)
    df_pl    = _load_planteles_norm()

    # normaliza columna Plantel en Datos
    if "Plantel" not in df_datos.columns:
        raise ValueError(f"La hoja '{SHEET_DATOS}' no tiene la columna 'Plantel'.")
    df_datos["Plantel"] = df_datos["Plantel"].astype(str).str.strip()

    set_listados = set(df_pl["Plantel"].dropna().unique().tolist())
    set_con_datos = set(df_datos["Plantel"].dropna().unique().tolist())
    set_sin_datos = set_listados - set_con_datos
    return set_listados, set_con_datos, set_sin_datos

def plantel_has_data(plantel_nombre: str) -> bool:
    _, con_datos, _ = _planteles_sets()
    return _norm(plantel_nombre) in con_datos

def get_missing_planteles() -> list[str]:
    _, _, faltantes = _planteles_sets()
    return sorted(faltantes)

def guard_plantel_or_stop(plantel_nombre: str) -> bool:
    pn = _norm(plantel_nombre)
    if not pn:
        st.warning("⚠️ No se pudo identificar el plantel de la sesión.", icon="⚠️")
        st.stop()
        return False
    try:
        ok = plantel_has_data(pn)
    except Exception as e:
        st.error(f"No pude leer '{EXCEL_FILE}' / hoja '{SHEET_DATOS}': {e}")
        st.stop()
        return False
    if not ok:
        st.warning(
            f"⚠️ Su plantel **{pn}** NO tiene **EVALUACIONES CAPTURADAS**; "
            "no se mostrará información.",
            icon="⚠️",
        )
        st.stop()
        return False
    return True
