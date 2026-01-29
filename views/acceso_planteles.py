import streamlit as st

from data.planteles import cargar_planteles


def mostrar_acceso_planteles():
    st.title("Acceso Planteles")
    st.caption("Búsqueda desde assets/Datos1.xlsx → hoja 'Planteles'.")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Buscar plantel",
            placeholder="Escribe parte del nombre del plantel…",
        )
    with col2:
        mostrar_contrasena = st.checkbox("Mostrar contraseña", value=False)

    try:
        df = cargar_planteles()
    except Exception as e:
        st.error(f"No se pudo cargar la información de planteles: {e}")
        st.stop()

    # Filtro
    if query.strip():
        mask = df["Plantel"].str.contains(query.strip(), case=False, na=False)
        res = df[mask].copy()
    else:
        res = df.copy()

    # Ocultar contraseña (si aplica)
    if not mostrar_contrasena:
        res["Contrasena"] = res["Contrasena"].apply(lambda x: "•" * len(str(x)) if str(x) else "")

    st.write(f"Registros encontrados: **{len(res)}**")
    st.dataframe(res, use_container_width=True, hide_index=True)
