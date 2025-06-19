import streamlit as st
import pandas as pd
import polars as pl
from config import EXCEL_FILE, SHEET_DATOS

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

