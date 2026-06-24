# views/indicadores_academicos_v2.py
import os
import re
import math
import smtplib
import unicodedata
from io import BytesIO
from html import escape
from datetime import datetime
from email.message import EmailMessage

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import streamlit as st


# =========================
# CONFIG
# =========================
LABEL_FONT_SIZE_ADMIN = 15
LABEL_FONT_SIZE_PLANTEL = 15
Y_AXIS_PADDING_MULT = 1.35

PERM_SEND_EMAIL_CODE = "SEND_EMAIL_INDICADORES"
EMAIL_META_MAX_NO_COMP_PCT = 10.0
EMAIL_META_SEMANA_OBJETIVO = 18

EXCEL_PATH = "assets/Datos1.xlsx"
CACHE_DIR = "assets/cache_indicadores"
MAX_PREVIEW_ROWS = 500  # Compatibilidad: ya no se usa para recortar la tabla.
DEFAULT_TABLE_HEIGHT = 520
USE_PLANTEL_DETAIL_CACHE = os.getenv("USE_PLANTEL_DETAIL_CACHE", "false").lower() == "true"

USE_FAST_CACHE = os.getenv("USE_FAST_CACHE", "true").lower() == "true"

REPROBACION_COLS = [
    "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "MODULO",
    "DOCENTE", "grado", "cvegrupo", "pEspecifico", "pAlcanzado", "pRelativo"
]

MATRICULA_COLS = ["Plantel", "matriculaTotal"]
METRICAS_ORDEN = ["pEspecifico", "pAlcanzado", "pRelativo"]

# Categorías usadas para identificar estudiantes por cantidad de módulos NO competentes.
# Se mantiene el mismo criterio del resumen: 1, 2, 3... 10 y 11 o más.
CATEGORIAS_MODULOS_NC = [str(i) for i in range(1, 11)] + ["11 o más"]


# =========================
# Seguimiento académico de estudiantes NO competentes
# =========================
# Este archivo CSV permite iniciar sin base de datos.
# Si después migras a BD, estas funciones pueden cambiarse por consultas SQL.
SEGUIMIENTO_NC_PATH = os.getenv(
    "SEGUIMIENTO_NC_PATH",
    "assets/seguimiento_no_competentes.csv"
)

CAUSAS_NO_COMPETENCIA = [
    "",
    "Ausentismo",
    "Económica",
    "Emocional",
    "Académica",
]

# Responsables solicitados para captura directa en tabla.
# Se guardan en el campo responsable_nombre para mantener compatibilidad con el CSV existente.
RESPONSABLES_SEGUIMIENTO = [
    "",
    "JPFT",
    "FPSE",
    "TTA",
    "OE",
    "TB",
]

# Se conserva este nombre porque algunas funciones previas lo usan.
# En esta versión se iguala al catálogo de responsables solicitado.
FUNCIONES_SEGUIMIENTO = RESPONSABLES_SEGUIMIENTO

ESTADOS_SEGUIMIENTO = [
    "Sin seguimiento",
    "En proceso",
    "Recuperado",
]



# =========================
# Helpers base
# =========================
def slug(v):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(v).strip())


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _read_excel(sheet_name, usecols=None):
    return pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, usecols=usecols)


def _read_fast_or_excel(parquet_name, sheet_name, usecols=None):
    parquet_path = _cache_path(parquet_name)

    if USE_FAST_CACHE and os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)

    return _read_excel(sheet_name, usecols=usecols)


def _norm_txt(x):
    s = "" if x is None else str(x)
    s = s.strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def _find_col_like(df, candidates):
    cols = list(df.columns)
    low = [_norm_txt(c) for c in cols]
    for cand in candidates:
        c = _norm_txt(cand)
        for orig, lo in zip(cols, low):
            if lo == c or c in lo:
                return orig
    return None


def _wk_key(v):
    s = str(v).strip()
    nums = re.findall(r"\d+", s)
    return int(nums[0]) if nums else None


def _sem_key(v):
    if v is None:
        return None

    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    if isinstance(v, int):
        return int(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)

    s_norm = _norm_txt(v)

    if "prim" in s_norm:
        return 2
    if "terc" in s_norm:
        return 4
    if "quint" in s_norm:
        return 6

    nums = re.findall(r"\d+", str(v))
    return int(nums[0]) if nums else None


def asegurar_metricas(df):
    for col in METRICAS_ORDEN:
        if col not in df.columns:
            df[col] = pd.NA
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def agregar_fila_total(tabla):
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


def _preparar_columnas_detalle(df):
    df = asegurar_metricas(df.copy())

    columnas_base = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA",
        "MODULO", "DOCENTE", "grado", "cvegrupo"
    ]
    orden = [c for c in columnas_base if c in df.columns] + [c for c in METRICAS_ORDEN if c in df.columns]

    if orden:
        return df[orden]

    return df


def mostrar_dataframe_preview(df, max_rows=None, height=DEFAULT_TABLE_HEIGHT):
    """
    Muestra el DataFrame completo.

    Antes se usaba df.head(MAX_PREVIEW_ROWS), lo que provocaba que si un plantel
    tenía más de 500 registros solo se vieran los primeros 500. Se mantiene el
    nombre de la función para no romper llamadas existentes, pero ya no recorta.
    """
    total = len(df) if df is not None else 0
    st.caption(f"Mostrando {total:,} registro(s). La tabla no está recortada; usa el scroll para revisar todos los registros.")
    st.dataframe(df, use_container_width=True, height=height)


# =========================
# Carga de datos
# =========================
@st.cache_data(show_spinner=False)
def cargar_reprobacion():
    df = _read_fast_or_excel("reprobacion.parquet", "Reprobacion", usecols=None)
    return asegurar_metricas(df)


@st.cache_data(show_spinner=False)
def cargar_matricula():
    try:
        df = _read_fast_or_excel("matricula.parquet", "Matricula", usecols=MATRICULA_COLS)
    except Exception:
        df = _read_fast_or_excel("matricula.parquet", "Matricula", usecols=None)

    if "matriculaTotal" in df.columns:
        df["matriculaTotal"] = pd.to_numeric(df["matriculaTotal"], errors="coerce").fillna(0)

    return df


@st.cache_data(show_spinner=False)
def cargar_resumen():
    parquet_name = "resumen.parquet"
    parquet_path = _cache_path(parquet_name)

    if USE_FAST_CACHE and os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)

    df_reprobacion = cargar_reprobacion()
    df_matricula = cargar_matricula()

    if "Plantel" not in df_reprobacion.columns or "matricula" not in df_reprobacion.columns:
        raise ValueError("La hoja Reprobacion debe contener al menos las columnas 'Plantel' y 'matricula'.")

    df_modulos = (
        df_reprobacion
        .groupby(["Plantel", "matricula"])
        .size()
        .reset_index(name="modulos_nc")
    )

    df_modulos["categoria"] = df_modulos["modulos_nc"].apply(lambda x: str(x) if x <= 10 else "11 o más")

    resumen = (
        df_modulos
        .groupby(["Plantel", "categoria"])
        .size()
        .reset_index(name="total_estudiantes")
    )

    tabla = (
        resumen
        .pivot(index="Plantel", columns="categoria", values="total_estudiantes")
        .fillna(0)
        .astype(int)
        .reset_index()
    )

    if "Plantel" in df_matricula.columns:
        tabla = tabla.merge(df_matricula, on="Plantel", how="left")

    if "matriculaTotal" not in tabla.columns:
        tabla["matriculaTotal"] = 0

    tabla["matriculaTotal"] = pd.to_numeric(tabla["matriculaTotal"], errors="coerce").fillna(0)

    columnas_excluir = {"Plantel", "matriculaTotal"}
    columnas_nc = [c for c in tabla.columns if c not in columnas_excluir]

    tabla["Total estudiantes no competentes"] = tabla[columnas_nc].sum(axis=1)
    tabla["% Estudiantes no competentes"] = (
        (tabla["Total estudiantes no competentes"] / tabla["matriculaTotal"]) * 100
    ).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)

    return tabla


@st.cache_data(show_spinner=False)
def cargar_seguimiento():
    parquet_path = _cache_path("seguimiento.parquet")

    if USE_FAST_CACHE and os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)

    last_error = None
    for sheet_name in ("Seguimiento", "SEGUIMIENTO", "seguimiento"):
        try:
            return _read_excel(sheet_name, usecols=None)
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error

    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def cargar_datos_sheet():
    try:
        return _read_fast_or_excel("datos.parquet", "Datos", usecols=None)
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def cargar_planteles_sheet():
    return _read_fast_or_excel("planteles.parquet", "Planteles", usecols=None)


@st.cache_data(show_spinner=False)
def cargar_permisos_sheet():
    return _read_fast_or_excel("permisos.parquet", "Permisos", usecols=None)


@st.cache_data(show_spinner=False)
def obtener_detalle_no_competentes(plantel_sel):
    """
    Devuelve el detalle completo de NO competentes para el plantel seleccionado.

    Importante:
    - No se recorta a 500 filas.
    - Por defecto NO se usa el parquet parcial detalle_por_plantel, porque si ese
      cache está viejo o fue generado incompleto puede provocar que la tabla y el
      Excel bajen menos registros que el total real.
    - Si necesitas volver a activar ese cache por rendimiento, define:
      USE_PLANTEL_DETAIL_CACHE=true
    """
    if USE_FAST_CACHE and USE_PLANTEL_DETAIL_CACHE and plantel_sel != "Todos":
        path = _cache_path(f"detalle_por_plantel/{slug(plantel_sel)}.parquet")
        if os.path.exists(path):
            df = pd.read_parquet(path)
            return _preparar_columnas_detalle(df)

    df = cargar_reprobacion()
    if plantel_sel != "Todos":
        df = df[df["Plantel"] == plantel_sel].copy()

    return _preparar_columnas_detalle(df)


@st.cache_data(show_spinner=False)
def obtener_sin_registro_calificaciones(plantel_sel):
    df = obtener_detalle_no_competentes(plantel_sel)
    if "pEspecifico" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["pEspecifico"] == 0].copy()


# =========================
# Identificación/impresión por cantidad de módulos NO competentes
# =========================
def _categoria_modulos_nc(total_modulos):
    try:
        n = int(total_modulos)
    except Exception:
        n = 0

    if n <= 0:
        return "0"
    return str(n) if n <= 10 else "11 o más"


def _orden_categoria_modulos_nc(categoria):
    texto = _norm_txt(categoria)
    nums = re.findall(r"\d+", texto)
    if nums:
        n = int(nums[0])
        return n if n <= 10 else 11
    if "mas" in texto or "+" in texto:
        return 11
    return 999


def _join_unique_values(series):
    values = []
    for value in series.dropna().tolist():
        text = str(value).strip()
        if not text or text.lower() in ("nan", "none", "null"):
            continue
        values.append(text)
    values = list(dict.fromkeys(values))
    return " | ".join(values)


def agregar_conteo_modulos_no_competentes(df):
    """
    Agrega a cada registro académico dos columnas:
    - modulos_nc: cantidad de módulos/registros NO competentes del estudiante.
    - categoria_modulos_nc: 1, 2, 3... 10, 11 o más.

    Se agrupa por Plantel + matrícula cuando ambas columnas existen. Esto permite
    que el usuario identifique todos los datos completos de los estudiantes que
    tienen 1, 2, 7, 11 o más módulos NO competentes, sin perder el detalle original.
    """
    if df is None or getattr(df, "empty", True):
        base_cols = list(df.columns) if df is not None else []
        return pd.DataFrame(columns=base_cols + ["modulos_nc", "categoria_modulos_nc"])

    d = df.copy()
    # Si el DataFrame ya venía filtrado/con conteo previo, se recalcula para evitar
    # columnas duplicadas con sufijos _x/_y al hacer merge.
    d = d.drop(columns=["modulos_nc", "categoria_modulos_nc"], errors="ignore")

    if "matricula" not in d.columns:
        d["modulos_nc"] = 1
        d["categoria_modulos_nc"] = "1"
        return d

    group_cols = ["matricula"]
    if "Plantel" in d.columns:
        group_cols = ["Plantel", "matricula"]

    conteo = (
        d.groupby(group_cols, dropna=False)
        .size()
        .reset_index(name="modulos_nc")
    )
    conteo["modulos_nc"] = pd.to_numeric(conteo["modulos_nc"], errors="coerce").fillna(0).astype(int)
    conteo["categoria_modulos_nc"] = conteo["modulos_nc"].apply(_categoria_modulos_nc)

    d = d.merge(conteo, on=group_cols, how="left")
    d["modulos_nc"] = pd.to_numeric(d["modulos_nc"], errors="coerce").fillna(0).astype(int)
    d["categoria_modulos_nc"] = d["categoria_modulos_nc"].fillna(d["modulos_nc"].apply(_categoria_modulos_nc))

    sort_cols = [c for c in ["Plantel", "modulos_nc", "ESTUDIANTE", "matricula", "MODULO"] if c in d.columns]
    if sort_cols:
        ascending = [True] * len(sort_cols)
        if "modulos_nc" in sort_cols:
            ascending[sort_cols.index("modulos_nc")] = False
        d = d.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)

    return d


def filtrar_detalle_por_categorias_modulos(df, categorias):
    d = agregar_conteo_modulos_no_competentes(df)
    if d.empty or not categorias:
        return d.iloc[0:0].copy()

    categorias_norm = {str(c).strip() for c in categorias}
    return d[d["categoria_modulos_nc"].astype(str).isin(categorias_norm)].copy()


def construir_resumen_estudiantes_por_modulos(df_detalle):
    """
    Convierte el detalle académico a una vista de 1 fila por estudiante para impresión.
    Incluye módulos y docentes concatenados para que el usuario pueda identificar
    claramente a quién debe dar atención según la cantidad de módulos NO competentes.
    """
    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame()

    d = agregar_conteo_modulos_no_competentes(df_detalle)
    if d.empty:
        return pd.DataFrame()

    if "matricula" not in d.columns:
        return d.copy()

    group_cols = ["matricula"]
    if "Plantel" in d.columns:
        group_cols = ["Plantel", "matricula"]

    agg = {}
    for col in ["ESTUDIANTE", "CARRERA", "grado", "cvegrupo", "modulos_nc", "categoria_modulos_nc"]:
        if col in d.columns:
            agg[col] = "first"

    if "MODULO" in d.columns:
        agg["MODULO"] = _join_unique_values
    if "DOCENTE" in d.columns:
        agg["DOCENTE"] = _join_unique_values

    for col in METRICAS_ORDEN:
        if col in d.columns:
            agg[col] = "min"

    resumen = d.groupby(group_cols, dropna=False).agg(agg).reset_index()

    rename_map = {
        "MODULO": "MODULOS_NO_COMPETENTES",
        "DOCENTE": "DOCENTES_RELACIONADOS",
        "pEspecifico": "pEspecifico_min",
        "pAlcanzado": "pAlcanzado_min",
        "pRelativo": "pRelativo_min",
    }
    resumen = resumen.rename(columns=rename_map)

    orden = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "grado", "cvegrupo",
        "modulos_nc", "categoria_modulos_nc", "MODULOS_NO_COMPETENTES", "DOCENTES_RELACIONADOS",
        "pEspecifico_min", "pAlcanzado_min", "pRelativo_min"
    ]
    orden = [c for c in orden if c in resumen.columns]
    resto = [c for c in resumen.columns if c not in orden]
    resumen = resumen[orden + resto]

    sort_cols = [c for c in ["Plantel", "modulos_nc", "ESTUDIANTE", "matricula"] if c in resumen.columns]
    if sort_cols:
        ascending = [True] * len(sort_cols)
        if "modulos_nc" in sort_cols:
            ascending[sort_cols.index("modulos_nc")] = False
        resumen = resumen.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)

    return resumen


def construir_resumen_categorias_modulos(df_detalle):
    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame(columns=["Módulos NO competentes", "Estudiantes", "Registros académicos"])

    d = agregar_conteo_modulos_no_competentes(df_detalle)
    if d.empty or "categoria_modulos_nc" not in d.columns:
        return pd.DataFrame(columns=["Módulos NO competentes", "Estudiantes", "Registros académicos"])

    if "matricula" in d.columns:
        resumen = (
            d.groupby("categoria_modulos_nc", dropna=False)
            .agg(
                Estudiantes=("matricula", "nunique"),
                **{"Registros académicos": ("matricula", "size")}
            )
            .reset_index()
        )
    else:
        resumen = (
            d.groupby("categoria_modulos_nc", dropna=False)
            .size()
            .reset_index(name="Registros académicos")
        )
        resumen["Estudiantes"] = resumen["Registros académicos"]

    resumen = resumen.rename(columns={"categoria_modulos_nc": "Módulos NO competentes"})
    resumen["__orden__"] = resumen["Módulos NO competentes"].apply(_orden_categoria_modulos_nc)
    resumen = resumen.sort_values("__orden__").drop(columns=["__orden__"]).reset_index(drop=True)
    return resumen


def _label_categorias_modulos(categorias):
    if not categorias:
        return "Sin selección"
    cats = sorted([str(c) for c in categorias], key=_orden_categoria_modulos_nc)
    return ", ".join(cats)



