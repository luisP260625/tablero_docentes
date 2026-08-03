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
# Nuevo campo para rol docente
# ==========================================================
COL_CLAVE_DOCENTE = "CLAVE_DOCENTE"

CLAVE_DOCENTE_ALIASES = [
    "clave_docente",
    "CLAVE_DOCENTE",
    "Clave Docente",
    "CLAVE DOCENTE",
    "ClaveDocente",
    "CLAVEDOCENTE",
    "clave docente",
]


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
# en el archivo de Excel.
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
    Normaliza valores de texto para comparar planteles, textos generales, etc.
    Evita problemas cuando Excel convierte valores numéricos a 123.0.
    """
    if s is None:
        return ""

    try:
        if pd.isna(s):
            return ""
    except Exception:
        pass

    try:
        if isinstance(s, float) and s.is_integer():
            s = int(s)
    except Exception:
        pass

    s = str(s).strip()

    if s.endswith(".0"):
        posible_numero = s[:-2]
        if posible_numero.isdigit():
            s = posible_numero

    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    return " ".join(s.strip().upper().split())


def _norm_clave_docente(s: Any) -> str:
    """
    Normaliza clave_docente para que 08100003, 8100003 y 8100003.0 coincidan.
    """
    v = _norm_value(s)

    if v.endswith(".0"):
        v = v[:-2]

    if v.isdigit():
        return v.lstrip("0") or "0"

    return v


def _norm_docente_nombre(s: Any) -> str:
    """
    Normaliza nombre docente.
    Quita el prefijo '*' porque en Datos, Planteles, SemCaptura y Reprobacion
    puede venir como '*NOMBRE DOCENTE'.
    """
    v = _norm_value(s)

    while v.startswith("*"):
        v = v[1:].strip()

    return v


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
    Es más robusto contra espacios, acentos, mayúsculas y valores tipo 123.0.
    """
    target = _norm_value(value)

    return df.filter(
        pl.col(col)
        .map_elements(_norm_value, return_dtype=pl.Utf8)
        == target
    )


def _filter_clave_docente_equals(df: pl.DataFrame, col: str, value: Any) -> pl.DataFrame:
    """
    Filtra clave_docente permitiendo coincidencia con o sin ceros a la izquierda.
    """
    target = _norm_clave_docente(value)

    return df.filter(
        pl.col(col)
        .map_elements(_norm_clave_docente, return_dtype=pl.Utf8)
        == target
    )


def _filter_docente_nombre_equals(df: pl.DataFrame, col: str, value: Any) -> pl.DataFrame:
    """
    Filtra por nombre de docente ignorando el prefijo '*'.
    """
    target = _norm_docente_nombre(value)

    return df.filter(
        pl.col(col)
        .map_elements(_norm_docente_nombre, return_dtype=pl.Utf8)
        == target
    )


