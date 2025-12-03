import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO

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
        # v ya viene redondeado desde Polars; aquí solo lo mostramos con 2 decimales
        ax.text(v + 0.5, i, f"{n} - {v:.2f}%", va='center', fontsize=9)

    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    st.pyplot(fig)


def mostrar(df, plantel_usuario, es_admin):
    st.subheader("📉 Top 15 Docentes y Módulos con Mayor Porcentaje de No Competencia")

    # ===== Filtros =====
    semana = st.selectbox("📅 Selecciona una semana", sorted(df["Semana"].unique()))
    plantel = (
        st.selectbox("🏫 Selecciona un plantel", sorted(df["Plantel"].unique()))
        if es_admin
        else plantel_usuario
    )

    # Filtrar por semana y plantel
    df_filtrado = df.filter(
        (df["Semana"] == semana) & (df["Plantel"] == plantel)
    )

    # Validar que hay datos
    if df_filtrado.is_empty():
        st.warning("No hay datos para la semana y plantel seleccionados.")
        return

    # =====================================================================
    #                           DOCENTES
    # =====================================================================
    # TODOS los docentes del plantel/semana
    docentes_all = (
        df_filtrado
        .group_by("DOCENTE")
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL")
        )
        .with_columns([
            pl.lit(plantel).alias("PLANTEL"),
            (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
            # Porcentaje de no competencia redondeado a 2 decimales
            ((pl.col("NO_COMP") / pl.col("TOTAL") * 100).round(2)).alias("PORCENTAJE")
        ])
        .sort("PORCENTAJE", descending=True)
    )

    # Top 15 para la gráfica
    docentes_top = docentes_all.head(15)

    st.markdown("### 👨‍🏫 Top 15 Docentes")

    if not docentes_all.is_empty():
        # ---------- Botón Excel: TODOS los docentes ----------
        # Columnas y orden:
        # Plantel, Nombre del docente, Total estudiantes,
        # Total estudiantes competentes, Total estudiantes no competentes,
        # Porcentaje de no competencia (ya redondeado)
        docentes_export = docentes_all.select([
            "PLANTEL",
            "DOCENTE",
            "TOTAL",
            "COMPETENTES",
            "NO_COMP",
            "PORCENTAJE"
        ]).rename({
            "PLANTEL": "Plantel",
            "DOCENTE": "Nombre del docente",
            "TOTAL": "Total de estudiantes",
            "COMPETENTES": "Total de estudiantes COMPETENTES",
            "NO_COMP": "Total de estudiantes NO COMPETENTES",
            "PORCENTAJE": "Porcentaje de no competencia"
        })

        buffer = BytesIO()
        df_docentes_pd = docentes_export.to_pandas()

        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df_docentes_pd.to_excel(
                writer,
                index=False,
                sheet_name="Docentes"
            )

        buffer.seek(0)

        st.download_button(
            label="⬇️ Descargar Excel de Docentes",
            data=buffer,
            file_name=f"Índice de no competencia Docente_Plantel({plantel}).xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Gráfica Top 15
        if not docentes_top.is_empty():
            graficar_barras(docentes_top, "DOCENTE")
        else:
            st.info("No hay suficientes datos para graficar el Top 15 de docentes.")
    else:
        st.info("No hay datos disponibles para docentes.")

    # =====================================================================
    #                           MÓDULOS
    # =====================================================================
    modulos = (
        df_filtrado
        .group_by("MODULO")
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL")
        )
        .with_columns(
            ((pl.col("NO_COMP") / pl.col("TOTAL") * 100).round(2)).alias("PORCENTAJE")
        )
        .sort("PORCENTAJE", descending=True)
        .head(15)
    )

    st.markdown("### 📚 Top 15 Módulos")
    if not modulos.is_empty():
        graficar_barras(modulos, "MODULO")
    else:
        st.info("No hay datos disponibles para módulos.")
