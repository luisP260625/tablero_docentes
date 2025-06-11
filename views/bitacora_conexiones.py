import streamlit as st
import pandas as pd
from io import BytesIO
from data.logger import obtener_bitacora

def exportar_excel(df):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Bitácora')
        workbook = writer.book
        worksheet = writer.sheets['Bitácora']

        # Formato opcional de encabezado
        format_header = workbook.add_format({
            'bold': True,
            'bg_color': '#D9E1F2',
            'border': 1
        })
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, format_header)

        # Ajuste automático de ancho de columnas
        for i, column in enumerate(df.columns):
            column_width = max(df[column].astype(str).map(len).max(), len(column)) + 2
            worksheet.set_column(i, i, column_width)

    buffer.seek(0)
    return buffer

def mostrar():
    st.subheader("📋 Bitácora de Conexiones de Usuarios")

    df_bitacora = obtener_bitacora()

    if df_bitacora.empty:
        st.info("No se han registrado accesos aún.")
        return

    st.dataframe(df_bitacora, use_container_width=True)

    excel_buffer = exportar_excel(df_bitacora)
    st.download_button(
        label="📊 Exportar Bitácora en Excel",
        data=excel_buffer,
        file_name="bitacora_conexiones.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
