import base64
import io
import json
import re
import uuid
from typing import List, Optional, Sequence, Tuple

import pandas as pd
import plotly.graph_objects as go
import polars as pl
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# CONFIGURACIÓN VISUAL
# ============================================================
BAR_COLOR = "#7A1631"          # Color vino
BAR_LINE_COLOR = "#7A1631"
TEXT_COLOR = "#334155"
LABEL_COLOR = "#475569"

COLUMNAS_REQUERIDAS = [
    "Semana",
    "Plantel",
    "DOCENTE",
    "MODULO",
    "NO COMPETENTES",
    "TOTAL ALUMNOS",
]

VALORES_TEXTO_INVALIDOS = ["", "nan", "none", "null"]


# ============================================================
# HELPERS DE DATOS
# ============================================================
def _wk_key(valor):
    """
    Permite ordenar semanas tipo:
    - 1
    - 12
    - Semana 12
    - Sem 12
    """
    if valor is None:
        return 999999

    texto = str(valor).strip()
    nums = re.findall(r"\d+", texto)

    if nums:
        try:
            return int(nums[0])
        except Exception:
            return 999999

    return 999999


def _ordenar_valores_select(valores: Sequence) -> List[str]:
    """
    Limpia y ordena valores para usarlos en selectbox.
    """
    valores_limpios = []

    for v in valores:
        if v is None:
            continue

        txt = str(v).strip()

        if not txt or txt.lower() in ("nan", "none", "null"):
            continue

        valores_limpios.append(txt)

    return sorted(
        list(dict.fromkeys(valores_limpios)),
        key=lambda x: (_wk_key(x), str(x).strip().lower()),
    )


def _asegurar_polars(df):
    """
    Asegura que el DataFrame recibido sea Polars.
    Se conserva compatibilidad si llega como pandas.
    """
    if isinstance(df, pl.DataFrame):
        return df

    if isinstance(df, pd.DataFrame):
        return pl.from_pandas(df)

    try:
        return pl.DataFrame(df)
    except Exception:
        return pl.DataFrame()


def _validar_columnas(df: pl.DataFrame) -> bool:
    """
    Valida que existan las columnas necesarias para calcular los Top 15.
    """
    faltantes = [col for col in COLUMNAS_REQUERIDAS if col not in df.columns]

    if faltantes:
        st.error(
            "El DataFrame no contiene las columnas requeridas para este módulo: "
            + ", ".join(faltantes)
        )
        return False

    return True


def _filtro_texto_valido(columna: str):
    """
    Genera una expresión Polars para descartar textos vacíos o inválidos.
    """
    return (
        pl.col(columna).is_not_null()
        & (
            ~pl.col(columna)
            .str.strip_chars()
            .str.to_lowercase()
            .is_in(VALORES_TEXTO_INVALIDOS)
        )
    )


