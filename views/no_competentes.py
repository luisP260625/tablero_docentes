import re
from typing import List, Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
import polars as pl
import streamlit as st


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

    Optimización:
    - Trabaja sobre el DataFrame ya filtrado.
    - Usa LazyFrame de Polars.
    - No convierte a pandas.
    - No genera Excel en memoria.
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
        .filter(
            pl.col(columna).is_not_null()
            & (
                ~pl.col(columna)
                .str.to_lowercase()
                .is_in(["", "nan", "none", "null"])
            )
        )
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


# ============================================================
# GRÁFICA HORIZONTAL COLOR VINO
# ============================================================
def graficar_barras_horizontales(
    df: pl.DataFrame,
    columna: str,
    titulo: str = "",
    nombre_archivo: str = "grafica_no_competencia",
):
    """
    Muestra gráfica horizontal tipo color vino.

    Características:
    - Barras horizontales.
    - Color vino.
    - Etiquetas a la derecha: NO_COMP - PORCENTAJE%.
    - Eje X inferior con porcentaje.
    - Herramientas de Plotly habilitadas para descargar imagen.
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
        height=max(520, len(etiquetas) * 38 + 120),
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
        fixedrange=False,
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
        fixedrange=False,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": True,
            "displaylogo": False,
            "scrollZoom": True,
            "responsive": True,
            "toImageButtonOptions": {
                "format": "png",
                "filename": nombre_archivo,
                "height": 700,
                "width": 1400,
                "scale": 2,
            },
        },
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

    if not docentes_top.is_empty():
        graficar_barras_horizontales(
            docentes_top,
            columna="DOCENTE",
            titulo="Top 15 Docente con Mayor % de No Competencia",
            nombre_archivo=f"top_15_docentes_no_competencia_{plantel}",
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

    if not modulos_top.is_empty():
        graficar_barras_horizontales(
            modulos_top,
            columna="MODULO",
            titulo="Top 15 Módulo con Mayor % de No Competencia",
            nombre_archivo=f"top_15_modulos_no_competencia_{plantel}",
        )
    else:
        st.info("No hay datos disponibles para módulos.")