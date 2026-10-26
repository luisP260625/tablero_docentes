    # 3. Los 6 docentes con fecha de captura más antigua
    # ======================================================
    mostrar_top_docentes_fecha_antigua(df_view)

    # ======================================================
    # 4. Selección por filtro de captura
    # ======================================================
    st.subheader("Selección por filtro de captura")

    filtro_captura = "Todos"

    if "PCAPTURA" in df_view.columns:
        filtro_captura = st.radio(
            "Selecciona un rango",
            options=[
                "Todos",
                "Menor o igual a 30",
                "31 a 60",
                "61 a 90",
                "91 a 100",
            ],
            horizontal=True,
            key="captura_filtro_pc",
        )

        df_view = agregar_columna_pc_num(df_view)
        df_view = aplicar_filtro_captura(df_view, filtro_captura)
    else:
        st.warning("No se encontró la columna PCAPTURA; no se puede aplicar el filtro.")

    # ======================================================
    # 5. Filtros rápidos
    # ======================================================
    st.subheader("Filtros rápidos")

    col1, col2 = st.columns(2)

    with col1:
        buscar_docente = st.text_input(
            "Buscar docente",
            key="captura_buscar_docente",
            placeholder="Escribe parte del nombre del docente",
        )

    with col2:
        buscar_modulo = st.text_input(
            "Buscar módulo",
            key="captura_buscar_modulo",
            placeholder="Escribe parte del módulo",
        )

    df_view = filtrar_texto_contiene(df_view, "DOCENTE", buscar_docente)
    df_view = filtrar_texto_contiene(df_view, "MODULO", buscar_modulo)

    # ======================================================
    # Limpieza de columnas auxiliares antes de mostrar tabla
    # ======================================================
    columnas_auxiliares = [
        "_PCAPTURA_NUM",
        "_FECHA_CAPTURA_DT",
    ]

    for columna_auxiliar in columnas_auxiliares:
        if columna_auxiliar in df_view.columns:
            df_view = df_view.drop(columna_auxiliar)

    total_filtrado = df_view.height

    if total_filtrado == 0:
        st.info("No hay registros con los filtros seleccionados.")
        return

    # ======================================================
    # 6. Registros a mostrar
    # ======================================================
    st.subheader("Registros a mostrar")

    col_limite, col_info = st.columns([1, 3])

    with col_limite:
        limite_opcion = st.selectbox(
            "Cantidad de registros",
            options=[500, 1000, 2000, 5000, "Todos"],
            index=1,
            key="captura_limite_registros",
        )

    df_display = limitar_registros(df_view, limite_opcion)

    with col_info:
        st.caption(f"Registros filtrados: **{total_filtrado:,}**")

        if limite_opcion != "Todos" and total_filtrado > int(limite_opcion):
            st.info(
                f"Mostrando {df_display.height:,} de {total_filtrado:,} registros filtrados. "
                "Para ver más información, cambia el límite de registros."
            )

    # ======================================================
    # 7. Tabla
    # ======================================================
    st.subheader("Tabla")

    mostrar_tabla_captura(df_display)

    # ======================================================
    # 8. Botón Descargar Excel eliminado por requerimiento
    # ======================================================