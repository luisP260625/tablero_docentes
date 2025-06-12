import pandas as pd
import polars as pl
from config import EXCEL_FILE, SHEET_PLANTELES
import streamlit as st

@st.cache_data(ttl=600)
def validar_usuario(user, password):
    # Caso especial hardcodeado para admin
    if user.lower() == "admin" and password == "admin":
        return True, "ADMIN", True

    try:
        xls = pd.ExcelFile(EXCEL_FILE)
        if SHEET_PLANTELES not in xls.sheet_names:
            return False, None, False

        df_pandas = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_PLANTELES)
        df = pl.from_pandas(df_pandas)

        usuario_filtrado = df.filter(
            (df["Usuario"].str.strip_chars() == user) & 
            (df["Contrasena"].str.strip_chars() == password)
        )

        if usuario_filtrado.is_empty():
            return False, None, False

        plantel = usuario_filtrado["Plantel"][0]
        rol = usuario_filtrado["Rol"][0].lower() if "Rol" in usuario_filtrado.columns else "usuario"
        es_admin = rol == "admin"

        return True, plantel, es_admin

    except Exception as e:
        return False, None, False