# =========================
# Seguimiento académico de estudiantes NO competentes
# =========================
def _seguimiento_nc_columns():
    return [
        "seguimiento_id",
        "corte",
        "plantel",
        "matricula",
        "estudiante",
        "carrera",
        "grado",
        "grupo",
        "modulos_nc",
        "categoria_modulos_nc",
        "modulos_no_competentes",
        "docentes_relacionados",
        "causa_principal",
        "causa_detalle",
        "responsable_nombre",
        "responsable_funcion",
        "estado",
        "fecha_inicio",
        "fecha_cierre",
        "observaciones",
        "usuario_captura",
        "usuario_actualizacion",
        "created_at",
        "updated_at",
    ]


def _asegurar_archivo_seguimiento_nc():
    folder = os.path.dirname(SEGUIMIENTO_NC_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists(SEGUIMIENTO_NC_PATH):
        pd.DataFrame(columns=_seguimiento_nc_columns()).to_csv(
            SEGUIMIENTO_NC_PATH,
            index=False,
            encoding="utf-8-sig",
        )


def cargar_seguimiento_no_competentes():
    """
    Lee el seguimiento capturado de estudiantes NO competentes.

    Se usa CSV para facilitar la implementación inmediata en Streamlit.
    En producción conviene migrarlo a una tabla de base de datos para manejo multiusuario.
    """
    _asegurar_archivo_seguimiento_nc()

    try:
        df = pd.read_csv(SEGUIMIENTO_NC_PATH, dtype=str, keep_default_na=False)
    except Exception:
        df = pd.DataFrame(columns=_seguimiento_nc_columns())

    for col in _seguimiento_nc_columns():
        if col not in df.columns:
            df[col] = ""

    return df[_seguimiento_nc_columns()].copy()


def guardar_seguimiento_no_competentes(df):
    _asegurar_archivo_seguimiento_nc()
    out = df.copy()

    for col in _seguimiento_nc_columns():
        if col not in out.columns:
            out[col] = ""

    out = out[_seguimiento_nc_columns()].fillna("")
    out.to_csv(SEGUIMIENTO_NC_PATH, index=False, encoding="utf-8-sig")


def reiniciar_seguimiento_academico(crear_respaldo=True):
    """
    Limpia el archivo CSV de Seguimiento Académico sin tocar el Excel base.

    Reglas:
    - Solo borra registros capturados del seguimiento.
    - Conserva la estructura/encabezados del CSV.
    - Opcionalmente crea un respaldo antes de limpiar.
    """
    _asegurar_archivo_seguimiento_nc()

    backup_path = None
    if crear_respaldo and os.path.exists(SEGUIMIENTO_NC_PATH):
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.dirname(SEGUIMIENTO_NC_PATH) or "."
        backup_path = os.path.join(
            base_dir,
            f"seguimiento_no_competentes_backup_{fecha}.csv"
        )

        try:
            df_actual = pd.read_csv(SEGUIMIENTO_NC_PATH, dtype=str, keep_default_na=False)
        except Exception:
            df_actual = pd.DataFrame(columns=_seguimiento_nc_columns())

        for col in _seguimiento_nc_columns():
            if col not in df_actual.columns:
                df_actual[col] = ""

        df_actual[_seguimiento_nc_columns()].fillna("").to_csv(
            backup_path,
            index=False,
            encoding="utf-8-sig",
        )

    df_vacio = pd.DataFrame(columns=_seguimiento_nc_columns())
    df_vacio.to_csv(SEGUIMIENTO_NC_PATH, index=False, encoding="utf-8-sig")

    try:
        st.cache_data.clear()
    except Exception:
        pass

    return backup_path


def render_admin_restablecer_seguimiento_academico():
    """
    Panel administrativo para limpiar los datos de prueba del Seguimiento Académico.
    Debe mostrarse únicamente a usuarios administradores.
    """
    st.markdown("---")

    with st.expander("⚙️ Administración del Seguimiento Académico", expanded=False):
        st.warning(
            "Esta opción limpia todos los registros capturados en el Seguimiento Académico. "
            "No borra los datos académicos originales del archivo Excel; solo limpia el archivo CSV de seguimiento."
        )

        st.caption(f"Archivo que se limpiará: `{SEGUIMIENTO_NC_PATH}`")

        try:
            df_actual = cargar_seguimiento_no_competentes()
            total_registros = len(df_actual)
        except Exception:
            total_registros = 0

        st.info(f"Registros actuales en Seguimiento Académico: **{total_registros:,}**")

        col_a, col_b = st.columns(2)
        with col_a:
            crear_respaldo = st.checkbox(
                "Crear respaldo antes de limpiar",
                value=True,
                key="crear_respaldo_limpieza_seguimiento_academico",
            )
        with col_b:
            confirmar_limpieza = st.checkbox(
                "Confirmo que deseo limpiar el seguimiento",
                value=False,
                key="confirmar_limpieza_seguimiento_academico",
            )

        st.caption(
            "Úsalo cuando termines pruebas y quieras dejar limpio el Seguimiento Académico para producción "
            "o para una nueva ronda de captura."
        )

        if st.button(
            "🧹 Restablecer Seguimiento Académico",
            key="btn_restablecer_seguimiento_academico",
            type="secondary",
        ):
            if not confirmar_limpieza:
                st.error("Primero marca la casilla de confirmación para evitar borrados accidentales.")
                return

            backup_path = reiniciar_seguimiento_academico(crear_respaldo=crear_respaldo)

            if backup_path:
                st.success(
                    "Seguimiento Académico restablecido correctamente. "
                    f"Se creó un respaldo en: `{backup_path}`"
                )
            else:
                st.success("Seguimiento Académico restablecido correctamente.")

            st.rerun()


def _obtener_corte_actual_indicadores():
    """
    Devuelve una etiqueta de corte para no sobrescribir seguimientos de cortes distintos.
    Si existe hoja SEGUIMIENTO con semana detectable, usa la semana más reciente.
    """
    try:
        etiqueta = obtener_etiqueta_semana_mas_reciente(cargar_seguimiento())
        if etiqueta:
            return str(etiqueta).strip()
    except Exception:
        pass
    return "Corte actual"


def _valor_seguro_fila(row, col, default=""):
    try:
        if col not in row.index:
            return default
        value = row.get(col, default)
        if pd.isna(value):
            return default
        text = str(value).strip()
        if text.lower() in ("nan", "none", "null"):
            return default
        return text
    except Exception:
        return default


def _to_int_safe(value, default=0):
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def normalizar_estado_seguimiento(valor):
    """
    Normaliza cualquier valor histórico o capturado al catálogo vigente:
    - Sin seguimiento
    - En proceso
    - Recuperado
    """
    texto = str(valor or "").strip()
    texto_norm = _norm_txt(texto)

    if texto == "Recuperado" or ("recuperado" in texto_norm and "no recuperado" not in texto_norm):
        return "Recuperado"

    if texto in ("En proceso", "Canalizado", "En recuperación"):
        return "En proceso"

    # Estados históricos que significaban atención abierta o no cerrada como recuperada.
    if texto in ("Finalizado no recuperado", "No localizado"):
        return "En proceso"

    return "Sin seguimiento"



def normalizar_fecha_seguimiento(valor):
    """
    Normaliza cualquier valor de fecha capturado en el editor a formato YYYY-MM-DD.
    Acepta strings, pandas Timestamp, datetime/date o celdas vacías.
    """
    if valor is None:
        return ""

    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass

    texto = str(valor).strip()
    if not texto or texto.lower() in ("nan", "nat", "none", "null"):
        return ""

    try:
        fecha = pd.to_datetime(texto, errors="coerce")
        if pd.isna(fecha):
            return ""
        return fecha.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _fecha_para_editor(valor):
    """
    Convierte una fecha guardada como texto a objeto date para que st.data_editor
    muestre un selector de fecha. Si está vacía, devuelve None.
    """
    fecha_txt = normalizar_fecha_seguimiento(valor)
    if not fecha_txt:
        return None
    try:
        return datetime.strptime(fecha_txt, "%Y-%m-%d").date()
    except Exception:
        return None


def fecha_cierre_por_estado_seguimiento(estado, fecha_cierre_capturada="", hoy=None):
    """
    Regla de negocio:
    - Si el estado es Recuperado, se permite capturar Fecha cierre.
    - Si Estado es Recuperado y Fecha cierre viene vacía, se asigna la fecha actual.
    - Si el estado es En proceso o Sin seguimiento, se limpia Fecha cierre.
    """
    hoy = hoy or datetime.now().strftime("%Y-%m-%d")
    estado_norm = normalizar_estado_seguimiento(estado)
    fecha_capturada = normalizar_fecha_seguimiento(fecha_cierre_capturada)

    if estado_norm == "Recuperado":
        return fecha_capturada or hoy

    return ""


def _aplicar_cambios_data_editor_desde_session_state(df, editor_key):
    """
    Aplica manualmente los cambios guardados por st.data_editor en st.session_state.

    Esto corrige el caso en el que el usuario cambia Estado a 'Recuperado'
    y la sección de Fecha cierre no se actualiza inmediatamente en la misma corrida.
    Streamlit guarda los cambios del editor en una estructura interna; esta función
    los refleja sobre el DataFrame antes de calcular qué estudiantes deben mostrar
    el selector de Fecha cierre.
    """
    if df is None or getattr(df, "empty", True):
        return df

    out = df.copy()
    state = st.session_state.get(editor_key, {})
    if not isinstance(state, dict):
        return out

    # Formato actual de Streamlit: {'edited_rows': {row_index: {col: value}}}
    edited_rows = state.get("edited_rows", {}) or {}
    if isinstance(edited_rows, dict):
        for row_idx, changes in edited_rows.items():
            try:
                idx = int(row_idx)
            except Exception:
                continue
            if idx < 0 or idx >= len(out) or not isinstance(changes, dict):
                continue
            for col, value in changes.items():
                if col in out.columns:
                    out.iat[idx, out.columns.get_loc(col)] = value

    # Formato usado por algunas versiones anteriores: {'edited_cells': {'0:Estado': 'Recuperado'}}
    edited_cells = state.get("edited_cells", {}) or {}
    if isinstance(edited_cells, dict):
        for cell_key, value in edited_cells.items():
            try:
                row_part, col = str(cell_key).split(":", 1)
                idx = int(row_part)
            except Exception:
                continue
            if idx < 0 or idx >= len(out) or col not in out.columns:
                continue
            out.iat[idx, out.columns.get_loc(col)] = value

    return out


def _crear_id_seguimiento(plantel, matricula, corte):
    base = f"{plantel}|{matricula}|{corte}"
    base = unicodedata.normalize("NFKD", base)
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_").lower()
    return base or f"seguimiento_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _prioridad_por_modulos(modulos_nc):
    n = _to_int_safe(modulos_nc)
    if n >= 11:
        return "Alta prioridad"
    if n >= 3:
        return "Atención prioritaria"
    if n in (1, 2):
        return "Recuperación inmediata"
    return "Sin prioridad"


def _causa_sugerida_estudiante(row_estudiante, df_detalle_estudiante):
    """
    Sugiere causa con base en el indicador existente.
    Si cualquier registro tiene pEspecifico = 0, se sugiere 'Sin evaluación registrada'.
    """
    if df_detalle_estudiante is not None and not df_detalle_estudiante.empty and "pEspecifico" in df_detalle_estudiante.columns:
        valores = pd.to_numeric(df_detalle_estudiante["pEspecifico"], errors="coerce").fillna(-1)
        if (valores == 0).any():
            return "Académica"

    for col in ("pEspecifico_min", "pEspecifico"):
        if col in row_estudiante.index:
            try:
                if float(row_estudiante.get(col)) == 0:
                    return "Académica"
            except Exception:
                pass

    return ""


def _filtrar_detalle_estudiante(df_detalle, plantel, matricula):
    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame()

    d = df_detalle.copy()
    if "matricula" in d.columns:
        d = d[d["matricula"].astype(str).str.strip() == str(matricula).strip()].copy()
    if "Plantel" in d.columns and plantel:
        d = d[d["Plantel"].astype(str).str.strip() == str(plantel).strip()].copy()
    return d


def _obtener_registro_seguimiento(seguimiento_id):
    df_seg = cargar_seguimiento_no_competentes()
    if df_seg.empty or "seguimiento_id" not in df_seg.columns:
        return None
    match = df_seg[df_seg["seguimiento_id"].astype(str) == str(seguimiento_id)]
    if match.empty:
        return None
    return match.iloc[-1]


def construir_tabla_seguimiento_estudiantes(df_resumen_estudiantes, corte_actual):
    """
    Une el resumen por estudiante con el CSV de seguimiento para mostrar estado actual.
    """
    if df_resumen_estudiantes is None or getattr(df_resumen_estudiantes, "empty", True):
        return pd.DataFrame()

    base = df_resumen_estudiantes.copy()

    for col in ["Plantel", "matricula", "ESTUDIANTE", "CARRERA", "grado", "cvegrupo", "modulos_nc", "categoria_modulos_nc"]:
        if col not in base.columns:
            base[col] = ""

    base["seguimiento_id"] = base.apply(
        lambda r: _crear_id_seguimiento(
            _valor_seguro_fila(r, "Plantel"),
            _valor_seguro_fila(r, "matricula"),
            corte_actual,
        ),
        axis=1,
    )

    df_seg = cargar_seguimiento_no_competentes()
    if not df_seg.empty:
        cols_merge = [
            "seguimiento_id", "causa_principal", "responsable_nombre",
            "responsable_funcion", "estado", "fecha_inicio",
            "fecha_cierre", "observaciones", "updated_at"
        ]
        df_seg_latest = df_seg.sort_values("updated_at").drop_duplicates("seguimiento_id", keep="last")
        base = base.merge(df_seg_latest[cols_merge], on="seguimiento_id", how="left")
    else:
        for col in ["causa_principal", "responsable_nombre", "responsable_funcion", "estado", "fecha_inicio", "fecha_cierre", "observaciones", "updated_at"]:
            base[col] = ""

    base["estado"] = base["estado"].fillna("").apply(normalizar_estado_seguimiento)
    base["prioridad"] = base["modulos_nc"].apply(_prioridad_por_modulos)

    rename = {
        "Plantel": "Plantel",
        "ESTUDIANTE": "Estudiante",
        "matricula": "Matrícula",
        "CARRERA": "Carrera",
        "grado": "Grado",
        "cvegrupo": "Grupo",
        "modulos_nc": "Módulos NC",
        "categoria_modulos_nc": "Categoría",
        "MODULOS_NO_COMPETENTES": "Módulos no competentes",
        "DOCENTES_RELACIONADOS": "Docentes relacionados",
        "causa_principal": "Causa",
        "responsable_nombre": "Responsable",
        "responsable_funcion": "Función",
        "estado": "Estado",
        "prioridad": "Prioridad",
        "fecha_inicio": "Fecha inicio",
        "fecha_cierre": "Fecha cierre",
        "observaciones": "Observaciones",
        "updated_at": "Última actualización",
    }

    base = base.rename(columns=rename)

    ordered = [
        "seguimiento_id",
        "Plantel", "Estudiante", "Matrícula", "Carrera", "Grado", "Grupo",
        "Módulos NC", "Categoría", "Prioridad", "Estado",
        "Causa", "Responsable", "Función", "Fecha inicio", "Fecha cierre", "Observaciones",
        "Módulos no competentes", "Docentes relacionados", "Última actualización"
    ]
    ordered = [c for c in ordered if c in base.columns]
    rest = [c for c in base.columns if c not in ordered]
    return base[ordered + rest]


def guardar_registro_seguimiento_estudiante(row_estudiante, df_detalle_estudiante, datos_form, corte_actual):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoy = datetime.now().strftime("%Y-%m-%d")
    usuario = _get_username_from_session() or "usuario_no_identificado"

    plantel = _valor_seguro_fila(row_estudiante, "Plantel") or _valor_seguro_fila(row_estudiante, "Plantel_x")
    matricula = _valor_seguro_fila(row_estudiante, "Matrícula") or _valor_seguro_fila(row_estudiante, "matricula")
    estudiante = _valor_seguro_fila(row_estudiante, "Estudiante") or _valor_seguro_fila(row_estudiante, "ESTUDIANTE")
    carrera = _valor_seguro_fila(row_estudiante, "Carrera") or _valor_seguro_fila(row_estudiante, "CARRERA")
    grado = _valor_seguro_fila(row_estudiante, "Grado") or _valor_seguro_fila(row_estudiante, "grado")
    grupo = _valor_seguro_fila(row_estudiante, "Grupo") or _valor_seguro_fila(row_estudiante, "cvegrupo")
    modulos_nc = _valor_seguro_fila(row_estudiante, "Módulos NC") or _valor_seguro_fila(row_estudiante, "modulos_nc")
    categoria = _valor_seguro_fila(row_estudiante, "Categoría") or _valor_seguro_fila(row_estudiante, "categoria_modulos_nc")
    modulos = _valor_seguro_fila(row_estudiante, "Módulos no competentes") or _valor_seguro_fila(row_estudiante, "MODULOS_NO_COMPETENTES")
    docentes = _valor_seguro_fila(row_estudiante, "Docentes relacionados") or _valor_seguro_fila(row_estudiante, "DOCENTES_RELACIONADOS")

    seguimiento_id = _valor_seguro_fila(row_estudiante, "seguimiento_id") or _crear_id_seguimiento(plantel, matricula, corte_actual)

    df_seg = cargar_seguimiento_no_competentes()
    previo = _obtener_registro_seguimiento(seguimiento_id)

    estado = normalizar_estado_seguimiento(datos_form.get("estado", "Sin seguimiento"))
    fecha_cierre = fecha_cierre_por_estado_seguimiento(estado, datos_form.get("fecha_cierre", ""), hoy)

    nuevo = {
        "seguimiento_id": seguimiento_id,
        "corte": corte_actual,
        "plantel": plantel,
        "matricula": matricula,
        "estudiante": estudiante,
        "carrera": carrera,
        "grado": grado,
        "grupo": grupo,
        "modulos_nc": str(modulos_nc),
        "categoria_modulos_nc": str(categoria),
        "modulos_no_competentes": str(modulos),
        "docentes_relacionados": str(docentes),
        "causa_principal": datos_form.get("causa_principal", ""),
        "causa_detalle": datos_form.get("causa_detalle", ""),
        "responsable_nombre": datos_form.get("responsable_nombre", ""),
        "responsable_funcion": datos_form.get("responsable_funcion", ""),
        "estado": estado,
        "fecha_inicio": datos_form.get("fecha_inicio", hoy) or hoy,
        "fecha_cierre": fecha_cierre,
        "observaciones": datos_form.get("observaciones", ""),
        "usuario_captura": _valor_seguro_fila(previo, "usuario_captura", usuario) if previo is not None else usuario,
        "usuario_actualizacion": usuario,
        "created_at": _valor_seguro_fila(previo, "created_at", ahora) if previo is not None else ahora,
        "updated_at": ahora,
    }

    df_seg = df_seg[df_seg["seguimiento_id"].astype(str) != str(seguimiento_id)].copy()
    df_seg = pd.concat([df_seg, pd.DataFrame([nuevo])], ignore_index=True)
    guardar_seguimiento_no_competentes(df_seg)


def _validar_formulario_seguimiento(causa, causa_detalle, responsable, funcion, estado, observaciones):
    errores = []
    if not causa:
        errores.append("Selecciona la causa principal de no competencia.")
    if causa == "Otro" and not causa_detalle.strip():
        errores.append("Cuando la causa es 'Otro', debes escribir el detalle de la causa.")
    if not responsable.strip():
        errores.append("Escribe el nombre de la persona responsable del seguimiento.")
    if not funcion:
        errores.append("Selecciona el puesto o función de la persona responsable.")
    if not estado:
        errores.append("Selecciona el estado del seguimiento.")
    if estado == "Finalizado no recuperado" and not observaciones.strip():
        errores.append("Si finaliza como no recuperado, captura observaciones para explicar el motivo.")
    return errores


def render_formulario_seguimiento_estudiante(row_estudiante, df_detalle_estudiante, corte_actual, key_prefix):
    seguimiento_id = _valor_seguro_fila(row_estudiante, "seguimiento_id")
    previo = _obtener_registro_seguimiento(seguimiento_id)
    hoy = datetime.now().strftime("%Y-%m-%d")

    estudiante = _valor_seguro_fila(row_estudiante, "Estudiante")
    matricula = _valor_seguro_fila(row_estudiante, "Matrícula")
    plantel = _valor_seguro_fila(row_estudiante, "Plantel")
    modulos_nc = _valor_seguro_fila(row_estudiante, "Módulos NC")
    modulos = _valor_seguro_fila(row_estudiante, "Módulos no competentes")
    docentes = _valor_seguro_fila(row_estudiante, "Docentes relacionados")

    causa_sugerida = _causa_sugerida_estudiante(row_estudiante, df_detalle_estudiante)

    def _prev(col, default=""):
        if previo is None:
            return default
        return _valor_seguro_fila(previo, col, default)

    causa_default = _prev("causa_principal", causa_sugerida)
    if causa_default not in CAUSAS_NO_COMPETENCIA:
        causa_default = causa_sugerida if causa_sugerida in CAUSAS_NO_COMPETENCIA else CAUSAS_NO_COMPETENCIA[0]

    funcion_default = _prev("responsable_funcion", FUNCIONES_SEGUIMIENTO[0])
    if funcion_default not in FUNCIONES_SEGUIMIENTO:
        funcion_default = FUNCIONES_SEGUIMIENTO[0]

    estado_default = _prev("estado", "En proceso")
    if estado_default not in ESTADOS_SEGUIMIENTO:
        estado_default = "En proceso"

    st.markdown(f"**Estudiante:** {estudiante}")
    st.caption(
        f"Matrícula: **{matricula}** | Plantel: **{plantel}** | "
        f"Corte: **{corte_actual}** | Módulos NO competentes: **{modulos_nc}**"
    )

    with st.expander("Ver módulos y docentes relacionados", expanded=False):
        st.write("**Módulos:**", modulos or "Sin dato")
        st.write("**Docentes:**", docentes or "Sin dato")
        if df_detalle_estudiante is not None and not df_detalle_estudiante.empty:
            cols = [c for c in ["MODULO", "DOCENTE", "pEspecifico", "pAlcanzado", "pRelativo"] if c in df_detalle_estudiante.columns]
            if cols:
                st.dataframe(df_detalle_estudiante[cols], use_container_width=True, height=220)

    with st.form(f"{key_prefix}_form_seguimiento_{seguimiento_id}"):
        causa = st.selectbox(
            "Causa principal de no competencia",
            CAUSAS_NO_COMPETENCIA,
            index=CAUSAS_NO_COMPETENCIA.index(causa_default),
            key=f"{key_prefix}_{seguimiento_id}_causa",
        )
        causa_detalle = st.text_input(
            "Detalle de causa / subcausa",
            value=_prev("causa_detalle", ""),
            placeholder="Ejemplo: faltas recurrentes, no entregó proyecto final, cambio de grupo, etc.",
            key=f"{key_prefix}_{seguimiento_id}_causa_detalle",
        )

        col_resp, col_func = st.columns(2)
        with col_resp:
            responsable = st.text_input(
                "Persona responsable del seguimiento",
                value=_prev("responsable_nombre", ""),
                placeholder="Nombre de quien atiende o dará seguimiento",
                key=f"{key_prefix}_{seguimiento_id}_responsable",
            )
        with col_func:
            funcion = st.selectbox(
                "Puesto o función",
                FUNCIONES_SEGUIMIENTO,
                index=FUNCIONES_SEGUIMIENTO.index(funcion_default),
                key=f"{key_prefix}_{seguimiento_id}_funcion",
            )

        estado = st.selectbox(
            "Estado del seguimiento",
            ESTADOS_SEGUIMIENTO,
            index=ESTADOS_SEGUIMIENTO.index(estado_default),
            key=f"{key_prefix}_{seguimiento_id}_estado",
        )

        col_ini, col_cierre = st.columns(2)
        with col_ini:
            fecha_inicio = st.text_input(
                "Fecha de inicio",
                value=_prev("fecha_inicio", hoy) or hoy,
                help="Formato recomendado: AAAA-MM-DD",
                key=f"{key_prefix}_{seguimiento_id}_fecha_inicio",
            )
        with col_cierre:
            fecha_cierre = st.text_input(
                "Fecha de cierre",
                value=_prev("fecha_cierre", ""),
                help="Se puede dejar vacío si aún no finaliza.",
                key=f"{key_prefix}_{seguimiento_id}_fecha_cierre",
            )

        observaciones = st.text_area(
            "Observaciones / acciones realizadas",
            value=_prev("observaciones", ""),
            placeholder="Describe qué acción se tomó, acuerdos, pendientes, contacto con estudiante, tutorías, etc.",
            height=130,
            key=f"{key_prefix}_{seguimiento_id}_observaciones",
        )

        col_save, col_cancel = st.columns(2)
        guardar = col_save.form_submit_button("💾 Guardar seguimiento", type="primary")
        cancelar = col_cancel.form_submit_button("Cancelar")

    if cancelar:
        st.session_state[f"{key_prefix}_seguimiento_open"] = False
        st.rerun()

    if guardar:
        errores = _validar_formulario_seguimiento(
            causa, causa_detalle, responsable, funcion, estado, observaciones
        )
        if errores:
            for error in errores:
                st.error(error)
            return

        guardar_registro_seguimiento_estudiante(
            row_estudiante=row_estudiante,
            df_detalle_estudiante=df_detalle_estudiante,
            datos_form={
                "causa_principal": causa,
                "causa_detalle": causa_detalle,
                "responsable_nombre": responsable,
                "responsable_funcion": funcion,
                "estado": estado,
                "fecha_inicio": fecha_inicio,
                "fecha_cierre": fecha_cierre,
                "observaciones": observaciones,
            },
            corte_actual=corte_actual,
        )
        st.success("Seguimiento guardado correctamente.")
        st.session_state[f"{key_prefix}_seguimiento_open"] = False
        st.rerun()


def render_reporte_seguimiento_no_competentes(df_tabla_seguimiento, corte_actual, key_prefix):
    st.markdown("#### 📊 Reporte de seguimiento")

    if df_tabla_seguimiento is None or df_tabla_seguimiento.empty:
        st.info("No hay estudiantes para generar reporte.")
        return

    total = len(df_tabla_seguimiento)
    sin_seg = int((df_tabla_seguimiento["Estado"].astype(str) == "Sin seguimiento").sum()) if "Estado" in df_tabla_seguimiento.columns else 0
    en_proceso = int(df_tabla_seguimiento["Estado"].astype(str).isin(["En proceso", "Canalizado", "En recuperación"]).sum()) if "Estado" in df_tabla_seguimiento.columns else 0
    finalizados = int((df_tabla_seguimiento["Estado"].astype(str) == "Recuperado").sum()) if "Estado" in df_tabla_seguimiento.columns else 0

    cols = st.columns(4)
    cols[0].metric("Estudiantes filtrados", f"{total:,}")
    cols[1].metric("Sin seguimiento", f"{sin_seg:,}")
    cols[2].metric("En atención", f"{en_proceso:,}")
    cols[3].metric("Recuperados", f"{finalizados:,}")

    tab_estado, tab_causa, tab_responsable, tab_observaciones = st.tabs(["Por estado", "Por causa", "Por responsable", "Con observaciones"])

    with tab_estado:
        if "Estado" in df_tabla_seguimiento.columns:
            rep = df_tabla_seguimiento.groupby("Estado", dropna=False).size().reset_index(name="Estudiantes")
            st.dataframe(rep, use_container_width=True, hide_index=True)

    with tab_causa:
        if "Causa" in df_tabla_seguimiento.columns:
            tmp = df_tabla_seguimiento.copy()
            tmp["Causa"] = tmp["Causa"].fillna("").replace("", "Sin capturar")
            rep = tmp.groupby("Causa", dropna=False).size().reset_index(name="Estudiantes")
            st.dataframe(rep.sort_values("Estudiantes", ascending=False), use_container_width=True, hide_index=True)

    with tab_responsable:
        if "Responsable" in df_tabla_seguimiento.columns:
            tmp = df_tabla_seguimiento.copy()
            tmp["Responsable"] = tmp["Responsable"].fillna("").replace("", "Sin asignar")
            rep = tmp.groupby("Responsable", dropna=False).size().reset_index(name="Estudiantes")
            st.dataframe(rep.sort_values("Estudiantes", ascending=False), use_container_width=True, hide_index=True)

    with tab_observaciones:
        if "Observaciones" in df_tabla_seguimiento.columns:
            tmp = df_tabla_seguimiento.copy()
            tmp["Tiene observaciones"] = tmp["Observaciones"].fillna("").astype(str).str.strip().ne("").map({True: "Con observaciones", False: "Sin observaciones"})
            rep = tmp.groupby("Tiene observaciones", dropna=False).size().reset_index(name="Estudiantes")
            st.dataframe(rep, use_container_width=True, hide_index=True)

    csv = df_tabla_seguimiento.drop(columns=["seguimiento_id"], errors="ignore").to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Descargar reporte de seguimiento CSV",
        data=csv,
        file_name=f"reporte_seguimiento_no_competentes_{_safe_download_name(corte_actual)}.csv",
        mime="text/csv",
        key=f"{key_prefix}_download_reporte_seguimiento",
    )


