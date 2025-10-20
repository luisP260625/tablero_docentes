# views/indicadores_academicos.py  (usa el nombre de tu módulo)
import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from datetime import datetime

# =========================
# Carga de datos
# =========================
@st.cache_data
def cargar_datos():
    # Asegúrate de que en "Reprobacion" exista la columna 'pRelativo'
    df_reprobacion = pd.read_excel("assets/Datos1.xlsx", sheet_name="Reprobacion")
    df_matricula   = pd.read_excel("assets/Datos1.xlsx", sheet_name="Matricula", usecols=["Plantel", "matriculaTotal"])
    return df_reprobacion, df_matricula

# =========================
# Exportadores
# =========================
def exportar_excel(df, filename="seguimiento_filtrado.xlsx"):
    """
    Exporta EXACTAMENTE las columnas del DataFrame recibido (incluyendo pRelativo si está presente).
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="NO_COMPETENTES")
        # Ajuste de ancho básico
        worksheet = writer.sheets["NO_COMPETENTES"]
        for idx, col in enumerate(df.columns, 1):
            width = min(max(12, int(df[col].astype(str).str.len().mean() + 5)), 40)
            worksheet.set_column(idx-1, idx-1, width)
    output.seek(0)
    return output

def exportar_html_imprimible(df: pd.DataFrame, titulo: str, subtitulo: str = "", filename: str = "no_competentes.html") -> BytesIO:
    """Genera un HTML listo para imprimir (Ctrl+P → PDF) con estilos básicos."""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    css = """
    <style>
      @media print {
        body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        .no-print { display: none !important; }
        table { page-break-inside: avoid; }
      }
      body { font-family: Arial, Helvetica, sans-serif; margin: 28px; color: #222; }
      h1 { margin: 0 0 8px 0; font-size: 24px; }
      h2 { margin: 0 0 16px 0; font-size: 16px; color: #555; }
      .meta { font-size: 12px; color: #666; margin-bottom: 16px; }
      table { border-collapse: collapse; width: 100%; font-size: 12px; }
      th, td { border: 1px solid #ddd; padding: 6px 8px; }
      th { background: #f3f6fb; text-align: left; }
      tr:nth-child(even) td { background: #fafafa; }
      .footer { margin-top: 24px; font-size: 11px; color: #666; }
    </style>
    """
    html_table = df.to_html(index=False, border=0)
    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>{titulo}</title>
        {css}
      </head>
      <body>
        <h1>{titulo}</h1>
        <h2>{subtitulo}</h2>
        <div class="meta">Generado: {ahora}</div>
        {html_table}
        <div class="footer">
          Documento para impresión — Use Ctrl+P o ⌘+P para guardar como PDF.
        </div>
      </body>
    </html>
    """
    b = BytesIO(html.encode("utf-8"))
    b.seek(0)
    return b

# =========================
# Vista principal
# =========================
def mostrar_indicadores_academicos():
    st.title("📊 Indicadores Académicos")

    df_reprobacion, df_matricula = cargar_datos()

    # --- Agregación para tabla/gráfica (igual que antes) ---
    df_modulos = df_reprobacion.groupby(["Plantel", "matricula"]).size().reset_index(name="modulos_reprobados")
    df_modulos["categoria"] = df_modulos["modulos_reprobados"].apply(lambda x: str(x) if x <= 10 else "11 o más")

    resumen = df_modulos.groupby(["Plantel", "categoria"]).size().reset_index(name="total_estudiantes")
    tabla = resumen.pivot(index="Plantel", columns="categoria", values="total_estudiantes").fillna(0).astype(int)
    tabla["Total estudiantes reprobados"] = tabla.sum(axis=1)
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

    # =========================
    # ADMIN
    # =========================
    if st.session_state["administrador"]:
        st.subheader("📋 Estudiantes agrupados por módulos cursados")
        st.dataframe(tabla, use_container_width=True)

        total_general = tabla["Total estudiantes reprobados"].sum()
        porcentaje_promedio = round((total_general / tabla["matriculaTotal"].sum()) * 100, 2)
        st.markdown(f"### 👥 Total general de estudiantes: **{total_general:,}**")
        st.markdown(f"### 📊 Porcentaje respecto a matrícula: **{porcentaje_promedio}%**")

        tabla_ordenada = tabla.sort_values(by="% Estudiantes reprobados", ascending=False)
        tabla_ordenada["etiqueta"] = (
            tabla_ordenada["Total estudiantes reprobados"].astype(str)
            + " - " + tabla_ordenada["% Estudiantes reprobados"].astype(str) + "%"
        )

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

        # ---------- Exportar / imprimir por plantel (con pRelativo al final) ----------
        st.markdown("---")
        st.subheader("🖨️ Imprimir / exportar NO competentes por plantel")

        planteles_disponibles = sorted(df_reprobacion["Plantel"].dropna().unique().tolist())
        plantel_sel = st.selectbox("Selecciona un plantel", planteles_disponibles)

        # Columnas base + pRelativo al final si existe
        columnas_exportar = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]
        df_print = df_reprobacion[df_reprobacion["Plantel"] == plantel_sel].copy()

        # Aseguramos pRelativo como float si existe
        if "pRelativo" in df_print.columns:
            df_print["pRelativo"] = pd.to_numeric(df_print["pRelativo"], errors="coerce")

        faltantes_cols = [c for c in columnas_exportar if c not in df_print.columns]
        cols_ok = [c for c in columnas_exportar if c in df_print.columns]

        # Orden final con pRelativo al final si existe
        if "pRelativo" in df_print.columns:
            orden_final = (["Plantel"] if "Plantel" in df_print.columns else []) + cols_ok + ["pRelativo"]
        else:
            orden_final = (["Plantel"] if "Plantel" in df_print.columns else []) + cols_ok

        df_print = df_print[orden_final]

        if df_print.empty:
            st.info(f"ℹ️ No hay registros de NO competentes para **{plantel_sel}**.")
        else:
            st.dataframe(df_print, use_container_width=True, height=360)

            # Botón Excel (incluye pRelativo si existe)
            archivo_xlsx = exportar_excel(df_print, filename=f"no_competentes_{plantel_sel}.xlsx")
            st.download_button(
                label="📤 Descargar Excel (NO competentes)",
                data=archivo_xlsx,
                file_name=f"no_competentes_{plantel_sel}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            # Botón HTML imprimible (incluye pRelativo si existe)
            archivo_html = exportar_html_imprimible(
                df_print,
                titulo="Estudiantes NO competentes",
                subtitulo=f"Plantel: {plantel_sel}",
                filename=f"no_competentes_{plantel_sel}.html"
            )
            st.download_button(
                label="🖨️ Descargar HTML para imprimir (Ctrl+P → PDF)",
                data=archivo_html,
                file_name=f"no_competentes_{plantel_sel}.html",
                mime="text/html",
                use_container_width=True
            )

    # =========================
    # PLANTEL (no administrador)
    # =========================
    else:
        plantel_usuario = st.session_state["plantel_usuario"]
        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario]
        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        # 🔹 Seguimiento semanal (sin cambios)
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

        # 🔹 Exportación / impresión (NO competentes del plantel actual, con pRelativo al final)
        columnas_exportar = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]
        df_exportar = df_reprobacion[df_reprobacion["Plantel"] == plantel_usuario].copy()

        # Aseguramos pRelativo como float si existe
        if "pRelativo" in df_exportar.columns:
            df_exportar["pRelativo"] = pd.to_numeric(df_exportar["pRelativo"], errors="coerce")

        faltantes_cols = [c for c in columnas_exportar if c not in df_exportar.columns]
        cols_ok = [c for c in columnas_exportar if c in df_exportar.columns]

        if "Plantel" in df_exportar.columns:
            base_cols = ["Plantel"] + cols_ok
        else:
            base_cols = cols_ok

        # Orden final con pRelativo al final si existe
        if "pRelativo" in df_exportar.columns:
            orden_final = base_cols + ["pRelativo"]
        else:
            orden_final = base_cols

        df_exportar = df_exportar[orden_final]

        st.markdown("### 📄 Estudiantes NO competentes (detalle)")
        if df_exportar.empty:
            st.info("ℹ️ No hay registros de NO competentes para este plantel.")
        else:
            st.dataframe(df_exportar, use_container_width=True, height=360)

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("📤 Exportar estudiantes a Excel"):
                    archivo = exportar_excel(df_exportar, filename=f"estudiantes_{plantel_usuario}.xlsx")
                    st.success("✅ Archivo Excel generado.")
                    st.download_button(
                        label="⬇️ Descargar Excel",
                        data=archivo,
                        file_name=f"estudiantes_{plantel_usuario}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            with col_b:
                archivo_html = exportar_html_imprimible(
                    df_exportar,
                    titulo="Estudiantes NO competentes",
                    subtitulo=f"Plantel: {plantel_usuario}",
                    filename=f"no_competentes_{plantel_usuario}.html"
                )
                st.download_button(
                    label="🖨️ Descargar HTML para imprimir (Ctrl+P → PDF)",
                    data=archivo_html,
                    file_name=f"no_competentes_{plantel_usuario}.html",
                    mime="text/html"
                )
