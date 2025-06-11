import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_modulos_reincidentes(df):
    st.markdown("### 📚 Módulos Críticos Constantes")

    df = df.with_columns(
        (pl.col("NO COMPETENTES") / pl.col("TOTAL ALUMNOS") * 100).alias("PORCENTAJE")
    )

    por_modulo_semana = (
        df.group_by(["Semana", "MODULO", "Plantel"])
        .agg(pl.mean("PORCENTAJE").alias("PORCENTAJE_SEMANA"))
        .with_columns(
            (pl.col("PORCENTAJE_SEMANA") >= 50).cast(pl.Int8).alias("ES_CRITICO")
        )
    )

    estadisticas = (
        por_modulo_semana
        .group_by(["MODULO", "Plantel"])
        .agg([
            pl.count().alias("Total_Semanas"),
            pl.sum("ES_CRITICO").alias("Semanas_Criticas"),
            pl.mean("PORCENTAJE_SEMANA").alias("PROMEDIO")
        ])
        .filter((pl.col("Total_Semanas") == pl.col("Semanas_Criticas")) & (pl.col("Total_Semanas") > 1))
        .sort("Total_Semanas", descending=True)
        .head(15)
    )

    st.dataframe(estadisticas.to_pandas())
    descargar_csv("modulos_reincidentes", estadisticas)
    st.info("Se muestran solo módulos que han mantenido ≥50% de no competencia en todas las semanas donde aparecen.")