def render_tab_seguimiento_no_competentes(df_resumen_estudiantes, df_detalle_filtrado, plantel_sel, categorias_label, key_prefix):
    st.caption(
        "Edita directamente las columnas **Causa**, **Responsable**, **Estado** y **Observaciones**. "
        "La **Fecha cierre** queda bloqueada en la tabla principal y solo se habilita abajo para estudiantes con **Estado = Recuperado**. "
        "La **Última actualización** se registra automáticamente al guardar y no se puede modificar manualmente."
    )

    corte_actual = _obtener_corte_actual_indicadores()
    df_tabla = construir_tabla_seguimiento_estudiantes(df_resumen_estudiantes, corte_actual)

    if df_tabla.empty:
        st.info("No hay estudiantes para seguimiento con los filtros actuales.")
        return

    st.markdown(
        f"**Corte:** {corte_actual} | **Plantel:** {plantel_sel} | "
        f"**Categoría(s):** {categorias_label}"
    )

    def _normalizar_causa_editor(valor):
        texto = str(valor or "").strip()
        return texto if texto in CAUSAS_NO_COMPETENCIA else ""

    def _normalizar_responsable_editor(valor):
        texto = str(valor or "").strip().upper()
        return texto if texto in RESPONSABLES_SEGUIMIENTO else ""

    def _normalizar_estado_editor(valor):
        return normalizar_estado_seguimiento(valor)

    cols_editor = [
        "seguimiento_id",
        "Plantel", "Estudiante", "Matrícula", "Carrera", "Grado", "Grupo",
        "Módulos NC", "Categoría", "Prioridad",
        "Causa", "Responsable", "Estado",
        "Fecha cierre", "Observaciones", "Última actualización",
    ]
    cols_editor = [c for c in cols_editor if c in df_tabla.columns]
    df_editor = df_tabla[cols_editor].copy()

    for col in ["Causa", "Responsable", "Estado", "Fecha cierre", "Observaciones", "Última actualización"]:
        if col not in df_editor.columns:
            df_editor[col] = ""

    df_editor["Causa"] = df_editor["Causa"].apply(_normalizar_causa_editor)
    df_editor["Responsable"] = df_editor["Responsable"].apply(_normalizar_responsable_editor)
    df_editor["Estado"] = df_editor["Estado"].apply(_normalizar_estado_editor)
    df_editor["Fecha cierre"] = df_editor["Fecha cierre"].apply(_fecha_para_editor)

    # Regla de negocio solicitada:
    # Fecha cierre NO se edita en la tabla principal. Solo se habilita en una tabla secundaria
    # cuando el Estado del estudiante sea Recuperado.
    disabled_cols = [
        c for c in df_editor.columns
        if c not in ["Causa", "Responsable", "Estado", "Observaciones"]
    ]

    editor_key_principal = f"{key_prefix}_editor_seguimiento_directo"

    def _marcar_cambio_editor_seguimiento():
        # Forzar que Streamlit registre el cambio y vuelva a calcular la sección de Fecha cierre.
        st.session_state[f"{editor_key_principal}_changed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    edited_df = st.data_editor(
        df_editor,
        use_container_width=True,
        height=500,
        hide_index=True,
        num_rows="fixed",
        disabled=disabled_cols,
        key=editor_key_principal,
        on_change=_marcar_cambio_editor_seguimiento,
        column_config={
            "seguimiento_id": None,
            "Causa": st.column_config.SelectboxColumn(
                "Causa",
                help="Selecciona la causa principal de no competencia.",
                options=CAUSAS_NO_COMPETENCIA,
                required=False,
            ),
            "Responsable": st.column_config.SelectboxColumn(
                "Responsable",
                help="Selecciona quién dará seguimiento: JPFT, FPSE, TTA, OE o TB.",
                options=RESPONSABLES_SEGUIMIENTO,
                required=False,
            ),
            "Estado": st.column_config.SelectboxColumn(
                "Estado",
                help="Estado actual del seguimiento del estudiante.",
                options=ESTADOS_SEGUIMIENTO,
                required=True,
            ),
            "Fecha cierre": st.column_config.DateColumn(
                "Fecha cierre",
                help="Campo bloqueado aquí. Solo se captura abajo cuando el Estado sea Recuperado.",
                format="YYYY-MM-DD",
                required=False,
            ),
            "Observaciones": st.column_config.TextColumn(
                "Observaciones",
                help="Captura comentarios, acuerdos, acciones realizadas o pendientes del seguimiento.",
                max_chars=500,
                required=False,
            ),
            "Módulos NC": st.column_config.NumberColumn("Módulos NC", format="%d"),
        },
    )

    # Corrección: aplicar cambios vivos del editor antes de calcular la sección de Fecha cierre.
    # Así, al cambiar Estado a Recuperado, el selector de Fecha cierre aparece inmediatamente abajo.
    edited_df = _aplicar_cambios_data_editor_desde_session_state(edited_df, editor_key_principal)

    st.caption(
        "Para capturar: haz clic en la celda de **Causa**, **Responsable**, **Estado** u **Observaciones**. "
        "La **Fecha cierre** se habilita únicamente en la sección inferior cuando el Estado sea **Recuperado**. "
        "La columna **Última actualización** se coloca automáticamente al guardar los cambios."
    )

    # Normalización del resultado del editor principal.
    edited_df = edited_df.copy()
    edited_df["Causa"] = edited_df["Causa"].apply(_normalizar_causa_editor)
    edited_df["Responsable"] = edited_df["Responsable"].apply(_normalizar_responsable_editor)
    edited_df["Estado"] = edited_df["Estado"].apply(_normalizar_estado_editor)
    if "Observaciones" in edited_df.columns:
        edited_df["Observaciones"] = edited_df["Observaciones"].fillna("").astype(str)

    # Editor secundario: solo estudiantes recuperados pueden capturar Fecha cierre.
    st.markdown("##### 📅 Fecha de cierre")
    st.caption(
        "Este apartado solo muestra estudiantes con **Estado = Recuperado**. "
        "Mientras un estudiante esté en **En proceso** o **Sin seguimiento**, no se permite capturar Fecha cierre."
    )

    fecha_cierre_map = {}
    df_recuperados = edited_df[edited_df["Estado"].astype(str) == "Recuperado"].copy()

    if df_recuperados.empty:
        st.info(
            "No hay estudiantes con Estado Recuperado. Cambia el Estado a **Recuperado** en la tabla principal "
            "y la captura de Fecha cierre se habilitará automáticamente aquí abajo."
        )
    else:
        cols_fecha = [
            "seguimiento_id", "Estudiante", "Matrícula", "Estado", "Fecha cierre"
        ]
        cols_fecha = [c for c in cols_fecha if c in df_recuperados.columns]
        df_fechas = df_recuperados[cols_fecha].copy()

        if "Fecha cierre" not in df_fechas.columns:
            df_fechas["Fecha cierre"] = None
        df_fechas["Fecha cierre"] = df_fechas["Fecha cierre"].apply(_fecha_para_editor)

        disabled_fecha_cols = [c for c in df_fechas.columns if c != "Fecha cierre"]

        edited_fechas = st.data_editor(
            df_fechas,
            use_container_width=True,
            height=min(260, 90 + (len(df_fechas) * 38)),
            hide_index=True,
            num_rows="fixed",
            disabled=disabled_fecha_cols,
            key=f"{key_prefix}_editor_fechas_cierre_recuperados",
            column_config={
                "seguimiento_id": None,
                "Fecha cierre": st.column_config.DateColumn(
                    "Fecha cierre",
                    help="Selecciona la fecha de cierre únicamente para estudiantes recuperados. Si la dejas vacía, al guardar se asignará la fecha actual.",
                    format="YYYY-MM-DD",
                    required=False,
                ),
            },
        )

        for _, row_fecha in edited_fechas.iterrows():
            sid = _valor_seguro_fila(row_fecha, "seguimiento_id")
            if sid:
                fecha_cierre_map[sid] = normalizar_fecha_seguimiento(row_fecha.get("Fecha cierre", ""))

    col_guardar, col_info = st.columns([1, 2])
    with col_guardar:
        guardar_cambios = st.button(
            "💾 Guardar cambios de seguimiento",
            type="primary",
            key=f"{key_prefix}_guardar_cambios_editor",
        )
    with col_info:
        st.info(
            "Regla activa: **Fecha cierre solo se captura si Estado = Recuperado**. "
            "Si el Estado es **En proceso** o **Sin seguimiento**, el sistema limpia la Fecha cierre aunque exista un valor previo. "
            "Si el Estado es **Recuperado** y no capturas Fecha cierre, se asigna la fecha actual al guardar. "
            "La Última actualización siempre la coloca el sistema."
        )

    if guardar_cambios:
        df_previos = cargar_seguimiento_no_competentes()
        ids_previos = set(df_previos["seguimiento_id"].astype(str).tolist()) if not df_previos.empty else set()
        guardados = 0
        hoy = datetime.now().strftime("%Y-%m-%d")

        for _, row in edited_df.iterrows():
            seguimiento_id = _valor_seguro_fila(row, "seguimiento_id")
            if not seguimiento_id:
                continue

            causa = _normalizar_causa_editor(row.get("Causa", ""))
            responsable = _normalizar_responsable_editor(row.get("Responsable", ""))
            estado = _normalizar_estado_editor(row.get("Estado", "Sin seguimiento"))
            observaciones = str(row.get("Observaciones", "") or "").strip()

            fecha_cierre_capturada = ""
            if estado == "Recuperado":
                fecha_cierre_capturada = fecha_cierre_map.get(
                    seguimiento_id,
                    normalizar_fecha_seguimiento(row.get("Fecha cierre", "")),
                )

            tiene_captura = bool(
                causa
                or responsable
                or estado != "Sin seguimiento"
                or observaciones
                or fecha_cierre_capturada
            )
            existe_previo = seguimiento_id in ids_previos

            # Evita crear miles de registros vacíos cuando no se ha capturado nada.
            # Si el registro ya existía, sí se guarda para permitir regresar a "Sin seguimiento".
            if not tiene_captura and not existe_previo:
                continue

            previo = _obtener_registro_seguimiento(seguimiento_id)
            fecha_inicio_previa = _valor_seguro_fila(previo, "fecha_inicio", "") if previo is not None else ""
            causa_detalle_previa = _valor_seguro_fila(previo, "causa_detalle", "") if previo is not None else ""

            fecha_inicio = fecha_inicio_previa or (hoy if tiene_captura else "")
            fecha_cierre = fecha_cierre_por_estado_seguimiento(estado, fecha_cierre_capturada, hoy)

            guardar_registro_seguimiento_estudiante(
                row_estudiante=row,
                df_detalle_estudiante=pd.DataFrame(),
                datos_form={
                    "causa_principal": causa,
                    "causa_detalle": causa_detalle_previa,
                    "responsable_nombre": responsable,
                    "responsable_funcion": responsable,
                    "estado": estado,
                    "fecha_inicio": fecha_inicio,
                    "fecha_cierre": fecha_cierre,
                    "observaciones": observaciones,
                },
                corte_actual=corte_actual,
            )
            guardados += 1

        st.success(f"Seguimiento guardado correctamente. Registros actualizados: {guardados:,}.")
        st.rerun()

    # Reporte con la información visible/actual del editor.
    df_reporte = edited_df.copy()
    df_reporte["Causa"] = df_reporte["Causa"].apply(_normalizar_causa_editor)
    df_reporte["Responsable"] = df_reporte["Responsable"].apply(_normalizar_responsable_editor)
    df_reporte["Estado"] = df_reporte["Estado"].apply(_normalizar_estado_editor)
    if "Fecha cierre" in df_reporte.columns:
        df_reporte["Fecha cierre"] = df_reporte.apply(
            lambda r: fecha_cierre_por_estado_seguimiento(
                r.get("Estado", ""),
                fecha_cierre_map.get(
                    _valor_seguro_fila(r, "seguimiento_id"),
                    normalizar_fecha_seguimiento(r.get("Fecha cierre", "")),
                ),
            ),
            axis=1,
        )
    if "Observaciones" in df_reporte.columns:
        df_reporte["Observaciones"] = df_reporte["Observaciones"].fillna("").astype(str)

    render_reporte_seguimiento_no_competentes(df_reporte, corte_actual, key_prefix)

