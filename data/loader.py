import streamlit as st
import pandas as pd
import polars as pl
from config import EXCEL_FILE, SHEET_DATOS, SHEET_SEMCAPTURA


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

            # Ejemplo: 1778025600000 = timestamp en milisegundos
            if valor_maximo > 1_000_000_000_000:
                fechas = pd.to_datetime(valores, unit="ms", errors="coerce")

            # Timestamp en segundos
            elif valor_maximo > 1_000_000_000:
                fechas = pd.to_datetime(valores, unit="s", errors="coerce")

            # Número serial de Excel
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


@st.cache_data(ttl=600)  # cache por 10 minutos
def cargar_datos():
    try:
        xls = pd.ExcelFile(EXCEL_FILE)
        if SHEET_DATOS not in xls.sheet_names:
            return None, "La hoja 'Datos' no fue encontrada en el archivo."

        df_pandas = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_DATOS)
        df = pl.from_pandas(df_pandas).sort(["Semana", "Plantel", "DOCENTE"])

        return df, None

    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=600)  # cache por 10 minutos
def cargar_semcaptura():
    """Carga la hoja SemCaptura del Excel para la vista 'Captura Docentes'."""
    try:
        xls = pd.ExcelFile(EXCEL_FILE)

        if SHEET_SEMCAPTURA not in xls.sheet_names:
            return None, "La hoja 'SemCaptura' no fue encontrada en el archivo."

        df_pandas = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_SEMCAPTURA)

        columnas = [
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

        faltantes = [c for c in columnas if c not in df_pandas.columns]

        if faltantes:
            return None, f"Faltan columnas en 'SemCaptura': {faltantes}"

        df_pandas = df_pandas[columnas]

        # Formatear FECHA_CAPTURA para que se muestre como dd/mm/aaaa
        df_pandas["FECHA_CAPTURA"] = formatear_fecha_captura(
            df_pandas["FECHA_CAPTURA"]
        )

        df = pl.from_pandas(df_pandas)

        sort_cols = [
            c
            for c in [
                "Plantel",
                "DOCENTE",
                "MODULO",
                "SEMESTRE",
                "GRUPO",
                "UAPRENDIZAJE",
                "RAPRENDIZAJE",
            ]
            if c in df.columns
        ]

        if sort_cols:
            df = df.sort(sort_cols)

        return df, None

    except Exception as e:
        return None, str(e)