import streamlit as st
import polars as pl
import matplotlib.pyplot as plt
import io
import pandas as pd
import unicodedata


# ========= Helpers Excel por docente =========
def _slugify_filename(text: str) -> str:
    """
    Convierte 'José Pérez / 3A' en un nombre seguro para archivo.
    """
    if not isinstance(text, str):
        text = str(text or "")

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    return "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_"
        for ch in text
    ).strip("_")


def _auto_width_xlsx(ws, df: pd.DataFrame, start_col=0):
    """
    Ajuste sencillo de ancho de columnas según contenido.
    """
    for idx, col in enumerate(df.columns, start=start_col):
        try:
            max_len_vals = df[col].astype(str).map(len).max() if not df.empty else 0
        except Exception:
            max_len_vals = 0

        header_len = len(str(col))
        width = min(max(max_len_vals, header_len) + 2, 60)

        try:
            ws.set_column(idx, idx, width)
        except Exception:
            pass


def _excel_docente_bytes(
    detalle_df: pd.DataFrame,
    resumen_semestre_df: pd.DataFrame | None,
    docente: str,
    modulo: str,
    plantel: str,
    semana: int | str,
) -> bytes:
    """
    Crea un Excel en memoria con:
    - Detalle por grupo
    - Resumen por semestre, si aplica
    """

    buffer = io.BytesIO()

    try:
        writer = pd.ExcelWriter(buffer, engine="xlsxwriter")
    except Exception:
        writer = pd.ExcelWriter(buffer)

    with writer:
        # ----------------------------
        # Hoja: Detalle por grupo
        # ----------------------------
        sheet_detalle = "Detalle por grupo"

        meta = pd.DataFrame(
            {
                "Campo": ["Docente", "Plantel", "Módulo", "Semana"],
                "Valor": [docente, plantel, modulo, semana],
            }
        )

        meta.to_excel(
            writer,
            sheet_name=sheet_detalle,
            index=False,
            startrow=0,
        )

        startrow = len(meta) + 2

        detalle_df.to_excel(
            writer,
            sheet_name=sheet_detalle,
            index=False,
            startrow=startrow,
        )

        wb = writer.book
        ws_det = writer.sheets[sheet_detalle]

        try:
            fmt_title = wb.add_format({"bold": True, "font_size": 12})
            ws_det.write(0, 0, "Campo", fmt_title)
            ws_det.write(0, 1, "Valor", fmt_title)
            ws_det.freeze_panes(startrow, 0)
        except Exception:
            pass

        _auto_width_xlsx(ws_det, detalle_df, start_col=0)

        # ----------------------------
        # Hoja: Resumen por semestre
        # ----------------------------
        if resumen_semestre_df is not None and not resumen_semestre_df.empty:
            sheet_resumen = "Resumen por semestre"

            resumen_semestre_df.to_excel(
                writer,
                sheet_name=sheet_resumen,
                index=False,
            )

            ws_res = writer.sheets[sheet_resumen]
            _auto_width_xlsx(ws_res, resumen_semestre_df, start_col=0)

    buffer.seek(0)
    return buffer.getvalue()


def _planteles_disponibles(df: pl.DataFrame) -> list[str]:
    """
    Obtiene planteles disponibles de forma segura.
    """
    if df is None or df.is_empty() or "Plantel" not in df.columns:
        return []

    return sorted(
        [str(x) for x in df["Plantel"].drop_nulls().unique().to_list()]
    )


def _normalizar_semcaptura(df_semcaptura: pl.DataFrame) -> pl.DataFrame:
    """
    Normaliza nombres de columnas mínimos para evitar errores.
    No fuerza todo a mayúsculas porque la vista usa Plantel, DOCENTE y MODULO.
    """

    if df_semcaptura is None or df_semcaptura.is_empty():
        return df_semcaptura

    rename_map = {}

    for col in df_semcaptura.columns:
        limpio = col.strip()

        if limpio.upper() == "PLANTEL":
            rename_map[col] = "Plantel"
        elif limpio.upper() == "DOCENTE":
            rename_map[col] = "DOCENTE"
        elif limpio.upper() == "MODULO":
            rename_map[col] = "MODULO"
        elif limpio.upper() == "GRUPO":
            rename_map[col] = "GRUPO"
        elif limpio.upper() == "UAPRENDIZAJE":
            rename_map[col] = "UAPRENDIZAJE"
        elif limpio.upper() == "RAPRENDIZAJE":
            rename_map[col] = "RAPRENDIZAJE"
        elif limpio.upper() == "IEVALUAR":
            rename_map[col] = "IEVALUAR"
        elif limpio.upper() == "IEVALUADOS":
            rename_map[col] = "IEVALUADOS"
        elif limpio.upper() == "PCAPTURA":
            rename_map[col] = "PCAPTURA"
        elif limpio.upper() == "TOTALE":
            rename_map[col] = "TOTALE"
        elif limpio.upper() == "ESTATUS":
            rename_map[col] = "ESTATUS"

    if rename_map:
        df_semcaptura = df_semcaptura.rename(rename_map)

    return df_semcaptura


