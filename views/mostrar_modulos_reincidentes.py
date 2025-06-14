import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_modulos_reincidentes(df):
    st.markdown("### 📚 Módulos Críticos Constantes")

    # Calcular porcentaje por fila (opcional, no se usa en agrupación corregida)
    df = df.with_columns(
        (pl.col("NO COMPETENTES") / pl.col("TOTAL ALUMNOS") * 100).alias("PORCENTAJE")
    )

    # Agrupar por semana y módulo y calcular porcentaje real por totales
    por_modulo_semana = (
        df.group_by(["Semana", "MODULO", "Plantel"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NC"),
            pl.sum("TOTAL ALUMNOS").alias("TA")
        ])
        .with_columns([
            ((pl.col("NC") / pl.col("TA")) * 100).alias("PORCENTAJE_SEMANA"),
            ((pl.col("NC") / pl.col("TA")) * 100 >= 30).cast(pl.Int8).alias("ES_CRITICO")
        ])
    )

    # Agrupar por módulo y plantel
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

    # Eliminar columna 'Total_Semanas' antes de mostrar y exportar
    estadisticas = estadisticas.drop("Total_Semanas")

    st.dataframe(estadisticas.to_pandas())
    descargar_csv("modulos_reincidentes", estadisticas)
    st.info("Se muestran solo módulos que han mantenido ≥30% de no competencia en todas las semanas donde aparecen.")
