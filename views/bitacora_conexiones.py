import streamlit as st
import pandas as pd
from io import BytesIO
from pathlib import Path

from config import EXCEL_FILE, SHEET_PLANTELES
from data.logger import LOG_FILE


def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    project_root = Path(__file__).resolve().parents[1]
    return str((project_root / p).resolve())


@st.cache_data(ttl=600, show_spinner=False)
def _cargar_planteles() -> pd.DataFrame:
    excel = _abs_path(EXCEL_FILE)
    df = pd.read_excel(excel, sheet_name=SHEET_PLANTELES, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    if not {"Plantel", "Usuario"}.issubset(df.columns):
        raise ValueError(f"La hoja '{SHEET_PLANTELES}' debe incluir columnas 'Plantel' y 'Usuario'.")

    out = df[["Plantel", "Usuario"]].copy()

    # ✅ NO convertir NaN a "nan"
    out["Plantel"] = out["Plantel"].where(out["Plantel"].notna(), "")
    out["Usuario"] = out["Usuario"].where(out["Usuario"].notna(), "")

    out["Plantel"] = out["Plantel"].astype(str).str.strip()
    out["Usuario"] = out["Usuario"].astype(str).str.strip().str.upper()

    # ✅ excluir filas sin plantel (usuarios globales)
    out = out[out["Plantel"] != ""]
    out = out[~out["Plantel"].str.lower().isin(["nan", "none"])]

    # ✅ excluir usuario vacío
    out = out[out["Usuario"] != ""]

    # Un plantel = 1 usuario esperado (si hay duplicados, conserva el primero)
    out = out.drop_duplicates(subset=["Plantel"]).sort_values("Plantel")
    return out


def _cargar_logs_raw() -> pd.DataFrame:
    log_path = _abs_path(LOG_FILE)
    p = Path(log_path)

    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=["FechaHora", "Usuario", "Plantel"])

    # ✅ keep_default_na=False evita que campos vacíos se vuelvan NaN
    df = pd.read_csv(
        log_path,
        header=None,
        dtype=str,
        engine="python",
        keep_default_na=False
    ).dropna(how="all")

    if df.empty:
        return pd.DataFrame(columns=["FechaHora", "Usuario", "Plantel"])

    if df.shape[1] >= 3:
        df = df.iloc[:, :3].copy()
        df.columns = ["Plantel", "Usuario", "FechaHora"]
    else:
        df = df.iloc[:, :2].copy()
        df.columns = ["Usuario", "FechaHora"]
        df["Plantel"] = ""

    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()

    # ✅ normaliza Plantel (evita "nan")
    df["Plantel"] = df["Plantel"].astype(str).str.strip()
    df.loc[df["Plantel"].str.lower().isin(["nan", "none"]), "Plantel"] = ""

    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
    df = df.dropna(subset=["Usuario", "FechaHora"]).sort_values("FechaHora", ascending=False)
    return df[["FechaHora", "Usuario", "Plantel"]]


def _exportar_excel_multi(df_logs: pd.DataFrame, df_con: pd.DataFrame, df_sin: pd.DataFrame) -> BytesIO:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_logs.to_excel(writer, index=False, sheet_name="Logs")
        df_con.to_excel(writer, index=False, sheet_name="Planteles_Con_Acceso")
        df_sin.to_excel(writer, index=False, sheet_name="Planteles_Sin_Acceso")
    buffer.seek(0)
    return buffer


def mostrar():
    st.subheader("📋 Bitácora de Conexiones (por Plantel)")
    st.caption(f"📌 Excel: {_abs_path(EXCEL_FILE)}")
    st.caption(f"📌 Bitácora: {_abs_path(LOG_FILE)}")

    p = Path(_abs_path(LOG_FILE))
    st.caption(f"🧪 Debug bitácora -> existe: {p.exists()} | size: {p.stat().st_size if p.exists() else 0} bytes")

    try:
        df_planteles = _cargar_planteles()
    except Exception as e:
        st.error(f"No pude cargar '{SHEET_PLANTELES}' desde '{EXCEL_FILE}'. Detalle: {e}")
        return

    df_logs = _cargar_logs_raw()
    if df_logs.empty:
        st.info("No se han registrado accesos aún.")
        st.dataframe(df_planteles, use_container_width=True, hide_index=True)
        return

    # ✅ MAPEO CLAVE:
    # Si el log NO trae Plantel (histórico), lo obtenemos del catálogo por Usuario.
    df_map = df_logs.merge(df_planteles, on="Usuario", how="left", suffixes=("", "_cat"))
    # Plantel final: preferir el del log, si está vacío usar el del catálogo
    df_map["Plantel_final"] = df_map["Plantel"].where(df_map["Plantel"].str.strip() != "", df_map["Plantel_cat"])
    df_map["Plantel_final"] = df_map["Plantel_final"].fillna("").astype(str).str.strip()
    df_map.loc[df_map["Plantel_final"].str.lower().isin(["nan", "none"]), "Plantel_final"] = ""

    # Planteles que han ingresado (solo los que existen en catálogo)
    planteles_con = set(df_map[df_map["Plantel_final"] != ""]["Plantel_final"].unique().tolist())

    df_con = df_planteles[df_planteles["Plantel"].isin(planteles_con)].copy()
    df_sin = df_planteles[~df_planteles["Plantel"].isin(planteles_con)].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accesos totales", int(len(df_logs)))
    c2.metric("Usuarios con acceso", int(df_logs["Usuario"].nunique()))
    c3.metric("Planteles con acceso", int(df_con["Plantel"].nunique()))
    c4.metric("Planteles sin acceso", int(df_sin["Plantel"].nunique()))

    tab1, tab2, tab3 = st.tabs(["✅ Planteles con acceso", "🚫 Planteles sin acceso", "🧾 Logs (detalle)"])

    with tab1:
        st.dataframe(df_con.sort_values("Plantel"), use_container_width=True, hide_index=True)

    with tab2:
        st.dataframe(df_sin.sort_values("Plantel"), use_container_width=True, hide_index=True)

    with tab3:
        # Mostrar ya mapeado a Plantel_final
        df_show = df_map[["FechaHora", "Usuario", "Plantel_final"]].rename(columns={"Plantel_final": "Plantel"})
        st.dataframe(df_show.head(200), use_container_width=True, hide_index=True)

    excel_buffer = _exportar_excel_multi(
        df_map[["FechaHora", "Usuario", "Plantel_final"]].rename(columns={"Plantel_final": "Plantel"}).copy(),
        df_con.copy(),
        df_sin.copy(),
    )
    st.download_button(
        "📊 Exportar Bitácora (Logs + Con acceso + Sin acceso) a Excel",
        data=excel_buffer,
        file_name="bitacora_conexiones_organizada.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