def _validar_columnas(df: pl.DataFrame, columnas: list[str], nombre_df: str) -> bool:
    """
    Valida columnas requeridas.
    """
    faltantes = [c for c in columnas if c not in df.columns]

    if faltantes:
        st.error(f"❌ Faltan columnas en {nombre_df}: {faltantes}")

        with st.expander(f"Columnas disponibles en {nombre_df}"):
            st.write(df.columns)

        return False

    return True


def _graficar_semanal(df_semanal: pl.DataFrame):
    """
    Grafica no competentes por semana.
    """
    if df_semanal is None or df_semanal.is_empty():
        st.info("No hay información semanal para graficar.")
        return

    semanas = [int(s) for s in df_semanal["Semana"].to_list()]
    nc = [int(x) for x in df_semanal["NO_COMP"].to_list()]
    total = [int(x) for x in df_semanal["TOTAL"].to_list()]

    porcentajes = [
        f"{(n / t * 100):.1f}%" if t > 0 else "0%"
        for n, t in zip(nc, total)
    ]

    fig, ax = plt.subplots(figsize=(8, 3))

    bar_color = "#9f2241"

    bars = ax.bar(
        semanas,
        nc,
        width=0.6,
        align="center",
        color=bar_color,
        edgecolor=bar_color,
    )

    if semanas:
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

    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.set_xlabel("Semana")

    fig.tight_layout()
    st.pyplot(fig)