def _obtener_config_relacion(columna: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Define qué columna relacionada debe agregarse al Excel.

    - Si el Excel es por DOCENTE, se agrega la lista de MODULOS.
    - Si el Excel es por MODULO, se agrega la lista de DOCENTES.
    """
    if columna == "DOCENTE":
        return "MODULO", "MODULOS_RELACIONADOS", "Módulos que imparte"

    if columna == "MODULO":
        return "DOCENTE", "DOCENTES_RELACIONADOS", "Docentes que imparten el módulo"

    return None, None, None


def preparar_dataframe_base(df) -> pl.DataFrame:
    """
    Prepara únicamente las columnas necesarias.

    Mejora rendimiento porque:
    - No arrastra columnas innecesarias.
    - Convierte tipos una sola vez.
    - Mantiene cálculos en Polars.
    """
    df_pl = _asegurar_polars(df)

    if df_pl.is_empty():
        return df_pl

    if not _validar_columnas(df_pl):
        return pl.DataFrame()

    return (
        df_pl
        .select(COLUMNAS_REQUERIDAS)
        .with_columns([
            pl.col("Semana").cast(pl.Utf8).str.strip_chars(),
            pl.col("Plantel").cast(pl.Utf8).str.strip_chars(),
            pl.col("DOCENTE").cast(pl.Utf8).str.strip_chars(),
            pl.col("MODULO").cast(pl.Utf8).str.strip_chars(),

            pl.col("NO COMPETENTES")
            .cast(pl.Float64, strict=False)
            .fill_null(0)
            .fill_nan(0),

            pl.col("TOTAL ALUMNOS")
            .cast(pl.Float64, strict=False)
            .fill_null(0)
            .fill_nan(0),
        ])
    )


def obtener_opciones(df: pl.DataFrame, columna: str) -> List[str]:
    """
    Obtiene opciones únicas para filtros.
    """
    if df.is_empty() or columna not in df.columns:
        return []

    return _ordenar_valores_select(df[columna].unique().to_list())


def filtrar_por_semana_plantel(
    df: pl.DataFrame,
    semana: str,
    plantel: str,
) -> pl.DataFrame:
    """
    Filtra por semana y plantel.
    """
    if df.is_empty():
        return df

    return (
        df
        .lazy()
        .filter(
            (pl.col("Semana") == str(semana).strip())
            & (pl.col("Plantel") == str(plantel).strip())
        )
        .collect()
    )


def calcular_top_no_competencia(
    df_filtrado: pl.DataFrame,
    columna: str,
    top_n: int = 15,
    incluir_plantel: Optional[str] = None,
) -> pl.DataFrame:
    """
    Calcula el Top N por porcentaje de no competencia.

    Fórmula:
    PORCENTAJE = NO_COMP / TOTAL * 100

    Importante:
    - Esta función sigue limitada a Top 15 para la gráfica.
    - El Excel completo se calcula en otra función.
    """
    if df_filtrado.is_empty() or columna not in df_filtrado.columns:
        return pl.DataFrame()

    expresiones_extra = [
        (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
        ((pl.col("NO_COMP") / pl.col("TOTAL") * 100).round(2)).alias("PORCENTAJE"),
    ]

    if incluir_plantel is not None:
        expresiones_extra.insert(
            0,
            pl.lit(str(incluir_plantel)).alias("PLANTEL"),
        )

    return (
        df_filtrado
        .lazy()
        .filter(_filtro_texto_valido(columna))
        .group_by(columna)
        .agg([
            pl.sum("NO COMPETENTES").alias("NO_COMP"),
            pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
        ])
        .filter(pl.col("TOTAL") > 0)
        .with_columns(expresiones_extra)
        .sort(
            by=["PORCENTAJE", "NO_COMP", "TOTAL", columna],
            descending=[True, True, True, False],
        )
        .head(top_n)
        .collect()
    )


def calcular_no_competencia_completa(
    df_filtrado: pl.DataFrame,
    columna: str,
    semana: str,
    plantel: str,
) -> pl.DataFrame:
    """
    Calcula la tabla completa para exportar a Excel.

    Importante:
    - No limita a Top 15.
    - Usa exactamente el DataFrame ya filtrado por semana y plantel.
    - Si se exporta por DOCENTE, agrega los módulos que imparte.
    - Si se exporta por MODULO, agrega los docentes que imparten ese módulo.
    """
    if df_filtrado.is_empty() or columna not in df_filtrado.columns:
        return pl.DataFrame()

    columna_relacionada, alias_relacion, _ = _obtener_config_relacion(columna)

    agregaciones = [
        pl.sum("NO COMPETENTES").alias("NO_COMP"),
        pl.sum("TOTAL ALUMNOS").alias("TOTAL"),
    ]

    if columna_relacionada and columna_relacionada in df_filtrado.columns:
        agregaciones.append(
            pl.col(columna_relacionada)
            .filter(_filtro_texto_valido(columna_relacionada))
            .unique()
            .sort()
            .alias(alias_relacion)
        )

    expresiones_post = [
        pl.lit(str(semana)).alias("SEMANA"),
        pl.lit(str(plantel)).alias("PLANTEL"),
        (pl.col("TOTAL") - pl.col("NO_COMP")).alias("COMPETENTES"),
        ((pl.col("NO_COMP") / pl.col("TOTAL") * 100).round(2)).alias("PORCENTAJE"),
    ]

    if alias_relacion:
        expresiones_post.append(
            pl.col(alias_relacion)
            .list.join("| ")
            .alias(alias_relacion)
        )

    columnas_salida = [
        "SEMANA",
        "PLANTEL",
        columna,
    ]

    if alias_relacion:
        columnas_salida.append(alias_relacion)

    columnas_salida.extend([
        "NO_COMP",
        "COMPETENTES",
        "TOTAL",
        "PORCENTAJE",
    ])

    return (
        df_filtrado
        .lazy()
        .filter(_filtro_texto_valido(columna))
        .group_by(columna)
        .agg(agregaciones)
        .filter(pl.col("TOTAL") > 0)
        .with_columns(expresiones_post)
        .select(columnas_salida)
        .sort(
            by=["PORCENTAJE", "NO_COMP", "TOTAL", columna],
            descending=[True, True, True, False],
        )
        .collect()
    )


def _limpiar_nombre_archivo(texto: str) -> str:
    """
    Genera nombres de archivo seguros para la descarga.
    """
    texto_limpio = re.sub(r"[^A-Za-z0-9_-]+", "_", str(texto or "").strip())
    texto_limpio = texto_limpio.strip("_")

    return texto_limpio or "archivo"


def _generar_excel_base64(
    df_exportar: pl.DataFrame,
    columna: str,
    nombre_hoja: str,
) -> str:
    """
    Convierte el DataFrame completo a Excel y lo deja listo para descargar
    desde el botón personalizado de la barra de herramientas de Plotly.
    """
    if df_exportar is None or df_exportar.is_empty():
        return ""

    _, alias_relacion, nombre_columna_relacion = _obtener_config_relacion(columna)

    df_excel = df_exportar.to_pandas()

    nombre_columna_principal = "Docente" if columna == "DOCENTE" else "Módulo"

    rename_map = {
        "SEMANA": "Semana",
        "PLANTEL": "Plantel",
        columna: nombre_columna_principal,
        "NO_COMP": "No competentes",
        "COMPETENTES": "Competentes",
        "TOTAL": "Total alumnos",
        "PORCENTAJE": "% No competencia",
    }

    if alias_relacion and nombre_columna_relacion:
        rename_map[alias_relacion] = nombre_columna_relacion

    df_excel = df_excel.rename(columns=rename_map)

    columnas_ordenadas = [
        "Semana",
        "Plantel",
        nombre_columna_principal,
    ]

    if nombre_columna_relacion:
        columnas_ordenadas.append(nombre_columna_relacion)

    columnas_ordenadas.extend([
        "No competentes",
        "Competentes",
        "Total alumnos",
        "% No competencia",
    ])

    columnas_existentes = [col for col in columnas_ordenadas if col in df_excel.columns]
    df_excel = df_excel[columnas_existentes]

    salida = io.BytesIO()

    try:
        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            sheet_name = nombre_hoja[:31] or "Datos"
            df_excel.to_excel(writer, index=False, sheet_name=sheet_name)

            worksheet = writer.sheets[sheet_name]

            # Congelar encabezado para revisar mejor archivos largos.
            worksheet.freeze_panes = "A2"

            # Ajuste sencillo de anchos para que el archivo sea legible al abrirlo.
            for column_cells in worksheet.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter

                for cell in column_cells:
                    value = "" if cell.value is None else str(cell.value)
                    max_length = max(max_length, len(value))

                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 70)

            # Formato numérico del porcentaje.
            if "% No competencia" in df_excel.columns:
                porcentaje_col_idx = df_excel.columns.get_loc("% No competencia") + 1
                for row in range(2, worksheet.max_row + 1):
                    worksheet.cell(row=row, column=porcentaje_col_idx).number_format = '0.00'

    except Exception as exc:
        st.error(
            "No se pudo generar el Excel. Verifica que tengas instalado openpyxl "
            "en tu entorno de Streamlit. Detalle: " + str(exc)
        )
        return ""

    return base64.b64encode(salida.getvalue()).decode("utf-8")


def _renderizar_plotly_con_descarga_excel(
    fig: go.Figure,
    alto: int,
    nombre_archivo_imagen: str,
    nombre_archivo_excel: str,
    excel_base64: str,
):
    """
    Renderiza Plotly como componente HTML para poder agregar un botón
    personalizado en la barra de herramientas que descargue el Excel completo.
    """
    plot_id = f"plotly_{uuid.uuid4().hex}"
    fig_json = fig.to_json()

    html = f"""
    <div id="{plot_id}" style="width:100%;height:{alto}px;"></div>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
        const fig = {fig_json};
        const excelBase64 = {json.dumps(excel_base64)};
        const excelFileName = {json.dumps(nombre_archivo_excel)};

        const excelDownloadButton = {{
            name: 'Descargar Excel completo',
            title: 'Descargar Excel completo',
            icon: {{
                width: 512,
                height: 512,
                path: 'M256 32c17.7 0 32 14.3 32 32v192h70.1c28.5 0 42.8 34.5 22.6 54.6L278.6 412.7c-12.5 12.5-32.8 12.5-45.3 0L131.2 310.6c-20.2-20.2-5.9-54.6 22.6-54.6H224V64c0-17.7 14.3-32 32-32zM96 432h320c17.7 0 32 14.3 32 32s-14.3 32-32 32H96c-17.7 0-32-14.3-32-32s14.3-32 32-32z'
            }},
            click: function() {{
                if (!excelBase64) {{
                    alert('No hay datos disponibles para exportar.');
                    return;
                }}

                const link = document.createElement('a');
                link.href = 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,' + excelBase64;
                link.download = excelFileName;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            }}
        }};

        const config = {{
            displayModeBar: true,
            displaylogo: false,
            scrollZoom: false,
            responsive: true,
            modeBarButtonsToAdd: excelBase64 ? [excelDownloadButton] : [],
            modeBarButtonsToRemove: [
                'zoom2d',
                'pan2d',
                'select2d',
                'lasso2d',
                'autoScale2d',
                'resetScale2d',
                'zoomIn2d',
                'zoomOut2d'
            ],
            toImageButtonOptions: {{
                format: 'png',
                filename: {json.dumps(nombre_archivo_imagen)},
                height: 700,
                width: 1400,
                scale: 2
            }}
        }};

        const graphDiv = document.getElementById('{plot_id}');
        Plotly.newPlot(graphDiv, fig.data, fig.layout, config);

        window.addEventListener('resize', function() {{
            Plotly.Plots.resize(graphDiv);
        }});
    </script>
    """

    components.html(
        html,
        height=alto + 45,
        scrolling=False,
    )


# ============================================================
# GRÁFICA HORIZONTAL COLOR VINO
# ============================================================
def graficar_barras_horizontales(
    df: pl.DataFrame,
    columna: str,
    titulo: str = "",
    nombre_archivo: str = "grafica_no_competencia",
    df_excel_completo: Optional[pl.DataFrame] = None,
    nombre_archivo_excel: str = "datos_no_competencia.xlsx",
):
    """
    Muestra gráfica horizontal tipo color vino.

    Características:
    - Barras horizontales.
    - Color vino.
    - Etiquetas a la derecha: NO_COMP - PORCENTAJE%.
    - Eje X inferior con porcentaje.
    - La gráfica conserva solo Top 15.
    - Ícono extra en la barra de herramientas para descargar Excel completo.
    - Se ocultan íconos de Zoom, Pan, Box Select, Lasso Select, Autoscale y Reset Axes.
    """
    if df is None or df.is_empty():
        st.info("No hay datos para graficar.")
        return

    etiquetas = df[columna].cast(pl.Utf8).to_list()
    porcentajes = [float(x or 0) for x in df["PORCENTAJE"].to_list()]
    no_comp = [int(round(float(x or 0))) for x in df["NO_COMP"].to_list()]

    textos = [
        f"{n} - {p:.2f}%"
        for n, p in zip(no_comp, porcentajes)
    ]

    max_x = max(porcentajes) if porcentajes else 0
    rango_x = max_x * 1.22 if max_x > 0 else 1
    alto_grafica = max(520, len(etiquetas) * 38 + 120)

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=porcentajes,
            y=etiquetas,
            orientation="h",
            marker=dict(
                color=BAR_COLOR,
                line=dict(
                    color=BAR_LINE_COLOR,
                    width=1,
                ),
            ),
            text=textos,
            textposition="outside",
            textfont=dict(
                size=14,
                color=TEXT_COLOR,
            ),
            cliponaxis=False,
            hoverinfo="skip",
            hovertemplate="",
            showlegend=False,
        )
    )

    fig.update_layout(
        title=dict(
            text=titulo,
            x=0.5,
            xanchor="center",
            font=dict(
                size=22,
                color="#222222",
            ),
        ),
        height=alto_grafica,
        margin=dict(
            l=260,
            r=160,
            t=70,
            b=70,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        bargap=0.25,
        showlegend=False,
        hovermode=False,
        dragmode=False,
        font=dict(
            family="Arial, sans-serif",
            color=TEXT_COLOR,
            size=14,
        ),
    )

    fig.update_xaxes(
        title_text="Porcentaje de No Competencia (%)",
        range=[0, rango_x],
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="#555555",
        linewidth=1,
        ticks="outside",
        tickfont=dict(
            size=13,
            color="#333333",
        ),
        title_font=dict(
            size=14,
            color="#333333",
        ),
        fixedrange=True,
    )

    fig.update_yaxes(
        title_text="",
        autorange="reversed",
        showgrid=False,
        showline=True,
        linecolor="#555555",
        linewidth=1,
        ticks="outside",
        tickfont=dict(
            size=14,
            color="#333333",
        ),
        automargin=True,
        fixedrange=True,
    )

    excel_base64 = _generar_excel_base64(
        df_exportar=df_excel_completo,
        columna=columna,
        nombre_hoja=columna.title(),
    )

    _renderizar_plotly_con_descarga_excel(
        fig=fig,
        alto=alto_grafica,
        nombre_archivo_imagen=nombre_archivo,
        nombre_archivo_excel=nombre_archivo_excel,
        excel_base64=excel_base64,
    )


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================
def mostrar(df, plantel_usuario, es_admin):
    st.subheader("📉 Top 15 Docentes y Módulos con Mayor Porcentaje de No Competencia")

    df_base = preparar_dataframe_base(df)

    if df_base.is_empty():
        st.warning("No hay información disponible para mostrar.")
        return

    # ========================================================
    # FILTROS
    # ========================================================
    semanas = obtener_opciones(df_base, "Semana")

    if not semanas:
        st.warning("No hay semanas disponibles en la información.")
        return

    semana = st.selectbox(
        "📅 Selecciona una semana",
        semanas,
        key="no_competentes_semana",
    )

    if es_admin:
        planteles = obtener_opciones(df_base, "Plantel")

        if not planteles:
            st.warning("No hay planteles disponibles en la información.")
            return

        plantel = st.selectbox(
            "🏫 Selecciona un plantel",
            planteles,
            key="no_competentes_plantel",
        )
    else:
        plantel = str(plantel_usuario or "").strip()

        if not plantel:
            st.error("No se detectó el plantel del usuario en la sesión.")
            return

    df_filtrado = filtrar_por_semana_plantel(
        df=df_base,
        semana=semana,
        plantel=plantel,
    )

    if df_filtrado.is_empty():
        st.warning("No hay datos para la semana y plantel seleccionados.")
        return

    nombre_seguro_plantel = _limpiar_nombre_archivo(plantel)
    nombre_seguro_semana = _limpiar_nombre_archivo(semana)

    # ========================================================
    # TOP 15 DOCENTES
    # ========================================================
    st.markdown("### 👨‍🏫 Top 15 Docentes")

    docentes_top = calcular_top_no_competencia(
        df_filtrado=df_filtrado,
        columna="DOCENTE",
        top_n=15,
        incluir_plantel=plantel,
    )

    docentes_excel = calcular_no_competencia_completa(
        df_filtrado=df_filtrado,
        columna="DOCENTE",
        semana=semana,
        plantel=plantel,
    )

    if not docentes_top.is_empty():
        graficar_barras_horizontales(
            docentes_top,
            columna="DOCENTE",
            titulo="Top 15 Docentes con Mayor % de No Competencia",
            nombre_archivo=f"top_15_docentes_no_competencia_{nombre_seguro_plantel}",
            df_excel_completo=docentes_excel,
            nombre_archivo_excel=(
                f"docentes_no_competencia_{nombre_seguro_plantel}_"
                f"semana_{nombre_seguro_semana}.xlsx"
            ),
        )
    else:
        st.info("No hay datos disponibles para docentes.")

    # ========================================================
    # TOP 15 MÓDULOS
    # ========================================================
    st.markdown("### 📚 Top 15 Módulos")

    modulos_top = calcular_top_no_competencia(
        df_filtrado=df_filtrado,
        columna="MODULO",
        top_n=15,
    )

    modulos_excel = calcular_no_competencia_completa(
        df_filtrado=df_filtrado,
        columna="MODULO",
        semana=semana,
        plantel=plantel,
    )

    if not modulos_top.is_empty():
        graficar_barras_horizontales(
            modulos_top,
            columna="MODULO",
            titulo="Top 15 Módulos con Mayor % de No Competencia",
            nombre_archivo=f"top_15_modulos_no_competencia_{nombre_seguro_plantel}",
            df_excel_completo=modulos_excel,
            nombre_archivo_excel=(
                f"modulos_no_competencia_{nombre_seguro_plantel}_"
                f"semana_{nombre_seguro_semana}.xlsx"
            ),
        )
    else:
        st.info("No hay datos disponibles para módulos.")