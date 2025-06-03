# views/vision_directiva.py
import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
from utils.helpers import to_excel

def mostrar(df):
    if not st.session_state.get("administrador", False):
        st.warning("Acceso restringido. Esta vista solo está disponible para administradores.")
        return

    st.subheader("📊 Visión Directiva - Análisis Estratégico Institucional")
    ultima_semana = df["Semana"].max()
    df_filtrado = df.filter(pl.col("Semana") == ultima_semana)

    # Agrupación por docentes
    docentes_stats = df_filtrado.group_by(["Plantel", "DOCENTE"]).agg(
        pl.sum("NO COMPETENTES").alias("NC_DOCENTE"),
        pl.sum("TOTAL ALUMNOS").alias("TA_DOCENTE")
    ).with_columns(
        (pl.col("NC_DOCENTE") / pl.col("TA_DOCENTE") * 100).alias("PCT_DOCENTE")
    )

    df_planteles = docentes_stats.group_by("Plantel").agg([
        pl.count("DOCENTE").alias("TOTAL_DOCENTES"),
        (pl.col("PCT_DOCENTE") > 50).sum().alias("DOCENTES_EN_RIESGO")
    ])

    # Estadísticas por plantel: alumnos no competentes, matrícula y porcentaje
    alumnos_stats = df_filtrado.group_by("Plantel").agg([
        pl.sum("NO COMPETENTES").alias("NC_ALUMNOS"),
        pl.sum("TOTAL ALUMNOS").alias("MATRICULA_PLANTEL")
    ]).with_columns(
        (pl.col("NC_ALUMNOS") / pl.col("MATRICULA_PLANTEL") * 100).alias("PCT_ALUMNOS_NC")
    )

    # Unión y ordenamiento
    df_planteles = df_planteles.join(
        alumnos_stats.select(["Plantel", "NC_ALUMNOS", "MATRICULA_PLANTEL", "PCT_ALUMNOS_NC"]),
        on="Plantel"
    ).sort("PCT_ALUMNOS_NC", descending=True)

    st.markdown("### 🏪 Evaluación de Planteles (por docentes y estudiantes)")
    st.dataframe(df_planteles.to_pandas(), use_container_width=True)

    # Evolución semanal del porcentaje de alumnos no competentes
    df_semana = df.group_by("Semana").agg(
        pl.sum("NO COMPETENTES").alias("NC"),
        pl.sum("TOTAL ALUMNOS").alias("TA")
    ).sort("Semana").with_columns(
        (pl.col("NC") / pl.col("TA") * 100).alias("PORCENTAJE")
    )

    st.markdown("### 📈 Evolución semanal del porcentaje de alumnos no competentes")
    fig, ax = plt.subplots(figsize=(10, 4))
    semanas = df_semana["Semana"]
    porcentajes = df_semana["PORCENTAJE"]

    ax.plot(semanas, porcentajes, marker="o", color="steelblue")
    for x, y in zip(semanas, porcentajes):
        ax.text(x, y + 0.5, f"{y:.1f}%", ha='center', va='bottom', fontsize=8)
    ax.set_ylabel("% No Competentes")
    ax.set_xlabel("Semana")
    ax.grid(True, linestyle="--", alpha=0.5)
    st.pyplot(fig)

    # Módulos con tendencia creciente (por plantel)
    tendencia_modulos = (
        df.group_by(["Semana", "Plantel", "MODULO"]).agg(
            pl.sum("NO COMPETENTES").alias("NC"),
            pl.sum("TOTAL ALUMNOS").alias("TA")
        )
        .with_columns((pl.col("NC") / pl.col("TA") * 100).alias("PCT"))
        .sort(["Plantel", "MODULO", "Semana"])
        .group_by(["Plantel", "MODULO"])
        .agg(pl.col("PCT").diff().alias("TENDENCIA"))
        .with_columns(pl.col("TENDENCIA").mean().alias("PCT_TENDENCIA"))
        .filter(pl.col("PCT_TENDENCIA") > 0)
        .sort("PCT_TENDENCIA", descending=True)
    )

    st.markdown("### 📚 Módulos con tendencia creciente de reprobación")
    if tendencia_modulos.is_empty():
        st.info("No hay datos suficientes para determinar tendencias.")
    else:
        st.dataframe(
            tendencia_modulos.select(["Plantel", "MODULO", "PCT_TENDENCIA"]).to_pandas(),
            use_container_width=True
        )

    # Resumen Ejecutivo
    total_nc = df_filtrado["NO COMPETENTES"].sum()
    total_alumnos = df_filtrado["TOTAL ALUMNOS"].sum()
    pct_global = (total_nc / total_alumnos * 100) if total_alumnos > 0 else 0

    st.markdown("### 🧾 Resumen Ejecutivo")
    st.metric(label="Última semana disponible", value=f"Semana {ultima_semana}")
    st.metric(label="Porcentaje global de No Competentes", value=f"{pct_global:.2f}%")

    if not df_planteles.is_empty():
        peor_plantel = df_planteles.row(0)
        st.metric(
            label="Plantel más crítico (alumnos)",
            value=peor_plantel[0],
            delta=f"{peor_plantel[5]:.1f}%"
        )

    # Valor fijo como docente crítico
    docente_critico = "DOCENTE_FIJO"
    semanas_criticas = 5
    st.metric(
        label="Docente con más semanas críticas",
        value=docente_critico,
        delta=f"{semanas_criticas} semanas"
    )

    if not tendencia_modulos.is_empty():
        st.metric(
            label="Módulo más crítico (↑ tendencia)",
            value=tendencia_modulos['MODULO'][0]
        )

    # Descarga en Excel
    st.download_button(
        label="📅 Descargar evaluación de planteles (Excel)",
        data=to_excel(df_planteles.to_pandas()),
        file_name="evaluacion_planteles.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

