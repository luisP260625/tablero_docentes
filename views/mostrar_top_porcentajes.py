import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
from utils.descarga import descargar_csv  # Asegúrate que esta función exista

# Gráfico de barras horizontales
def graficar_barras(df, columna):
    fig, ax = plt.subplots(figsize=(10, 8))
    etiquetas = df[columna].to_list()
    porcentajes = df["PORCENTAJE"].to_list()
    no_comp = df["NO_COMP"].to_list()

    ax.barh(etiquetas, porcentajes, color='#c4a96b')
    ax.invert_yaxis()
    ax.set_xlabel("Porcentaje de No Competencia (%)")
    ax.set_title(f"Top 15 {columna.title()} con Mayor % de No Competencia")

    for i, (v, n) in enumerate(zip(porcentajes, no_comp)):
        ax.text(v + 0.5, i, f"{n}\n{v:.1f}%", va='center', fontsize=8)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False) 
    st.pyplot(fig)

# Función principal (ya NO contiene selectbox)
def mostrar_top_porcentajes(df, semana):
    st.markdown("### 👨‍🏫 Top de Docentes y Módulos por Semana (uno por plantel)")

    df = df.with_columns(
        (pl.col("NO COMPETENTES") / pl.col("TOTAL ALUMNOS") * 100).alias("PORCENTAJE")
    )

    # ---------------- DOCENTES ----------------
    docentes = (
        df.group_by(["Plantel", "DOCENTE"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
            pl.mean("PORCENTAJE").alias("PORCENTAJE")
        ])
        .sort(["Plantel", "PORCENTAJE"], descending=[False, True])
        .group_by("Plantel").agg(pl.all().first())  # Solo 1 docente por plantel
        .with_columns(
            ((pl.col("Plantel") + " - " + pl.col("DOCENTE")).alias("ETIQUETA"))
        )
        .sort("PORCENTAJE", descending=True)
        .head(20)
    )

    st.markdown(f"#### 👨‍🏫 Docentes - Semana {semana}")
    graficar_barras(docentes, "ETIQUETA")
    #descargar_csv(f"top_docentes_{semana}", docentes)

    # ---------------- MÓDULOS ----------------
    modulos = (
        df.group_by(["Plantel", "MODULO"])
        .agg([
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
            pl.mean("PORCENTAJE").alias("PORCENTAJE")
        ])
        .sort(["Plantel", "PORCENTAJE"], descending=[False, True])
        .group_by("Plantel").agg(pl.all().first())  # Solo 1 módulo por plantel
        .with_columns(
            ((pl.col("Plantel") + " - " + pl.col("MODULO")).alias("ETIQUETA"))
        )
        .sort("PORCENTAJE", descending=True)
        .head(20)
    )

    st.markdown(f"#### 📚 Módulos - Semana {semana}")
    graficar_barras(modulos, "ETIQUETA")
    #descargar_csv(f"top_modulos_{semana}", modulos)
