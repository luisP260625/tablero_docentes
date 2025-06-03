import streamlit as st
import polars as pl
import matplotlib.pyplot as plt

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

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(semanas, nc, color="#C7B07C", edgecolor="white")
    for i, bar in enumerate(bars):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{nc[i]} - {porcentajes[i]}", ha='center', va='bottom')
    st.pyplot(fig)

    ultima_semana = df["Semana"].max()

    df_modulos = df_docente.filter(df_docente["Semana"] == ultima_semana).group_by("MODULO").agg(
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        (pl.sum("TOTAL ALUMNOS") - pl.sum("NO COMPETENTES")).alias("COMPETENTES"),
        (pl.sum("NO COMPETENTES") / pl.sum("TOTAL ALUMNOS") * 100).alias("PORCENTAJE_NO_COMP")
    ).sort("PORCENTAJE_NO_COMP", descending=True)

    # Reordenando las columnas antes de mostrar los datos
    df_modulos = df_modulos.select(["MODULO", "NO_COMP", "COMPETENTES", "TOTAL", "PORCENTAJE_NO_COMP"])
    st.markdown(f"### 📘 Módulos asignados al docente en la semana {ultima_semana}")
    st.dataframe(df_modulos.to_pandas(), use_container_width=True)

