import streamlit as st
import pandas as pd

from data.logger import obtener_bitacora_df


def mostrar():
    st.title("📌 Bitácora de Conexiones")

    # Botón para recargar (vuelve a bajar de Spaces)
    colA, colB = st.columns([1, 3])
    with colA:
        if st.button("🔄 Recargar"):
            st.rerun()

    df = obtener_bitacora_df()

    if df.empty:
        st.info("Aún no hay registros. En cuanto alguien inicie sesión, se generará la bitácora en Spaces.")
        return

    # Parse de fecha (si alguna viene mal, no revienta)
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
    df = df.dropna(subset=["FechaHora"]).sort_values("FechaHora", ascending=False)

    # Filtros
    st.subheader("Filtros")
    c1, c2, c3 = st.columns(3)

    planteles = sorted([p for p in df["Plantel"].dropna().unique().tolist() if str(p).strip() != ""])
    with c1:
        sel_plantel = st.selectbox("Plantel", ["(Todos)"] + planteles)

    with c2:
        usuarios = sorted(df["Usuario"].dropna().unique().tolist())
        sel_usuario = st.selectbox("Usuario", ["(Todos)"] + usuarios)

    with c3:
        fechas = df["FechaHora"].dt.date
        min_d, max_d = fechas.min(), fechas.max()
        rango = st.date_input("Rango fechas", value=(min_d, max_d), min_value=min_d, max_value=max_d)

    if isinstance(rango, tuple) and len(rango) == 2:
        d1, d2 = rango
        df = df[(df["FechaHora"].dt.date >= d1) & (df["FechaHora"].dt.date <= d2)]

    if sel_plantel != "(Todos)":
        df = df[df["Plantel"] == sel_plantel]

    if sel_usuario != "(Todos)":
        df = df[df["Usuario"] == sel_usuario]

    # KPIs
    st.subheader("Resumen")
    k1, k2, k3 = st.columns(3)
    k1.metric("Total registros", len(df))
    k2.metric("Usuarios únicos", df["Usuario"].nunique())
    k3.metric("Planteles únicos", df["Plantel"].nunique())

    # Tabla
    st.subheader("Registros")
    df_show = df.copy()
    df_show["FechaHora"] = df_show["FechaHora"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # Descarga CSV
    csv_bytes = df_show.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Descargar CSV",
        data=csv_bytes,
        file_name="bitacora_conexiones.csv",
        mime="text/csv",
    )
