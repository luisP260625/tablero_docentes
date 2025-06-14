import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_ranking_por_plantel(df, plantel_usuario):
    st.title("🏆 Ranking de Docentes y Módulos Críticos del Plantel")

    # Filtrar datos por plantel
    df = df.filter(pl.col("Plantel") == plantel_usuario)

    # ===============================
    # ==== DOCENTES SIN FILTRO ======
    # ===============================

    semanas = df.select("Semana").unique()
    docentes = df.select("DOCENTE").unique()
    docente_semana = docentes.join(semanas, how="cross")

    por_docente_semana = (
        df.group_by(["DOCENTE", "Semana"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NC"),
            pl.sum("TOTAL ALUMNOS").alias("TA")
        ])
        .with_columns([
            ((pl.col("NC") / pl.col("TA")) * 100).alias("PROMEDIO_SEMANA"),
            ((pl.col("NC") / pl.col("TA")) * 100 >= 30).cast(pl.Int8).alias("ES_CRITICO_SEMANA")
        ])
    )

    docente_semana_completo = docente_semana.join(
        por_docente_semana, on=["DOCENTE", "Semana"], how="left"
    ).fill_null(0)

    ranking_docentes = (
        docente_semana_completo
        .group_by("DOCENTE")
        .agg([
            pl.sum("ES_CRITICO_SEMANA").alias("Semanas_Criticas"),
            pl.mean("PROMEDIO_SEMANA").alias("Promedio")
        ])
        .sort("Semanas_Criticas", descending=True)
    )

    st.subheader("🧍‍♂️ Docentes Críticos (por número de semanas ≥30%)")
    st.dataframe(ranking_docentes.to_pandas())
    descargar_csv("ranking_docentes", ranking_docentes)

    # ===============================
    # ==== MÓDULOS SIN FILTRO =======
    # ===============================

    modulos = df.select("MODULO").unique()
    modulo_semana = modulos.join(semanas, how="cross")

    por_modulo_semana = (
        df.group_by(["MODULO", "Semana"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NC"),
            pl.sum("TOTAL ALUMNOS").alias("TA")
        ])
        .with_columns([
            ((pl.col("NC") / pl.col("TA")) * 100).alias("PROMEDIO_SEMANA"),
            ((pl.col("NC") / pl.col("TA")) * 100 >= 30).cast(pl.Int8).alias("ES_CRITICO_SEMANA")
        ])
    )

    modulo_semana_completo = modulo_semana.join(
        por_modulo_semana, on=["MODULO", "Semana"], how="left"
    ).fill_null(0)

    ranking_modulos = (
        modulo_semana_completo
        .group_by("MODULO")
        .agg([
            pl.sum("ES_CRITICO_SEMANA").alias("Semanas_Criticas"),
            pl.mean("PROMEDIO_SEMANA").alias("Promedio")
        ])
        .sort("Semanas_Criticas", descending=True)
        .head(15)
    )

    st.subheader("📚 Módulos Críticos (por número de semanas ≥30%)")
    st.dataframe(ranking_modulos.to_pandas())
    descargar_csv("ranking_modulos", ranking_modulos)

    st.info("El criterio de consistencia ha sido eliminado. Ahora se muestran todos los docentes y módulos que hayan tenido al menos una semana crítica (≥30% de no competencia).")
