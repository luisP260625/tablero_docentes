from pathlib import Path
import unicodedata

import streamlit as st
import pandas as pd
import polars as pl

from config import EXCEL_FILE, SHEET_DATOS, SHEET_SEMCAPTURA


SHEET_REPROBACION = "Reprobacion"

CACHE_DIR = Path("assets/cache_indicadores")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DATOS = CACHE_DIR / "datos.parquet"
CACHE_SEMCAPTURA = CACHE_DIR / "semcaptura.parquet"
CACHE_REPROBACION = CACHE_DIR / "reprobacion.parquet"


# ==========================================================
# Utilidades de cache
# ==========================================================
def _mtime(path: str | Path) -> float:
    path = Path(path)

    if not path.exists():
        return 0

    return path.stat().st_mtime


def _cache_vigente(cache_path: Path, excel_path: str | Path) -> bool:
    excel_path = Path(excel_path)

    if not cache_path.exists():
        return False

    if not excel_path.exists():
        return False

    return cache_path.stat().st_mtime >= excel_path.stat().st_mtime


# ==========================================================
# Utilidades de normalización
# ==========================================================
def _norm_colname(s) -> str:
    """
    Normaliza nombres de columna:
    CLAVE_DOCENTE, clave docente, Clave Docente -> CLAVEDOCENTE
    """
    if s is None:
        return ""

    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    return (
        s.strip()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
        .upper()
    )


def _es_columna_clave_docente(columna) -> bool:
    """
    Detecta cualquier variante de la columna CLAVE_DOCENTE.
    """
    return _norm_colname(columna) == "CLAVEDOCENTE"


def _limpiar_valor_clave_docente(valor) -> str:
    """
    Convierte CLAVE_DOCENTE a texto seguro.

    Evita errores como:
    Expected bytes, got a 'int' object
    Conversion failed for column CLAVE_DOCENTE with type object

    Soporta:
    - Vacíos
    - NaN
    - bytes
    - int
    - float
    - texto
    - valores como 8100003.0
    """
    if valor is None:
        return ""

    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass

    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", errors="ignore")

    try:
        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
    except Exception:
        pass

    texto = str(valor).strip()

    if texto.endswith(".0"):
        posible_numero = texto[:-2]
        if posible_numero.isdigit():
            texto = posible_numero

    return texto


def _normalizar_clave_docente_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza cualquier columna CLAVE_DOCENTE antes de guardar Parquet
    y antes de convertir a Polars.

    Esto evita errores por tipos mezclados provenientes de Excel.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    for col in df.columns:
        if _es_columna_clave_docente(col):
            df[col] = df[col].map(_limpiar_valor_clave_docente).astype("string").fillna("")

    return df


def _tiene_columna_normalizada(df: pd.DataFrame, nombre_normalizado: str) -> bool:
    """
    Revisa si existe una columna por nombre normalizado.
    """
    if df is None or df.empty:
        return False

    return any(_norm_colname(c) == nombre_normalizado for c in df.columns)


def _leer_excel_rapido(excel_path: str, sheet_name: str, usecols=None) -> pd.DataFrame:
    """
    Lee Excel usando calamine si está instalado.
    Si no está disponible, usa el motor normal de pandas/openpyxl.
    """
    try:
        return pd.read_excel(
            excel_path,
            sheet_name=sheet_name,
            engine="calamine",
            usecols=usecols,
        )
    except Exception:
        return pd.read_excel(
            excel_path,
            sheet_name=sheet_name,
            usecols=usecols,
        )


def _ordenar_polars_si_existen(df: pl.DataFrame, columnas: list[str]) -> pl.DataFrame:
    columnas_existentes = [c for c in columnas if c in df.columns]

    if columnas_existentes:
        return df.sort(columnas_existentes)

    return df


def formatear_fecha_captura(serie: pd.Series) -> pd.Series:
    """
    Convierte la columna FECHA_CAPTURA a formato dd/mm/aaaa.

    Soporta:
    - Fechas normales de Excel
    - Fechas como texto
    - Fechas convertidas a timestamp en milisegundos
    - Fechas como número serial de Excel
    """
    serie_original = serie.copy()

    if pd.api.types.is_datetime64_any_dtype(serie):
        fechas = pd.to_datetime(serie, errors="coerce")

    elif pd.api.types.is_numeric_dtype(serie):
        valores = pd.to_numeric(serie, errors="coerce")
        valores_validos = valores.dropna()

        if valores_validos.empty:
            fechas = pd.to_datetime(serie, errors="coerce")
        else:
            valor_maximo = valores_validos.abs().max()

            if valor_maximo > 1_000_000_000_000:
                fechas = pd.to_datetime(valores, unit="ms", errors="coerce")

            elif valor_maximo > 1_000_000_000:
                fechas = pd.to_datetime(valores, unit="s", errors="coerce")

            else:
                fechas = pd.to_datetime(
                    valores,
                    unit="D",
                    origin="1899-12-30",
                    errors="coerce",
                )

    else:
        fechas = pd.to_datetime(
            serie.astype(str),
            errors="coerce",
            dayfirst=True,
        )

    fechas_formateadas = fechas.dt.strftime("%d/%m/%Y")

    return fechas_formateadas.fillna(serie_original.astype(str))


