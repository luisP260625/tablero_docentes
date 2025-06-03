import pandas as pd
import polars as pl
from config import EXCEL_FILE, SHEET_PLANTELES
import streamlit as st

@st.cache_data(ttl=600)
def validar_usuario(user, password):
    if user.lower() == "admin" and password == "admin":
        return True, "ADMIN"

    try:
        xls = pd.ExcelFile(EXCEL_FILE)
        if SHEET_PLANTELES not in xls.sheet_names:
            return False, None

        df_pandas = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_PLANTELES)
        df = pl.from_pandas(df_pandas)

        usuario_filtrado = df.filter(
            (df["Usuario"].str.strip_chars() == user) &
            (df["Contrasena"].str.strip_chars() == password)
        )

        if usuario_filtrado.is_empty():
            return False, None
        return True, usuario_filtrado["Plantel"][0]
    except:
        return False, None

