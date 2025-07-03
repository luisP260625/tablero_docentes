import streamlit as st
import pandas as pd
import plotly.express as px

@st.cache_data
def cargar_datos():
    df_reprobacion = pd.read_excel("assets/Datos1.xlsx", sheet_name="Reprobacion")
    df_matricula = pd.read_excel("assets/Datos1.xlsx", sheet_name="Matricula", usecols=["Plantel", "matriculaTotal"])
    return df_reprobacion, df_matricula

def exportar_excel(df, filename="seguimiento_filtrado.xlsx"):
    from io import BytesIO
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return output

def mostrar_indicadores_academicos():
    st.title("📊 Indicadores Académicos")

    df_reprobacion, df_matricula = cargar_datos()

    # 🔄 Ya no se filtran los reprobados; se usan todos los registros
    df_modulos = df_reprobacion.groupby(["Plantel", "matricula"]).size().reset_index(name="modulos_reprobados")
    df_modulos["categoria"] = df_modulos["modulos_reprobados"].apply(lambda x: str(x) if x <= 10 else "11 o más")

    resumen = df_modulos.groupby(["Plantel", "categoria"]).size().reset_index(name="total_estudiantes")
    tabla = resumen.pivot(index="Plantel", columns="categoria", values="total_estudiantes").fillna(0).astype(int)
    tabla["Total estudiantes reprobados"] = tabla.sum(axis=1)  # Podrías renombrar este campo si ya no representa solo reprobados
    tabla = tabla.merge(df_matricula, on="Plantel", how="left")
    tabla["% Estudiantes reprobados"] = (tabla["Total estudiantes reprobados"] / tabla["matriculaTotal"]) * 100
    tabla["% Estudiantes reprobados"] = tabla["% Estudiantes reprobados"].round(2)

    orden_columnas = (
        ["Plantel", "matriculaTotal"] +
        [str(i) for i in range(1, 11) if str(i) in tabla.columns] +
        (["11 o más"] if "11 o más" in tabla.columns else []) +
        ["Total estudiantes reprobados", "% Estudiantes reprobados"]
    )
    tabla = tabla.reset_index()
    columnas_presentes = [col for col in orden_columnas if col in tabla.columns]
    tabla = tabla[columnas_presentes]

    if st.session_state["administrador"]:
        st.subheader("📋 Estudiantes agrupados por módulos cursados")
        st.dataframe(tabla, use_container_width=True)

        total_general = tabla["Total estudiantes reprobados"].sum()
        porcentaje_promedio = round((total_general / tabla["matriculaTotal"].sum()) * 100, 2)
        st.markdown(f"### 👥 Total general de estudiantes: **{total_general:,}**")
        st.markdown(f"### 📊 Porcentaje respecto a matrícula: **{porcentaje_promedio}%**")

        tabla_ordenada = tabla.sort_values(by="% Estudiantes reprobados", ascending=False)
        tabla_ordenada["etiqueta"] = tabla_ordenada["Total estudiantes reprobados"].astype(str) + " - " + tabla_ordenada["% Estudiantes reprobados"].astype(str) + "%"

        fig = px.bar(
            tabla_ordenada,
            x="Plantel",
            y="% Estudiantes reprobados",
            text="etiqueta",
            title="Porcentaje de estudiantes por plantel",
        )
        fig.update_traces(textangle=0, textposition='auto', textfont=dict(size=14))
        fig.update_layout(
            xaxis_tickangle=-45,
            yaxis_title="% de estudiantes",
            xaxis_title="Plantel",
            height=600
        )
        st.plotly_chart(fig, use_container_width=True)

    else:
        plantel_usuario = st.session_state["plantel_usuario"]
        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario]
        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        # 🔹 Seguimiento semanal
        df_seguimiento = pd.read_excel("assets/Datos1.xlsx", sheet_name="Seguimiento")
        df_plantel = df_seguimiento[df_seguimiento["Plantel"] == plantel_usuario]

        columnas_cantidad = [col for col in df_plantel.columns if col.startswith("Sem ") and not col.endswith("%")]
        columnas_porcentaje = [col for col in df_plantel.columns if col.endswith("%") and col.replace(" %", "") in columnas_cantidad]

        df_valores = df_plantel[columnas_cantidad].sum().reset_index()
        df_valores.columns = ["Semana", "Cantidad"]
        df_valores["Semana"] = df_valores["Semana"].str.strip()

        df_porcentajes = df_plantel[columnas_porcentaje].mean().reset_index()
        df_porcentajes.columns = ["Semana", "Porcentaje"]
        df_porcentajes["Semana"] = df_porcentajes["Semana"].str.replace(" %", "").str.strip()

        df_semana = pd.merge(df_valores, df_porcentajes, on="Semana", how="inner")
        df_semana["Porcentaje"] = df_semana["Porcentaje"].round(2)
        df_semana["Etiqueta"] = df_semana["Cantidad"].astype(int).astype(str) + " - " + df_semana["Porcentaje"].astype(str) + "%"

        fig = px.bar(
            df_semana,
            x="Semana",
            y="Cantidad",
            text="Etiqueta",
            title=f"Seguimiento semanal – {plantel_usuario}",
            labels={"Cantidad": "Estudiantes"}
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            xaxis_title="Semana",
            yaxis_title="Cantidad de estudiantes",
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        # 🔹 Matrícula total
        matricula_plantel = df_matricula[df_matricula["Plantel"] == plantel_usuario]["matriculaTotal"].values[0]
        st.markdown(f"### 🎓 Matrícula total del plantel {plantel_usuario}: **{matricula_plantel:,}**")

        # 🔹 Exportación personalizada a Excel
        columnas_exportar = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]
        df_exportar = df_reprobacion[df_reprobacion["Plantel"] == plantel_usuario][columnas_exportar]

        if st.button("📤 Exportar estudiantes a Excel"):
            archivo = exportar_excel(df_exportar)
            st.success("✅ Archivo Excel generado.")
            st.download_button(
                label="⬇️ Descargar Excel",
                data=archivo,
                file_name=f"estudiantes_{plantel_usuario}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
