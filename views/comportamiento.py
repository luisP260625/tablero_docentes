import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Any, List, Tuple
import unicodedata

import polars as pl


# ==========================================================
# Nombres EXACTOS en hoja Datos
# ==========================================================
COL_PLANTEL = "Plantel"
COL_DOCENTE = "DOCENTE"
COL_SEMANA = "Semana"
COL_MODULO = "MODULO"
COL_SEMESTRE = "SEMESTRE"
COL_NO_COMP = "NO COMPETENTES"
COL_COMPET = "COMPETENTES"
COL_TOTAL = "TOTAL ALUMNOS"


# ==========================================================
# Columnas que se mostrarán desde SemCaptura
# ==========================================================
SEMCAPTURA_COLS_REQUERIDAS = [
    "Modulo",
    "semestre",
    "Fecha de captura",
    "grupo",
    "UAPRENDIZAJE",
    "RAPRENDIZAJE",
    "IEVALUAR",
    "IEVALUADOS",
    "PCAPTURA",
    "TOTALE",
    "ESTATUS",
]


# Variantes aceptadas para columnas que pueden venir con nombres distintos
# en el archivo de Excel. Esto evita perder funcionalidad si la columna llega
# como "FECHA_CAPTURA", "fecha captura", "FechaCaptura", etc.
SEMCAPTURA_ALIASES = {
    "Fecha de captura": [
        "Fecha de captura",
        "FECHA DE CAPTURA",
        "fecha captura",
        "FECHA CAPTURA",
        "FECHA_CAPTURA",
        "FechaCaptura",
        "Fecha_Captura",
        "FECHACAPTURA",
        "FCAPTURA",
        "F CAPTURA",
    ],
}


# ==========================================================
# Utilidades generales
# ==========================================================
def _to_polars(df: Any) -> Optional[pl.DataFrame]:
    """
    Convierte diferentes tipos de datos a Polars.
    """
    if df is None:
        return None

    if isinstance(df, pl.DataFrame):
        return df.clone()

    if isinstance(df, pd.DataFrame):
        return pl.from_pandas(df)

    try:
        return pl.DataFrame(df)
    except Exception:
        return None


def _to_pandas(df: Any) -> Optional[pd.DataFrame]:
    """
    Convierte diferentes tipos de datos a Pandas.
    """
    if df is None:
        return None

    if isinstance(df, pd.DataFrame):
        return df.copy()

    if isinstance(df, pl.DataFrame):
        try:
            return df.to_pandas()
        except Exception:
            return pd.DataFrame(df.to_dicts())

    try:
        return pd.DataFrame(df)
    except Exception:
        return None


def _validar_columnas_polars(base: pl.DataFrame, requeridas: List[str]) -> List[str]:
    """
    Valida columnas requeridas en un DataFrame Polars.
    """
    return [c for c in requeridas if c not in base.columns]


def _norm_colname(s: Any) -> str:
    """
    Normaliza nombres de columna para matching robusto:
    sin acentos, sin espacios, sin guiones, en mayúsculas.
    """
    if s is None:
        return ""

    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = (
        s.strip()
        .replace(" ", "")
        .replace("_", "")
        .replace(".", "")
        .replace("-", "")
        .upper()
    )

    return s


def _norm_value(s: Any) -> str:
    """
    Normaliza valores de texto para comparar docentes, planteles, etc.
    """
    if s is None:
        return ""

    try:
        if pd.isna(s):
            return ""
    except Exception:
        pass

    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    return " ".join(s.strip().upper().split())


def _find_col_pl(df: pl.DataFrame, nombres_posibles: List[str]) -> Optional[str]:
    """
    Busca una columna en un DataFrame Polars usando normalización.
    """
    if df is None or df.is_empty():
        return None

    mapa = {_norm_colname(c): c for c in df.columns}

    for nombre in nombres_posibles:
        key = _norm_colname(nombre)
        if key in mapa:
            return mapa[key]

    return None


def _find_col_pd(df: pd.DataFrame, nombres_posibles: List[str]) -> Optional[str]:
    """
    Busca una columna en un DataFrame Pandas usando normalización.
    """
    if df is None or df.empty:
        return None

    mapa = {_norm_colname(c): c for c in df.columns}

    for nombre in nombres_posibles:
        key = _norm_colname(nombre)
        if key in mapa:
            return mapa[key]

    return None