def mostrar(df, plantel_usuario, es_admin, df_semcaptura=None):
    """
    Vista: Módulos Seguimiento (FT)

    Optimización:
    - Ya no lee SemCaptura directamente desde Excel.
    - Recibe df_semcaptura desde app.py usando data.loader.cargar_semcaptura().
    """

    if df is None or df.is_empty():
        st.info("No hay información de Datos disponible para mostrar.")
        return

    if df_semcaptura is None or df_semcaptura.is_empty():
        st.info("No hay información de SemCaptura disponible para mostrar.")
        return

    df_semcaptura = _normalizar_semcaptura(df_semcaptura)

    columnas_datos = [
        "Plantel",
        "Semana",
        "MODULO",
        "DOCENTE",
        "NO COMPETENTES",
        "TOTAL ALUMNOS",
        "SEMESTRE",
    ]

    columnas_semcaptura = [
        "Plantel",
        "DOCENTE",
        "MODULO",
        "GRUPO",
        "UAPRENDIZAJE",
        "RAPRENDIZAJE",
        "IEVALUAR",
        "IEVALUADOS",
        "PCAPTURA",
        "TOTALE",
        "ESTATUS",
    ]

    if not _validar_columnas(df, columnas_datos, "Datos"):
        return

    if not _validar_columnas(df_semcaptura, columnas_semcaptura, "SemCaptura"):
        return

    st.subheader("🚩 Módulos Críticos por Semana y Docente")

    # ----------------------------
    # Filtro de plantel
    # ----------------------------
    if es_admin:
        planteles = _planteles_disponibles(df)

        if not planteles:
            st.info("No hay planteles disponibles.")
            return

        plantel = st.selectbox(
            "🏫 Selecciona un plantel",
            planteles,
            key="mc_sel_plantel",
        )
    else:
        plantel = plantel_usuario
        st.text_input(
            "Plantel",
            plantel or "",
            disabled=True,
            key="mc_plantel_ro",
        )

    if not plantel:
        st.warning("No se encontró plantel para filtrar.")
        return

    df_plantel = df.filter(pl.col("Plantel") == plantel)

    if df_plantel.is_empty():
        st.info("No hay información para el plantel seleccionado.")
        return

    # ----------------------------
    # Agrupación por módulo/docente/semana
    # ----------------------------
    modulos_criticos = (
        df_plantel.group_by(["Semana", "MODULO", "DOCENTE"])
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        )
        .with_columns(
            (
                pl.col("NO_COMP")
                / pl.when(pl.col("TOTAL") > 0)
                .then(pl.col("TOTAL"))
                .otherwise(1)
                .cast(pl.Float64)
                * 100
            )
            .fill_nan(0)
            .fill_null(0)
            .alias("PORCENTAJE")
        )
        .sort(["Semana", "PORCENTAJE"], descending=[True, True])
    )

    if modulos_criticos.is_empty():
        st.info("No hay módulos en el plantel seleccionado.")
        return

    modulos_disponibles = sorted(
        [str(x) for x in modulos_criticos["MODULO"].drop_nulls().unique().to_list()]
    )

    if not modulos_disponibles:
        st.info("No hay módulos disponibles para el plantel seleccionado.")
        return

    modulo = st.selectbox(
        "📚 Selecciona un módulo crítico",
        modulos_disponibles,
        key="mc_sel_modulo",
    )

    df_modulo_completo = df_plantel.filter(pl.col("MODULO") == modulo)

    if df_modulo_completo.is_empty():
        st.info("No hay información para el módulo seleccionado.")
        return

    # ----------------------------
    # Gráfica semanal
    # ----------------------------
    st.markdown(f"### 📊 Seguimiento semanal del módulo: {modulo}")

    df_semanal = (
        df_modulo_completo.group_by("Semana")
        .agg(
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        )
        .sort("Semana")
        .with_columns(
            (
                pl.col("NO_COMP")
                / pl.when(pl.col("TOTAL") > 0)
                .then(pl.col("TOTAL"))
                .otherwise(1)
                .cast(pl.Float64)
                * 100
            )
            .fill_nan(0)
            .fill_null(0)
            .alias("PORCENTAJE")
        )
    )

    _graficar_semanal(df_semanal)

    # ----------------------------
    # Última semana con actividad
    # ----------------------------
    ultima_semana = df_modulo_completo["Semana"].max()

    if ultima_semana is None:
        st.info("No se pudo identificar la última semana del módulo.")
        return

    try:
        ultima_semana = int(ultima_semana)
    except Exception:
        pass

    df_modulo_ultima = df_modulo_completo.filter(pl.col("Semana") == ultima_semana)

    st.markdown(f"### 👨‍🏫 Docentes que impartieron el módulo en la semana {ultima_semana}")

    docentes = sorted(
        [str(x) for x in df_modulo_ultima["DOCENTE"].drop_nulls().unique().to_list()]
    )

    if not docentes:
        st.info("No hay docentes disponibles para este módulo.")
        return

    # ----------------------------
    # Detalle por docente
    # ----------------------------
    for docente in docentes:
        st.markdown(f"#### 👤 Docente: {docente}")

        df_docente = df_modulo_ultima.filter(pl.col("DOCENTE") == docente)

        # ----------------------------
        # Resumen por semestre
        # ----------------------------
        resumen_1 = (
            df_docente.group_by("SEMESTRE")
            .agg(
                pl.sum("NO COMPETENTES").alias("NO_COMP"),
                pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
            )
            .with_columns(
                [
                    (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
                    (
                        pl.col("NO_COMP")
                        / pl.when(pl.col("TOTAL") > 0)
                        .then(pl.col("TOTAL"))
                        .otherwise(1)
                        .cast(pl.Float64)
                        * 100
                    )
                    .round(2)
                    .alias("PORCENTAJE_NO_COMP"),
                ]
            )
            .fill_null(0)
        )

        resumen_1_filtrado = (
            resumen_1.with_columns(
                [
                    (
                        (pl.col("NO_COMP") == 0)
                        & (pl.col("COMPETENTES") == 0)
                        & (pl.col("TOTAL") == 0)
                        & (
                            (pl.col("PORCENTAJE_NO_COMP") == 0)
                            | (pl.col("PORCENTAJE_NO_COMP").is_null())
                        )
                    ).alias("FILA_VACIA")
                ]
            )
            .filter(~pl.col("FILA_VACIA"))
            .drop("FILA_VACIA")
        )

        if not resumen_1_filtrado.is_empty():
            st.markdown("**📌 Resumen por semestre**")
            st.dataframe(
                resumen_1_filtrado.to_pandas(),
                use_container_width=True,
            )
        else:
            st.info("📬 No hay datos relevantes en el resumen por semestre para este docente.")

        # ----------------------------
        # Detalle por grupo desde SemCaptura
        # ----------------------------
        df_sem_grupo = df_semcaptura.filter(
            (pl.col("Plantel") == plantel)
            & (pl.col("DOCENTE") == docente)
            & (pl.col("MODULO") == modulo)
        )

        columnas_detalle = [
            "GRUPO",
            "UAPRENDIZAJE",
            "RAPRENDIZAJE",
            "IEVALUAR",
            "IEVALUADOS",
            "PCAPTURA",
            "TOTALE",
            "ESTATUS",
        ]

        if df_sem_grupo.is_empty():
            st.info("📬 No hay información detallada por grupo para este docente.")
            continue

        resumen_2 = df_sem_grupo.select(columnas_detalle).sort(
            ["GRUPO", "RAPRENDIZAJE"]
        )

        resumen_2_clean = resumen_2.fill_null(0)

        resumen_2_filtrado = resumen_2_clean.filter(
            ~(
                (pl.col("IEVALUAR") == 0)
                & (pl.col("IEVALUADOS") == 0)
                & (pl.col("TOTALE") == 0)
            )
        )

        if resumen_2_filtrado.is_empty():
            st.info("📬 No hay información detallada por grupo para este docente.")
            continue

        st.markdown(
            "**📄 Detalle por grupo: El porcentaje de captura que se presenta, "
            "corresponde al conjunto de los indicadores evaluados.**"
        )

        detalle_pd = resumen_2_filtrado.to_pandas()

        st.dataframe(
            detalle_pd,
            use_container_width=True,
        )

        # ----------------------------
        # Botón Excel por docente
        # ----------------------------
        docente_slug = _slugify_filename(docente)
        archivo_nombre = f"{docente_slug}_porcentajeCaptura.xlsx"

        resumen_sem_pd = (
            resumen_1_filtrado.to_pandas()
            if not resumen_1_filtrado.is_empty()
            else None
        )

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
            help="Crea un archivo Excel con el Detalle por grupo y el Resumen por semestre si aplica.",
            key=f"mc_download_{plantel}_{modulo}_{docente}_{ultima_semana}",
        )