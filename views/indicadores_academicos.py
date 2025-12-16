# views/indicadores_academicos.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime

# =========================
# CONFIG (tamaños de texto)
# =========================
LABEL_FONT_SIZE_ADMIN = 15     # <- tamaño etiquetas gráfica admin (prueba 9, 10, 11, 12)
LABEL_FONT_SIZE_PLANTEL = 15   # <- tamaño etiquetas gráfica plantel (prueba 9, 10, 11, 12)

# Multiplicador para dar "aire" arriba y que no se corte la etiqueta
Y_AXIS_PADDING_MULT = 1.35

# =========================
# Carga de datos
# =========================
@st.cache_data
def cargar_datos():
    df_reprobacion = pd.read_excel("assets/Datos1.xlsx", sheet_name="Reprobacion")
    df_matricula = pd.read_excel(
        "assets/Datos1.xlsx", sheet_name="Matricula", usecols=["Plantel", "matriculaTotal"]
    )
    return df_reprobacion, df_matricula


# =========================
# Utilidades
# =========================
METRICAS_ORDEN = ["pEspecifico", "pAlcanzado", "pRelativo"]


def asegurar_metricas(df: pd.DataFrame) -> pd.DataFrame:
    for col in METRICAS_ORDEN:
        if col not in df.columns:
            df[col] = pd.NA
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def agregar_fila_total(tabla: pd.DataFrame) -> pd.DataFrame:
    df = tabla.copy()
    numeric_cols = df.select_dtypes(include="number").columns.tolist()

    total_row = {col: (df[col].sum() if col in numeric_cols else "") for col in df.columns}
    if "Plantel" in df.columns:
        total_row["Plantel"] = "TOTAL"

    if (
        "% Estudiantes no competentes" in df.columns
        and "Total estudiantes no competentes" in df.columns
        and "matriculaTotal" in df.columns
    ):
        total_nc = df["Total estudiantes no competentes"].sum()
        total_matricula = df["matriculaTotal"].sum()
        total_row["% Estudiantes no competentes"] = round(
            (total_nc / total_matricula) * 100, 2
        ) if total_matricula else 0

    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)


# =========================
# Exportadores
# =========================
def exportar_excel(df, filename="seguimiento_filtrado.xlsx"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="NO_COMPETENTES")
        worksheet = writer.sheets["NO_COMPETENTES"]
        for idx, col in enumerate(df.columns, 1):
            try:
                width = min(max(12, int(df[col].astype(str).str.len().mean() + 5)), 40)
            except Exception:
                width = 20
            worksheet.set_column(idx - 1, idx - 1, width)
    output.seek(0)
    return output