# ==========================================================
# DATOS
# ==========================================================
@st.cache_data(ttl=3600, show_spinner="Cargando datos principales...")
def _cargar_datos_cacheados(excel_mtime: float):
    """
    Carga la hoja Datos.

    1. Si existe assets/cache_indicadores/datos.parquet actualizado, lo usa.
    2. Si no existe o está desactualizado, lee Datos1.xlsx y regenera el Parquet.
    3. Normaliza CLAVE_DOCENTE para evitar errores de tipos mixtos.
    """
    try:
        if _cache_vigente(CACHE_DATOS, EXCEL_FILE):
            df_pandas = pd.read_parquet(CACHE_DATOS)
            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)
        else:
            df_pandas = _leer_excel_rapido(
                EXCEL_FILE,
                sheet_name=SHEET_DATOS,
            )

            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)
            df_pandas.to_parquet(CACHE_DATOS, index=False)

        df = pl.from_pandas(df_pandas)

        df = _ordenar_polars_si_existen(
            df,
            ["Semana", "Plantel", "DOCENTE"],
        )

        return df, None

    except Exception as e:
        return None, str(e)


def cargar_datos():
    """
    Función usada por app.py.

    Mantiene la misma salida:
    return df, error
    """
    return _cargar_datos_cacheados(_mtime(EXCEL_FILE))


# ==========================================================
# SEMCAPTURA
# ==========================================================
@st.cache_data(ttl=3600, show_spinner="Cargando SemCaptura...")
def _cargar_semcaptura_cacheada(excel_mtime: float):
    """
    Carga la hoja SemCaptura.

    1. Si existe assets/cache_indicadores/semcaptura.parquet actualizado, lo usa.
    2. Si no existe o está desactualizado, lee Datos1.xlsx y regenera el Parquet.
    3. Incluye CLAVE_DOCENTE si existe, para poder filtrar por rol docente.
    4. Normaliza CLAVE_DOCENTE para evitar errores de tipos mixtos.
    """
    try:
        columnas_requeridas = [
            "Plantel",
            "DOCENTE",
            "MODULO",
            "SEMESTRE",
            "FECHA_CAPTURA",
            "GRUPO",
            "UAPRENDIZAJE",
            "RAPRENDIZAJE",
            "IEVALUAR",
            "IEVALUADOS",
            "PCAPTURA",
            "TOTALE",
            "ESTATUS",
        ]

        columnas_opcionales = [
            "CLAVE_DOCENTE",
            "clave_docente",
            "Clave Docente",
            "CLAVE DOCENTE",
            "ClaveDocente",
        ]

        columnas_lectura = columnas_requeridas + columnas_opcionales

        leer_desde_excel = not _cache_vigente(CACHE_SEMCAPTURA, EXCEL_FILE)

        if not leer_desde_excel:
            df_pandas = pd.read_parquet(CACHE_SEMCAPTURA)
            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)

            # Si el cache fue creado por una versión anterior y no trae CLAVE_DOCENTE,
            # se fuerza lectura desde Excel para recuperar esa columna.
            if not _tiene_columna_normalizada(df_pandas, "CLAVEDOCENTE"):
                leer_desde_excel = True

        if leer_desde_excel:
            df_pandas = _leer_excel_rapido(
                EXCEL_FILE,
                sheet_name=SHEET_SEMCAPTURA,
                usecols=lambda col: col in columnas_lectura,
            )

            faltantes = [c for c in columnas_requeridas if c not in df_pandas.columns]

            if faltantes:
                return None, f"Faltan columnas en '{SHEET_SEMCAPTURA}': {faltantes}"

            columnas_existentes = [
                c for c in columnas_requeridas + columnas_opcionales
                if c in df_pandas.columns
            ]

            df_pandas = df_pandas[columnas_existentes]

            df_pandas["FECHA_CAPTURA"] = formatear_fecha_captura(
                df_pandas["FECHA_CAPTURA"]
            )

            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)
            df_pandas.to_parquet(CACHE_SEMCAPTURA, index=False)

        df = pl.from_pandas(df_pandas)

        df = _ordenar_polars_si_existen(
            df,
            [
                "Plantel",
                "DOCENTE",
                "MODULO",
                "SEMESTRE",
                "GRUPO",
                "UAPRENDIZAJE",
                "RAPRENDIZAJE",
            ],
        )

        return df, None

    except Exception as e:
        return None, str(e)


def cargar_semcaptura():
    """
    Función usada por app.py.

    Mantiene la misma salida:
    return df, error
    """
    return _cargar_semcaptura_cacheada(_mtime(EXCEL_FILE))


# ==========================================================
# REPROBACION
# ==========================================================
@st.cache_data(ttl=3600, show_spinner="Cargando Reprobacion...")
def _cargar_reprobacion_cacheada(excel_mtime: float):
    """
    Carga la hoja Reprobacion.

    1. Si existe assets/cache_indicadores/reprobacion.parquet actualizado, lo usa.
    2. Si no existe o está desactualizado, lee Datos1.xlsx y regenera el Parquet.
    3. Normaliza CLAVE_DOCENTE para evitar errores de tipos mixtos.
    """
    try:
        if _cache_vigente(CACHE_REPROBACION, EXCEL_FILE):
            df_pandas = pd.read_parquet(CACHE_REPROBACION)
            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)
        else:
            df_pandas = _leer_excel_rapido(
                EXCEL_FILE,
                sheet_name=SHEET_REPROBACION,
            )

            df_pandas = _normalizar_clave_docente_dataframe(df_pandas)
            df_pandas.to_parquet(CACHE_REPROBACION, index=False)

        df = pl.from_pandas(df_pandas)

        df = _ordenar_polars_si_existen(
            df,
            ["Plantel", "DOCENTE", "Semana", "matricula"],
        )

        return df, None

    except Exception as e:
        return None, str(e)


def cargar_reprobacion():
    """
    Función usada por app.py para la vista Docentes Seguimiento (FT).

    Mantiene la misma salida:
    return df, error
    """
    return _cargar_reprobacion_cacheada(_mtime(EXCEL_FILE))