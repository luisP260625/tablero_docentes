import streamlit as st
from views.mostrar_top_porcentajes import mostrar_top_porcentajes
from views.mostrar_docentes_reincidentes import mostrar_docentes_reincidentes
from views.mostrar_modulos_reincidentes import mostrar_modulos_reincidentes
def mostrar_estatal(df):
    st.subheader("📊 Análisis Estatal de No Competencia Académica")

    tabs = st.tabs(["🔝 Top Docentes y Módulos", "🧍‍♂️ Docentes Reincidentes", "📚 Módulos Críticos"])

    with tabs[0]:
        semana = st.selectbox("📅 Selecciona una semana", sorted(df["Semana"].unique()))
        df_filtrado = df.filter(df["Semana"] == semana)
        mostrar_top_porcentajes(df_filtrado, semana)

    with tabs[1]:
        mostrar_docentes_reincidentes(df)

    with tabs[2]:
        mostrar_modulos_reincidentes(df)