def _filter_text_equals(df: pl.DataFrame, col: str, value: Any) -> pl.DataFrame:
    """
    Filtra texto con normalización de valor.
    Es más robusto contra espacios, acentos y mayúsculas.
    """
    target = _norm_value(value)

    return df.filter(
        pl.col(col)
        .map_elements(_norm_value, return_dtype=pl.Utf8)
        == target
    )


def _seleccionar_columnas_case_insensitive_pl(
    df: pl.DataFrame,
    cols_deseadas: List[str],
    aliases: Optional[dict[str, List[str]]] = None,
) -> pl.DataFrame:
    """
    Selecciona columnas aunque vengan con diferente casing.
    Devuelve las columnas con los nombres indicados en cols_deseadas.

    aliases permite buscar una columna con nombres alternativos.
    Ejemplo:
    - "Fecha de captura" puede venir como "FECHA_CAPTURA" o "fecha captura".
    """
    if df is None or df.is_empty():
        return pl.DataFrame({c: [] for c in cols_deseadas})

    aliases = aliases or {}
    mapa = {_norm_colname(c): c for c in df.columns}

    exprs = []

    for col_deseada in cols_deseadas:
        nombres_a_buscar = [col_deseada] + aliases.get(col_deseada, [])

        col_real = None

        for nombre in nombres_a_buscar:
            key = _norm_colname(nombre)

            if key in mapa:
                col_real = mapa[key]
                break

        if col_real:
            exprs.append(pl.col(col_real).alias(col_deseada))
        else:
            exprs.append(pl.lit(None).alias(col_deseada))

    return df.select(exprs)


def _drop_columns_by_norm(df: pd.DataFrame, cols_a_eliminar: List[str]) -> pd.DataFrame:
    """
    Elimina columnas por nombre normalizado.
    Ejemplo: status / ESTATUS / Estatus.
    """
    if df is None or df.empty:
        return df

    keys_eliminar = {_norm_colname(c) for c in cols_a_eliminar}
    columnas_finales = [
        c for c in df.columns
        if _norm_colname(c) not in keys_eliminar
    ]

    return df[columnas_finales].copy()


def _rename_column_by_norm(
    df: pd.DataFrame,
    nombre_actual: str,
    nombre_nuevo: str,
) -> pd.DataFrame:
    """
    Renombra una columna usando matching robusto.
    """
    if df is None or df.empty:
        return df

    actual_key = _norm_colname(nombre_actual)
    renames = {}

    for c in df.columns:
        if _norm_colname(c) == actual_key:
            renames[c] = nombre_nuevo

    if renames:
        df = df.rename(columns=renames)

    return df


def _set_index_consecutivo(df: pd.DataFrame, inicio: int = 1) -> pd.DataFrame:
    """
    Hace que el índice visible inicie en 1.
    """
    if df is None:
        return pd.DataFrame()

    out = df.copy().reset_index(drop=True)
    out.index = range(inicio, inicio + len(out))
    out.index.name = ""

    return out


def _planteles_desde_polars(df: pl.DataFrame) -> list[str]:
    """
    Devuelve lista ordenada de planteles.
    """
    if df is None or df.is_empty() or COL_PLANTEL not in df.columns:
        return []

    return sorted(
        [str(x) for x in df[COL_PLANTEL].drop_nulls().unique().to_list()]
    )


def _docentes_desde_polars(df: pl.DataFrame) -> list[str]:
    """
    Devuelve lista ordenada de docentes.
    """
    if df is None or df.is_empty() or COL_DOCENTE not in df.columns:
        return []

    return sorted(
        [str(x) for x in df[COL_DOCENTE].drop_nulls().unique().to_list()]
    )


# ==========================================================
# Cálculos y visuales
# ==========================================================
def _current_week_from_docente_pl(df_docente: pl.DataFrame) -> Optional[int]:
    """
    Obtiene la última semana disponible del docente desde Polars.
    """
    if df_docente is None or df_docente.is_empty() or COL_SEMANA not in df_docente.columns:
        return None

    df_tmp = df_docente.with_columns(
        pl.col(COL_SEMANA).cast(pl.Int64, strict=False).alias("_SEMANA_NUM")
    )

    semana = df_tmp["_SEMANA_NUM"].max()

    if semana is None:
        return None

    try:
        return int(semana)
    except Exception:
        return None


