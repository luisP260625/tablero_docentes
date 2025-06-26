import streamlit as st
import polars as pl
import matplotlib.pyplot as plt

def graficar_barras(df, columna):
    fig, ax = plt.subplots(figsize=(10, 6))

    etiquetas = df[columna].to_list()
    porcentajes = df["PORCENTAJE"].to_list()
    no_comp = df["NO_COMP"].to_list()

    ax.barh(etiquetas, porcentajes, color='#751739')
    ax.invert_yaxis()
    ax.set_xlabel("Porcentaje de No Competencia (%)")
    ax.set_title(f"Top 15 {columna.title()} con Mayor % de No Competencia")

    for i, (v, n) in enumerate(zip(porcentajes, no_comp)):
        ax.text(v + 0.5, i, f"{n} - {v:.1f}%", va='center', fontsize=9)

    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    st.pyplot(fig)

def mostrar(df, plantel_usuario, es_admin):
    st.subheader("📉 Top 15 Docentes y Módulos con Mayor Porcentaje de No Competencia")
    semana = st.selectbox("📅 Selecciona una semana", sorted(df["Semana"].unique()))
    plantel = st.selectbox("🏫 Selecciona un plantel", sorted(df["Plantel"].unique())) if es_admin else plantel_usuario

    df_filtrado = df.filter(
        (df["Semana"] == semana) & (df["Plantel"] == plantel)
    )

    # Validar que hay datos
    if df_filtrado.is_empty():
        st.warning("No hay datos para la semana y plantel seleccionados.")
        return

    # Total general de no competentes
    total_no_comp = df_filtrado.select(
        pl.sum("NO COMPETENTES").alias("TOTAL_NO_COMP")
    ).item()

    #st.markdown(f"#### 🎯 Total General de No Competencia: **{total_no_comp}**")

    # Agrupar por docente
    docentes = df_filtrado.group_by("DOCENTE").agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL")
    ).with_columns(
        (pl.col("NO_COMP") / pl.col("TOTAL") * 100).alias("PORCENTAJE")
    ).sort("PORCENTAJE", descending=True).head(15)

    # Agrupar por módulo
    modulos = df_filtrado.group_by("MODULO").agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL")
    ).with_columns(
        (pl.col("NO_COMP") / pl.col("TOTAL") * 100).alias("PORCENTAJE")
    ).sort("PORCENTAJE", descending=True).head(15)

    st.markdown("### 👨‍🏫 Top 15 Docentes")
    if not docentes.is_empty():
        graficar_barras(docentes, "DOCENTE")
    else:
        st.info("No hay datos disponibles para docentes.")

    st.markdown("### 📚 Top 15 Módulos")
    if not modulos.is_empty():
        graficar_barras(modulos, "MODULO")
    else:
        st.info("No hay datos disponibles para módulos.")