def render_seccion_impresion_por_modulos(plantel_sel, key_prefix="modulos_nc"):
    """
    Sección reutilizable para administradores y planteles.
    Permite filtrar e imprimir estudiantes por:
    - Grado: Todos, 2, 4, 6 o los grados que existan en el momento.
    - Cantidad de módulos NO competentes: 1, 2, 3... 10 y 11 o más.

    El filtro de cantidad de módulos puede inhabilitarse para mostrar todos los
    estudiantes del grado seleccionado sin perder resumen, detalle ni seguimiento.
    """
    df_base = obtener_detalle_no_competentes(plantel_sel)

    st.markdown("---")
    st.subheader("Selecciona e imprime la relación de estudiantes clasificados según el número de módulos en los que no resultaron competentes.")
    st.caption(
        "Primero selecciona el grado que deseas revisar. Después puedes habilitar el filtro por "
        "cantidad de módulos NO competentes o inhabilitarlo para mostrar todos los estudiantes "
        "del grado seleccionado."
    )

    if df_base is None or df_base.empty:
        st.info(f"ℹ️ No hay registros de NO competentes para **{plantel_sel}**.")
        return

    plantel_key = _safe_download_name(plantel_sel)

    # =========================
    # 1) Filtro por grado
    # =========================
    # Se busca la columna de grado de forma flexible para no romper si el archivo
    # viene con "grado", "Grado", "SEMESTRE" o "Semestre".
    grado_col = _find_col_like(df_base, ["grado", "Grado", "SEMESTRE", "Semestre"])

    if grado_col and grado_col in df_base.columns:
        grados_existentes = []
        for value in df_base[grado_col].dropna().tolist():
            grado_key = _sem_key(value)
            if grado_key is None:
                continue
            grados_existentes.append(int(grado_key))

        # Se muestran únicamente los grados que realmente existan en la información actual.
        # Si existen 2, 4 y 6, las opciones quedan: Todos, 2, 4, 6.
        grados_existentes = sorted(set(grados_existentes))
        opciones_grado = ["Todos"] + [str(g) for g in grados_existentes]
    else:
        grados_existentes = []
        opciones_grado = ["Todos"]

    grado_sel = st.selectbox(
        "Grado a identificar/imprimir",
        options=opciones_grado,
        index=0,
        key=f"{key_prefix}_{plantel_key}_grado",
        help="Este filtro toma los grados existentes en los datos actuales. Normalmente: Todos, 2, 4 y 6."
    )

    df_base_grado = df_base.copy()

    if grado_sel != "Todos" and grado_col and grado_col in df_base_grado.columns:
        grado_objetivo = int(grado_sel)
        df_base_grado = df_base_grado[
            df_base_grado[grado_col].apply(_sem_key) == grado_objetivo
        ].copy()

    if df_base_grado.empty:
        st.info(f"No hay estudiantes NO competentes para el grado **{grado_sel}** en **{plantel_sel}**.")
        return

    # El conteo de módulos se calcula después del filtro de grado.
    # Así, si el usuario selecciona grado 2, la categoría 1, 2, 3... se calcula
    # solo con los módulos NO competentes de ese grado.
    df_con_conteo = agregar_conteo_modulos_no_competentes(df_base_grado)
    resumen_categorias = construir_resumen_categorias_modulos(df_con_conteo)

    categorias_disponibles = sorted(
        df_con_conteo["categoria_modulos_nc"].dropna().astype(str).unique().tolist(),
        key=_orden_categoria_modulos_nc
    )

    if not categorias_disponibles:
        st.info(f"No se detectaron categorías de módulos NO competentes para el grado **{grado_sel}**.")
        return

    # =========================
    # 2) Filtro por cantidad de módulos NO competentes
    # =========================
    aplicar_filtro_modulos = st.checkbox(
        "Habilitar filtro por cantidad de módulos NO competentes",
        value=True,
        key=f"{key_prefix}_{plantel_key}_habilitar_filtro_modulos",
        help=(
            "Si está activado, puedes seleccionar una o varias cantidades de módulos. "
            "Si lo desactivas, se mostrarán todas las cantidades del grado seleccionado."
        ),
    )

    seleccion = st.multiselect(
        "Cantidad de módulos NO competentes a identificar/imprimir",
        options=categorias_disponibles,
        default=categorias_disponibles,
        key=f"{key_prefix}_{plantel_key}_grado_{_safe_download_name(grado_sel)}_categorias",
        disabled=not aplicar_filtro_modulos,
        help=(
            "Puedes seleccionar 1, 2, 3... 10 o 11 o más. "
            "También puedes combinar varias categorías. "
            "Desactiva la casilla anterior para inhabilitar este filtro."
        )
    )

    if aplicar_filtro_modulos:
        if not seleccion:
            st.info("Selecciona al menos una categoría o inhabilita el filtro por cantidad de módulos NO competentes.")
            return

        categorias_norm = {str(c).strip() for c in seleccion}
        df_detalle_filtrado = df_con_conteo[
            df_con_conteo["categoria_modulos_nc"].astype(str).isin(categorias_norm)
        ].copy()
        categorias_label = _label_categorias_modulos(seleccion)
    else:
        df_detalle_filtrado = df_con_conteo.copy()
        categorias_label = "Todas (filtro por cantidad inhabilitado)"

    df_resumen_estudiantes = construir_resumen_estudiantes_por_modulos(df_detalle_filtrado)

    estudiantes_unicos = (
        df_resumen_estudiantes["matricula"].nunique()
        if not df_resumen_estudiantes.empty and "matricula" in df_resumen_estudiantes.columns
        else len(df_resumen_estudiantes)
    )
    registros = len(df_detalle_filtrado)

    st.markdown(
        f"#### Resultado filtrado: **{estudiantes_unicos:,} estudiante(s)** | "
        f"**{registros:,} registro(s) académico(s)** | "
        f"Grado: **{grado_sel}** | Categoría(s): **{categorias_label}**"
    )

    if df_detalle_filtrado.empty:
        st.info("No hay estudiantes para los filtros seleccionados.")
        return

    with st.expander("Ver resumen por cantidad de módulos NO competentes", expanded=False):
        st.dataframe(resumen_categorias, use_container_width=True, hide_index=True)

    tab_resumen, tab_detalle, tab_seguimiento = st.tabs([
        "👤 Resumen por estudiante",
        "📚 Detalle por módulo",
        "📝 Seguimiento académico"
    ])

    with tab_resumen:
        st.caption(
            "Vista recomendada para impresión de atención: una fila por estudiante con sus módulos y docentes relacionados."
        )
        mostrar_dataframe_preview(df_resumen_estudiantes, height=430)
        render_botones_descarga_detalle(
            df_resumen_estudiantes,
            plantel_sel,
            tipo="resumen_por_modulos_no_competentes",
            key_prefix=f"{key_prefix}_resumen_{_safe_download_name(grado_sel)}_{_safe_download_name(categorias_label)}"
        )

    with tab_detalle:
        st.caption(
            "Vista completa: conserva cada registro/módulo académico original y agrega la cantidad total de módulos NO competentes del estudiante."
        )
        mostrar_dataframe_preview(df_detalle_filtrado, height=520)
        render_botones_descarga_detalle(
            df_detalle_filtrado,
            plantel_sel,
            tipo="detalle_por_modulos_no_competentes",
            key_prefix=f"{key_prefix}_detalle_{_safe_download_name(grado_sel)}_{_safe_download_name(categorias_label)}"
        )

    with tab_seguimiento:
        render_tab_seguimiento_no_competentes(
            df_resumen_estudiantes=df_resumen_estudiantes,
            df_detalle_filtrado=df_detalle_filtrado,
            plantel_sel=plantel_sel,
            categorias_label=f"Grado {grado_sel} | {categorias_label}",
            key_prefix=f"{key_prefix}_seguimiento_{_safe_download_name(grado_sel)}_{_safe_download_name(categorias_label)}"
        )



def _mapear_columnas_seguimiento(df):
    mapping = {}
    for col in df.columns:
        col_str = str(col).strip()
        col_norm = _norm_txt(col_str)

        if "sem" not in col_norm:
            continue

        wk = _wk_key(col_str)
        if wk is None:
            continue

        base = f"Sem {wk}"
        is_pct = ("%" in col_str) or ("porcentaje" in col_norm) or ("pct" in col_norm)

        if base not in mapping:
            mapping[base] = {"cantidad": None, "porcentaje": None, "week_num": wk}

        if is_pct:
            mapping[base]["porcentaje"] = col
        else:
            mapping[base]["cantidad"] = col

    return mapping


def _detectar_columna_semana(df):
    return _find_col_like(df, ["Semana", "Sem", "Semana Corte", "Week"])


def filtrar_semana_mas_reciente_si_existe(df):
    if df is None or getattr(df, "empty", True):
        return df

    col_semana = _detectar_columna_semana(df)
    if not col_semana:
        return df

    tmp = df.copy()
    tmp["__week_key__"] = tmp[col_semana].apply(_wk_key)

    if tmp["__week_key__"].notna().any():
        week_max = int(tmp["__week_key__"].dropna().max())
        tmp = tmp[tmp["__week_key__"] == week_max].copy()

    tmp.drop(columns=["__week_key__"], inplace=True, errors="ignore")
    return tmp


def obtener_etiqueta_semana_mas_reciente(df):
    if df is None or getattr(df, "empty", True):
        return None

    col_semana = _detectar_columna_semana(df)
    if not col_semana:
        return None

    tmp = df[[col_semana]].copy()
    tmp["__week_key__"] = tmp[col_semana].apply(_wk_key)

    if tmp["__week_key__"].notna().any():
        week_max = int(tmp["__week_key__"].dropna().max())
        match = tmp[tmp["__week_key__"] == week_max]
        if not match.empty:
            return str(match[col_semana].iloc[0]).strip()

    return None


def _obtener_matricula_total_plantel(plantel_usuario):
    """Devuelve la matrícula total del plantel para validar/calcular porcentajes."""
    try:
        df_matricula = cargar_matricula()
    except Exception:
        return 0.0

    if df_matricula is None or getattr(df_matricula, "empty", True):
        return 0.0

    col_plantel = _find_col_like(df_matricula, ["Plantel"])
    col_matricula = _find_col_like(df_matricula, ["matriculaTotal", "Matrícula Total", "matricula total"])

    if not col_plantel or not col_matricula:
        return 0.0

    objetivo = str(plantel_usuario).strip().lower()
    dfp = df_matricula[
        df_matricula[col_plantel].astype(str).str.strip().str.lower() == objetivo
    ].copy()

    if dfp.empty:
        return 0.0

    return float(pd.to_numeric(dfp[col_matricula], errors="coerce").fillna(0).sum())