def _filtrar_docente_seguro_pl(
    df: pl.DataFrame,
    *,
    clave_docente: Optional[str] = None,
    nombre_docente: Optional[str] = None,
    hoja_nombre: str = "Datos",
) -> Tuple[Optional[pl.DataFrame], Optional[str]]:
    """
    Filtra información del docente en modo seguro.

    Seguridad:
    - Nunca regresa todo el DataFrame.
    - Nunca filtra únicamente por plantel.
    - Si la hoja tiene CLAVE_DOCENTE, usa la clave como regla fuerte.
    - Si hay filas históricas sin CLAVE_DOCENTE, solo las incluye cuando:
        1. el nombre DOCENTE coincide con el nombre autenticado,
        2. no existe una CLAVE_DOCENTE diferente en esas filas,
        3. el filtro por nombre no genera una ambigüedad detectable.
    - Si detecta una inconsistencia, bloquea la vista en lugar de mostrar datos dudosos.
    """
    if df is None or df.is_empty():
        return df, None

    clave_norm = _norm_clave_docente(clave_docente)
    nombre_norm = _norm_docente_nombre(nombre_docente)

    if not clave_norm and not nombre_norm:
        return pl.DataFrame(), (
            f"No se recibió clave_docente ni nombre de docente para filtrar '{hoja_nombre}'."
        )

    col_clave_real = _find_col_pl(df, CLAVE_DOCENTE_ALIASES)
    col_docente_real = _find_col_pl(df, [COL_DOCENTE, "Docente"])

    candidatos = None
    mensajes = []

    # ------------------------------------------------------
    # 1) Filtro por nombre autenticado.
    # ------------------------------------------------------
    # Para la hoja Datos esto es necesario porque existen semanas históricas
    # donde CLAVE_DOCENTE está vacía, pero DOCENTE sí está informado.
    if nombre_norm and col_docente_real:
        candidatos = _filter_docente_nombre_equals(
            df,
            col_docente_real,
            nombre_docente,
        )

        if candidatos is not None and not candidatos.is_empty():
            # Si existe columna de clave, se validan las claves dentro de los candidatos.
            # Se permiten claves vacías y la clave del login. Se bloquea cualquier clave distinta.
            if col_clave_real and clave_norm:
                claves_encontradas = (
                    candidatos
                    .select(
                        pl.col(col_clave_real)
                        .map_elements(_norm_clave_docente, return_dtype=pl.Utf8)
                        .alias("_CLAVE_NORM")
                    )
                    .filter(pl.col("_CLAVE_NORM") != "")
                    .unique()
                    .get_column("_CLAVE_NORM")
                    .to_list()
                )

                claves_distintas = [c for c in claves_encontradas if c != clave_norm]

                if claves_distintas:
                    return pl.DataFrame(), (
                        f"Se bloqueó la consulta por seguridad. En '{hoja_nombre}' hay registros "
                        f"con el mismo DOCENTE, pero con CLAVE_DOCENTE diferente a la del login. "
                        f"Clave login: {clave_norm}. Claves encontradas: {', '.join(claves_encontradas)}."
                    )

            return candidatos, None

        mensajes.append(
            f"No hubo coincidencias seguras por DOCENTE en '{hoja_nombre}'."
        )
    elif nombre_norm and not col_docente_real:
        mensajes.append(
            f"No se encontró columna DOCENTE en '{hoja_nombre}'."
        )

    # ------------------------------------------------------
    # 2) Filtro por clave como respaldo.
    # ------------------------------------------------------
    # Se usa cuando no se encontró por nombre, pero la hoja tiene clave.
    if clave_norm and col_clave_real:
        df_por_clave = _filter_clave_docente_equals(
            df,
            col_clave_real,
            clave_docente,
        )

        if df_por_clave is not None and not df_por_clave.is_empty():
            # Si además tenemos nombre, validamos que no se esté trayendo otro docente.
            if nombre_norm and col_docente_real:
                docentes_encontrados = (
                    df_por_clave
                    .select(
                        pl.col(col_docente_real)
                        .map_elements(_norm_docente_nombre, return_dtype=pl.Utf8)
                        .alias("_DOCENTE_NORM")
                    )
                    .filter(pl.col("_DOCENTE_NORM") != "")
                    .unique()
                    .get_column("_DOCENTE_NORM")
                    .to_list()
                )

                docentes_distintos = [d for d in docentes_encontrados if d != nombre_norm]

                if docentes_distintos:
                    return pl.DataFrame(), (
                        f"Se bloqueó la consulta por seguridad. En '{hoja_nombre}' la CLAVE_DOCENTE "
                        f"del login está asociada a otro nombre de DOCENTE. "
                        f"Docente login: {nombre_norm}. Docentes encontrados: {', '.join(docentes_encontrados)}."
                    )

            return df_por_clave, None

        mensajes.append(
            f"No hubo coincidencias por CLAVE_DOCENTE en '{hoja_nombre}'."
        )
    elif clave_norm and not col_clave_real:
        mensajes.append(
            f"No se encontró columna CLAVE_DOCENTE en '{hoja_nombre}'."
        )

    return pl.DataFrame(), (
        "No se encontró información segura para el docente. "
        + " ".join(mensajes)
    )