def _grafica_semanal(sem_df: pd.DataFrame, titulo: str, color_hex: str = "#c3b08f") -> None:
    """
    Dibuja gráfica semanal de no competentes.
    """
    if sem_df is None or sem_df.shape[0] == 0:
        st.info("Sin datos para la gráfica.")
        return

    semanas = sem_df["semana"].astype(int).tolist()
    no_comp = sem_df["no_comp"].astype(int).tolist()
    total = sem_df["total"].astype(int).tolist()
    porcent = [(n / t) if t else 0.0 for n, t in zip(no_comp, total)]

    fig, ax = plt.subplots(figsize=(8, 4))

    bars = ax.bar(
        semanas,
        no_comp,
        width=0.6,
        align="center",
        color=color_hex,
        edgecolor=color_hex,
    )

    if titulo:
        ax.set_title(titulo)

    ax.set_xlabel("Semana")
    ax.set_xticks(semanas)

    if semanas:
        ax.set_xlim(min(semanas) - 0.5, max(semanas) + 0.5)

    y_max = max(no_comp) if no_comp else 0
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)

    for i, bar in enumerate(bars):
        ax.annotate(
            f"{no_comp[i]} - {porcent[i] * 100:.1f}%",
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            rotation=90,
            fontsize=8,
        )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()

    st.pyplot(fig)


def _preparar_grafica_semanal(df_docente: pl.DataFrame) -> pd.DataFrame:
    """
    Prepara el resumen semanal desde Polars.
    Convierte a Pandas solo el resultado pequeño.
    """
    if df_docente is None or df_docente.is_empty():
        return pd.DataFrame(columns=["semana", "no_comp", "total"])

    sem = (
        df_docente
        .with_columns(
            pl.col(COL_SEMANA).cast(pl.Int64, strict=False).alias("_SEMANA_NUM")
        )
        .drop_nulls("_SEMANA_NUM")
        .group_by("_SEMANA_NUM")
        .agg(
            pl.sum(COL_NO_COMP).alias("no_comp"),
            pl.sum(COL_TOTAL).alias("total"),
        )
        .sort("_SEMANA_NUM")
        .rename({"_SEMANA_NUM": "semana"})
    )

    return sem.to_pandas()


def _tabla_modulos_ultima_semana_pl(df_docente: pl.DataFrame) -> pd.DataFrame:
    """
    Devuelve tabla de módulos de la última semana disponible.
    """
    columnas_salida = [
        "Modulo",
        "semestre",
        "no_com",
        "competentes",
        "total",
        "porcentaje_no_comp",
    ]

    if df_docente is None or df_docente.is_empty():
        return pd.DataFrame(columns=columnas_salida)

    ult_sem = _current_week_from_docente_pl(df_docente)

    if ult_sem is None:
        return pd.DataFrame(columns=columnas_salida)

    df_u = (
        df_docente
        .with_columns(
            pl.col(COL_SEMANA).cast(pl.Int64, strict=False).alias("_SEMANA_NUM")
        )
        .filter(pl.col("_SEMANA_NUM") == ult_sem)
    )

    if df_u.is_empty():
        return pd.DataFrame(columns=columnas_salida)

    agg = (
        df_u
        .group_by([COL_MODULO, COL_SEMESTRE])
        .agg(
            pl.sum(COL_NO_COMP).alias("no_com"),
            pl.sum(COL_COMPET).alias("competentes"),
            pl.sum(COL_TOTAL).alias("total"),
        )
        .with_columns(
            (
                pl.col("no_com")
                / pl.when(pl.col("total") > 0)
                .then(pl.col("total"))
                .otherwise(1)
                .cast(pl.Float64)
                * 100
            )
            .round(1)
            .alias("porcentaje_no_comp")
        )
        .rename(
            {
                COL_MODULO: "Modulo",
                COL_SEMESTRE: "semestre",
            }
        )
        .select(columnas_salida)
        .sort(["Modulo", "semestre"])
    )

    return agg.to_pandas()


