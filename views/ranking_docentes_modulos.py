import streamlit as st
import polars as pl
from utils.descarga import descargar_csv

def mostrar_ranking_por_plantel(df, plantel_usuario):
    st.title("🏆 Ranking de Docentes y Módulos Críticos del Plantel")

    # Filtrar datos por plantel
    df = df.filter(pl.col("Plantel") == plantel_usuario)

    # ===============================
    # ==== DOCENTES CORREGIDO =======
    # ===============================

    # Obtener semanas y docentes únicos
    semanas = df.select("Semana").unique()
    docentes = df.select("DOCENTE").unique()
    docente_semana = docentes.join(semanas, how="cross")

    # Agrupar datos reales: suma de NO_COMPETENTES y TOTAL_ALUMNOS por semana
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

    # Unir con todas las semanas posibles por docente (rellenar vacíos con 0)
    docente_semana_completo = docente_semana.join(
        por_docente_semana, on=["DOCENTE", "Semana"], how="left"
    ).fill_null(0)

    # Agrupar por docente para ranking
    ranking_docentes = (
        docente_semana_completo
        .group_by("DOCENTE")
        .agg([
            pl.count().alias("Total_Semanas"),  # Siempre será 11
            pl.sum("ES_CRITICO_SEMANA").alias("Semanas_Criticas"),
            pl.mean("PROMEDIO_SEMANA").alias("Promedio")
        ])
        .filter(pl.col("Semanas_Criticas") >= 2)
        .sort("Semanas_Criticas", descending=True)
    )

    st.subheader("🧍‍♂️ Docentes Críticos Constantes (del plantel)")
    st.dataframe(ranking_docentes.to_pandas())
    descargar_csv("ranking_docentes", ranking_docentes)

    # ===============================
    # ==== MÓDULOS CORREGIDO ========
    # ===============================

    # Obtener semanas y módulos únicos
    modulos = df.select("MODULO").unique()
    modulo_semana = modulos.join(semanas, how="cross")

    # Agrupar datos reales por módulo y semana
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

    # Unir con todas las combinaciones posibles módulo-semana
    modulo_semana_completo = modulo_semana.join(
        por_modulo_semana, on=["MODULO", "Semana"], how="left"
    ).fill_null(0)

    # Calcular ranking
    ranking_modulos = (
        modulo_semana_completo
        .group_by("MODULO")
        .agg([
            pl.count().alias("Total_Semanas"),
            pl.sum("ES_CRITICO_SEMANA").alias("Semanas_Criticas"),
            pl.mean("PROMEDIO_SEMANA").alias("Promedio")
        ])
        .filter(pl.col("Semanas_Criticas") >= 2)
        .sort("Semanas_Criticas", descending=True)
        .head(15)
    )

    st.subheader("📚 Módulos Críticos Constantes (del plantel)")
    st.dataframe(ranking_modulos.to_pandas())
    descargar_csv("ranking_modulos", ranking_modulos)

    st.info("Los rankings se basan en semanas con ≥30% de no competencia. Las semanas están normalizadas a 11 para todos los casos.")
