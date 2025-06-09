import streamlit as st
import polars as pl
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO

def generar_excel(df_docente):
    df_pandas = df_docente.to_pandas()

    # Crear un archivo en memoria
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
        df_pandas.to_excel(writer, sheet_name="Seguimiento Docente", index=False)

    excel_buffer.seek(0)
    return excel_buffer

def mostrar(df, plantel_usuario, es_admin):
    st.subheader("📈 Evolución Semanal del Desempeño Docente")

    plantel = st.selectbox("🏫 Selecciona un plantel", sorted(df["Plantel"].unique())) if es_admin else plantel_usuario
    docentes = df.filter(df["Plantel"] == plantel)["DOCENTE"].unique().to_list()
    docente = st.selectbox("👨‍🏫 Selecciona un docente", sorted(docentes))

    df_docente = df.filter((df["Plantel"] == plantel) & (df["DOCENTE"] == docente))

    df_agrupado = df_docente.group_by("Semana").agg(
        pl.sum("NO COMPETENTES").alias("NC"),
        pl.sum("TOTAL ALUMNOS").alias("TA")
    ).sort("Semana")

    semanas = df_agrupado["Semana"]
    nc = df_agrupado["NC"]
    ta = df_agrupado["TA"]
    porcentajes = [f"{(n / t * 100):.1f}%" if t > 0 else "0%" for n, t in zip(nc, ta)]

    # Generar la gráfica
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(semanas, nc, color="#C7B07C", edgecolor="white")
    for i, bar in enumerate(bars):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{nc[i]} - {porcentajes[i]}", ha='center', va='bottom')
    st.pyplot(fig)

    ultima_semana = df["Semana"].max()

    # Modificar la agrupación para incluir el semestre correctamente nombrado
    df_modulos = df_docente.filter(df_docente["Semana"] == ultima_semana).group_by(["MODULO", "SEMESTRE","PCAPTURA"]).agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        (pl.sum("TOTAL ALUMNOS") - pl.sum("NO COMPETENTES")).alias("COMPETENTES"),
        (pl.sum("NO COMPETENTES") / pl.sum("TOTAL ALUMNOS") * 100).alias("PORCENTAJE_NO_COMP")
    ).sort("PORCENTAJE_NO_COMP", descending=True)

    df_modulos = df_modulos.select(["MODULO", "SEMESTRE", "PCAPTURA", "NO_COMP", "COMPETENTES", "TOTAL", "PORCENTAJE_NO_COMP"])

    st.markdown(f"### 📘 Módulos asignados al docente en la semana {ultima_semana}")
    st.dataframe(df_modulos.to_pandas(), use_container_width=True)

    # Agregar botón de descarga sin eliminar la gráfica
    excel_buffer = generar_excel(df_docente)
    st.download_button(
        label="📥 Descargar seguimiento en Excel",
        data=excel_buffer,
        file_name=f"seguimiento_{docente}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )