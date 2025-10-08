# views/modulo_semcaptura.py  (o el nombre que uses para este módulo)
import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
import os
from utils.helpers import to_excel
from config import RUTA_EXCEL_SEMCAPTURA

@st.cache_data
def cargar_semcaptura():
    if not os.path.exists(RUTA_EXCEL_SEMCAPTURA):
        st.error("❌ No se encontró el archivo 'Datos1.xlsx' en la carpeta 'assets'.")
        return None
    try:
        return pl.read_excel(RUTA_EXCEL_SEMCAPTURA, sheet_name="SemCaptura")
    except Exception as e:
        st.error(f"❌ Error al leer la hoja 'SemCaptura': {e}")
        return None

def mostrar(df, plantel_usuario, es_admin):
    df_semcaptura = cargar_semcaptura()
    if df_semcaptura is None:
        st.stop()

    st.subheader("🚩 Módulos Críticos por Semana y Docente")

    # --- filtros base ---
    plantel = (
        st.selectbox("🏫 Selecciona un plantel", sorted(df["Plantel"].unique()))
        if es_admin else plantel_usuario
    )
    df_plantel = df.filter(pl.col("Plantel") == plantel)

    modulos_criticos = (
        df_plantel.group_by(["Semana", "MODULO", "DOCENTE"])
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        )
        .with_columns(
            (pl.col("NO_COMP") / pl.col("TOTAL").cast(pl.Float64) * 100)
            .fill_nan(0).fill_null(0).alias("PORCENTAJE")
        )
        .sort(["Semana", "PORCENTAJE"], descending=True)
    )

    if modulos_criticos.is_empty():
        st.info("No hay módulos en el plantel seleccionado.")
        return

    modulos_disponibles = sorted(modulos_criticos["MODULO"].unique().to_list())
    modulo = st.selectbox("📚 Selecciona un módulo crítico", modulos_disponibles)

    df_modulo_completo = df_plantel.filter(pl.col("MODULO") == modulo)

    # ================== GRÁFICA SEMANAL (ACTUALIZADA) ==================
    st.markdown(f"### 📊 Seguimiento semanal del módulo: {modulo}")

    df_semanal = (
        df_modulo_completo.group_by("Semana")
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        )
        .sort("Semana")
        .with_columns(
            (pl.col("NO_COMP") / pl.col("TOTAL").cast(pl.Float64) * 100)
            .fill_nan(0).fill_null(0).alias("PORCENTAJE")
        )
    )

    # Datos para la gráfica
    semanas = [int(s) for s in df_semanal["Semana"].to_list()]                  # solo semanas existentes
    nc = df_semanal["NO_COMP"].to_list()
    ta = df_semanal["TOTAL"].to_list()
    porcentajes = [f"{(n / t * 100):.1f}%" if t > 0 else "0%" for n, t in zip(nc, ta)]

    fig, ax = plt.subplots(figsize=(8, 3))
    bar_color = "#9f2241"                                                      # color solicitado
    bars = ax.bar(semanas, nc, width=0.6, align="center", color=bar_color, edgecolor=bar_color)

    # Ticks SOLO de semanas presentes + límites para evitar 4.6, 4.7, ...
    if len(semanas) > 0:
        ax.set_xticks(semanas)
        ax.set_xlim(min(semanas) - 0.5, max(semanas) + 0.5)

    # Margen superior para que no se salgan las etiquetas
    y_max = max(nc) if nc else 0
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)

    # Etiquetas "conteo - porcentaje" rotadas (dentro del área)
    total = sum(nc) if nc else 0
    for i, bar in enumerate(bars):
        ax.annotate(
            f"{nc[i]} - {porcentajes[i]}",
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            rotation=90,
            fontsize=8,
        )

    # Limpieza visual y SIN etiqueta de eje Y
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.set_xlabel("Semana")
    # ax.set_ylabel("No Competentes")  # <- eliminado

    fig.tight_layout()
    st.pyplot(fig)
    # ================== FIN GRÁFICA SEMANAL ==================

    # Última semana con actividad
    ultima_semana = int(df_modulo_completo["Semana"].max())
    df_modulo_ultima = df_modulo_completo.filter(pl.col("Semana") == ultima_semana)

    st.markdown(f"### 👨‍🏫 Docentes que impartieron el módulo en la semana {ultima_semana}")
    docentes = df_modulo_ultima["DOCENTE"].unique().to_list()

    for docente in docentes:
        st.markdown(f"#### 👤 Docente: {docente}")
        df_docente = df_modulo_ultima.filter(pl.col("DOCENTE") == docente)

        # Resumen por semestre
        resumen_1 = (
            df_docente.group_by("SEMESTRE")
            .agg(
                pl.sum("NO COMPETENTES").alias("NO_COMP"),
                pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
            )
            .with_columns([
                (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
                (
                    pl.col("NO_COMP")
                    / pl.when(pl.col("TOTAL") > 0).then(pl.col("TOTAL")).otherwise(1).cast(pl.Float64)
                    * 100
                ).round(2).alias("PORCENTAJE_NO_COMP"),
            ])
        )

        resumen_1_clean = resumen_1.fill_null(0).with_columns([
            pl.col("NO_COMP").cast(pl.Float64),
            pl.col("COMPETENTES").cast(pl.Float64),
            pl.col("TOTAL").cast(pl.Float64),
            pl.col("PORCENTAJE_NO_COMP").cast(pl.Float64),
        ])

        resumen_1_limpio = resumen_1_clean.with_columns([
            (
                (pl.col("NO_COMP") == 0)
                & (pl.col("COMPETENTES") == 0)
                & (pl.col("TOTAL") == 0)
                & ((pl.col("PORCENTAJE_NO_COMP") == 0) | (pl.col("PORCENTAJE_NO_COMP").is_null()))
            ).alias("FILA_VACIA")
        ])

        resumen_1_filtrado = resumen_1_limpio.filter(~pl.col("FILA_VACIA")).drop("FILA_VACIA")

        if not resumen_1_filtrado.is_empty():
            st.markdown("**📌 Resumen por semestre**")
            st.dataframe(resumen_1_filtrado.to_pandas(), use_container_width=True)
        else:
            st.info("📬 No hay datos relevantes en el resumen por semestre para este docente.")

        # Detalle por grupo (sin perder funcionalidad)
        df_sem_grupo = df_semcaptura.filter(
            (pl.col("Plantel") == plantel)
            & (pl.col("DOCENTE") == docente)
            & (pl.col("MODULO") == modulo)
        )

        columnas = [
            "GRUPO", "UAPRENDIZAJE", "RAPRENDIZAJE",
            "IEVALUAR", "IEVALUADOS", "PCAPTURA", "TOTALE", "ESTATUS",
        ]

        resumen_2 = df_sem_grupo.select(columnas).sort(["GRUPO", "RAPRENDIZAJE"])
        resumen_2_clean = resumen_2.fill_null(0)

        resumen_2_filtrado = resumen_2_clean.filter(
            ~(
                (pl.col("IEVALUAR") == 0)
                & (pl.col("IEVALUADOS") == 0)
                & (pl.col("TOTALE") == 0)
            )
        )

        if not resumen_2_filtrado.is_empty():
            st.markdown("**📄 Detalle por grupo: El porcentaje de captura que se presenta, corresponde al conjunto de los indicadores evaluados.**")
            st.dataframe(resumen_2_filtrado.to_pandas(), use_container_width=True)
        else:
            st.info("📬 No hay información detallada por grupo para este docente.")

    # Exportar Excel del módulo completo (sin cambios)
    excel_data = to_excel(df_modulo_completo.to_pandas())
    st.download_button(
        label="📅 Descargar reporte detallado del módulo",
        data=excel_data,
        file_name=f"modulo_{modulo}_detalle.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