def exportar_html_imprimible(df: pd.DataFrame, titulo: str, subtitulo: str = "", filename: str = "no_competentes.html") -> BytesIO:
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

    # --- Agregación para tabla/gráfica ---
    df_modulos = (
        df_reprobacion
        .groupby(["Plantel", "matricula"])
        .size()
        .reset_index(name="modulos_nc")
    )
    df_modulos["categoria"] = df_modulos["modulos_nc"].apply(lambda x: str(x) if x <= 10 else "11 o más")

    resumen = df_modulos.groupby(["Plantel", "categoria"]).size().reset_index(name="total_estudiantes")
    tabla = (
        resumen.pivot(index="Plantel", columns="categoria", values="total_estudiantes")
        .fillna(0)
        .astype(int)
    )

    tabla["Total estudiantes no competentes"] = tabla.sum(axis=1)
    tabla = tabla.merge(df_matricula, on="Plantel", how="left")

    tabla["matriculaTotal"] = pd.to_numeric(tabla["matriculaTotal"], errors="coerce").fillna(0)
    tabla["% Estudiantes no competentes"] = (tabla["Total estudiantes no competentes"] / tabla["matriculaTotal"]) * 100
    tabla["% Estudiantes no competentes"] = (
        tabla["% Estudiantes no competentes"]
        .replace([float("inf"), -float("inf")], 0)
        .fillna(0)
        .round(2)
    )

    orden_columnas = (
        ["Plantel", "matriculaTotal"] +
        [str(i) for i in range(1, 11) if str(i) in tabla.columns] +
        (["11 o más"] if "11 o más" in tabla.columns else []) +
        ["Total estudiantes no competentes", "% Estudiantes no competentes"]
    )
    tabla = tabla.reset_index()
    columnas_presentes = [col for col in orden_columnas if col in tabla.columns]
    tabla = tabla[columnas_presentes]

    # =========================
    # ADMIN
    # =========================
    if st.session_state["administrador"]:

        vista = st.radio(
            "Visualización de la gráfica:",
            ["% NO competencia", "Total NO competentes"],
            horizontal=True
        )

        tabla_ordenada = tabla.sort_values(by="% Estudiantes no competentes", ascending=False).copy()

        # Etiqueta: "Total - %"
        tabla_ordenada["etiqueta"] = tabla_ordenada.apply(
            lambda r: f"{int(r['Total estudiantes no competentes'])} - {float(r['% Estudiantes no competentes']):.1f}%",
            axis=1
        )

        if vista == "% NO competencia":
            y_col = "% Estudiantes no competentes"
            titulo = "Porcentaje de estudiantes NO competentes por plantel"
            y_title = "% de estudiantes NO competentes"
        else:
            y_col = "Total estudiantes no competentes"
            titulo = "Total de estudiantes NO competentes por plantel"
            y_title = "Total de estudiantes NO competentes"

        ymax = float(tabla_ordenada[y_col].max()) if not tabla_ordenada.empty else 0

        fig = go.Figure(
            data=[
                go.Bar(
                    x=tabla_ordenada["Plantel"],
                    y=tabla_ordenada[y_col],
                    text=tabla_ordenada["etiqueta"],
                    textposition="outside",
                    textangle=-90,  # si se ve al revés: -90
                    marker_color="#FFC107",
                    cliponaxis=False,
                    outsidetextfont=dict(size=LABEL_FONT_SIZE_ADMIN),
                    hoverinfo="skip",
                    hovertemplate="",
                )
            ]
        )

        fig.update_layout(
            title=titulo,
            xaxis_title="Plantel",
            yaxis_title=y_title,
            xaxis_tickangle=-45,
            height=560,
            showlegend=False,
            # 👇 CLAVE: ya NO fuerza tamaño grande; lo igualamos a tu tamaño configurado
            uniformtext=dict(minsize=LABEL_FONT_SIZE_ADMIN, mode="show"),
            yaxis=dict(range=[0, ymax * Y_AXIS_PADDING_MULT if ymax else 1]),
            margin=dict(t=90),
        )

        st.plotly_chart(fig, use_container_width=True)

        # 2) Tabla agrupada + TOTAL
        st.subheader("📋 Estudiantes agrupados por módulos NO competentes")
        tabla_con_total = agregar_fila_total(tabla)
        st.dataframe(tabla_con_total, use_container_width=True)

        col_imp_xlsx, col_imp_html = st.columns(2)
        with col_imp_xlsx:
            archivo_xlsx_agrupada = exportar_excel(tabla_con_total, filename="agrupados_no_competentes.xlsx")
            st.download_button(
                label="📤 Descargar Excel (tabla agrupada)",
                data=archivo_xlsx_agrupada,
                file_name="agrupados_no_competentes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        with col_imp_html:
            archivo_html_agrupada = exportar_html_imprimible(
                tabla_con_total,
                titulo="Estudiantes agrupados por módulos NO competentes",
                subtitulo="(Vista agrupada con TOTAL)",
                filename="agrupados_no_competentes.html"
            )
            st.download_button(
                label="🖨️ Descargar HTML (tabla agrupada)",
                data=archivo_html_agrupada,
                file_name="agrupados_no_competentes.html",
                mime="text/html",
                use_container_width=True
            )

        # Totales generales
        total_general = int(tabla["Total estudiantes no competentes"].sum())
        total_matricula = float(tabla["matriculaTotal"].sum())
        porcentaje_promedio = round((total_general / total_matricula) * 100, 2) if total_matricula else 0
        st.markdown(f"### 👥 Total general de estudiantes NO competentes: **{total_general:,}**")
        st.markdown(f"### 📊 Porcentaje respecto a la matrícula: **{porcentaje_promedio}%**")

        # Imprimir / exportar por plantel
        st.markdown("---")
        st.subheader("🖨️ Imprimir / exportar NO competentes por plantel")

        planteles_disponibles = sorted(df_reprobacion["Plantel"].dropna().unique().tolist())
        plantel_sel = st.selectbox("Selecciona un plantel", planteles_disponibles)

        columnas_base = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]
        df_print = df_reprobacion[df_reprobacion["Plantel"] == plantel_sel].copy()

        df_print = asegurar_metricas(df_print)

        cols_presentes_base = [c for c in columnas_base if c in df_print.columns]
        orden_final = (["Plantel"] if "Plantel" in df_print.columns else []) + cols_presentes_base + METRICAS_ORDEN
        df_print = df_print[orden_final]

        fila_sel = tabla[tabla["Plantel"] == plantel_sel]
        if not fila_sel.empty and "Total estudiantes no competentes" in fila_sel.columns:
            total_nc_admin = int(fila_sel["Total estudiantes no competentes"].iloc[0])
        else:
            total_nc_admin = df_print["matricula"].nunique() if "matricula" in df_print.columns else len(df_print)

        if df_print.empty:
            st.info(f"ℹ️ No hay registros de NO competentes para **{plantel_sel}**.")
        else:
            st.markdown(f"### ⚠️ Estudiantes NO competentes {total_nc_admin} (Detalle) — {plantel_sel}")
            st.dataframe(df_print, use_container_width=True, height=360)

            col1, col2 = st.columns(2)
            with col1:
                archivo_xlsx = exportar_excel(df_print, filename=f"no_competentes_{plantel_sel}.xlsx")
                st.download_button(
                    label="📤 Descargar Excel",
                    data=archivo_xlsx,
                    file_name=f"no_competentes_{plantel_sel}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col2:
                archivo_html = exportar_html_imprimible(
                    df_print,
                    titulo="Estudiantes NO competentes",
                    subtitulo=f"Plantel: {plantel_sel}",
                    filename=f"no_competentes_{plantel_sel}.html"
                )
                st.download_button(
                    label="🖨️ Descargar HTML",
                    data=archivo_html,
                    file_name=f"no_competentes_{plantel_sel}.html",
                    mime="text/html",
                    use_container_width=True
                )

            # Estudiantes sin registro de Calificaciones
            df_sin_registro = (
                df_print[df_print["pEspecifico"] == 0].copy()
                if "pEspecifico" in df_print.columns
                else pd.DataFrame()
            )

            if df_sin_registro.empty:
                total_sin_registro = 0
            else:
                total_sin_registro = (
                    df_sin_registro["matricula"].nunique()
                    if "matricula" in df_sin_registro.columns
                    else len(df_sin_registro)
                )

            st.markdown(f"### 🚨 Estudiantes sin registro de Calificaciones {total_sin_registro} (Detalle) — {plantel_sel}")

            if df_sin_registro.empty:
                st.info(f"ℹ️ No hay registros con pEspecifico = 0 para **{plantel_sel}**.")
            else:
                st.dataframe(df_sin_registro, use_container_width=True, height=360)

                archivo_sin_registro = exportar_excel(
                    df_sin_registro,
                    filename=f"sin_registro_calificaciones_{plantel_sel}.xlsx"
                )
                st.download_button(
                    label="📤 Sin registro de Calificaciones",
                    data=archivo_sin_registro,
                    file_name=f"sin_registro_calificaciones_{plantel_sel}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

    # =========================
    # PLANTEL (no administrador)
    # =========================
    else:
        plantel_usuario = st.session_state["plantel_usuario"]

        # 1) Seguimiento semanal (GRÁFICA)
        df_seguimiento = pd.read_excel("assets/Datos1.xlsx", sheet_name="Seguimiento")
        df_plantel = df_seguimiento[df_seguimiento["Plantel"] == plantel_usuario]

        columnas_cantidad = [col for col in df_plantel.columns if col.startswith("Sem ") and not col.endswith("%")]
        columnas_porcentaje = [
            col for col in df_plantel.columns
            if col.endswith("%") and col.replace(" %", "") in columnas_cantidad
        ]

        df_valores = df_plantel[columnas_cantidad].sum().reset_index()
        df_valores.columns = ["Semana", "Cantidad"]
        df_valores["Semana"] = df_valores["Semana"].str.strip()

        df_porcentajes = df_plantel[columnas_porcentaje].mean().reset_index()
        df_porcentajes.columns = ["Semana", "Porcentaje"]
        df_porcentajes["Semana"] = df_porcentajes["Semana"].str.replace(" %", "").str.strip()

        df_semana = pd.merge(df_valores, df_porcentajes, on="Semana", how="inner")
        df_semana["Porcentaje"] = pd.to_numeric(df_semana["Porcentaje"], errors="coerce").fillna(0).round(2)

        df_semana["Etiqueta"] = df_semana.apply(
            lambda r: f"{int(r['Cantidad'])} - {float(r['Porcentaje']):.1f}%",
            axis=1
        )

        st.subheader(f"📈 Seguimiento semanal – {plantel_usuario}")

        ymax = float(df_semana["Cantidad"].max()) if not df_semana.empty else 0

        fig = go.Figure(
            data=[
                go.Bar(
                    x=df_semana["Semana"],
                    y=df_semana["Cantidad"],
                    text=df_semana["Etiqueta"],
                    textposition="outside",
                    textangle=-90,  # si se ve al revés: -90
                    marker_color="#FFC107",
                    cliponaxis=False,
                    outsidetextfont=dict(size=LABEL_FONT_SIZE_PLANTEL),
                    hoverinfo="skip",
                    hovertemplate="",
                )
            ]
        )

        fig.update_layout(
            xaxis_title="Semana",
            yaxis_title="Cantidad de estudiantes",
            height=520,
            showlegend=False,
            uniformtext=dict(minsize=LABEL_FONT_SIZE_PLANTEL, mode="show"),
            yaxis=dict(range=[0, ymax * Y_AXIS_PADDING_MULT if ymax else 1]),
            margin=dict(t=70),
        )

        st.plotly_chart(fig, use_container_width=True)

        # 2) Estudiantes del plantel (TABLA)
        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario]
        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        # 3) Matrícula total del plantel
        vals = df_matricula[df_matricula["Plantel"] == plantel_usuario]["matriculaTotal"].values
        matricula_plantel = int(vals[0]) if len(vals) else 0
        st.markdown(f"### 🎓 Matrícula total del plantel {plantel_usuario}: **{matricula_plantel:,}**")

        # 4) Estudiantes NO competentes (Detalle)
        columnas_base = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]
        df_exportar = df_reprobacion[df_reprobacion["Plantel"] == plantel_usuario].copy()

        df_exportar = asegurar_metricas(df_exportar)

        cols_presentes_base = [c for c in columnas_base if c in df_exportar.columns]
        base_cols = (["Plantel"] if "Plantel" in df_exportar.columns else []) + cols_presentes_base
        orden_final = base_cols + METRICAS_ORDEN
        df_exportar = df_exportar[orden_final]

        if not tabla_filtrada.empty and "Total estudiantes no competentes" in tabla_filtrada.columns:
            total_nc = int(tabla_filtrada["Total estudiantes no competentes"].iloc[0])
        else:
            total_nc = df_reprobacion[df_reprobacion["Plantel"] == plantel_usuario]["matricula"].nunique()

        st.subheader(f"⚠️ Estudiantes NO competentes {total_nc} (Detalle)")
        if df_exportar.empty:
            st.info("ℹ️ No hay registros de NO competentes para este plantel.")
        else:
            st.dataframe(df_exportar, use_container_width=True, height=360)

            col_a, col_b = st.columns(2)
            with col_a:
                archivo = exportar_excel(df_exportar, filename=f"estudiantes_{plantel_usuario}.xlsx")
                st.download_button(
                    label="📤 Exportar estudiantes a Excel",
                    data=archivo,
                    file_name=f"estudiantes_{plantel_usuario}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_b:
                archivo_html = exportar_html_imprimible(
                    df_exportar,
                    titulo="Estudiantes NO competentes",
                    subtitulo=f"Plantel: {plantel_usuario}",
                    filename=f"no_competentes_{plantel_usuario}.html"
                )
                st.download_button(
                    label="🖨️ Descargar HTML para imprimir",
                    data=archivo_html,
                    file_name=f"no_competentes_{plantel_usuario}.html",
                    mime="text/html",
                    use_container_width=True
                )

        # 🚨 Estudiantes sin registro de Calificaciones – Plantel
        df_sin_registro_plantel = (
            df_exportar[df_exportar["pEspecifico"] == 0].copy()
            if "pEspecifico" in df_exportar.columns
            else pd.DataFrame()
        )

        if df_sin_registro_plantel.empty:
            total_sin_registro_plantel = 0
        else:
            total_sin_registro_plantel = (
                df_sin_registro_plantel["matricula"].nunique()
                if "matricula" in df_sin_registro_plantel.columns
                else len(df_sin_registro_plantel)
            )

        st.subheader(f"🚨 Estudiantes sin registro de Calificaciones {total_sin_registro_plantel} (Detalle)")

        if df_sin_registro_plantel.empty:
            st.info("ℹ️ No hay registros con pEspecifico = 0 para este plantel.")
        else:
            st.dataframe(df_sin_registro_plantel, use_container_width=True, height=360)

            archivo_sin_registro_plantel = exportar_excel(
                df_sin_registro_plantel,
                filename=f"sin_registro_calificaciones_{plantel_usuario}.xlsx"
            )
            st.download_button(
                label="📤 Sin registro de Calificaciones",
                data=archivo_sin_registro_plantel,
                file_name=f"sin_registro_calificaciones_{plantel_usuario}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