def _normalizar_porcentaje_seguimiento(df_semana, plantel_usuario=None):
    """
    Corrige el porcentaje del seguimiento semanal sin alterar las cantidades.

    Pandas suele leer las celdas de Excel con formato porcentaje como fracciones:
    22.21% puede llegar como 0.2221. Esta función detecta ese caso y lo
    convierte a escala 0-100 para que la gráfica muestre 22.21% y no 0.22%.

    Si existe matrícula del plantel, se usa como referencia para evitar falsos
    positivos cuando un porcentaje real sea menor a 1%.
    """
    if df_semana is None or getattr(df_semana, "empty", True) or "Porcentaje" not in df_semana.columns:
        return df_semana

    out = df_semana.copy()
    valores = pd.to_numeric(out["Porcentaje"], errors="coerce")

    max_abs = valores.abs().max(skipna=True)
    if pd.isna(max_abs):
        out["Porcentaje"] = 0.0
        return out

    matricula = _obtener_matricula_total_plantel(plantel_usuario) if plantel_usuario else 0.0

    if matricula > 0 and "Cantidad" in out.columns:
        cantidades = pd.to_numeric(out["Cantidad"], errors="coerce")
        pct_calculado = (cantidades / matricula) * 100.0
        validos = valores.notna() & pct_calculado.notna()

        if max_abs == 0 and pct_calculado.fillna(0).abs().max() > 0:
            valores = pct_calculado
        elif max_abs <= 1 and validos.any():
            diferencia_directa = (valores[validos] - pct_calculado[validos]).abs().median()
            diferencia_escalada = ((valores[validos] * 100.0) - pct_calculado[validos]).abs().median()

            if diferencia_escalada < diferencia_directa:
                valores = valores * 100.0
        elif max_abs <= 1:
            valores = valores * 100.0
    elif max_abs <= 1:
        valores = valores * 100.0

    out["Porcentaje"] = valores.replace([float("inf"), -float("inf")], 0).fillna(0).round(2)
    return out


@st.cache_data(show_spinner=False)
def obtener_seguimiento_plantel(plantel_usuario):
    df_seguimiento = cargar_seguimiento()
    if df_seguimiento is None or getattr(df_seguimiento, "empty", True):
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    col_plantel = _find_col_like(df_seguimiento, ["Plantel"])
    if not col_plantel:
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    objetivo = str(plantel_usuario).strip().lower()
    df_plantel = df_seguimiento[
        df_seguimiento[col_plantel].astype(str).str.strip().str.lower() == objetivo
    ].copy()

    if df_plantel.empty:
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    mapping = _mapear_columnas_seguimiento(df_plantel)
    if not mapping:
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    rows = []
    for semana, meta in mapping.items():
        col_cantidad = meta.get("cantidad")
        col_porcentaje = meta.get("porcentaje")

        cantidad = 0
        porcentaje = 0.0

        if col_cantidad is not None and col_cantidad in df_plantel.columns:
            cantidad = pd.to_numeric(df_plantel[col_cantidad], errors="coerce").fillna(0).sum()

        if col_porcentaje is not None and col_porcentaje in df_plantel.columns:
            porcentaje = pd.to_numeric(df_plantel[col_porcentaje], errors="coerce").fillna(0).mean()

        rows.append({
            "Semana": semana,
            "Cantidad": int(round(float(cantidad))) if pd.notna(cantidad) else 0,
            "Porcentaje": float(porcentaje) if pd.notna(porcentaje) else 0.0,
            "Semana_num": meta.get("week_num") or 0,
        })

    df_semana = pd.DataFrame(rows)
    if df_semana.empty:
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    df_semana = df_semana.sort_values("Semana_num").reset_index(drop=True)
    df_semana = _normalizar_porcentaje_seguimiento(df_semana, plantel_usuario)
    df_semana["Etiqueta"] = df_semana.apply(
        lambda r: f"{int(r['Cantidad'])} - {float(r['Porcentaje']):.2f}%",
        axis=1
    )
    return df_semana


def _datos_tendencia_seguimiento(df):
    if df is None or getattr(df, "empty", True):
        return {
            "texto": "Tendencia vs semana previa: sin información.",
            "valor_card": "Sin información",
            "detalle_card": "No hay datos de seguimiento semanal.",
        }

    if len(df) < 2:
        return {
            "texto": "Tendencia vs semana previa: sin comparación.",
            "valor_card": "Sin comparación",
            "detalle_card": "No hay semana previa disponible para comparar.",
        }

    ultimo = df.iloc[-1]
    previo = df.iloc[-2]

    delta_cantidad = int(ultimo["Cantidad"] - previo["Cantidad"])
    delta_porcentaje = round(float(ultimo["Porcentaje"] - previo["Porcentaje"]), 2)

    if delta_porcentaje > 0:
        estado = "subió"
        flecha = "↑"
    elif delta_porcentaje < 0:
        estado = "bajó"
        flecha = "↓"
    else:
        estado = "se mantuvo"
        flecha = "→"

    return {
        "texto": (
            f"Tendencia vs semana previa: {flecha} {estado} "
            f"({delta_cantidad:+d} estudiantes; {delta_porcentaje:+.2f} pp)."
        ),
        "valor_card": f"{flecha} {estado.capitalize()}",
        "detalle_card": f"{delta_cantidad:+d} estudiantes; {delta_porcentaje:+.2f} pp",
    }


def _resumen_tendencia_seguimiento(df):
    return _datos_tendencia_seguimiento(df)["texto"]


def _pie_semanas_seguimiento(df):
    if df is None or getattr(df, "empty", True) or "Semana" not in df.columns:
        return None

    semanas = []
    for valor in df["Semana"].dropna().tolist():
        s = str(valor).strip()
        wk = _wk_key(s)
        if wk is not None:
            semanas.append(f"Semana {wk}")
        elif s:
            semanas.append(s)

    semanas = list(dict.fromkeys(semanas))
    if not semanas:
        return None

    if len(semanas) == 1:
        return f"Comportamiento correspondiente a: {semanas[0]}."

    return "Comportamiento correspondiente a: " + ", ".join(semanas) + "."




