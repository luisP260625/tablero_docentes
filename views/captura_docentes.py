import streamlit as st
import polars as pl
from utils.helpers import to_excel

# Columnas solicitadas por el requerimiento
COLUMNAS_SEMCAPTURA = [
    "Plantel",
    "DOCENTE",
    "MODULO",
    "SEMESTRE",
    "GRUPO",
    "UAPRENDIZAJE",
    "RAPRENDIZAJE",
    "IEVALUADOS",
    "PCAPTURA",
    "TOTALE",
    "ESTATUS",
]

def mostrar(df_semcaptura: pl.DataFrame, plantel_usuario: str, administrador: bool):
    st.title(" % de Captura Docentes")

    if df_semcaptura is None or df_semcaptura.is_empty():
        st.info("No hay información disponible para mostrar.")
        return

    # Garantiza columnas (por si el Excel cambia)
    cols_presentes = [c for c in COLUMNAS_SEMCAPTURA if c in df_semcaptura.columns]
    df_view = df_semcaptura.select(cols_presentes)

    # Filtrado por rol
    if not administrador:
        df_view = df_view.filter(pl.col("Plantel") == plantel_usuario)

    # ==========================
    # Filtros por % de captura
    # Regla de negocio (PCAPTURA):
    # 1) Todos
    # 2) PCAPTURA <= 30
    # 3) 31 <= PCAPTURA <= 60
    # 4) 61 <= PCAPTURA <= 90
    # ==========================
    filtro = "Todos"
    pc_num = None

    if "PCAPTURA" in df_view.columns:
        filtro = st.radio(
            "Selección por filtro de captura",
            options=["Todos", "≤30", "31 a 60", "61 a 90"],
            horizontal=True,
        )

        # Normaliza PCAPTURA a numérico (soporta valores como '70', '70.5', '70%')
        pc_num = (
            pl.col("PCAPTURA")
            .cast(pl.Utf8)
            .str.replace_all("%", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
        )

        # Aplica filtro seleccionado
        if filtro == "≤30":
            df_view = df_view.filter(pc_num <= 30)
        elif filtro == "31 a 60":
            df_view = df_view.filter((pc_num >= 31) & (pc_num <= 60))
        elif filtro == "61 a 90":
            df_view = df_view.filter((pc_num >= 61) & (pc_num <= 90))
    else:
        st.warning("No se encontró la columna PCAPTURA; no se puede aplicar el filtro.")

    st.caption(f"Registros mostrados: **{df_view.height:,}**")

    # Tabla
    st.dataframe(df_view.to_pandas(), use_container_width=True, height=600)

    # Descarga Excel (solo lo que se ve en pantalla)
    excel_bytes = to_excel(df_view.to_pandas())

    # El Excel se genera con el mismo filtro que se ve en pantalla
    base = "SemCaptura_TODOS" if administrador else f"SemCaptura_{plantel_usuario}"
    sufijo = "TODOS" if filtro == "Todos" else filtro.replace("≤", "LE").replace(" ", "_")
    nombre = f"{base}_{sufijo}"

    st.download_button(
        label="⬇️ Descargar Excel",
        data=excel_bytes,
        file_name=f"{nombre}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