def _seleccionar_columnas_case_insensitive_pl(
    df: pl.DataFrame,
    cols_deseadas: List[str],
    aliases: Optional[dict[str, List[str]]] = None,
) -> pl.DataFrame:
    """
    Selecciona columnas aunque vengan con diferente casing.
    Devuelve las columnas con los nombres indicados en cols_deseadas.
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


def _grafica_semanal(
    sem_df: pd.DataFrame,
    titulo: str,
    color_hex: str = "#c3b08f",
) -> None:
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
    clave_docente_usuario: Optional[str] = None,
    nombre_docente_usuario: Optional[str] = None,
    es_docente: bool = False,
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra SemCaptura por docente y plantel.

    Si el rol es docente, filtra por clave_docente y, si es necesario,
    por nombre de docente.
    """
    semcaptura_pl = _to_polars(semcaptura_raw)

    if semcaptura_pl is None or semcaptura_pl.is_empty():
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'SemCaptura' o está vacía."

    if es_docente:
        df_sc, msg_doc = _filtrar_docente_seguro_pl(
            semcaptura_pl,
            clave_docente=clave_docente_usuario,
            nombre_docente=nombre_docente_usuario or sel_docente,
            hoja_nombre="SemCaptura",
        )

        if msg_doc and (df_sc is None or df_sc.is_empty()):
            return pd.DataFrame(), msg_doc
    else:
        col_docente_real = _find_col_pl(semcaptura_pl, [COL_DOCENTE, "Docente"])

        if not col_docente_real:
            return pd.DataFrame(), "La hoja 'SemCaptura' no contiene una columna DOCENTE para poder filtrar."

        df_sc = _filter_docente_nombre_equals(
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

    if df_sc is None or df_sc.is_empty():
        if es_docente:
            return pd.DataFrame(), (
                "ℹ️ No hay registros en 'SemCaptura' para tu usuario docente."
            )

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
COL_OTROS_MODULOS_ADEUDADOS = "Otros módulos que adeuda"


def _normalizar_texto_expr_pl(
    columna: str,
    *,
    alias: str,
    quitar_decimal_cero: bool = False,
) -> pl.Expr:
    """
    Normaliza texto usando expresiones nativas de Polars.

    A diferencia de map_elements(), esta transformación no ejecuta una
    función de Python por cada celda y por ello es mucho más rápida en
    conjuntos de datos grandes.
    """
    expr = (
        pl.col(columna)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.strip_chars()
        .str.to_uppercase()
        .str.replace_all(r"\s+", " ")
    )

    # Normalización de caracteres comunes en español.
    reemplazos = [
        ("Á", "A"),
        ("É", "E"),
        ("Í", "I"),
        ("Ó", "O"),
        ("Ú", "U"),
        ("Ü", "U"),
    ]

    for origen, destino in reemplazos:
        expr = expr.str.replace_all(origen, destino)

    if quitar_decimal_cero:
        expr = expr.str.replace(r"\.0$", "")

    return expr.alias(alias)


def _agregar_otros_modulos_adeudados_pl(
    reprobacion_pl: pl.DataFrame,
    df_rep_docente: pl.DataFrame,
    *,
    sel_plantel: Optional[str],
    semana_actual: Optional[int],
) -> pl.DataFrame:
    """
    Agrega la cantidad de módulos adicionales que adeuda cada estudiante.

    El cálculo se limita a:
    - el mismo plantel;
    - la misma semana;
    - únicamente las matrículas visibles para el docente consultado.

    Esta versión evita map_elements() sobre toda la hoja Reprobacion.
    Las operaciones se ejecutan con expresiones nativas y vectorizadas
    de Polars para reducir de manera importante el tiempo y la memoria.
    """
    if df_rep_docente is None or df_rep_docente.is_empty():
        return df_rep_docente

    if reprobacion_pl is None or reprobacion_pl.is_empty():
        return df_rep_docente.with_columns(
            pl.lit(None).cast(pl.Int64).alias(COL_OTROS_MODULOS_ADEUDADOS)
        )

    col_matricula_real = _find_col_pl(
        reprobacion_pl,
        ["matricula", "matrícula", "MATRICULA", "MATRÍCULA"],
    )
    col_modulo_real = _find_col_pl(
        reprobacion_pl,
        [COL_MODULO, "Modulo", "Módulo", "MODULO"],
    )

    if not col_matricula_real or not col_modulo_real:
        return df_rep_docente.with_columns(
            pl.lit(None).cast(pl.Int64).alias(COL_OTROS_MODULOS_ADEUDADOS)
        )

    # Evita conflicto si la entrada ya trae la columna calculada.
    if COL_OTROS_MODULOS_ADEUDADOS in df_rep_docente.columns:
        df_rep_docente = df_rep_docente.drop(COL_OTROS_MODULOS_ADEUDADOS)

    # ------------------------------------------------------
    # 1) Matrículas realmente visibles para el docente.
    # ------------------------------------------------------
    matriculas_objetivo = (
        df_rep_docente
        .select(
            _normalizar_texto_expr_pl(
                col_matricula_real,
                alias="_MATRICULA_NORM",
                quitar_decimal_cero=True,
            )
        )
        .filter(pl.col("_MATRICULA_NORM") != "")
        .unique()
    )

    if matriculas_objetivo.is_empty():
        return df_rep_docente.with_columns(
            pl.lit(0).cast(pl.Int64).alias(COL_OTROS_MODULOS_ADEUDADOS)
        )

    # ------------------------------------------------------
    # 2) Universo: mismo plantel y misma semana.
    # ------------------------------------------------------
    universo = reprobacion_pl

    col_plantel_real = _find_col_pl(universo, [COL_PLANTEL, "Plantel"])

    if col_plantel_real and sel_plantel:
        plantel_objetivo = _norm_value(sel_plantel)

        universo = universo.filter(
            _normalizar_texto_expr_pl(
                col_plantel_real,
                alias="_PLANTEL_NORM",
            )
            == plantel_objetivo
        )

    col_semana_real = _find_col_pl(universo, [COL_SEMANA, "Semana"])

    if col_semana_real and semana_actual is not None:
        universo = universo.filter(
            pl.col(col_semana_real)
            .cast(pl.Int64, strict=False)
            == int(semana_actual)
        )

    if universo.is_empty():
        return df_rep_docente.with_columns(
            pl.lit(0).cast(pl.Int64).alias(COL_OTROS_MODULOS_ADEUDADOS)
        )

    # ------------------------------------------------------
    # 3) Normalizar solo las dos columnas necesarias y conservar
    #    únicamente las matrículas del docente consultado.
    # ------------------------------------------------------
    universo_objetivo = (
        universo
        .select(
            _normalizar_texto_expr_pl(
                col_matricula_real,
                alias="_MATRICULA_NORM",
                quitar_decimal_cero=True,
            ),
            _normalizar_texto_expr_pl(
                col_modulo_real,
                alias="_MODULO_NORM",
            ),
        )
        .filter(
            (pl.col("_MATRICULA_NORM") != "")
            & (pl.col("_MODULO_NORM") != "")
        )
        .join(
            matriculas_objetivo,
            on="_MATRICULA_NORM",
            how="semi",
        )
        .unique(["_MATRICULA_NORM", "_MODULO_NORM"])
    )

    if universo_objetivo.is_empty():
        return df_rep_docente.with_columns(
            pl.lit(0).cast(pl.Int64).alias(COL_OTROS_MODULOS_ADEUDADOS)
        )

    # ------------------------------------------------------
    # 4) Total de módulos únicos adeudados por estudiante.
    # ------------------------------------------------------
    total_por_estudiante = (
        universo_objetivo
        .group_by("_MATRICULA_NORM")
        .agg(
            pl.len()
            .cast(pl.Int64)
            .alias("_TOTAL_MODULOS_ADEUDADOS")
        )
    )

    # ------------------------------------------------------
    # 5) Módulos únicos adeudados con el docente consultado.
    # ------------------------------------------------------
    modulos_con_docente = (
        df_rep_docente
        .select(
            _normalizar_texto_expr_pl(
                col_matricula_real,
                alias="_MATRICULA_NORM",
                quitar_decimal_cero=True,
            ),
            _normalizar_texto_expr_pl(
                col_modulo_real,
                alias="_MODULO_NORM",
            ),
        )
        .filter(
            (pl.col("_MATRICULA_NORM") != "")
            & (pl.col("_MODULO_NORM") != "")
        )
        .unique(["_MATRICULA_NORM", "_MODULO_NORM"])
        .group_by("_MATRICULA_NORM")
        .agg(
            pl.len()
            .cast(pl.Int64)
            .alias("_MODULOS_CON_DOCENTE")
        )
    )

    conteo = (
        total_por_estudiante
        .join(
            modulos_con_docente,
            on="_MATRICULA_NORM",
            how="left",
        )
        .with_columns(
            pl.col("_MODULOS_CON_DOCENTE")
            .fill_null(0)
            .cast(pl.Int64)
        )
        .with_columns(
            pl.when(
                (
                    pl.col("_TOTAL_MODULOS_ADEUDADOS")
                    - pl.col("_MODULOS_CON_DOCENTE")
                ) > 0
            )
            .then(
                pl.col("_TOTAL_MODULOS_ADEUDADOS")
                - pl.col("_MODULOS_CON_DOCENTE")
            )
            .otherwise(0)
            .cast(pl.Int64)
            .alias(COL_OTROS_MODULOS_ADEUDADOS)
        )
        .select(
            "_MATRICULA_NORM",
            COL_OTROS_MODULOS_ADEUDADOS,
        )
    )

    # ------------------------------------------------------
    # 6) Agregar el resultado a cada fila visible.
    # ------------------------------------------------------
    return (
        df_rep_docente
        .with_columns(
            _normalizar_texto_expr_pl(
                col_matricula_real,
                alias="_MATRICULA_NORM",
                quitar_decimal_cero=True,
            )
        )
        .join(
            conteo,
            on="_MATRICULA_NORM",
            how="left",
        )
        .with_columns(
            pl.col(COL_OTROS_MODULOS_ADEUDADOS)
            .fill_null(0)
            .cast(pl.Int64)
        )
        .drop("_MATRICULA_NORM")
    )

def _preparar_reprobacion_docente(
    reprobacion_raw: Any,
    *,
    sel_docente: str,
    sel_plantel: Optional[str],
    semana_actual: Optional[int],
    clave_docente_usuario: Optional[str] = None,
    nombre_docente_usuario: Optional[str] = None,
    es_docente: bool = False,
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra Reprobacion por docente, plantel y semana actual.

    Si el rol es docente, filtra por clave_docente y, si es necesario,
    por nombre de docente.
    """
    reprobacion_pl = _to_polars(reprobacion_raw)

    if reprobacion_pl is None or reprobacion_pl.is_empty():
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'Reprobacion' o está vacía."

    if es_docente:
        df_rep, msg_doc = _filtrar_docente_seguro_pl(
            reprobacion_pl,
            clave_docente=clave_docente_usuario,
            nombre_docente=nombre_docente_usuario or sel_docente,
            hoja_nombre="Reprobacion",
        )

        if msg_doc and (df_rep is None or df_rep.is_empty()):
            return pd.DataFrame(), msg_doc
    else:
        col_docente_real = _find_col_pl(reprobacion_pl, [COL_DOCENTE, "Docente"])

        if not col_docente_real:
            return pd.DataFrame(), "La hoja 'Reprobacion' no contiene una columna DOCENTE para poder filtrar."

        df_rep = _filter_docente_nombre_equals(
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

    if df_rep is None or df_rep.is_empty():
        if es_docente:
            if semana_actual is not None:
                return pd.DataFrame(), (
                    f"ℹ️ No hay registros en 'Reprobacion' para tu usuario docente "
                    f"en la semana **{semana_actual}**."
                )

            return pd.DataFrame(), "ℹ️ No hay registros en 'Reprobacion' para tu usuario docente."

        if semana_actual is not None:
            return pd.DataFrame(), (
                f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}** "
                f"en la semana **{semana_actual}**."
            )

        return pd.DataFrame(), f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}**."

    # Agregar únicamente la cantidad de módulos adicionales que cada
    # estudiante adeuda con otros docentes, sin mostrar información ajena.
    df_rep = _agregar_otros_modulos_adeudados_pl(
        reprobacion_pl,
        df_rep,
        sel_plantel=sel_plantel,
        semana_actual=semana_actual,
    )

    df_rep_out = df_rep.to_pandas()

    # Colocar la nueva columna inmediatamente después de MODULO para que sea
    # visible y fácil de interpretar en la tabla.
    col_modulo_salida = _find_col_pd(
        df_rep_out,
        [COL_MODULO, "Modulo", "Módulo", "MODULO"],
    )

    if (
        col_modulo_salida
        and COL_OTROS_MODULOS_ADEUDADOS in df_rep_out.columns
    ):
        columnas_salida = [
            c for c in df_rep_out.columns
            if c != COL_OTROS_MODULOS_ADEUDADOS
        ]
        posicion_modulo = columnas_salida.index(col_modulo_salida) + 1
        columnas_salida.insert(
            posicion_modulo,
            COL_OTROS_MODULOS_ADEUDADOS,
        )
        df_rep_out = df_rep_out[columnas_salida]

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
    es_docente: bool = False,
    clave_docente_usuario: Optional[str] = None,
    nombre_docente_usuario: Optional[str] = None,
    semcaptura_raw: Any = None,
    reprobacion_raw: Any = None,
) -> None:
    """
    Vista Docentes Seguimiento (FT).

    Roles:
    - Admin:
        Puede seleccionar plantel y docente.

    - Usuario de plantel:
        Ve su plantel y puede seleccionar docente.

    - Docente:
        Entra con clave_docente.
        Solo ve información correspondiente a su propio usuario.
        Para Datos usa clave_docente si existe con datos; si está vacía,
        usa nombre_docente_usuario.
        Para SemCaptura/Reprobacion usa clave_docente y fallback por nombre.
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
    # Filtro inicial por rol docente
    # ======================================================
    if es_docente:
        base_pl_filtrado, msg_doc = _filtrar_docente_seguro_pl(
            base_pl,
            clave_docente=clave_docente_usuario,
            nombre_docente=nombre_docente_usuario,
            hoja_nombre="Datos",
        )

        if base_pl_filtrado is None or base_pl_filtrado.is_empty():
            st.info(
                "No hay información disponible para tu usuario docente en la hoja 'Datos'."
            )

            if msg_doc:
                with st.expander("Detalle técnico del filtro"):
                    st.write(msg_doc)

            with st.expander("Columnas disponibles en Datos"):
                st.write(list(base_pl.columns))

            return

        base_pl = base_pl_filtrado

    # ======================================================
    # Selección de plantel
    # ======================================================
    if es_docente:
        planteles_docente = _planteles_desde_polars(base_pl)

        if not planteles_docente:
            st.info("No hay planteles disponibles para tu usuario docente.")
            return

        # Si el docente aparece en varios planteles, solo puede elegir entre los suyos.
        if len(planteles_docente) == 1:
            sel_plantel = planteles_docente[0]

            st.text_input(
                "Plantel",
                sel_plantel or "",
                disabled=True,
                key="cmp_plantel_ro_comportamiento_docente",
            )
        else:
            sel_plantel = st.selectbox(
                "Selecciona un plantel",
                planteles_docente,
                key="cmp_sel_plantel_comportamiento_docente",
            )

    elif es_admin:
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
        df_plantel_pl = _filter_text_equals(
            base_pl,
            COL_PLANTEL,
            sel_plantel,
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

    if es_docente:
        # En rol docente NO se permite seleccionar otro docente.
        sel_docente = docentes[0] if len(docentes) == 1 else " | ".join(docentes)

        st.text_input(
            "Docente",
            sel_docente or "",
            disabled=True,
            key="cmp_docente_ro_comportamiento",
        )

        df_docente_pl = df_plantel_pl
    else:
        sel_docente = st.selectbox(
            "Selecciona un docente",
            docentes,
            key="cmp_sel_docente_comportamiento",
        )

        df_docente_pl = _filter_docente_nombre_equals(
            df_plantel_pl,
            COL_DOCENTE,
            sel_docente,
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
        clave_docente_usuario=clave_docente_usuario,
        nombre_docente_usuario=nombre_docente_usuario,
        es_docente=es_docente,
    )

    if msg_sc:
        if (
            msg_sc.startswith("La hoja")
            or msg_sc.startswith("No se encontró")
            or "No se encontró información" in msg_sc
        ):
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
        clave_docente_usuario=clave_docente_usuario,
        nombre_docente_usuario=nombre_docente_usuario,
        es_docente=es_docente,
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
