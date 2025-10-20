# views/modulo_semcaptura.py
import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
import os
import io
import pandas as pd
import unicodedata
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

# ========= Helpers Excel por docente =========
def _slugify_filename(text: str) -> str:
    """Convierte 'José Pérez / 3A' -> 'Jose_Perez__3A' y limpia caracteres inválidos."""
    if not isinstance(text, str):
        text = str(text or "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text).strip("_")

def _auto_width_xlsx(ws, df: pd.DataFrame, start_col=0):
    """Ajuste sencillo de ancho de columnas según contenido."""
    for idx, col in enumerate(df.columns, start=start_col):
        try:
            max_len_vals = df[col].astype(str).map(len).max() if not df.empty else 0
        except Exception:
            max_len_vals = 0
        header_len = len(str(col))
        width = min(max(max_len_vals, header_len) + 2, 60)
        ws.set_column(idx, idx, width)

def _excel_docente_bytes(
    detalle_df: pd.DataFrame,
    resumen_semestre_df: pd.DataFrame | None,
    docente: str,
    modulo: str,
    plantel: str,
    semana: int | str,
) -> bytes:
    """Crea un Excel en memoria con 'Detalle por grupo' y opcional 'Resumen por semestre'."""
    buffer = io.BytesIO()
    # Intentamos xlsxwriter; si no, usamos openpyxl
    try:
        writer = pd.ExcelWriter(buffer, engine="xlsxwriter")
    except Exception:
        writer = pd.ExcelWriter(buffer)  # que pandas elija engine disponible

    with writer:
        # --- Hoja: Detalle por grupo ---
        sheet_detalle = "Detalle por grupo"
        meta = pd.DataFrame(
            {
                "Campo": ["Docente", "Plantel", "Módulo", "Semana"],
                "Valor": [docente, plantel, modulo, semana],
            }
        )
        meta.to_excel(writer, sheet_name=sheet_detalle, index=False, startrow=0)
        startrow = len(meta) + 2  # dejar una fila en blanco
        detalle_df.to_excel(writer, sheet_name=sheet_detalle, index=False, startrow=startrow)

        wb = writer.book
        ws_det = writer.sheets[sheet_detalle]

        # Estilos simples
        try:
            fmt_title = wb.add_format({"bold": True, "font_size": 12})
            ws_det.write(0, 0, "Campo", fmt_title)
            ws_det.write(0, 1, "Valor", fmt_title)
            ws_det.freeze_panes(startrow, 0)
        except Exception:
            pass

        # Auto ancho de columnas (para tabla)
        _auto_width_xlsx(ws_det, detalle_df, start_col=0)

        # --- Hoja: Resumen por semestre (opcional) ---
        if resumen_semestre_df is not None and not resumen_semestre_df.empty:
            sheet_resumen = "Resumen por semestre"
            resumen_semestre_df.to_excel(writer, sheet_name=sheet_resumen, index=False)
            ws_res = writer.sheets[sheet_resumen]
            _auto_width_xlsx(ws_res, resumen_semestre_df, start_col=0)

    buffer.seek(0)
    return buffer.getvalue()
# ========= Fin helpers Excel =========


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

    semanas = [int(s) for s in df_semanal["Semana"].to_list()]
    nc = df_semanal["NO_COMP"].to_list()
    ta = df_semanal["TOTAL"].to_list()
    porcentajes = [f"{(n / t * 100):.1f}%" if t > 0 else "0%" for n, t in zip(nc, ta)]

    fig, ax = plt.subplots(figsize=(8, 3))
    bar_color = "#9f2241"
    bars = ax.bar(semanas, nc, width=0.6, align="center", color=bar_color, edgecolor=bar_color)
    if len(semanas) > 0:
        ax.set_xticks(semanas)
        ax.set_xlim(min(semanas) - 0.5, max(semanas) + 0.5)
    y_max = max(nc) if nc else 0
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)
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
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.set_xlabel("Semana")
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

        # Resumen por semestre (para hoja opcional en Excel)
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

        # Detalle por grupo (base para Excel)
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

            # ========= Botón Excel por DOCENTE =========
            docente_slug = _slugify_filename(docente)
            archivo_nombre = f"{docente_slug}_porcentajeCaptura.xlsx"

            detalle_pd = resumen_2_filtrado.to_pandas()
            resumen_sem_pd = resumen_1_filtrado.to_pandas() if not resumen_1_filtrado.is_empty() else None

            excel_bytes = _excel_docente_bytes(
                detalle_df=detalle_pd,
                resumen_semestre_df=resumen_sem_pd,
                docente=docente,
                modulo=modulo,
                plantel=plantel,
                semana=ultima_semana,
            )

            st.download_button(
                label="⬇️ Crear/Descargar Excel del docente",
                data=excel_bytes,
                file_name=archivo_nombre,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Crea un archivo Excel con el Detalle por grupo y (si aplica) el Resumen por semestre.",
            )
            # ========= Fin Botón Excel =========

        else:
            st.info("📬 No hay información detallada por grupo para este docente.")