# ==========================================================
# Preparar SemCaptura
# ==========================================================
def _preparar_semcaptura_docente(
    semcaptura_raw: Any,
    *,
    sel_docente: str,
    sel_plantel: Optional[str],
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra SemCaptura por docente y plantel.
    """
    semcaptura_pl = _to_polars(semcaptura_raw)

    if semcaptura_pl is None or semcaptura_pl.is_empty():
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'SemCaptura' o está vacía."

    col_docente_real = _find_col_pl(semcaptura_pl, [COL_DOCENTE, "Docente"])

    if not col_docente_real:
        return pd.DataFrame(), "La hoja 'SemCaptura' no contiene una columna DOCENTE para poder filtrar."

    df_sc = _filter_text_equals(
        semcaptura_pl,
        col_docente_real,
        sel_docente,
    )

    col_plantel_real = _find_col_pl(semcaptura_pl, [COL_PLANTEL, "Plantel"])

    if col_plantel_real and sel_plantel:
        df_sc = _filter_text_equals(
            df_sc,
            col_plantel_real,
            sel_plantel,
        )

    if df_sc.is_empty():
        return pd.DataFrame(), f"ℹ️ No hay registros en 'SemCaptura' para el docente **{sel_docente}**."

    df_sc_out = _seleccionar_columnas_case_insensitive_pl(
        df_sc,
        SEMCAPTURA_COLS_REQUERIDAS,
        aliases=SEMCAPTURA_ALIASES,
    )

    return df_sc_out.to_pandas().reset_index(drop=True), None


# ==========================================================
# Preparar Reprobacion
# ==========================================================
def _preparar_reprobacion_docente(
    reprobacion_raw: Any,
    *,
    sel_docente: str,
    sel_plantel: Optional[str],
    semana_actual: Optional[int],
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra Reprobacion por docente, plantel y semana actual.
    """
    reprobacion_pl = _to_polars(reprobacion_raw)

    if reprobacion_pl is None or reprobacion_pl.is_empty():
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'Reprobacion' o está vacía."

    col_docente_real = _find_col_pl(reprobacion_pl, [COL_DOCENTE, "Docente"])

    if not col_docente_real:
        return pd.DataFrame(), "La hoja 'Reprobacion' no contiene una columna DOCENTE para poder filtrar."

    df_rep = _filter_text_equals(
        reprobacion_pl,
        col_docente_real,
        sel_docente,
    )

    col_plantel_real = _find_col_pl(reprobacion_pl, [COL_PLANTEL, "Plantel"])

    if col_plantel_real and sel_plantel:
        df_rep = _filter_text_equals(
            df_rep,
            col_plantel_real,
            sel_plantel,
        )

    col_semana_real = _find_col_pl(reprobacion_pl, [COL_SEMANA, "Semana"])

    if col_semana_real and semana_actual is not None:
        df_rep = (
            df_rep
            .with_columns(
                pl.col(col_semana_real)
                .cast(pl.Int64, strict=False)
                .alias("_SEMANA_NUM")
            )
            .filter(pl.col("_SEMANA_NUM") == int(semana_actual))
            .drop("_SEMANA_NUM")
        )

    if df_rep.is_empty():
        if semana_actual is not None:
            return pd.DataFrame(), (
                f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}** "
                f"en la semana **{semana_actual}**."
            )

        return pd.DataFrame(), f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}**."

    df_rep_out = df_rep.to_pandas()

    # No mostrar status / estatus
    df_rep_out = _drop_columns_by_norm(
        df_rep_out,
        ["status", "estatus"],
    )

    # Renombrar MINIMO
    df_rep_out = _rename_column_by_norm(
        df_rep_out,
        "MINIMO",
        "Porcentaje Mínimo para aprobar",
    )

    # Índice 1, 2, 3...
    df_rep_out = _set_index_consecutivo(df_rep_out, inicio=1)

    return df_rep_out, None


def _contar_estudiantes_no_competentes(df_rep_out: pd.DataFrame) -> int:
    """
    Cuenta estudiantes no competentes.
    Si existe matrícula, cuenta matrículas únicas.
    """
    if df_rep_out is None or df_rep_out.empty:
        return 0

    col_matricula = _find_col_pd(
        df_rep_out,
        ["matricula", "matrícula", "MATRICULA"],
    )

    if col_matricula:
        return int(
            df_rep_out[col_matricula]
            .dropna()
            .astype(str)
            .str.strip()
            .nunique()
        )

    return int(len(df_rep_out))


