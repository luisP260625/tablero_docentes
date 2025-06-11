import streamlit as st
import pandas as pd
from io import BytesIO
from fpdf import FPDF
from data.logger import obtener_bitacora

def exportar_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    col_widths = [60, 60, 70]
    headers = ["Usuario", "Número de accesos", "Fechas de acceso"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 10, h, border=1)
    pdf.ln()

    for _, row in df.iterrows():
        fechas_texto = ", ".join(row["Fechas"])
        fechas_truncadas = fechas_texto[:60] + "..." if len(fechas_texto) > 60 else fechas_texto

        pdf.cell(col_widths[0], 10, str(row["Usuario"]), border=1)
        pdf.cell(col_widths[1], 10, str(row["Accesos"]), border=1)
        pdf.cell(col_widths[2], 10, fechas_truncadas, border=1)
        pdf.ln()

    # ✅ Exportación segura como PDF para Streamlit
    buffer = BytesIO()
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    buffer.write(pdf_bytes)
    buffer.seek(0)
    return buffer

def mostrar():
    st.subheader("📋 Bitácora de Conexiones de Usuarios")

    df_bitacora = obtener_bitacora()

    if df_bitacora.empty:
        st.info("No se han registrado accesos aún.")
        return

    st.dataframe(df_bitacora, use_container_width=True)

    pdf_buffer = exportar_pdf(df_bitacora)
    st.download_button(
        label="📄 Exportar Bitácora en PDF",
        data=pdf_buffer,
        file_name="bitacora_conexiones.pdf",
        mime="application/pdf"
    )
