import streamlit as st
import polars as pl
import pandas as pd
from utils.helpers import to_excel


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

    if "PCAPTURA" not in df.columns:
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

    if "_PCAPTURA_NUM" not in df.columns:
        return df

    if filtro == "≤30":
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

    if not texto or columna not in df.columns:
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
    Esto no afecta el Excel si se decide exportar todos los datos filtrados.
    """

    if limite_opcion == "Todos":
        return df

    try:
        limite = int(limite_opcion)
        return df.head(limite)
    except Exception:
        return df.head(1000)


def generar_nombre_archivo(
    administrador: bool,
    plantel_usuario: str | None,
    plantel_filtro: str,
    filtro_captura: str,
) -> str:
    """
    Genera nombre del archivo Excel.
    """

    if administrador:
        base = "SemCaptura_TODOS" if plantel_filtro == "Todos" else f"SemCaptura_{plantel_filtro}"
    else:
        base = f"SemCaptura_{plantel_usuario}"

    sufijo = (
        "TODOS"
        if filtro_captura == "Todos"
        else filtro_captura.replace("≤", "LE").replace(" ", "_")
    )

    nombre = f"{base}_{sufijo}"

    caracteres_invalidos = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]

    for caracter in caracteres_invalidos:
        nombre = nombre.replace(caracter, "_")

    return nombre


def mostrar(df_semcaptura: pl.DataFrame, plantel_usuario: str, administrador: bool):
    st.title("% de Captura Docentes")

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
    # Filtro por rol / plantel
    # ======================================================
    plantel_filtro = "Todos"

    if administrador:
        if "PLANTEL" in df_view.columns:
            planteles = ["Todos"] + lista_unicos(df_view, "PLANTEL")

            plantel_filtro = st.selectbox(
                "🏫 Filtrar por plantel",
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

        st.text_input(
            "Plantel",
            plantel_usuario or "",
            disabled=True,
            key="captura_plantel_ro",
        )

    # ======================================================
    # Filtros rápidos de texto
    # ======================================================
    with st.expander("🔎 Filtros rápidos", expanded=False):
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
    # Filtro por porcentaje de captura
    # ======================================================
    filtro = "Todos"

    if "PCAPTURA" in df_view.columns:
        filtro = st.radio(
            "Selección por filtro de captura",
            options=["Todos", "≤30", "31 a 60", "61 a 90", "91 a 100"],
            horizontal=True,
            key="captura_filtro_pc",
        )

        df_view = agregar_columna_pc_num(df_view)
        df_view = aplicar_filtro_captura(df_view, filtro)
    else:
        st.warning("No se encontró la columna PCAPTURA; no se puede aplicar el filtro.")

    # Quitamos columna auxiliar antes de mostrar/exportar
    if "_PCAPTURA_NUM" in df_view.columns:
        df_view = df_view.drop("_PCAPTURA_NUM")

    total_filtrado = df_view.height

    st.caption(f"Registros filtrados: **{total_filtrado:,}**")

    if total_filtrado == 0:
        st.info("No hay registros con los filtros seleccionados.")
        return

    # ======================================================
    # Límite de registros visibles
    # ======================================================
    col_limite, col_info = st.columns([1, 3])

    with col_limite:
        limite_opcion = st.selectbox(
            "Registros a mostrar",
            options=[500, 1000, 2000, 5000, "Todos"],
            index=1,
            key="captura_limite_registros",
        )

    df_display = limitar_registros(df_view, limite_opcion)

    with col_info:
        if limite_opcion != "Todos" and total_filtrado > int(limite_opcion):
            st.info(
                f"Mostrando {df_display.height:,} de {total_filtrado:,} registros filtrados. "
                "Para ver más, cambia el límite o usa la descarga."
            )

    # ======================================================
    # Convertir a Pandas solo lo visible
    # ======================================================
    pdf_display = df_display.to_pandas()

    # ======================================================
    # Mostrar tabla
    # ======================================================
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

    # ======================================================
    # Descarga optimizada
    # ======================================================
    st.markdown("---")

    with st.expander("⬇️ Descargar Excel", expanded=False):
        st.info(
            "Para mejorar el rendimiento, el Excel no se genera automáticamente. "
            "Activa la opción solo cuando necesites descargarlo."
        )

        preparar_excel = st.checkbox(
            "Preparar archivo Excel con todos los registros filtrados",
            value=False,
            key="captura_preparar_excel",
        )

        if preparar_excel:
            with st.spinner("Generando Excel..."):
                pdf_export = df_view.to_pandas()
                excel_bytes = to_excel(pdf_export)

            nombre = generar_nombre_archivo(
                administrador=administrador,
                plantel_usuario=plantel_usuario,
                plantel_filtro=plantel_filtro,
                filtro_captura=filtro,
            )

            st.download_button(
                label="⬇️ Descargar Excel",
                data=excel_bytes,
                file_name=f"{nombre}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="captura_download_excel",
            )