# ==========================================================
# Interfaz pública
# ==========================================================
def mostrar(
    df: Any,
    plantel_usuario: Optional[str] = None,
    es_admin: bool = False,
    semcaptura_raw: Any = None,
    reprobacion_raw: Any = None,
) -> None:
    """
    Vista Docentes Seguimiento (FT).

    Optimización:
    - Ya no lee SemCaptura directamente desde Excel.
    - Ya no lee Reprobacion directamente desde Excel.
    - Filtra primero en Polars.
    - Convierte a Pandas solo resultados pequeños para tabla/gráfica.
    """
    base_pl = _to_polars(df)

    if base_pl is None or base_pl.is_empty():
        st.warning("No hay datos para mostrar.")
        return

    faltantes = _validar_columnas_polars(
        base_pl,
        [
            COL_PLANTEL,
            COL_DOCENTE,
            COL_SEMANA,
            COL_NO_COMP,
            COL_COMPET,
            COL_TOTAL,
            COL_MODULO,
            COL_SEMESTRE,
        ],
    )

    if faltantes:
        st.error("Faltan columnas requeridas en 'Datos': " + ", ".join(faltantes))

        with st.expander("Columnas disponibles"):
            st.write(list(base_pl.columns))

        return

    # ======================================================
    # Selección de plantel
    # ======================================================
    if es_admin:
        planteles = _planteles_desde_polars(base_pl)

        if not planteles:
            st.info("No hay planteles disponibles.")
            return

        default_idx = planteles.index(plantel_usuario) if plantel_usuario in planteles else 0

        sel_plantel = st.selectbox(
            "Selecciona un plantel",
            planteles,
            index=default_idx,
            key="cmp_sel_plantel_comportamiento",
        )
    else:
        sel_plantel = plantel_usuario

        st.text_input(
            "Plantel",
            sel_plantel or "",
            disabled=True,
            key="cmp_plantel_ro_comportamiento",
        )

    if sel_plantel:
        df_plantel_pl = base_pl.filter(
            pl.col(COL_PLANTEL).cast(pl.Utf8) == str(sel_plantel)
        )
    else:
        df_plantel_pl = base_pl

    if df_plantel_pl.is_empty():
        st.info("No hay datos para el plantel seleccionado.")
        return

    # ======================================================
    # Selección de docente
    # ======================================================
    docentes = _docentes_desde_polars(df_plantel_pl)

    if not docentes:
        st.info("No hay docentes para el plantel seleccionado.")
        return

    sel_docente = st.selectbox(
        "Selecciona un docente",
        docentes,
        key="cmp_sel_docente_comportamiento",
    )

    df_docente_pl = df_plantel_pl.filter(
        pl.col(COL_DOCENTE).cast(pl.Utf8) == str(sel_docente)
    )

    if df_docente_pl.is_empty():
        st.info("No hay datos para el docente seleccionado.")
        return

    # ======================================================
    # Gráfica semanal
    # ======================================================
    sem = _preparar_grafica_semanal(df_docente_pl)

    _grafica_semanal(
        sem,
        titulo=f"Comportamiento semanal - {sel_docente}",
        color_hex="#c3b08f",
    )

    # ======================================================
    # Tabla de módulos última semana
    # ======================================================
    st.markdown("**Módulos que ofrece el docente (última semana disponible)**")

    tabla = _tabla_modulos_ultima_semana_pl(df_docente_pl)

    st.dataframe(
        tabla,
        use_container_width=True,
    )

    # ======================================================
    # Tabla SemCaptura
    # ======================================================
    st.markdown("---")
    st.subheader("📋 Porcentaje de captura de evaluaciones.")

    df_sc_out, msg_sc = _preparar_semcaptura_docente(
        semcaptura_raw,
        sel_docente=str(sel_docente or ""),
        sel_plantel=str(sel_plantel or "") if sel_plantel else None,
    )

    if msg_sc:
        if msg_sc.startswith("La hoja"):
            st.error(msg_sc)

            semcaptura_pd = _to_pandas(semcaptura_raw)

            if semcaptura_pd is not None and not semcaptura_pd.empty:
                with st.expander("Columnas disponibles en SemCaptura"):
                    st.write(list(semcaptura_pd.columns))
        else:
            st.info(msg_sc)
    else:
        st.dataframe(
            df_sc_out,
            use_container_width=True,
            height=380,
        )

    # ======================================================
    # Tabla Reprobacion
    # ======================================================
    semana_actual = _current_week_from_docente_pl(df_docente_pl)
    semana_texto = str(semana_actual) if semana_actual is not None else "actual"

    df_rep_out, msg_rep = _preparar_reprobacion_docente(
        reprobacion_raw,
        sel_docente=str(sel_docente or ""),
        sel_plantel=str(sel_plantel or "") if sel_plantel else None,
        semana_actual=semana_actual,
    )

    if msg_rep:
        st.info(msg_rep)
        return

    no_estudiantes = _contar_estudiantes_no_competentes(df_rep_out)

    st.markdown(
        f"### 📋 {no_estudiantes} Estudiantes NO Competentes en la semana {semana_texto}"
    )

    st.dataframe(
        df_rep_out,
        use_container_width=True,
        height=420,
    )