import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_docentes_reincidentes(df):
    st.markdown("### 🧍‍♂️ Docentes Reincidentes a Nivel General")

    # Calcular porcentaje por fila
    df = df.with_columns(
        (pl.col("NO COMPETENTES") / pl.col("TOTAL ALUMNOS") * 100).alias("PORCENTAJE")
    )

    # Agrupar por DOCENTE + Semana + Plantel
    por_docente_semana = (
        df.group_by(["DOCENTE", "Semana", "Plantel"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NC"),
            pl.sum("TOTAL ALUMNOS").alias("TA")
        ])
        .with_columns([
            ((pl.col("NC") / pl.col("TA")) * 100).alias("PORCENTAJE_SEMANA"),
            ((pl.col("NC") / pl.col("TA")) * 100 >= 30).cast(pl.Int8).alias("ES_CRITICO")
        ])
    )

    # Agrupar por DOCENTE y Plantel
    estadisticas = (
        por_docente_semana
        .group_by(["DOCENTE", "Plantel"])
        .agg([
            pl.count().alias("Total_Semanas"),
            pl.sum("ES_CRITICO").alias("Semanas_Criticas"),
            pl.mean("PORCENTAJE_SEMANA").alias("PROMEDIO")
        ])
        .filter((pl.col("Total_Semanas") == pl.col("Semanas_Criticas")) & (pl.col("Total_Semanas") > 1))
        .sort("Total_Semanas", descending=True)
    )

    st.dataframe(estadisticas.to_pandas())
    descargar_csv("docentes_reincidentes", estadisticas)
    st.info("Se muestran solo docentes que han tenido ≥30% de no competencia en **todas** las semanas donde han participado, incluyendo su plantel.")
