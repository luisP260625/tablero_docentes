import streamlit as st
import io

def descargar_csv(nombre_archivo: str, df):
    # Convertir a pandas para facilitar exportación CSV
    csv = df.to_pandas().to_csv(index=False).encode('utf-8')
    
    st.download_button(
        label="📄 Imprimir resultados",
        data=csv,
        file_name=f"{nombre_archivo}.csv",
        mime='text/csv'
    )
