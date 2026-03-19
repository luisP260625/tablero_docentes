import streamlit as st
import pandas as pd
import polars as pl
from config import EXCEL_FILE, SHEET_DATOS, SHEET_SEMCAPTURA


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

        df = pl.from_pandas(df_pandas)

        sort_cols = [
            c for c in ["Plantel", "DOCENTE", "MODULO", "SEMESTRE", "GRUPO", "UAPRENDIZAJE", "RAPRENDIZAJE"]
            if c in df.columns
        ]
        if sort_cols:
            df = df.sort(sort_cols)

        return df, None

    except Exception as e:
        return None, str(e)
