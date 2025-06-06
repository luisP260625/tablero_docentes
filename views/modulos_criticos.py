import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
from utils.helpers import to_excel

def mostrar(df, plantel_usuario, es_admin):
    st.subheader("🚩 Módulos Críticos por Semana y Docente")

    # Selección de plantel
    plantel = st.selectbox("🏫 Selecciona un plantel", sorted(df["Plantel"].unique())) if es_admin else plantel_usuario
    df_plantel = df.filter(pl.col("Plantel") == plantel)

    # Agrupar datos y calcular porcentaje de no competentes (sin filtrar por porcentaje)
    modulos_criticos = df_plantel.group_by(["Semana", "MODULO", "DOCENTE"]).agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL")
    ).with_columns(
        (pl.col("NO_COMP") / pl.col("TOTAL") * 100).alias("PORCENTAJE")
    ).sort(["Semana", "PORCENTAJE"], descending=True)  # Ordenar por semana y porcentaje

    if modulos_criticos.is_empty():
        st.info("No hay módulos en el plantel seleccionado.")
        return

    # Selección de módulo crítico
    modulos_disponibles = sorted(modulos_criticos["MODULO"].unique().to_list())
    modulo = st.selectbox("📚 Selecciona un módulo crítico", modulos_disponibles)

    # 🔁 Usar todos los datos del módulo (sin filtro de porcentaje) para gráfica y exportación
    df_modulo_completo = df_plantel.filter(pl.col("MODULO") == modulo)

    # Gráfica de evolución semanal - usando todos los docentes
    st.markdown(f"### 📊 Seguimiento semanal de No Competentes en el módulo: {modulo}")
    df_semanal = df_modulo_completo.group_by("Semana").agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL")
    ).sort("Semana").with_columns(
        (pl.col("NO_COMP") / pl.col("TOTAL") * 100).alias("PORCENTAJE")
    )

    semanas = df_semanal["Semana"]
    nc = df_semanal["NO_COMP"]
    ta = df_semanal["TOTAL"]
    porcentajes = [f"{(n / t * 100):.1f}%" if t > 0 else "0%" for n, t in zip(nc, ta)]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(semanas, nc, color="firebrick", edgecolor="firebrick")
    for i, bar in enumerate(bars):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{nc[i]} - {porcentajes[i]}", ha='center', va='bottom')
    ax.set_ylabel("No Competentes")
    ax.set_title(f"Evolución semanal del módulo {modulo}")
    st.pyplot(fig)

    # Obtener la última semana disponible para ese módulo
    ultima_semana = df_modulo_completo["Semana"].max()

    # Filtrar todos los docentes que impartieron ese módulo en esa semana (sin filtrar por porcentaje)
    df_modulo_ultima = df_modulo_completo.filter(
        pl.col("Semana") == ultima_semana
    )

    # Mostrar tabla de docentes que impartieron el módulo en la última semana
    st.markdown(f"### 👨‍🏫 Docentes que impartieron el módulo en la semana {ultima_semana}")

    df_docentes = df_modulo_ultima.group_by(["DOCENTE", "SEMESTRE"]).agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL")
    ).with_columns([
        (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
        (pl.col("NO_COMP") / pl.col("TOTAL") * 100).alias("PORCENTAJE_NO_COMP")
    ]).sort("PORCENTAJE_NO_COMP", descending=True)

    # Reordenando las columnas antes de mostrarlas
    df_docentes = df_docentes.select(["DOCENTE", "SEMESTRE","NO_COMP", "COMPETENTES", "TOTAL", "PORCENTAJE_NO_COMP"])

    st.dataframe(df_docentes.to_pandas(), use_container_width=True)

    # Botón de descarga (todos los datos del módulo sin filtro por porcentaje)
    excel_data = to_excel(df_modulo_completo.to_pandas())
    st.download_button(
        label="📥 Descargar reporte detallado del módulo",
        data=excel_data,
        file_name=f"modulo_{modulo}_detalle.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