def _render_cards_resumen(items):
    if not items:
        return

    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        titulo = str(item.get("titulo", "")).strip()
        valor = str(item.get("valor", "")).strip()
        detalle = str(item.get("detalle", "")).strip()

        with col:
            st.markdown(
                f"""
                <div style="border:1px solid #D0D5DD;border-radius:14px;padding:16px 14px;background:#FFFFFF;min-height:120px;box-shadow:0 1px 2px rgba(16,24,40,0.05);">
                    <div style="font-size:13px;color:#667085;margin-bottom:8px;font-weight:600;">{titulo}</div>
                    <div style="font-size:24px;color:#101828;font-weight:800;line-height:1.15;">{valor}</div>
                    <div style="font-size:12px;color:#667085;margin-top:10px;line-height:1.35;">{detalle}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def construir_figura_seguimiento_plantel(plantel_objetivo, show_title=True):
    seguimiento_plantel = obtener_seguimiento_plantel(plantel_objetivo)

    if seguimiento_plantel is None or seguimiento_plantel.empty:
        return None, seguimiento_plantel

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=seguimiento_plantel["Semana"],
            y=seguimiento_plantel["Cantidad"],
            name="Cantidad",
            text=seguimiento_plantel["Etiqueta"],
            textposition="outside",
            textangle=-90,
            marker_color="#FFC107",
            cliponaxis=False,
            outsidetextfont=dict(size=LABEL_FONT_SIZE_ADMIN + 2, color="#2b2b2b"),
            hoverinfo="skip",
            hovertemplate="",
            customdata=seguimiento_plantel["Porcentaje"],
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=seguimiento_plantel["Semana"],
            y=seguimiento_plantel["Porcentaje"],
            name="% NO competencia",
            mode="lines+markers",
            line=dict(color="#1f77b4", width=3),
            marker=dict(size=9),
            hoverinfo="skip",
            hovertemplate="",
        ),
        secondary_y=True,
    )

    max_cantidad = float(seguimiento_plantel["Cantidad"].max()) if not seguimiento_plantel.empty else 0
    max_porcentaje = float(seguimiento_plantel["Porcentaje"].max()) if not seguimiento_plantel.empty else 0

    fig.update_layout(
        title_text=f"Comportamiento semanal — {plantel_objetivo}" if show_title else "",
        height=560,
        hovermode=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        uniformtext=dict(minsize=LABEL_FONT_SIZE_ADMIN + 2, mode="show"),
        margin=dict(t=90 if show_title else 40, b=40),
    )
    fig.update_xaxes(
        title_text="",
        showticklabels=True,
        ticks="",
        showgrid=False,
        tickangle=0,
        tickfont=dict(size=12),
    )
    fig.update_yaxes(
        title_text="",
        showticklabels=False,
        ticks="",
        showgrid=False,
        zeroline=False,
        range=[0, max_cantidad * Y_AXIS_PADDING_MULT if max_cantidad else 1],
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="",
        showticklabels=False,
        ticks="",
        showgrid=False,
        zeroline=False,
        range=[0, max_porcentaje * Y_AXIS_PADDING_MULT if max_porcentaje else 1],
        secondary_y=True,
    )

    return fig, seguimiento_plantel


def generar_imagen_grafica_seguimiento(plantel_objetivo):
    fig, _ = construir_figura_seguimiento_plantel(plantel_objetivo, show_title=True)
    if fig is None:
        return None

    try:
        return pio.to_image(fig, format="png", width=1400, height=700, scale=2)
    except Exception:
        return None


def mostrar_grafica_seguimiento_plantel(plantel_objetivo, show_title=True, show_footer=True):
    fig, seguimiento_plantel = construir_figura_seguimiento_plantel(plantel_objetivo, show_title=show_title)

    if fig is None or seguimiento_plantel is None or seguimiento_plantel.empty:
        return False

    st.plotly_chart(fig, use_container_width=True)

    resumen = _resumen_tendencia_seguimiento(seguimiento_plantel)
    if show_footer and resumen:
        st.caption(resumen)

    return True



# =========================
# Permisos
# =========================
def _parse_perm_ids(raw):
    if raw is None:
        return set()

    if isinstance(raw, (list, tuple, set)):
        out = set()
        for it in raw:
            out |= _parse_perm_ids(it)
        return out

    if isinstance(raw, dict):
        out = set()
        for k in ("ids", "permisos", "permisos_ids", "permissions", "permission_ids"):
            if k in raw:
                out |= _parse_perm_ids(raw.get(k))
        return out

    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return set()

    tokens = re.split(r"[;,|\s]+", s)
    ids = set()
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        m = re.search(r"\d+", t)
        if m:
            try:
                ids.add(int(m.group(0)))
            except Exception:
                pass
    return ids


@st.cache_data(show_spinner=False)
def cargar_catalogo_permisos_xlsx():
    try:
        df = cargar_permisos_sheet()
    except Exception:
        return {}

    def _find_col_exact(name):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_id = _find_col_exact("id")
    col_perm = _find_col_exact("Permiso")

    if col_id is None or col_perm is None:
        return {}

    cat = {}
    for _, row in df.iterrows():
        rid = row.get(col_id)
        rperm = row.get(col_perm)
        if pd.isna(rid) or pd.isna(rperm):
            continue
        try:
            pid = int(str(rid).strip())
        except Exception:
            continue
        code = str(rperm).strip()
        if code:
            cat[pid] = code
    return cat


def _parse_perm_codes(raw, catalog):
    if raw is None:
        return set()

    if isinstance(raw, (list, tuple, set)):
        out = set()
        for it in raw:
            out |= _parse_perm_codes(it, catalog)
        return out

    if isinstance(raw, dict):
        out = set()
        for k in (
            "codes", "permisos_codes", "permissions_codes",
            "permisos", "permisos_ids", "permissions", "permission_ids",
            "ids",
        ):
            if k in raw:
                out |= _parse_perm_codes(raw.get(k), catalog)
        return out

    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return set()

    parts = re.split(r"[\s,;|]+", s)
    out = set()
    for t in parts:
        t = t.strip()
        if not t:
            continue
        if t.isdigit():
            pid = int(t)
            code = catalog.get(pid)
            if code:
                out.add(code)
        else:
            out.add(t)
    return out


@st.cache_data(show_spinner=False)
def cargar_permisos_usuarios_codigos_xlsx():
    try:
        df = cargar_planteles_sheet()
    except Exception:
        return {}

    catalog = cargar_catalogo_permisos_xlsx()

    def _find_col_exact(name):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_user = _find_col_exact("Usuario")
    col_perms = _find_col_exact("Permisos")

    if col_user is None or col_perms is None:
        return {}

    mapping = {}
    for _, row in df.iterrows():
        u = str(row.get(col_user, "")).strip()
        if not u or u.lower() in ("nan", "none"):
            continue
        mapping[u] = _parse_perm_codes(row.get(col_perms), catalog)

    return mapping


def _get_username_from_session():
    for k in (
        "usuario", "username", "user", "Usuario", "USER", "login_user", "current_user",
        "user_name", "user_email", "email"
    ):
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

        if isinstance(v, dict):
            for kk in ("usuario", "username", "user", "name", "email"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
    return None


def obtener_permisos_usuario_codigos():
    catalog = cargar_catalogo_permisos_xlsx()

    posibles = [
        st.session_state.get("permisos_codes"),
        st.session_state.get("permissions_codes"),
        st.session_state.get("permisos"),
        st.session_state.get("permisos_ids"),
        st.session_state.get("permissions"),
        st.session_state.get("permission_ids"),
        st.session_state.get("permisos_usuario"),
        st.session_state.get("user_permissions"),
    ]
    for raw in posibles:
        codes = _parse_perm_codes(raw, catalog)
        if codes:
            return codes

    username = _get_username_from_session()
    if username:
        m = cargar_permisos_usuarios_codigos_xlsx()
        if username in m:
            return m[username]
        for u, codes in m.items():
            if u.lower() == username.lower():
                return codes

    return set()


@st.cache_data(show_spinner=False)
def cargar_permisos_usuarios_xlsx():
    try:
        df = cargar_planteles_sheet()
    except Exception:
        return {}

    def _find_col_exact(name):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_user = _find_col_exact("Usuario")
    col_perms = _find_col_exact("Permisos")

    if col_user is None or col_perms is None:
        return {}

    mapping = {}
    for _, row in df.iterrows():
        u = str(row.get(col_user, "")).strip()
        if not u or u.lower() in ("nan", "none"):
            continue
        mapping[u] = _parse_perm_ids(row.get(col_perms))

    return mapping


def obtener_permisos_usuario():
    posibles = [
        st.session_state.get("permisos_ids"),
        st.session_state.get("permisos"),
        st.session_state.get("permissions"),
        st.session_state.get("permission_ids"),
        st.session_state.get("permisos_usuario"),
        st.session_state.get("user_permissions"),
    ]
    for raw in posibles:
        ids = _parse_perm_ids(raw)
        if ids:
            return ids

    username = _get_username_from_session()
    if username:
        m = cargar_permisos_usuarios_xlsx()
        if username in m:
            return m[username]
        for u, ids in m.items():
            if u.lower() == username.lower():
                return ids

    return set()


# =========================
# Cálculos para correo
# =========================
def modulo_mayor_porcentaje_no_competencia(df_datos, plantel):
    if df_datos is None or getattr(df_datos, "empty", True):
        return None, None, None, "No se pudo leer la hoja 'Datos' (o está vacía)."

    df = df_datos.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_plantel = _find_col_like(df, ["Plantel"])
    col_mod = _find_col_like(df, ["MODULO", "MÓDULO", "Modulo", "Módulo"])
    col_nc = _find_col_like(df, ["NO COMPETENTES", "NO_COMPETENTES", "NO COMP", "NO_COMP"])
    col_total = _find_col_like(df, ["TOTAL ALUMNOS", "TOTAL_ALUMNOS", "TOTAL"])
    col_semana = _find_col_like(df, ["Semana", "SEMANA"])

    if not col_plantel or not col_mod or not col_nc or not col_total:
        return None, None, None, (
            "La hoja 'Datos' debe contener columnas: Plantel, MODULO, NO COMPETENTES, TOTAL ALUMNOS "
            "(los nombres pueden variar ligeramente)."
        )

    dfp = df[df[col_plantel].astype(str).str.strip() == str(plantel).strip()].copy()
    if dfp.empty:
        return None, None, None, "No hay registros en hoja 'Datos' para el plantel seleccionado."

    semana_usada = None
    if col_semana and col_semana in dfp.columns:
        uniq = dfp[col_semana].dropna().unique().tolist()
        with_nums = [(v, _wk_key(v)) for v in uniq]
        nums_only = [x for x in with_nums if x[1] is not None]

        if nums_only:
            semana_usada = max(nums_only, key=lambda t: t[1])[0]
        else:
            semana_usada = sorted([str(v).strip() for v in uniq])[-1]

        dfp = dfp[dfp[col_semana].astype(str).str.strip() == str(semana_usada).strip()].copy()
        if dfp.empty:
            return None, None, None, "No hay registros para la semana seleccionada automáticamente en ese plantel."

    dfp[col_nc] = pd.to_numeric(dfp[col_nc], errors="coerce").fillna(0)
    dfp[col_total] = pd.to_numeric(dfp[col_total], errors="coerce").fillna(0)

    g = dfp.groupby(col_mod, dropna=True).agg(
        NO_COMP=(col_nc, "sum"),
        TOTAL=(col_total, "sum"),
    ).reset_index()

    g = g[g["TOTAL"] > 0].copy()
    if g.empty:
        return None, None, semana_usada, "No fue posible calcular % (TOTAL ALUMNOS en 0 o vacío)."

    g["PCT"] = (g["NO_COMP"] / g["TOTAL"]) * 100.0
    g[col_mod] = g[col_mod].astype(str).str.strip()
    g = g.sort_values(by=["PCT", "NO_COMP", "TOTAL", col_mod], ascending=[False, False, False, True])

    modulo = str(g.iloc[0][col_mod])
    pct = float(g.iloc[0]["PCT"])

    return modulo, round(pct, 2), semana_usada, None


def top_modulos_porcentaje_no_competencia_por_semestre(df_datos, plantel, semestres=(2, 4, 6), top_n=3):
    if df_datos is None or getattr(df_datos, "empty", True):
        return {}, None, "No se pudo leer la hoja 'Datos' (o está vacía)."

    df = df_datos.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_plantel = _find_col_like(df, ["Plantel"])
    col_mod = _find_col_like(df, ["MODULO", "MÓDULO", "Modulo", "Módulo"])
    col_nc = _find_col_like(df, ["NO COMPETENTES", "NO_COMPETENTES", "NO COMP", "NO_COMP"])
    col_total = _find_col_like(df, ["TOTAL ALUMNOS", "TOTAL_ALUMNOS", "TOTAL"])
    col_semana = _find_col_like(df, ["Semana", "SEMANA"])
    col_semestre = _find_col_like(df, ["SEMESTRE", "Semestre"])

    if not col_plantel or not col_mod or not col_nc or not col_total or not col_semestre:
        return {}, None, (
            "La hoja 'Datos' debe contener columnas: Plantel, MODULO, SEMESTRE, NO COMPETENTES, TOTAL ALUMNOS "
            "(los nombres pueden variar ligeramente)."
        )

    dfp = df[df[col_plantel].astype(str).str.strip() == str(plantel).strip()].copy()
    if dfp.empty:
        return {}, None, "No hay registros en hoja 'Datos' para el plantel seleccionado."

    semana_usada = None
    if col_semana and col_semana in dfp.columns:
        uniq = dfp[col_semana].dropna().unique().tolist()
        with_nums = [(v, _wk_key(v)) for v in uniq]
        nums_only = [x for x in with_nums if x[1] is not None]

        if nums_only:
            semana_usada = max(nums_only, key=lambda t: t[1])[0]
        else:
            semana_usada = sorted([str(v).strip() for v in uniq])[-1]

        dfp = dfp[dfp[col_semana].astype(str).str.strip() == str(semana_usada).strip()].copy()
        if dfp.empty:
            return {}, None, "No hay registros para la semana seleccionada automáticamente en ese plantel."

    dfp[col_nc] = pd.to_numeric(dfp[col_nc], errors="coerce").fillna(0)
    dfp[col_total] = pd.to_numeric(dfp[col_total], errors="coerce").fillna(0)
    dfp["_SEM_KEY_"] = dfp[col_semestre].apply(_sem_key)

    top_dict = {}
    for sem in semestres:
        dfs = dfp[dfp["_SEM_KEY_"] == int(sem)].copy()
        if dfs.empty:
            top_dict[int(sem)] = []
            continue

        g = dfs.groupby(col_mod, dropna=True).agg(
            NO_COMP=(col_nc, "sum"),
            TOTAL=(col_total, "sum"),
        ).reset_index()

        g = g[g["TOTAL"] > 0].copy()
        if g.empty:
            top_dict[int(sem)] = []
            continue

        g["PCT"] = (g["NO_COMP"] / g["TOTAL"]) * 100.0
        g[col_mod] = g[col_mod].astype(str).str.strip()
        g = g.sort_values(by=["PCT", "NO_COMP", "TOTAL", col_mod], ascending=[False, False, False, True])

        top = []
        for _, row in g.head(top_n).iterrows():
            top.append((str(row[col_mod]), round(float(row["PCT"]), 2)))

        top_dict[int(sem)] = top

    return top_dict, semana_usada, None


def top_docentes_porcentaje_no_competencia(df_datos, plantel, top_n=5):
    if df_datos is None or getattr(df_datos, "empty", True):
        return [], None, "No se pudo leer la hoja 'Datos' (o está vacía)."

    df = df_datos.copy()
    df.columns = [str(c).strip() for c in df.columns]

    col_plantel = _find_col_like(df, ["Plantel"])
    col_doc = _find_col_like(df, ["DOCENTE", "Docente", "NOMBRE DOCENTE", "PROFESOR", "MAESTRO"])
    col_nc = _find_col_like(df, ["NO COMPETENTES", "NO_COMPETENTES", "NO COMP", "NO_COMP"])
    col_total = _find_col_like(df, ["TOTAL ALUMNOS", "TOTAL_ALUMNOS", "TOTAL"])
    col_semana = _find_col_like(df, ["Semana", "SEMANA"])

    if not col_plantel or not col_doc or not col_nc or not col_total:
        return [], None, (
            "La hoja 'Datos' debe contener columnas: Plantel, DOCENTE, NO COMPETENTES, TOTAL ALUMNOS "
            "(los nombres pueden variar ligeramente)."
        )

    dfp = df[df[col_plantel].astype(str).str.strip() == str(plantel).strip()].copy()
    if dfp.empty:
        return [], None, "No hay registros en hoja 'Datos' para el plantel seleccionado."

    semana_usada = None
    if col_semana and col_semana in dfp.columns:
        uniq = dfp[col_semana].dropna().unique().tolist()
        with_nums = [(v, _wk_key(v)) for v in uniq]
        nums_only = [x for x in with_nums if x[1] is not None]

        if nums_only:
            semana_usada = max(nums_only, key=lambda t: t[1])[0]
        else:
            semana_usada = sorted([str(v).strip() for v in uniq])[-1]

        dfp = dfp[dfp[col_semana].astype(str).str.strip() == str(semana_usada).strip()].copy()
        if dfp.empty:
            return [], None, "No hay registros para la semana seleccionada automáticamente en ese plantel."

    dfp[col_nc] = pd.to_numeric(dfp[col_nc], errors="coerce").fillna(0)
    dfp[col_total] = pd.to_numeric(dfp[col_total], errors="coerce").fillna(0)
    dfp[col_doc] = dfp[col_doc].astype(str).str.strip()
    dfp = dfp[~dfp[col_doc].str.lower().isin(["", "nan", "none", "null"])].copy()

    g = dfp.groupby(col_doc, dropna=True).agg(
        NO_COMP=(col_nc, "sum"),
        TOTAL=(col_total, "sum"),
    ).reset_index()

    g = g[g["TOTAL"] > 0].copy()
    if g.empty:
        return [], semana_usada, "No fue posible calcular % (TOTAL ALUMNOS en 0 o vacío)."

    g["PCT"] = (g["NO_COMP"] / g["TOTAL"]) * 100.0
    g[col_doc] = g[col_doc].astype(str).str.strip()
    g = g.sort_values(by=["PCT", "NO_COMP", "TOTAL", col_doc], ascending=[False, False, False, True])

    top_list = []
    for _, row in g.head(top_n).iterrows():
        top_list.append((str(row[col_doc]), round(float(row["PCT"]), 2)))

    return top_list, semana_usada, None


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


def exportar_html_imprimible(df, titulo, subtitulo="", filename="no_competentes.html"):
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



def _safe_download_name(value):
    text = str(value or "todos").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text.lower() or "todos"


def render_botones_descarga_detalle(df, plantel_sel, tipo="no_competentes", key_prefix="detalle"):
    """
    Descargas manuales deshabilitadas por requerimiento.

    Antes esta función mostraba botones como:
    - Descargar Excel completo
    - Descargar HTML imprimible

    Se conserva la función para NO romper las llamadas existentes en el dashboard.
    Las tablas siguen mostrándose completas mediante st.dataframe(), por lo que el
    usuario puede usar las herramientas propias de la tabla para bajar la información.
    """
    return


# =========================
# Análisis de seguimiento para correo
# =========================
def _obtener_valor_fila(fila_df, col, default=0):
    if fila_df is None or getattr(fila_df, "empty", True) or col not in fila_df.columns:
        return default
    try:
        valor = fila_df[col].iloc[0]
        if pd.isna(valor):
            return default
        return valor
    except Exception:
        return default


def _construir_metas_semanales(total_actual, meta_maxima, semana_actual, semana_meta):
    if semana_actual is None or semana_meta is None or semana_actual >= semana_meta or total_actual <= meta_maxima:
        return []

    semanas_restantes = int(semana_meta - semana_actual)
    reduccion_total = max(int(total_actual) - int(meta_maxima), 0)
    if semanas_restantes <= 0 or reduccion_total <= 0:
        return []

    reduccion_promedio = reduccion_total / semanas_restantes
    metas = []
    for paso in range(1, semanas_restantes + 1):
        semana = int(semana_actual + paso)
        meta_semana = math.ceil(total_actual - (reduccion_promedio * paso))
        meta_semana = max(int(meta_maxima), int(meta_semana))
        metas.append((semana, meta_semana))
    return metas


def construir_analisis_seguimiento_plantel(plantel, tabla, total_sin_calif=0, semana_meta=EMAIL_META_SEMANA_OBJETIVO, meta_pct=EMAIL_META_MAX_NO_COMP_PCT):
    fila_p = tabla[tabla["Plantel"] == plantel].copy()

    matricula = int(_obtener_valor_fila(fila_p, "matriculaTotal", 0) or 0)
    total_no_comp = int(_obtener_valor_fila(fila_p, "Total estudiantes no competentes", 0) or 0)
    porcentaje_actual = float(_obtener_valor_fila(fila_p, "% Estudiantes no competentes", 0.0) or 0.0)

    meta_maxima = int(math.ceil(matricula * (meta_pct / 100.0))) if matricula > 0 else 0
    faltan_regularizar = max(total_no_comp - meta_maxima, 0)

    seguimiento = obtener_seguimiento_plantel(plantel)
    semana_actual = None
    reduccion_absoluta = 0
    reduccion_porcentual = 0.0
    ha_accionado = False

    if seguimiento is not None and not seguimiento.empty:
        if "Semana_num" in seguimiento.columns and seguimiento["Semana_num"].notna().any():
            semana_actual = int(seguimiento["Semana_num"].dropna().iloc[-1])

        cantidad_inicial = int(seguimiento["Cantidad"].iloc[0])
        cantidad_actual = int(seguimiento["Cantidad"].iloc[-1])
        reduccion_absoluta = max(cantidad_inicial - cantidad_actual, 0)
        reduccion_porcentual = round((reduccion_absoluta / cantidad_inicial) * 100, 2) if cantidad_inicial > 0 else 0.0
        ha_accionado = cantidad_actual < cantidad_inicial

    semanas_restantes = None
    promedio_semanal_necesario = 0
    if semana_actual is not None:
        semanas_restantes = max(int(semana_meta - semana_actual), 0)
        if semanas_restantes > 0 and faltan_regularizar > 0:
            promedio_semanal_necesario = int(math.ceil(faltan_regularizar / semanas_restantes))

    uno_modulo = int(_obtener_valor_fila(fila_p, "1", 0) or 0)
    dos_modulos = int(_obtener_valor_fila(fila_p, "2", 0) or 0)

    tendencia = _datos_tendencia_seguimiento(seguimiento)
    metas_semanales = _construir_metas_semanales(total_no_comp, meta_maxima, semana_actual, semana_meta)

    if faltan_regularizar <= 0:
        dictamen = (
            f"El plantel ya se encuentra dentro del parámetro esperado, con {porcentaje_actual:.2f}% de no competencia, "
            f"igual o menor al {meta_pct:.0f}% permitido."
        )
    else:
        accion_texto = "sí muestra evidencia de haber accionado" if ha_accionado else "no muestra una reducción acumulada suficiente"
        dictamen = (
            f"El plantel {accion_texto}; actualmente registra {total_no_comp:,} estudiantes no competentes "
            f"({porcentaje_actual:.2f}% de su matrícula). Para llegar al {meta_pct:.0f}% como máximo en la semana "
            f"{semana_meta}, debe regularizar al menos {faltan_regularizar:,} estudiantes adicionales."
        )

    recomendaciones = []
    if faltan_regularizar > 0:
        if promedio_semanal_necesario > 0 and semanas_restantes is not None:
            recomendaciones.append(
                f"Establecer una meta operativa de al menos {promedio_semanal_necesario:,} estudiantes regularizados por semana durante las próximas {semanas_restantes} semana(s)."
            )
        recomendaciones.append(
            f"Priorizar a los estudiantes con 1 y 2 módulos no competentes ({uno_modulo:,} y {dos_modulos:,} casos, respectivamente), ya que representan la oportunidad de recuperación más inmediata."
        )
        if total_sin_calif > 0:
            recomendaciones.append(
                f"Regularizar de inmediato los {int(total_sin_calif):,} estudiantes sin evaluación en algún módulo para evitar que permanezcan dentro del indicador."
            )
        recomendaciones.append(
            "Dar seguimiento puntual a los módulos y docentes con mayor porcentaje de no competencia para focalizar las acciones académicas y de acompañamiento."
        )
        recomendaciones.append(
            "Revisar semanalmente el avance contra la meta y ajustar la intervención si se detecta estancamiento o retroceso."
        )
    else:
        recomendaciones.append(
            "Mantener el seguimiento semanal y las acciones preventivas para no rebasar nuevamente el umbral del 10% de no competencia."
        )

    return {
        "seguimiento": seguimiento,
        "matricula": matricula,
        "total_no_comp": total_no_comp,
        "porcentaje_actual": porcentaje_actual,
        "meta_maxima": meta_maxima,
        "faltan_regularizar": faltan_regularizar,
        "semana_actual": semana_actual,
        "semana_meta": semana_meta,
        "semanas_restantes": semanas_restantes,
        "promedio_semanal_necesario": promedio_semanal_necesario,
        "ha_accionado": ha_accionado,
        "reduccion_absoluta": reduccion_absoluta,
        "reduccion_porcentual": reduccion_porcentual,
        "tendencia": tendencia,
        "dictamen": dictamen,
        "recomendaciones": recomendaciones,
        "uno_modulo": uno_modulo,
        "dos_modulos": dos_modulos,
        "metas_semanales": metas_semanales,
    }


def _render_metas_semanales_texto(metas):
    if not metas:
        return ""
    lines = ["Metas semanales sugeridas para llegar al 10%:"]
    for semana, meta in metas:
        lines.append(f"- Semana {int(semana)}: máximo {int(meta):,} estudiantes no competentes")
    return "\n".join(lines)


def _render_metas_semanales_html(metas):
    if not metas:
        return ""

    rows = []
    for semana, meta in metas:
        rows.append(
            f"<tr><td style='padding:8px;border:1px solid #D0D5DD;'>Semana {int(semana)}</td>"
            f"<td style='padding:8px;border:1px solid #D0D5DD;text-align:right;'>{int(meta):,}</td></tr>"
        )

    return (
        "<p><strong>Metas semanales sugeridas para llegar al 10%:</strong></p>"
        "<table style='border-collapse:collapse;width:100%;max-width:420px;'>"
        "<thead><tr>"
        "<th style='padding:8px;border:1px solid #D0D5DD;background:#F2F4F7;text-align:left;'>Semana</th>"
        "<th style='padding:8px;border:1px solid #D0D5DD;background:#F2F4F7;text-align:right;'>Máximo de estudiantes no competentes</th>"
        "</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def _render_top_semestres_html(top_dict, semana_usada):
    orden = [2, 4, 6]
    parts = ["<p><strong>Módulos con mayor % de NO competencia por semestre:</strong></p><ul>"]
    for sem in orden:
        items = top_dict.get(sem, [])
        if not items:
            parts.append(f"<li>Semestre {sem}: sin datos.</li>")
        else:
            detalle = ", ".join(f"{escape(mod)} ({pct:.2f}%)" for mod, pct in items)
            parts.append(f"<li>Semestre {sem}: {detalle}</li>")
    parts.append("</ul>")
    if semana_usada is not None:
        parts.append(f"<p><strong>Semana utilizada para módulos:</strong> {escape(str(semana_usada))}</p>")
    return "".join(parts)


def _render_top_docentes_html(top_list, semana_usada):
    parts = ["<p><strong>Docentes con mayor % de NO competencia:</strong></p><ol>"]
    if not top_list:
        parts.append("<li>Sin datos.</li>")
    else:
        for doc, pct in top_list:
            parts.append(f"<li>{escape(str(doc))} ({pct:.2f}%)</li>")
    parts.append("</ol>")
    if semana_usada is not None:
        parts.append(f"<p><strong>Semana utilizada para docentes:</strong> {escape(str(semana_usada))}</p>")
    return "".join(parts)


def construir_contenido_correo_plantel(
    plantel,
    total_no_comp,
    total_sin_calif,
    top_por_semestre,
    semana_modulos,
    mod_err,
    top_docentes,
    semana_docentes,
    doc_err,
    analisis,
    incluir_grafica=True,
):
    graph_cid = f"grafica_{_safe_download_name(plantel)}"

    if top_por_semestre and any(len(v) > 0 for v in top_por_semestre.values()):
        extra_mod_text = "\n" + _formatear_top_por_semestre(top_por_semestre, semana_modulos) + "\n"
        extra_mod_html = _render_top_semestres_html(top_por_semestre, semana_modulos)
    else:
        extra_mod_text = (
            "\nMódulos con MAYOR % de NO COMPETENCIA por semestre (plantel): "
            f"No se pudo determinar con certeza. Motivo: {mod_err}\n"
        )
        extra_mod_html = (
            "<p><strong>Módulos con mayor % de NO competencia por semestre:</strong> "
            f"No se pudo determinar con certeza. Motivo: {escape(str(mod_err or 'Sin información'))}</p>"
        )

    if top_docentes and len(top_docentes) > 0:
        extra_doc_text = "\n" + _formatear_top_docentes(top_docentes, semana_docentes) + "\n"
        extra_doc_html = _render_top_docentes_html(top_docentes, semana_docentes)
    else:
        extra_doc_text = (
            "\nDocentes con MAYOR % de NO COMPETENCIA (plantel): "
            f"No se pudo determinar con certeza. Motivo: {doc_err}\n"
        )
        extra_doc_html = (
            "<p><strong>Docentes con mayor % de NO competencia:</strong> "
            f"No se pudo determinar con certeza. Motivo: {escape(str(doc_err or 'Sin información'))}</p>"
        )

    metas_texto = _render_metas_semanales_texto(analisis.get("metas_semanales", []))
    metas_html = _render_metas_semanales_html(analisis.get("metas_semanales", []))

    recomendaciones_texto = "\n".join([f"- {item}" for item in analisis.get("recomendaciones", [])])
    recomendaciones_html = "".join(f"<li>{escape(item)}</li>" for item in analisis.get("recomendaciones", []))

    tendencia = analisis.get("tendencia", {}) or {}
    tendencia_texto = tendencia.get("texto", "Sin información de tendencia.")

    cuerpo_texto = (
        f"Estimado Plantel {plantel}:\n"
        "\nAnteponiendo un cordial saludo, se comparte el análisis actualizado de indicadores académicos del plantel.\n"
        f"Actualmente registra {total_no_comp:,} estudiantes NO COMPETENTES y {int(total_sin_calif):,} estudiantes SIN EVALUACIÓN en algún módulo.\n"
        f"Matrícula del plantel: {analisis.get('matricula', 0):,}.\n"
        f"Porcentaje actual de NO competencia: {analisis.get('porcentaje_actual', 0.0):.2f}%.\n"
        f"Meta máxima permitida (10%): {analisis.get('meta_maxima', 0):,} estudiantes.\n"
        f"Estudiantes por regularizar para llegar al 10%: {analisis.get('faltan_regularizar', 0):,}.\n"
        f"{analisis.get('dictamen', '')}\n"
        f"{tendencia_texto}\n"
    )

    if analisis.get("ha_accionado"):
        cuerpo_texto += (
            f"El plantel ha reducido {analisis.get('reduccion_absoluta', 0):,} estudiantes desde el inicio del seguimiento, "
            f"equivalente a {analisis.get('reduccion_porcentual', 0.0):.2f}% de reducción acumulada.\n"
        )

    if analisis.get("promedio_semanal_necesario", 0) > 0:
        cuerpo_texto += (
            f"Para alcanzar la meta en la semana {analisis.get('semana_meta')}, debe regularizar en promedio "
            f"{analisis.get('promedio_semanal_necesario'):,} estudiantes por semana.\n"
        )

    if metas_texto:
        cuerpo_texto += "\n" + metas_texto + "\n"

    cuerpo_texto += (
        "\nAcciones recomendadas para llegar al 10%:\n"
        f"{recomendaciones_texto}\n"
        f"{extra_mod_text}\n"
        "\nA continuación, se presentan los 5 docentes que registran el mayor porcentaje de NO COMPETENCIA en este cierre de semestre:\n"
        f"{extra_doc_text}\n"
        "\nSe adjunta/integra la gráfica de comportamiento semanal del plantel.\n"
        "Para consultar información detallada, particular o completa sobre los avances y resultados del plantel, "
        "le invitamos a revisar el tablero institucional en el siguiente enlace:\n"
        "https://tablero-docentes.conalepmexacademica.app/\n"
        "\nSin otro particular, reciba un cordial saludo.\n"
    )

    grafica_html = ""
    if incluir_grafica:
        grafica_html = (
            f"<div style='margin:20px 0;'>"
            f"<p><strong>Gráfica de seguimiento semanal</strong></p>"
            f"<img src='cid:{graph_cid}' alt='Gráfica de seguimiento semanal {escape(str(plantel))}' "
            "style='max-width:100%;height:auto;border:1px solid #D0D5DD;border-radius:8px;' />"
            f"</div>"
        )

    cuerpo_html = f"""
    <html>
      <body style="font-family:Arial,Helvetica,sans-serif;color:#222;line-height:1.55;">
        <p>Estimado Plantel <strong>{escape(str(plantel))}</strong>:</p>
        <p>Anteponiendo un cordial saludo, se comparte el análisis actualizado de indicadores académicos del plantel.</p>

        <table style="border-collapse:collapse;width:100%;max-width:760px;margin:12px 0 20px 0;">
          <tr>
            <td style="padding:10px;border:1px solid #D0D5DD;background:#F9FAFB;"><strong>Matrícula</strong><br>{analisis.get('matricula', 0):,}</td>
            <td style="padding:10px;border:1px solid #D0D5DD;background:#F9FAFB;"><strong>No competentes</strong><br>{total_no_comp:,}</td>
            <td style="padding:10px;border:1px solid #D0D5DD;background:#F9FAFB;"><strong>% actual</strong><br>{analisis.get('porcentaje_actual', 0.0):.2f}%</td>
            <td style="padding:10px;border:1px solid #D0D5DD;background:#F9FAFB;"><strong>Meta 10%</strong><br>{analisis.get('meta_maxima', 0):,}</td>
          </tr>
        </table>

        <p>{escape(analisis.get('dictamen', ''))}</p>
        <p><strong>{escape(tendencia_texto)}</strong></p>

        <p>Actualmente el plantel registra <strong>{int(total_sin_calif):,}</strong> estudiantes sin evaluación en algún módulo.</p>
    """

    if analisis.get("ha_accionado"):
        cuerpo_html += (
            f"<p>Durante el seguimiento, el plantel ha reducido <strong>{analisis.get('reduccion_absoluta', 0):,}</strong> "
            f"estudiantes no competentes, lo que representa una reducción acumulada de "
            f"<strong>{analisis.get('reduccion_porcentual', 0.0):.2f}%</strong>.</p>"
        )

    if analisis.get("promedio_semanal_necesario", 0) > 0:
        cuerpo_html += (
            f"<p>Para llegar al 10% como máximo en la semana <strong>{analisis.get('semana_meta')}</strong>, "
            f"es necesario regularizar en promedio al menos <strong>{analisis.get('promedio_semanal_necesario'):,}</strong> "
            f"estudiantes por semana.</p>"
        )

    cuerpo_html += grafica_html

    if metas_html:
        cuerpo_html += metas_html

    cuerpo_html += (
        "<p><strong>Acciones recomendadas para llegar al 10%:</strong></p>"
        f"<ul>{recomendaciones_html}</ul>"
        f"{extra_mod_html}"
        f"{extra_doc_html}"
        "<p>Para consultar información detallada, particular o completa sobre los avances y resultados del plantel, "
        "le invitamos a revisar el tablero institucional en el siguiente enlace:</p>"
        "<p><a href='https://tablero-docentes.conalepmexacademica.app/'>https://tablero-docentes.conalepmexacademica.app/</a></p>"
        "<p>Sin otro particular, reciba un cordial saludo.</p>"
        "</body></html>"
    )

    return {
        "text": cuerpo_texto,
        "html": cuerpo_html,
        "graph_cid": graph_cid,
    }


# =========================
# Email (SMTP)
# =========================
@st.cache_data(show_spinner=False)
def cargar_emails_planteles():
    df = cargar_planteles_sheet()

    def _find_col(obj):
        for c in df.columns:
            if str(c).strip().lower() == obj.lower():
                return c
        return None

    col_plantel = _find_col("Plantel")
    col_email = _find_col("Email")
    col_ccp = _find_col("Ccp")

    if col_plantel is None or col_email is None:
        raise KeyError("La hoja 'Planteles' debe contener las columnas 'Plantel' y 'Email'.")

    mapping = {}
    for _, row in df.iterrows():
        plantel = str(row.get(col_plantel, "")).strip()
        email_raw = str(row.get(col_email, "")).strip()

        if not plantel or plantel.lower() in ("nan", "none"):
            continue

        to_list = []
        if email_raw and email_raw.lower() not in ("nan", "none"):
            to_list = [e.strip() for e in re.split(r"[;,]+", email_raw) if e.strip()]

        cc_list = []
        if col_ccp is not None:
            ccp_raw = str(row.get(col_ccp, "")).strip()
            if ccp_raw and ccp_raw.lower() not in ("nan", "none"):
                cc_list = [e.strip() for e in re.split(r"[;,]+", ccp_raw) if e.strip()]

        if to_list:
            mapping[plantel] = {"to": to_list, "cc": cc_list}
        else:
            mapping.setdefault(plantel, {"to": [], "cc": cc_list})

    return mapping


def _smtp_config():
    smtp = {}
    try:
        if "smtp" in st.secrets:
            smtp = dict(st.secrets["smtp"])
    except Exception:
        smtp = {}

    host = smtp.get("host") or os.getenv("SMTP_HOST", "")
    port = int(smtp.get("port") or os.getenv("SMTP_PORT", "587"))
    user = smtp.get("user") or os.getenv("SMTP_USER", "")
    password = smtp.get("password") or os.getenv("SMTP_PASSWORD", "")
    from_email = smtp.get("from_email") or os.getenv("SMTP_FROM", user)
    use_tls = bool(smtp.get("use_tls", True))

    if not host:
        raise ValueError("Falta configuración SMTP: host. Configura st.secrets['smtp']['host'] o SMTP_HOST.")
    if not from_email:
        raise ValueError("Falta configuración SMTP: from_email. Configura st.secrets['smtp']['from_email'] o SMTP_FROM.")

    return host, port, user, password, from_email, use_tls


def enviar_correo(destinatarios, asunto, cuerpo, cc=None, cuerpo_html=None, inline_images=None):
    host, port, user, password, from_email, use_tls = _smtp_config()
    cc = cc or []
    inline_images = inline_images or []

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = from_email
    msg["To"] = ", ".join(destinatarios)

    if cc:
        msg["Cc"] = ", ".join(cc)

    msg.set_content(cuerpo)

    if cuerpo_html:
        msg.add_alternative(cuerpo_html, subtype="html")
        html_part = msg.get_payload()[-1]
        for img in inline_images:
            data = img.get("data")
            cid = img.get("cid")
            if not data or not cid:
                continue
            html_part.add_related(
                data,
                maintype="image",
                subtype=img.get("subtype", "png"),
                cid=f"<{cid}>",
                filename=img.get("filename", f"{cid}.png"),
            )

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()
        if user and password:
            server.login(user, password)
        server.send_message(msg)


def contar_sin_calificaciones(df_reprobacion, plantel):
    df_p = df_reprobacion[df_reprobacion["Plantel"] == plantel].copy()
    df_p = asegurar_metricas(df_p)
    if "pEspecifico" not in df_p.columns:
        return 0
    df_sin = df_p[df_p["pEspecifico"] == 0].copy()
    if df_sin.empty:
        return 0
    if "matricula" in df_sin.columns:
        return int(df_sin["matricula"].nunique())
    return int(len(df_sin))


def _formatear_top_por_semestre(top_dict, semana_usada):
    orden = [2, 4, 6]
    lines = []
    lines.append("Módulos con MAYOR % de NO COMPETENCIA por semestre (plantel):")

    for sem in orden:
        items = top_dict.get(sem, [])
        lines.append(f"- Semestre {sem}:")
        if not items:
            lines.append("  (Sin datos)")
        else:
            for i, (mod, pct) in enumerate(items, start=1):
                lines.append(f"  {i}) {mod} ({pct:.2f}%)")

    if semana_usada is not None:
        lines.append(f"Semana: {semana_usada}")

    return "\n".join(lines)


def _formatear_top_docentes(top_list, semana_usada):
    lines = []
    lines.append("Docentes con MAYOR % de NO COMPETENCIA (plantel):")

    if not top_list:
        lines.append("(Sin datos)")
    else:
        for i, (doc, pct) in enumerate(top_list, start=1):
            lines.append(f"{i}) {doc} ({pct:.2f}%)")

    if semana_usada is not None:
        lines.append(f"Semana: {semana_usada}")

    return "\n".join(lines)


def texto_correo_plantel(
    plantel,
    total_no_comp,
    total_sin_calif,
    top_por_semestre,
    semana_modulos,
    mod_err,
    top_docentes,
    semana_docentes,
    doc_err
):
    if top_por_semestre and any(len(v) > 0 for v in top_por_semestre.values()):
        extra_mod = "\n" + _formatear_top_por_semestre(top_por_semestre, semana_modulos) + "\n"
    else:
        extra_mod = (
            "\nMódulos con MAYOR % de NO COMPETENCIA por semestre (plantel): "
            f"No se pudo determinar con certeza. Motivo: {mod_err}\n"
        )

    if top_docentes and len(top_docentes) > 0:
        extra_doc = "\n" + _formatear_top_docentes(top_docentes, semana_docentes) + "\n"
    else:
        extra_doc = (
            "\nDocentes con MAYOR % de NO COMPETENCIA (plantel): "
            f"No se pudo determinar con certeza. Motivo: {doc_err}\n"
        )

    return (
        f"Estimado Plantel {plantel}:\n"
        "\nAnteponiendo un cordial saludo, con base al semestre ordinario del periodo 2.2526, "
        f"el plantel a su digno cargo registra {total_no_comp} estudiantes NO COMPETENTES y "
        f"{total_sin_calif} estudiantes SIN EVALUACIÓN en algún módulo.\n"
        "Esta situación requiere atención inmediata, ya que impacta directamente en los resultados académicos y "
        "en la calidad educativa que ofrecemos.\n "
        "Les exhortamos a implementar de manera urgente estrategias efectivas que permitan revertir estos indicadores y "
        "asegurar avances significativos.\n"
        "El compromiso y la acción oportuna de su equipo serán determinantes para mostrar resultados favorables en el próximo corte. \n"
        f"{extra_mod}\n"
        "\nA continuación, se presentan los 5 docentes que registran el mayor porcentaje de NO COMPETENCIA en este cierre de semestre:\n"
        f"{extra_doc}\n"
        "\nPara consultar información detallada, particular o completa sobre los avances y resultados del plantel, "
        "le invitamos a revisar el tablero institucional en el siguiente enlace:\n"
        "https://tablero-docentes.conalepmexacademica.app/\n"
        "\nSin otro particular, reciba un cordial saludo.\n"
    )


def construir_borradores_envio(plantel_sel, planteles_disponibles, tabla, df_reprobacion, df_datos, emails_map):
    objetivos = planteles_disponibles if plantel_sel == "Todos" else [plantel_sel]

    borradores = []
    sin_email = []

    for p in objetivos:
        info = emails_map.get(p, {"to": [], "cc": []})
        destinatarios = info.get("to", []) or []
        cc_list = info.get("cc", []) or []

        if not destinatarios:
            sin_email.append(p)
            continue

        fila_p = tabla[tabla["Plantel"] == p]
        total_no_comp = int(fila_p["Total estudiantes no competentes"].iloc[0]) if (not fila_p.empty and "Total estudiantes no competentes" in fila_p.columns) else 0
        total_sin_calif = contar_sin_calificaciones(df_reprobacion, p)

        top_por_semestre, semana_usada, mod_err = top_modulos_porcentaje_no_competencia_por_semestre(df_datos, p)
        top_docentes, semana_docentes, doc_err = top_docentes_porcentaje_no_competencia(df_datos, p, top_n=5)
        analisis = construir_analisis_seguimiento_plantel(
            plantel=p,
            tabla=tabla,
            total_sin_calif=total_sin_calif,
            semana_meta=EMAIL_META_SEMANA_OBJETIVO,
            meta_pct=EMAIL_META_MAX_NO_COMP_PCT,
        )

        asunto = f"Indicadores académicos - {p}"
        img_bytes = generar_imagen_grafica_seguimiento(p)
        contenido = construir_contenido_correo_plantel(
            plantel=p,
            total_no_comp=total_no_comp,
            total_sin_calif=total_sin_calif,
            top_por_semestre=top_por_semestre,
            semana_modulos=semana_usada,
            mod_err=mod_err,
            top_docentes=top_docentes,
            semana_docentes=semana_docentes,
            doc_err=doc_err,
            analisis=analisis,
            incluir_grafica=bool(img_bytes),
        )

        inline_images = []
        if img_bytes:
            inline_images.append({
                "cid": contenido["graph_cid"],
                "data": img_bytes,
                "filename": f"seguimiento_{_safe_download_name(p)}.png",
                "subtype": "png",
            })

        borradores.append({
            "plantel": p,
            "to": destinatarios,
            "cc": cc_list,
            "subject": asunto,
            "body": contenido["text"],
            "body_html": contenido["html"],
            "inline_images": inline_images,
        })

    return borradores, sin_email


def enviar_borradores(borradores):
    enviados = []
    fallidos = []
    for b in borradores:
        try:
            enviar_correo(
                b["to"],
                b["subject"],
                b["body"],
                cc=b.get("cc", []),
                cuerpo_html=b.get("body_html"),
                inline_images=b.get("inline_images", []),
            )
            enviados.append(b["plantel"])
        except Exception as e:
            fallidos.append(f"{b['plantel']} ({e})")
    return enviados, fallidos


# =========================
# Exportaciones cacheadas
# =========================
@st.cache_data(show_spinner=False)
def generar_excel_no_competentes(plantel_sel):
    df = obtener_detalle_no_competentes(plantel_sel)
    return exportar_excel(df).getvalue()


@st.cache_data(show_spinner=False)
def generar_html_no_competentes(plantel_sel):
    df = obtener_detalle_no_competentes(plantel_sel)
    return exportar_html_imprimible(
        df,
        titulo="Estudiantes NO competentes",
        subtitulo=f"Plantel: {plantel_sel}",
    ).getvalue()


@st.cache_data(show_spinner=False)
def generar_excel_sin_registro(plantel_sel):
    df = obtener_sin_registro_calificaciones(plantel_sel)
    return exportar_excel(df).getvalue()


@st.cache_data(show_spinner=False)
def generar_excel_tabla_agrupada():
    tabla_con_total = agregar_fila_total(cargar_resumen())
    return exportar_excel(tabla_con_total, filename="agrupados_no_competentes.xlsx").getvalue()


@st.cache_data(show_spinner=False)
def generar_html_tabla_agrupada():
    tabla_con_total = agregar_fila_total(cargar_resumen())
    return exportar_html_imprimible(
        tabla_con_total,
        titulo="Estudiantes agrupados por módulos NO competentes",
        subtitulo="(Vista agrupada con TOTAL)",
        filename="agrupados_no_competentes.html",
    ).getvalue()


# =========================
# Función principal
# =========================
def mostrar_indicadores_academicos():
    st.title("📊 Indicadores Académicos")

    tabla = cargar_resumen()
    df_matricula = cargar_matricula()

    is_admin = bool(st.session_state.get("administrador", False))
    plantel_usuario = st.session_state.get("plantel_usuario") or st.session_state.get("plantel")
    es_plantel = bool(plantel_usuario) and not is_admin

    permisos_codes = obtener_permisos_usuario_codigos()
    puede_enviar_email = (not es_plantel) and (PERM_SEND_EMAIL_CODE in permisos_codes)

    if not es_plantel:
        df_reprobacion = None
        planteles_disponibles = sorted(tabla["Plantel"].dropna().astype(str).unique().tolist())
        opciones_plantel = ["Todos"] + planteles_disponibles

        if "indicadores_admin_filtros_aplicados" not in st.session_state:
            st.session_state.indicadores_admin_filtros_aplicados = False

        with st.form("filtros_indicadores_admin"):
            vista = st.radio(
                "Visualización de la gráfica:",
                ["% NO competencia", "Total NO competentes"],
                horizontal=True
            )
            plantel_sel = st.selectbox("Selecciona un plantel", opciones_plantel)
            filtros_aplicados = st.form_submit_button("Aplicar filtros")

        if filtros_aplicados:
            st.session_state.indicadores_admin_filtros_aplicados = True

        if plantel_sel == "Todos":
            tabla_vista = tabla.copy()
        else:
            tabla_vista = tabla[tabla["Plantel"] == plantel_sel].copy()

        if tabla_vista.empty:
            st.warning("No hay información disponible para los filtros seleccionados.")
        else:
            sort_col = (
                "Total estudiantes no competentes"
                if vista == "Total NO competentes"
                else "% Estudiantes no competentes"
            )
            tabla_ordenada = tabla_vista.sort_values(by=sort_col, ascending=False).copy()
            tabla_ordenada["etiqueta"] = tabla_ordenada.apply(
                lambda r: f"{int(r['Total estudiantes no competentes'])} - {float(r['% Estudiantes no competentes']):.2f}%",
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

            if plantel_sel == "Todos":
                ymax = float(tabla_ordenada[y_col].max()) if not tabla_ordenada.empty else 0

                fig = go.Figure(
                    data=[
                        go.Bar(
                            x=tabla_ordenada["Plantel"],
                            y=tabla_ordenada[y_col],
                            text=tabla_ordenada["etiqueta"],
                            textposition="outside",
                            textangle=-90,
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
                    uniformtext=dict(minsize=LABEL_FONT_SIZE_ADMIN, mode="show"),
                    yaxis=dict(range=[0, ymax * Y_AXIS_PADDING_MULT if ymax else 1]),
                    margin=dict(t=90),
                )

                st.plotly_chart(fig, use_container_width=True)
            else:
                st.markdown(f"### 📈 Comportamiento semanal — {plantel_sel}")
                if not mostrar_grafica_seguimiento_plantel(plantel_sel, show_title=False, show_footer=True):
                    st.info(f"ℹ️ No hay datos de seguimiento semanal para **{plantel_sel}** en la hoja SEGUIMIENTO.")

            st.subheader("📋 Estudiantes agrupados por módulos NO competentes")
            tabla_con_total = agregar_fila_total(tabla_vista)
            st.dataframe(tabla_con_total, use_container_width=True)
            render_botones_descarga_detalle(
                tabla_con_total,
                plantel_sel,
                tipo="agrupados_no_competentes",
                key_prefix="admin_agrupado"
            )

            total_general = int(tabla_vista["Total estudiantes no competentes"].sum())
            total_matricula = float(tabla_vista["matriculaTotal"].sum())
            porcentaje_promedio = round((total_general / total_matricula) * 100, 2) if total_matricula else 0
            st.markdown(f"### 👥 Total general de estudiantes NO competentes: **{total_general:,}**")
            st.markdown(f"### 📊 Porcentaje respecto a la matrícula: **{porcentaje_promedio}%**")

        st.markdown("---")

        if plantel_sel == "Todos":
            if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
                st.markdown("### ⚠️ Estudiantes NO competentes (Detalle) — Todos")
                st.info("Presiona **Aplicar filtros** para cargar el detalle general de todos los planteles.")
            else:
                with st.spinner("Cargando detalle general de estudiantes NO competentes..."):
                    df_print = obtener_detalle_no_competentes("Todos")

                total_nc_admin = (
                    df_print["matricula"].nunique()
                    if not df_print.empty and "matricula" in df_print.columns
                    else len(df_print)
                )

                st.markdown(f"### ⚠️ Estudiantes NO competentes {total_nc_admin} (Detalle) — Todos")
                if df_print.empty:
                    st.info("ℹ️ No hay registros de NO competentes para **Todos**.")
                else:
                    mostrar_dataframe_preview(df_print)
                    render_botones_descarga_detalle(
                        df_print,
                        "Todos",
                        tipo="no_competentes",
                        key_prefix="admin_todos_nc"
                    )

            if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
                st.markdown("### 🚨 Estudiantes sin registro de Calificaciones (Detalle) — Todos")
                st.info("Presiona **Aplicar filtros** para cargar el detalle general de estudiantes sin registro.")
            else:
                with st.spinner("Cargando estudiantes sin registro de calificaciones..."):
                    df_sin_registro = obtener_sin_registro_calificaciones("Todos")

                total_sin_registro = (
                    df_sin_registro["matricula"].nunique()
                    if not df_sin_registro.empty and "matricula" in df_sin_registro.columns
                    else len(df_sin_registro)
                )

                st.markdown(f"### 🚨 Estudiantes sin registro de Calificaciones {total_sin_registro} (Detalle) — Todos")
                if df_sin_registro.empty:
                    st.info("ℹ️ No hay registros con pEspecifico = 0 para **Todos**.")
                else:
                    mostrar_dataframe_preview(df_sin_registro)
                    render_botones_descarga_detalle(
                        df_sin_registro,
                        "Todos",
                        tipo="sin_registro_calificaciones",
                        key_prefix="admin_todos_sr"
                    )

                render_seccion_impresion_por_modulos(
                    "Todos",
                    key_prefix="admin_todos_modulos"
                )
        else:
            df_print = obtener_detalle_no_competentes(plantel_sel)

            fila_sel = tabla[tabla["Plantel"] == plantel_sel]
            if not fila_sel.empty and "Total estudiantes no competentes" in fila_sel.columns:
                total_nc_admin = int(fila_sel["Total estudiantes no competentes"].iloc[0])
            else:
                total_nc_admin = df_print["matricula"].nunique() if "matricula" in df_print.columns else len(df_print)

            st.markdown(f"### ⚠️ Estudiantes NO competentes {total_nc_admin} (Detalle) — {plantel_sel}")
            if df_print.empty:
                st.info(f"ℹ️ No hay registros de NO competentes para **{plantel_sel}**.")
            else:
                mostrar_dataframe_preview(df_print)
                render_botones_descarga_detalle(
                    df_print,
                    plantel_sel,
                    tipo="no_competentes",
                    key_prefix="admin_plantel_nc"
                )

            df_sin_registro = obtener_sin_registro_calificaciones(plantel_sel)
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
                mostrar_dataframe_preview(df_sin_registro)
                render_botones_descarga_detalle(
                    df_sin_registro,
                    plantel_sel,
                    tipo="sin_registro_calificaciones",
                    key_prefix="admin_plantel_sr"
                )

            render_seccion_impresion_por_modulos(
                plantel_sel,
                key_prefix="admin_plantel_modulos"
            )

        if puede_enviar_email:
            if "confirm_send_open" not in st.session_state:
                st.session_state.confirm_send_open = False
            if "email_send_result" not in st.session_state:
                st.session_state.email_send_result = None

            if st.button("📧 Enviar correo", key="btn_enviar_correo_indicadores_v2"):
                st.session_state.confirm_send_open = True

            if st.session_state.email_send_result:
                res = st.session_state.email_send_result
                if res.get("enviados"):
                    st.success("Correo enviado correctamente a: " + ", ".join(res["enviados"]))
                if res.get("fallidos"):
                    st.warning("No se pudo enviar correo a: " + "; ".join(res["fallidos"]))
                if res.get("sin_email"):
                    st.warning("Sin Email en hoja Planteles: " + ", ".join(res["sin_email"]))

            def _confirm_ui():
                try:
                    emails_map = cargar_emails_planteles()
                except Exception as e:
                    st.error(f"No se pudo leer la hoja 'Planteles' (columna Email/Ccp): {e}")
                    return

                if df_reprobacion is None:
                    df_reprobacion_local = cargar_reprobacion()
                else:
                    df_reprobacion_local = df_reprobacion

                df_datos = cargar_datos_sheet()

                borradores, sin_email = construir_borradores_envio(
                    plantel_sel=plantel_sel,
                    planteles_disponibles=planteles_disponibles,
                    tabla=tabla,
                    df_reprobacion=df_reprobacion_local,
                    df_datos=df_datos,
                    emails_map=emails_map
                )

                if plantel_sel == "Todos":
                    aviso = "¿Está seguro de que se desea mandar la siguiente información vía correo electrónico a TODOS los planteles?"
                    st.warning(aviso)
                    if sin_email:
                        st.info("Nota: estos planteles no tienen Email en la hoja Planteles y NO recibirán correo: " + ", ".join(sin_email))

                    if borradores:
                        st.write("Se enviará un correo por plantel. Ejemplo del contenido a enviar:")
                        st.code(borradores[0]["body"])
                        st.write("Ejemplo de destinatarios:")
                        st.code("TO: " + ", ".join(borradores[0]["to"]))
                        if borradores[0].get("cc"):
                            st.code("CC: " + ", ".join(borradores[0]["cc"]))
                    else:
                        st.info("ℹ️ No hay planteles con Email para enviar.")
                else:
                    aviso = f"¿Está seguro de que se desea mandar la siguiente información vía correo electrónico al Plantel {plantel_sel}?"
                    st.warning(aviso)

                    b = next((x for x in borradores if x["plantel"] == plantel_sel), None)
                    if b is None:
                        if plantel_sel in sin_email:
                            st.info("Este plantel no tiene Email en la hoja Planteles. No se enviará nada.")
                        else:
                            st.info("No hay información para enviar.")
                    else:
                        st.code(b["body"])
                        st.code("TO: " + ", ".join(b["to"]))
                        if b.get("cc"):
                            st.code("CC: " + ", ".join(b["cc"]))

                col_ok, col_cancel = st.columns(2)
                with col_ok:
                    if st.button("✅ De acuerdo", key="btn_confirmar_envio_v2"):
                        if not borradores:
                            st.session_state.email_send_result = {"enviados": [], "fallidos": [], "sin_email": sin_email}
                            st.session_state.confirm_send_open = False
                            st.rerun()

                        with st.spinner("Enviando correos..."):
                            enviados, fallidos = enviar_borradores(borradores)

                        st.session_state.email_send_result = {"enviados": enviados, "fallidos": fallidos, "sin_email": sin_email}
                        st.session_state.confirm_send_open = False
                        st.rerun()

                with col_cancel:
                    if st.button("❌ Cancelar", key="btn_cancelar_envio_v2"):
                        st.session_state.confirm_send_open = False
                        st.rerun()

            if st.session_state.confirm_send_open:
                if hasattr(st, "dialog"):
                    @st.dialog("Confirmación")
                    def _dlg():
                        _confirm_ui()
                    _dlg()
                else:
                    with st.container():
                        _confirm_ui()
        else:
            st.info("ℹ️ Tu usuario no tiene permiso para enviar correos desde este módulo.")

        # Panel disponible solo en la vista de administrador para limpiar datos de prueba.
        if is_admin:
            render_admin_restablecer_seguimiento_academico()

    else:
        if not plantel_usuario:
            st.error("No se detectó el plantel del usuario en la sesión (plantel_usuario).")
            return

        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario].copy()

        if tabla_filtrada.empty:
            st.warning(f"No hay información disponible para el plantel {plantel_usuario}.")
            return

        st.markdown(f"### 📈 Comportamiento semanal — {plantel_usuario}")
        seguimiento_plantel = obtener_seguimiento_plantel(plantel_usuario)
        if not mostrar_grafica_seguimiento_plantel(plantel_usuario, show_title=False, show_footer=False):
            st.info(f"ℹ️ No hay datos de seguimiento semanal para **{plantel_usuario}** en la hoja SEGUIMIENTO.")

        vals = df_matricula[df_matricula["Plantel"] == plantel_usuario]["matriculaTotal"].values
        matricula_plantel = int(vals[0]) if len(vals) else 0

        if not tabla_filtrada.empty and "Total estudiantes no competentes" in tabla_filtrada.columns:
            total_nc = int(tabla_filtrada["Total estudiantes no competentes"].iloc[0])
        else:
            df_exportar_tmp = obtener_detalle_no_competentes(plantel_usuario)
            total_nc = df_exportar_tmp["matricula"].nunique() if "matricula" in df_exportar_tmp.columns else len(df_exportar_tmp)

        porcentaje_nc = float(tabla_filtrada["% Estudiantes no competentes"].iloc[0]) if "% Estudiantes no competentes" in tabla_filtrada.columns else 0.0
        tendencia = _datos_tendencia_seguimiento(seguimiento_plantel)

        _render_cards_resumen([
            {
                "titulo": "Tendencia vs semana previa",
                "valor": tendencia["valor_card"],
                "detalle": tendencia["detalle_card"],
            },
            {
                "titulo": "Matrícula",
                "valor": f"{matricula_plantel:,}",
                "detalle": f"Matrícula total del plantel {plantel_usuario}",
            },
            {
                "titulo": "Total de estudiantes NO competentes",
                "valor": f"{total_nc:,}",
                "detalle": "Total actual mostrado para el plantel.",
            },
            {
                "titulo": "Porcentaje respecto a la matrícula",
                "valor": f"{porcentaje_nc:.2f}%",
                "detalle": "Porcentaje actual de estudiantes NO competentes.",
            },
        ])

        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        df_exportar = obtener_detalle_no_competentes(plantel_usuario)

        st.subheader(f"⚠️ Estudiantes NO competentes {total_nc} (Detalle)")
        if df_exportar.empty:
            st.info("ℹ️ No hay registros de NO competentes para este plantel.")
        else:
            estudiantes_unicos_nc = (
                df_exportar["matricula"].nunique()
                if "matricula" in df_exportar.columns
                else len(df_exportar)
            )
            st.caption(
                f"Mostrando el detalle completo del plantel: "
                f"{estudiantes_unicos_nc:,} estudiante(s) único(s), "
                f"{len(df_exportar):,} registro(s) académico(s)."
            )
            mostrar_dataframe_preview(df_exportar)
            render_botones_descarga_detalle(
                df_exportar,
                plantel_usuario,
                tipo="no_competentes",
                key_prefix="plantel_nc"
            )


        df_sin_registro_plantel = obtener_sin_registro_calificaciones(plantel_usuario)

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
            estudiantes_unicos_sr = (
                df_sin_registro_plantel["matricula"].nunique()
                if "matricula" in df_sin_registro_plantel.columns
                else len(df_sin_registro_plantel)
            )
            st.caption(
                f"Mostrando el detalle completo del plantel: "
                f"{estudiantes_unicos_sr:,} estudiante(s) único(s), "
                f"{len(df_sin_registro_plantel):,} registro(s) académico(s)."
            )
            mostrar_dataframe_preview(df_sin_registro_plantel)
            render_botones_descarga_detalle(
                df_sin_registro_plantel,
                plantel_usuario,
                tipo="sin_registro_calificaciones",
                key_prefix="plantel_sr"
            )

        render_seccion_impresion_por_modulos(
            plantel_usuario,
            key_prefix="plantel_modulos"
        )

