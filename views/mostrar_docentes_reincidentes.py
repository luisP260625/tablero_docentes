import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_docentes_reincidentes(df):
    st.markdown("### 🧍‍♂️ Docentes Críticos Constantes")

    df = df.with_columns(
        (pl.col("NO COMPETENTES") / pl.col("TOTAL ALUMNOS") * 100).alias("PORCENTAJE")
    )

    por_docente_semana = (
        df.group_by(["Semana", "DOCENTE", "Plantel"])
        .agg(pl.mean("PORCENTAJE").alias("PORCENTAJE_SEMANA"))
        .with_columns(
            (pl.col("PORCENTAJE_SEMANA") >= 30).cast(pl.Int8).alias("ES_CRITICO")
        )
    )

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
    st.info("Se muestran solo docentes que han mantenido ≥50% de no competencia en todas las semanas donde aparecen.")
