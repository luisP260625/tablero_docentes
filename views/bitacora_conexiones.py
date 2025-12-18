import streamlit as st
import pandas as pd
from io import BytesIO
from pathlib import Path

from config import EXCEL_FILE, SHEET_PLANTELES
from data.logger import LOG_FILE


# =========================================================
# Rutas robustas (evita problemas si ejecutas Streamlit desde otra carpeta)
# =========================================================
def _abs_path(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    # views/ está dentro de la raíz del proyecto
    project_root = Path(__file__).resolve().parents[1]
    return str((project_root / p).resolve())


@st.cache_data(ttl=600, show_spinner=False)
def _cargar_planteles() -> pd.DataFrame:
    """Carga hoja Planteles y normaliza valores."""
    excel = _abs_path(EXCEL_FILE)
    df = pd.read_excel(excel, sheet_name=SHEET_PLANTELES, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    if not {"Plantel", "Usuario"}.issubset(set(df.columns)):
        raise ValueError(
            f"La hoja '{SHEET_PLANTELES}' debe incluir columnas 'Plantel' y 'Usuario'. "
            f"Columnas encontradas: {list(df.columns)}"
        )

    out = df[["Plantel", "Usuario"]].copy()
    out["Plantel"] = out["Plantel"].astype(str).str.strip()
    out["Usuario"] = out["Usuario"].astype(str).str.strip().str.upper()
    return out.drop_duplicates()


def _cargar_logs_raw() -> pd.DataFrame:
    """Lee data/bitacora.csv (Usuario, FechaHora)."""
    log_path = _abs_path(LOG_FILE)

    if not Path(log_path).exists():
        return pd.DataFrame(columns=["Usuario", "FechaHora"])

    df = pd.read_csv(log_path, names=["Usuario", "FechaHora"], dtype=str)
    df["Usuario"] = df["Usuario"].astype(str).str.strip().str.upper()
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
    df = df.dropna(subset=["Usuario"]).sort_values("FechaHora", ascending=False)
    return df


def _resumen_por_usuario(df_logs: pd.DataFrame) -> pd.DataFrame:
    if df_logs.empty:
        return pd.DataFrame(columns=["Usuario", "Accesos", "PrimerAcceso", "UltimoAcceso"])

    return (
        df_logs.groupby("Usuario")
        .agg(
            Accesos=("Usuario", "size"),
            PrimerAcceso=("FechaHora", "min"),
            UltimoAcceso=("FechaHora", "max"),
        )
        .reset_index()
        .sort_values(["Accesos", "UltimoAcceso"], ascending=[False, False])
    )


def _resumen_por_plantel(df_planteles: pd.DataFrame, df_user_summary: pd.DataFrame):
    """Regresa (planteles_con_acceso, planteles_sin_acceso)."""
    df = df_planteles.merge(df_user_summary, on="Usuario", how="left")
    con = df[df["Accesos"].notna()].copy()
    sin = df[df["Accesos"].isna()].copy()

    con["Accesos"] = con["Accesos"].astype(int)
    con = con.sort_values(["UltimoAcceso", "Accesos"], ascending=[False, False])

    con = con[["Plantel", "Usuario", "Accesos", "PrimerAcceso", "UltimoAcceso"]]
    sin = sin[["Plantel", "Usuario"]]
    return con, sin


def _exportar_excel_multi(df_logs: pd.DataFrame, df_con: pd.DataFrame, df_sin: pd.DataFrame) -> BytesIO:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_logs.to_excel(writer, index=False, sheet_name="Logs")
        df_con.to_excel(writer, index=False, sheet_name="Planteles_Con_Acceso")
        df_sin.to_excel(writer, index=False, sheet_name="Planteles_Sin_Acceso")

        wb = writer.book
        header = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})

        def _fmt(sheet_name: str, df: pd.DataFrame):
            ws = writer.sheets[sheet_name]
            for col_num, value in enumerate(df.columns.values):
                ws.write(0, col_num, value, header)
            for i, col in enumerate(df.columns):
                try:
                    width = max(df[col].astype(str).map(len).max(), len(col)) + 2
                except Exception:
                    width = len(col) + 2
                ws.set_column(i, i, min(int(width), 60))

        _fmt("Logs", df_logs)
        _fmt("Planteles_Con_Acceso", df_con)
        _fmt("Planteles_Sin_Acceso", df_sin)

    buffer.seek(0)
    return buffer


def mostrar():
    st.subheader("📋 Bitácora de Conexiones (por Plantel)")

    # Debug útil para confirmar rutas reales
    st.caption(f"📌 Excel: {_abs_path(EXCEL_FILE)}")
    st.caption(f"📌 Bitácora: {_abs_path(LOG_FILE)}")

    try:
        df_planteles = _cargar_planteles()
    except Exception as e:
        st.error(f"No pude cargar la hoja '{SHEET_PLANTELES}' desde '{EXCEL_FILE}'.\n\nDetalle: {e}")
        return

    df_logs = _cargar_logs_raw()

    if df_logs.empty:
        st.info("No se han registrado accesos aún.")
        st.markdown("### 🚫 Planteles sin acceso")
        st.dataframe(df_planteles.sort_values("Plantel"), use_container_width=True)
        return

    df_user = _resumen_por_usuario(df_logs)
    df_con, df_sin = _resumen_por_plantel(df_planteles, df_user)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accesos totales", int(len(df_logs)))
    c2.metric("Usuarios con acceso", int(df_user["Usuario"].nunique()))
    c3.metric("Planteles con acceso", int(df_con["Plantel"].nunique()))
    c4.metric("Planteles sin acceso", int(len(df_sin)))

    tab1, tab2, tab3 = st.tabs(["✅ Planteles con acceso", "🚫 Planteles sin acceso", "🧾 Logs (detalle)"])

    with tab1:
        st.dataframe(df_con, use_container_width=True)

    with tab2:
        if df_sin.empty:
            st.success("✅ Todos los planteles han registrado al menos un acceso.")
        else:
            st.dataframe(df_sin.sort_values("Plantel"), use_container_width=True)

    with tab3:
        colf1, colf2 = st.columns([2, 2])
        planteles_opts = ["(Todos)"] + sorted(df_planteles["Plantel"].unique().tolist())
        plantel_sel = colf1.selectbox("Filtrar por plantel", planteles_opts)
        user_q = colf2.text_input("Buscar usuario (contiene)", "")

        df_det = df_logs.merge(df_planteles, on="Usuario", how="left")
        df_det["Plantel"] = df_det["Plantel"].fillna("(NO ENCONTRADO EN PLANTELES)")

        if plantel_sel != "(Todos)":
            df_det = df_det[df_det["Plantel"] == plantel_sel]
        if user_q.strip():
            df_det = df_det[df_det["Usuario"].str.contains(user_q.strip().upper(), na=False)]

        st.dataframe(df_det[["FechaHora", "Usuario", "Plantel"]], use_container_width=True)

    excel_buffer = _exportar_excel_multi(
        df_logs[["FechaHora", "Usuario"]].copy(),
        df_con.copy(),
        df_sin.copy(),
    )
    st.download_button(
        label="📊 Exportar Bitácora (Logs + Con acceso + Sin acceso) a Excel",
        data=excel_buffer,
        file_name="bitacora_conexiones_organizada.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
