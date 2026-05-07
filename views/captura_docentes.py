import streamlit as st
import polars as pl
import pandas as pd
from utils.helpers import to_excel


COLUMNAS_SEMCAPTURA = [
    "PLANTEL",
    "DOCENTE",
    "MODULO",
    "SEMESTRE",
    "FECHA_CAPTURA",
    "GRUPO",
    "UAPRENDIZAJE",
    "RAPRENDIZAJE",
    "IEVALUAR",
    "IEVALUADOS",
    "PCAPTURA",
    "TOTALE",
    "ESTATUS",
]


def normalizar_columnas(df: pl.DataFrame) -> pl.DataFrame:
    """
    Normaliza nombres de columnas:
    - quita espacios al inicio/final
    - convierte a mayúsculas
    """
    rename_map = {c: c.strip().upper() for c in df.columns}
    return df.rename(rename_map)


def mostrar(df_semcaptura: pl.DataFrame, plantel_usuario: str, administrador: bool):
    st.title("% de Captura Docentes")

    if df_semcaptura is None or df_semcaptura.is_empty():
        st.info("No hay información disponible para mostrar.")
        return

    # Normalizar nombres de columnas para evitar problemas por espacios o mayúsculas
    df_semcaptura = normalizar_columnas(df_semcaptura)

    # Reordenar columnas: primero las esperadas, luego extras
    columnas_presentes = [c for c in COLUMNAS_SEMCAPTURA if c in df_semcaptura.columns]
    columnas_extra = [c for c in df_semcaptura.columns if c not in columnas_presentes]

    df_view = df_semcaptura.select(columnas_presentes + columnas_extra)

    # Filtrado por rol
    if not administrador and "PLANTEL" in df_view.columns:
        df_view = df_view.filter(pl.col("PLANTEL") == plantel_usuario)

    # Filtro por % de captura
    filtro = "Todos"

    if "PCAPTURA" in df_view.columns:
        filtro = st.radio(
            "Selección por filtro de captura",
            options=["Todos", "≤30", "31 a 60", "61 a 90"],
            horizontal=True,
        )

        df_view = df_view.with_columns(
            pl.col("PCAPTURA")
            .cast(pl.Utf8)
            .str.replace_all("%", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("_PCAPTURA_NUM")
        )

        if filtro == "≤30":
            df_view = df_view.filter(pl.col("_PCAPTURA_NUM") <= 30)

        elif filtro == "31 a 60":
            df_view = df_view.filter(
                (pl.col("_PCAPTURA_NUM") >= 31)
                & (pl.col("_PCAPTURA_NUM") <= 60)
            )

        elif filtro == "61 a 90":
            df_view = df_view.filter(
                (pl.col("_PCAPTURA_NUM") >= 61)
                & (pl.col("_PCAPTURA_NUM") <= 90)
            )

        df_view = df_view.drop("_PCAPTURA_NUM")

    else:
        st.warning("No se encontró la columna PCAPTURA; no se puede aplicar el filtro.")

    st.caption(f"Registros mostrados: **{df_view.height:,}**")

    # Convertir a pandas para configurar mejor la visualización
    pdf = df_view.to_pandas()

    # Mostrar tabla con anchos configurados
    st.dataframe(
        pdf,
        hide_index=True,
        height=600,
        use_container_width=True,
        column_config={
            "PLANTEL": st.column_config.TextColumn("Plantel", width="medium"),
            "DOCENTE": st.column_config.TextColumn("DOCENTE", width="medium"),
            "MODULO": st.column_config.TextColumn("MODULO", width="medium"),
            "SEMESTRE": st.column_config.NumberColumn("SEMESTRE", width="small"),
            "FECHA_CAPTURA": st.column_config.TextColumn("FECHA CAPTURA", width="medium"),
            "GRUPO": st.column_config.TextColumn("GRUPO", width="small"),
            "UAPRENDIZAJE": st.column_config.NumberColumn("UAPRENDIZAJE", width="small"),
            "RAPRENDIZAJE": st.column_config.NumberColumn("RAPRENDIZAJE", width="small"),
            "IEVALUAR": st.column_config.NumberColumn("IEVALUAR", width="small"),
            "IEVALUADOS": st.column_config.NumberColumn("IEVALUADOS", width="small"),
            "PCAPTURA": st.column_config.NumberColumn("PCAPTURA", width="small"),
            "TOTALE": st.column_config.NumberColumn("TOTALE", width="small"),
            "ESTATUS": st.column_config.TextColumn("ESTATUS", width="medium"),
        },
    )

    # Descargar exactamente lo mostrado
    excel_bytes = to_excel(pdf)

    base = "SemCaptura_TODOS" if administrador else f"SemCaptura_{plantel_usuario}"
    sufijo = "TODOS" if filtro == "Todos" else filtro.replace("≤", "LE").replace(" ", "_")
    nombre = f"{base}_{sufijo}"

    st.download_button(
        label="⬇️ Descargar Excel",
        data=excel_bytes,
        file_name=f"{nombre}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )