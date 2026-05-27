import streamlit as st
import polars as pl


TOP_DOCENTES_FECHA_ANTIGUA = 6


COLUMNAS_SEMCAPTURA = [
    "PLANTEL",
    "DOCENTE",
    "MODULO",
    "SEMESTRE",
    "FECHA_CAPTURA",
    "GRUPO",
    "UAPRENDIZAJE",
    "RAPRENDIZAJE",
    "IEVALUAR",
    "IEVALUADOS",
    "PCAPTURA",
    "TOTALE",
    "ESTATUS",
]


def normalizar_columnas(df: pl.DataFrame) -> pl.DataFrame:
    """
    Normaliza nombres de columnas:
    - Quita espacios al inicio/final.
    - Convierte a mayúsculas.
    """

    if df is None or df.is_empty():
        return df

    rename_map = {}

    for col in df.columns:
        col_limpia = str(col).strip().upper()

        if col != col_limpia:
            rename_map[col] = col_limpia

    if rename_map:
        df = df.rename(rename_map)

    return df


def ordenar_columnas(df: pl.DataFrame) -> pl.DataFrame:
    """
    Reordena columnas:
    - Primero las columnas esperadas.
    - Después cualquier columna extra.
    """

    if df is None or df.is_empty():
        return df

    columnas_presentes = [c for c in COLUMNAS_SEMCAPTURA if c in df.columns]
    columnas_extra = [c for c in df.columns if c not in columnas_presentes]

    return df.select(columnas_presentes + columnas_extra)


def agregar_columna_pc_num(df: pl.DataFrame) -> pl.DataFrame:
    """
    Convierte PCAPTURA a número auxiliar para poder filtrar.
    Soporta valores como:
    - 85
    - 85.5
    - 85%
    - 85,5
    """

    if df is None or df.is_empty() or "PCAPTURA" not in df.columns:
        return df

    return df.with_columns(
        pl.col("PCAPTURA")
        .cast(pl.Utf8)
        .str.replace_all("%", "")
        .str.replace_all(",", ".")
        .cast(pl.Float64, strict=False)
        .alias("_PCAPTURA_NUM")
    )


def aplicar_filtro_captura(df: pl.DataFrame, filtro: str) -> pl.DataFrame:
    """
    Aplica filtro por porcentaje de captura.
    """

    if df is None or df.is_empty() or "_PCAPTURA_NUM" not in df.columns:
        return df

    if filtro in ["≤30", "Menor o igual a 30"]:
        return df.filter(pl.col("_PCAPTURA_NUM") <= 30)

    if filtro == "31 a 60":
        return df.filter(
            (pl.col("_PCAPTURA_NUM") >= 31)
            & (pl.col("_PCAPTURA_NUM") <= 60)
        )

    if filtro == "61 a 90":
        return df.filter(
            (pl.col("_PCAPTURA_NUM") >= 61)
            & (pl.col("_PCAPTURA_NUM") <= 90)
        )

    if filtro == "91 a 100":
        return df.filter(
            (pl.col("_PCAPTURA_NUM") >= 91)
            & (pl.col("_PCAPTURA_NUM") <= 100)
        )

    return df


def agregar_columna_fecha_captura_dt(df: pl.DataFrame) -> pl.DataFrame:
    """
    Crea una columna auxiliar de fecha para ordenar registros con captura antigua.
    Soporta formatos frecuentes:
    - YYYY-MM-DD
    - DD/MM/YYYY
    - DD-MM-YYYY
    - YYYY/MM/DD
    - Fechas con hora.
    """

    if df is None or df.is_empty() or "FECHA_CAPTURA" not in df.columns:
        return df

    fecha_txt = pl.col("FECHA_CAPTURA").cast(pl.Utf8).str.strip_chars()

    expresiones_fecha = [
        fecha_txt.str.strptime(pl.Date, format="%Y-%m-%d", strict=False),
        fecha_txt.str.strptime(pl.Date, format="%d/%m/%Y", strict=False),
        fecha_txt.str.strptime(pl.Date, format="%d-%m-%Y", strict=False),
        fecha_txt.str.strptime(pl.Date, format="%Y/%m/%d", strict=False),
        fecha_txt.str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False).dt.date(),
        fecha_txt.str.strptime(pl.Datetime, format="%d/%m/%Y %H:%M:%S", strict=False).dt.date(),
        fecha_txt.str.strptime(pl.Datetime, format="%d-%m-%Y %H:%M:%S", strict=False).dt.date(),
        fecha_txt.str.strptime(pl.Datetime, format="%Y/%m/%d %H:%M:%S", strict=False).dt.date(),
        fecha_txt.str.strptime(pl.Datetime, format="%Y-%m-%dT%H:%M:%S", strict=False).dt.date(),
    ]

    return df.with_columns(
        pl.coalesce(expresiones_fecha).alias("_FECHA_CAPTURA_DT")
    )


def obtener_top_docentes_fecha_antigua(df: pl.DataFrame) -> pl.DataFrame:
    """
    Obtiene los docentes con fecha de captura más antigua.

    La lógica toma la fecha de captura más antigua por docente para evitar
    repetir al mismo docente varias veces cuando tiene varios módulos/grupos.
    """

    if df is None or df.is_empty() or "FECHA_CAPTURA" not in df.columns:
        return pl.DataFrame()

    df_aux = agregar_columna_fecha_captura_dt(df)

    if "_FECHA_CAPTURA_DT" not in df_aux.columns:
        return pl.DataFrame()

    df_aux = df_aux.filter(pl.col("_FECHA_CAPTURA_DT").is_not_null())

    if df_aux.is_empty():
        return pl.DataFrame()

    df_aux = df_aux.sort("_FECHA_CAPTURA_DT")

    if "DOCENTE" in df_aux.columns:
        df_aux = df_aux.unique(
            subset=["DOCENTE"],
            keep="first",
            maintain_order=True,
        )

    columnas_resumen = [
        "PLANTEL",
        "DOCENTE",
        "MODULO",
        "GRUPO",
        "FECHA_CAPTURA",
        "PCAPTURA",
        "ESTATUS",
    ]

    columnas_presentes = [c for c in columnas_resumen if c in df_aux.columns]

    return df_aux.head(TOP_DOCENTES_FECHA_ANTIGUA).select(columnas_presentes)


def lista_unicos(df: pl.DataFrame, columna: str) -> list[str]:
    """
    Devuelve valores únicos ordenados de una columna.
    """

    if df is None or df.is_empty() or columna not in df.columns:
        return []

    valores = (
        df.select(pl.col(columna).cast(pl.Utf8))
        .drop_nulls()
        .unique()
        .sort(columna)
        .get_column(columna)
        .to_list()
    )

    return [str(v) for v in valores if str(v).strip()]


def filtrar_texto_contiene(df: pl.DataFrame, columna: str, texto: str) -> pl.DataFrame:
    """
    Filtra una columna de texto por coincidencia parcial.
    """

    if df is None or df.is_empty() or not texto or columna not in df.columns:
        return df

    texto = texto.strip().upper()

    if not texto:
        return df

    return df.filter(
        pl.col(columna)
        .cast(pl.Utf8)
        .str.to_uppercase()
        .str.contains(texto, literal=True)
    )


def limitar_registros(df: pl.DataFrame, limite_opcion) -> pl.DataFrame:
    """
    Limita los registros visibles en pantalla.
    """

    if df is None or df.is_empty():
        return df

    if limite_opcion == "Todos":
        return df

    try:
        limite = int(limite_opcion)
        return df.head(limite)
    except Exception:
        return df.head(1000)


def mostrar_top_docentes_fecha_antigua(df_view: pl.DataFrame) -> None:
    """
    Muestra el apartado de docentes con fecha de captura más antigua.
    """

    st.subheader(f"{TOP_DOCENTES_FECHA_ANTIGUA} docentes con fecha de captura más antigua")

    if "FECHA_CAPTURA" not in df_view.columns:
        st.warning("No se encontró la columna FECHA_CAPTURA; no se puede calcular este apartado.")
        return

    top_docentes = obtener_top_docentes_fecha_antigua(df_view)

    if top_docentes is None or top_docentes.is_empty():
        st.info("No hay fechas de captura válidas para mostrar.")
        return

    st.dataframe(
        top_docentes.to_pandas(),
        hide_index=True,
        use_container_width=True,
        height=270,
        column_config={
            "PLANTEL": st.column_config.TextColumn("Plantel", width="medium"),
            "DOCENTE": st.column_config.TextColumn("Docente", width="large"),
            "MODULO": st.column_config.TextColumn("Módulo", width="large"),
            "GRUPO": st.column_config.TextColumn("Grupo", width="small"),
            "FECHA_CAPTURA": st.column_config.TextColumn("Fecha captura", width="medium"),
            "PCAPTURA": st.column_config.TextColumn("% captura", width="small"),
            "ESTATUS": st.column_config.TextColumn("Estatus", width="medium"),
        },
    )


def mostrar_tabla_captura(df_display: pl.DataFrame) -> None:
    """
    Muestra la tabla principal de captura docente.
    """

    pdf_display = df_display.to_pandas()

    st.dataframe(
        pdf_display,
        hide_index=True,
        height=600,
        use_container_width=True,
        column_config={
            "PLANTEL": st.column_config.TextColumn("Plantel", width="medium"),
            "DOCENTE": st.column_config.TextColumn("DOCENTE", width="medium"),
            "MODULO": st.column_config.TextColumn("MODULO", width="medium"),
            "SEMESTRE": st.column_config.NumberColumn("SEMESTRE", width="small"),
            "FECHA_CAPTURA": st.column_config.TextColumn("FECHA CAPTURA", width="medium"),
            "GRUPO": st.column_config.TextColumn("GRUPO", width="small"),
            "UAPRENDIZAJE": st.column_config.NumberColumn("UAPRENDIZAJE", width="small"),
            "RAPRENDIZAJE": st.column_config.NumberColumn("RAPRENDIZAJE", width="small"),
            "IEVALUAR": st.column_config.NumberColumn("IEVALUAR", width="small"),
            "IEVALUADOS": st.column_config.NumberColumn("IEVALUADOS", width="small"),
            "PCAPTURA": st.column_config.TextColumn("PCAPTURA", width="small"),
            "TOTALE": st.column_config.NumberColumn("TOTALE", width="small"),
            "ESTATUS": st.column_config.TextColumn("ESTATUS", width="medium"),
        },
    )


def mostrar(df_semcaptura: pl.DataFrame, plantel_usuario: str, administrador: bool):
    # ======================================================
    # 1. Título
    # ======================================================
    st.title("CAPTURA DOCENTES")

    if df_semcaptura is None or df_semcaptura.is_empty():
        st.info("No hay información disponible para mostrar.")
        return

    # ======================================================
    # Preparación base
    # ======================================================
    df_view = normalizar_columnas(df_semcaptura)

    if df_view is None or df_view.is_empty():
        st.info("No hay información disponible para mostrar.")
        return

    df_view = ordenar_columnas(df_view)

    # ======================================================
    # 2. Filtro por plantel
    # ======================================================
    plantel_filtro = "Todos"

    if administrador:
        if "PLANTEL" in df_view.columns:
            planteles = ["Todos"] + lista_unicos(df_view, "PLANTEL")

            plantel_filtro = st.selectbox(
                "Filtrar por plantel",
                planteles,
                key="captura_plantel_admin",
            )

            if plantel_filtro != "Todos":
                df_view = df_view.filter(pl.col("PLANTEL") == plantel_filtro)
        else:
            st.warning("No se encontró la columna PLANTEL.")
    else:
        if "PLANTEL" in df_view.columns:
            df_view = df_view.filter(pl.col("PLANTEL") == plantel_usuario)

        st.caption(f"Plantel: **{plantel_usuario or 'No asignado'}**")

    if df_view.is_empty():
        st.info("No hay registros disponibles para el plantel seleccionado.")
        return

    # ======================================================
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