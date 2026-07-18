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
# Rendimiento / visualización
# MAX_PREVIEW_ROWS ahora vuelve a proteger la interfaz: muestra una vista previa
# y evita mandar tablas gigantes al navegador en cada rerun de Streamlit.
MAX_PREVIEW_ROWS = int(os.getenv("MAX_PREVIEW_ROWS", "500"))
MAX_RENDER_ROWS = int(os.getenv("MAX_RENDER_ROWS", str(MAX_PREVIEW_ROWS)))
DEFAULT_TABLE_HEIGHT = int(os.getenv("DEFAULT_TABLE_HEIGHT", "520"))

# Si realmente se necesita ver todo en pantalla, el usuario podrá activarlo con checkbox.
# Para forzarlo globalmente desde servidor: ALLOW_FULL_TABLE_RENDER=true
ALLOW_FULL_TABLE_RENDER = os.getenv("ALLOW_FULL_TABLE_RENDER", "false").lower() == "true"
SHOW_FULL_TABLE_CHECKBOX = os.getenv("SHOW_FULL_TABLE_CHECKBOX", "true").lower() == "true"

# Caché rápido. Si existen archivos parquet, se usan. Si no existen, se lee Excel
# y opcionalmente se intenta crear el parquet para próximas cargas.
USE_PLANTEL_DETAIL_CACHE = os.getenv("USE_PLANTEL_DETAIL_CACHE", "false").lower() == "true"
USE_FAST_CACHE = os.getenv("USE_FAST_CACHE", "true").lower() == "true"
AUTO_WRITE_PARQUET_CACHE = os.getenv("AUTO_WRITE_PARQUET_CACHE", "true").lower() == "true"

REPROBACION_COLS = [
    "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "MODULO",
    "DOCENTE", "grado", "cvegrupo", "MINIMO",
    "pEspecifico", "pAlcanzado", "pRelativo"
]

MATRICULA_COLS = ["Plantel", "matriculaTotal"]

# Métricas internas necesarias para cálculos heredados.
# pEspecifico y pRelativo ya no se muestran en el detalle final,
# pero pEspecifico se conserva internamente para detectar registros sin evaluación.
METRICAS_ORDEN = ["pEspecifico", "pAlcanzado", "pRelativo"]
METRICAS_DETALLE_PRESENTACION = ["pAlcanzado"]
MINIMO_COL_NAME = "MINIMO"
MINIMO_DISPLAY_NAME = "Porcentaje mínimo para aprobar"

# Columnas que se conservan para cálculos internos, pero se ocultan en la tabla final.
# Se ocultan únicamente pEspecifico y pRelativo; pAlcanzado permanece visible.
COLUMNAS_METRICAS_OCULTAS_PRESENTACION = [
    "pEspecifico", "pRelativo",
    "PEspecifico", "pRelativo",
    "pEspecifico_min", "pRelativo_min",
    "PEspecifico_min", "pRelativo_min",
]

# Categorías usadas para identificar estudiantes por cantidad de módulos NO competentes.
# Se mantiene el mismo criterio del resumen: 1, 2, 3... 10 y 11 o más.
CATEGORIAS_MODULOS_NC = [str(i) for i in range(1, 11)] + ["11 o más"]

# Fila estatal que se toma desde la hoja Seguimiento.
SEGUIMIENTO_ESTATAL_NOMBRE = "CONALEP Estado de México"
VISTA_COMPORTAMIENTO_ESTATAL = "Comportamiento estatal"

# Reglas normativas para regularización y permanencia académica.
UMBRAL_ASESORIA_INTERSEMESTRAL = 56.0
MAX_MODULOS_ASESORIA_INTERSEMESTRAL = 3
MAX_MODULOS_BAJA_PARCIAL = 6

# Opciones de consulta del reporte normativo.
# Se separan de forma explícita los dos grupos solicitados:
# - Grupo 1: estudiantes que adeudan de 1 a 3 módulos.
# - Grupo 2: estudiantes que adeudan de 4 a 6 módulos.
OPCIONES_REPORTE_NORMATIVO = [
    "Todos los estudiantes",
    "GRUPO 1 — Adeudan de 1 a 3 módulos",
    "GRUPO 1 — Pueden presentar al menos una intersemestral",
    "GRUPO 1 — Todos sus módulos son intersemestrales",
    "GRUPO 1 — Necesitan asesorías combinadas",
    "GRUPO 1 — Necesitan asesorías semestrales",
    "GRUPO 1 — Información académica por validar",
    "GRUPO 2 — Adeudan de 4 a 6 módulos",
    "GRUPO 2 — Pueden presentar al menos una intersemestral",
    "GRUPO 2 — Pueden quedar con 3 módulos",
    "GRUPO 2 — Solo pueden reducir parcialmente el adeudo",
    "GRUPO 2 — Necesitan otra ruta de regularización",
    "GRUPO 2 — Información académica por validar",
    "7 o más — Deben regularizarse antes de reinscribirse",
]




# =========================
# Helpers base
# =========================
def slug(v):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(v).strip())


def obtener_numero_semana_indicadores():
    """
    Devuelve la semana académica que debe mostrarse en el encabezado.

    Importante:
    - NO usa la semana calendario del sistema.
    - Toma la semana más reciente con información desde la hoja Seguimiento.
    - Prioriza la fila estatal: CONALEP Estado de México.
    - Si no encuentra la fila estatal, revisa todas las filas de Seguimiento.
    """

    def _semana_maxima_con_datos(df_semana):
        if df_semana is None or getattr(df_semana, "empty", True):
            return None
        if "Semana_num" not in df_semana.columns:
            return None

        d = df_semana.copy()
        d["Semana_num"] = pd.to_numeric(d["Semana_num"], errors="coerce")
        d = d[d["Semana_num"].notna()].copy()

        if d.empty:
            return None

        # Preferir semanas que realmente tengan información capturada.
        # Esto evita tomar columnas futuras vacías o precargadas.
        mascara = pd.Series(False, index=d.index)
        if "Cantidad" in d.columns:
            cantidad = pd.to_numeric(d["Cantidad"], errors="coerce").fillna(0)
            mascara = mascara | (cantidad.abs() > 0)
        if "Porcentaje" in d.columns:
            porcentaje = pd.to_numeric(d["Porcentaje"], errors="coerce").fillna(0)
            mascara = mascara | (porcentaje.abs() > 0)

        if mascara.any():
            return int(d.loc[mascara, "Semana_num"].max())

        return int(d["Semana_num"].max())

    # 1) Primero intentar con la fila estatal de Seguimiento.
    try:
        seguimiento_estatal, _ = obtener_seguimiento_estatal()
        semana = _semana_maxima_con_datos(seguimiento_estatal)
        if semana is not None:
            return semana
    except Exception:
        pass

    # 2) Respaldo: revisar todas las filas de la hoja Seguimiento.
    try:
        df_seguimiento = cargar_seguimiento()
        if df_seguimiento is None or getattr(df_seguimiento, "empty", True):
            return ""

        mapping = _mapear_columnas_seguimiento(df_seguimiento)
        semanas_con_datos = []

        for _, meta in mapping.items():
            week_num = meta.get("week_num")
            if week_num is None:
                continue

            tiene_datos = False
            col_cantidad = meta.get("cantidad")
            col_porcentaje = meta.get("porcentaje")

            if col_cantidad is not None and col_cantidad in df_seguimiento.columns:
                valores = pd.to_numeric(df_seguimiento[col_cantidad], errors="coerce")
                if valores.fillna(0).abs().sum() > 0:
                    tiene_datos = True

            if col_porcentaje is not None and col_porcentaje in df_seguimiento.columns:
                valores = pd.to_numeric(df_seguimiento[col_porcentaje], errors="coerce")
                if valores.fillna(0).abs().sum() > 0:
                    tiene_datos = True

            if tiene_datos:
                semanas_con_datos.append(int(week_num))

        if semanas_con_datos:
            return max(semanas_con_datos)
    except Exception:
        pass

    return ""


def construir_titulo_indicadores():
    semana = obtener_numero_semana_indicadores()
    if semana == "" or semana is None:
        return "📊 Indicadores Académicos"
    return f"📊 Indicadores Académicos semana {semana}"


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _ensure_parent_dir(file_path):
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_excel(sheet_name, usecols=None):
    return pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, usecols=usecols)


def _write_parquet_cache_safe(df, parquet_path):
    """
    Intenta guardar caché parquet sin romper el flujo si el servidor no tiene
    pyarrow/fastparquet o permisos de escritura.
    """
    if not AUTO_WRITE_PARQUET_CACHE or df is None:
        return

    try:
        _ensure_parent_dir(parquet_path)
        df.to_parquet(parquet_path, index=False)
    except Exception:
        # La app debe seguir funcionando aunque no pueda crear parquet.
        pass


def _read_fast_or_excel(parquet_name, sheet_name, usecols=None):
    """
    Lee primero parquet si existe. Si no existe, lee Excel y deja preparado
    el parquet para acelerar las próximas ejecuciones.
    """
    parquet_path = _cache_path(parquet_name)

    if USE_FAST_CACHE and os.path.exists(parquet_path):
        try:
            return pd.read_parquet(parquet_path)
        except Exception:
            # Si el parquet está corrupto o desactualizado, se regresa a Excel.
            pass

    df = _read_excel(sheet_name, usecols=usecols)

    if USE_FAST_CACHE:
        _write_parquet_cache_safe(df, parquet_path)

    return df


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


def normalizar_columna_minimo(df):
    """
    Garantiza una columna estándar MINIMO tomada desde la hoja Reprobacion.

    Soporta variaciones como MÍNIMO, Minimo o minimo. Si la columna todavía
    no existe en el origen/caché, se crea vacía para no romper la tabla.
    """
    if df is None:
        return df

    d = df.copy()
    col_minimo = _find_col_like(d, ["MINIMO", "MÍNIMO", "Minimo", "Mínimo", "minimo"])

    if col_minimo and col_minimo != MINIMO_COL_NAME:
        d = d.rename(columns={col_minimo: MINIMO_COL_NAME})

    if MINIMO_COL_NAME not in d.columns:
        d[MINIMO_COL_NAME] = pd.NA

    return d


def ocultar_columnas_metricas_presentacion(df):
    """
    Oculta columnas de porcentaje/ponderación en vistas finales sin eliminarlas
    del flujo de cálculo. Se usa únicamente para presentación/exportación final.
    """
    if df is None:
        return df

    d = df.copy()
    ocultas = {_norm_txt(c) for c in COLUMNAS_METRICAS_OCULTAS_PRESENTACION}
    columnas_a_ocultar = [c for c in d.columns if _norm_txt(c) in ocultas]
    return d.drop(columns=columnas_a_ocultar, errors="ignore")


def renombrar_minimo_presentacion(df):
    """
    Renombra MINIMO únicamente para vistas/exportaciones finales.

    Internamente se conserva el nombre MINIMO para no afectar la lectura desde
    Excel, el caché ni cualquier cálculo que dependa del nombre original.
    """
    if df is None:
        return df

    d = df.copy()
    if MINIMO_COL_NAME in d.columns:
        d = d.rename(columns={MINIMO_COL_NAME: MINIMO_DISPLAY_NAME})
    return d


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


def _preparar_columnas_detalle(df, incluir_metricas_internas=False):
    """
    Prepara el detalle para mostrar/exportar.

    Por requerimiento, las columnas pEspecifico y pRelativo no se muestran en
    la tabla final. Sin embargo, siguen existiendo en la carga completa para no
    romper cálculos internos como la detección de registros sin calificación.
    """
    df = normalizar_columna_minimo(df.copy())
    df = asegurar_metricas(df)

    columnas_base = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA",
        "MODULO", "DOCENTE", "grado", "cvegrupo"
    ]

    metricas = METRICAS_ORDEN if incluir_metricas_internas else METRICAS_DETALLE_PRESENTACION

    # Orden solicitado para la vista de detalle:
    # pAlcanzado debe mostrarse antes del mínimo requerido.
    orden = (
        [c for c in columnas_base if c in df.columns]
        + [c for c in metricas if c in df.columns]
        + [c for c in [MINIMO_COL_NAME] if c in df.columns]
    )

    if orden:
        return df[orden]

    return df




def preparar_detalle_no_competentes_presentacion(df):
    """
    Formatea específicamente la tabla de la sección:
    "Detalle de estudiantes con sus respectivos módulos NO competentes.".

    Resultado esperado en la vista final:
    - Incluye el mínimo tomado de la hoja Reprobacion.
    - Muestra el mínimo con el encabezado: Porcentaje mínimo para aprobar.
    - Oculta pEspecifico.
    - Oculta pRelativo.
    - Mantiene pAlcanzado visible antes del mínimo requerido.

    Esta función es solo de presentación; los cálculos internos siguen usando
    cargar_reprobacion(), donde pEspecifico, pRelativo y MINIMO permanecen disponibles.
    """
    if df is None:
        return df

    d = normalizar_columna_minimo(df.copy())
    d = ocultar_columnas_metricas_presentacion(d)

    columnas_preferidas = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA",
        "MODULO", "DOCENTE", "grado", "cvegrupo",
        "pAlcanzado", MINIMO_COL_NAME,
    ]

    orden = [c for c in columnas_preferidas if c in d.columns]
    resto = [c for c in d.columns if c not in orden]

    if orden:
        d = d[orden + resto]

    return renombrar_minimo_presentacion(d)

def _next_dataframe_widget_key(prefix="df_preview"):
    """Genera llaves estables por rerun para evitar DuplicateWidgetID."""
    counter_key = "_indicadores_dataframe_widget_counter"
    current = int(st.session_state.get(counter_key, 0)) + 1
    st.session_state[counter_key] = current
    return f"{prefix}_{current}"


def mostrar_dataframe_preview(df, max_rows=None, height=DEFAULT_TABLE_HEIGHT):
    """
    Muestra una vista previa segura para rendimiento.

    No elimina funcionalidad: si el usuario necesita ver todos los registros,
    puede activar el checkbox de tabla completa. Por defecto se evita enviar
    DataFrames muy grandes al navegador, que es una causa común de lentitud,
    timeout o cierre de sesión en Streamlit.
    """
    if df is None:
        st.info("No hay datos para mostrar.")
        return

    total = len(df)
    max_rows = int(max_rows or MAX_RENDER_ROWS or MAX_PREVIEW_ROWS)

    if total == 0:
        st.caption("Mostrando 0 registro(s).")
        st.dataframe(df, use_container_width=True, height=height)
        return

    show_full = ALLOW_FULL_TABLE_RENDER or total <= max_rows

    if total > max_rows and SHOW_FULL_TABLE_CHECKBOX:
        show_full = st.checkbox(
            f"Mostrar los {total:,} registros en pantalla (puede tardar)",
            value=ALLOW_FULL_TABLE_RENDER,
            key=_next_dataframe_widget_key("mostrar_todo_dataframe"),
            help=(
                "Por rendimiento, el tablero muestra primero una vista previa. "
                "Activa esta opción solo cuando realmente necesites ver todos los registros en pantalla."
            ),
        )

    if show_full:
        st.caption(f"Mostrando {total:,} de {total:,} registro(s).")
        st.dataframe(df, use_container_width=True, height=height)
    else:
        df_preview = df.head(max_rows)
        st.caption(
            f"Mostrando vista previa de {len(df_preview):,} de {total:,} registro(s). "
            "Esto mejora el tiempo de carga y evita saturar la sesión."
        )
        st.dataframe(df_preview, use_container_width=True, height=height)


# =========================
# Carga de datos
# =========================
@st.cache_data(show_spinner=False)
def cargar_reprobacion():
    df = _read_fast_or_excel("reprobacion.parquet", "Reprobacion", usecols=None)

    # Si existe un parquet anterior sin MINIMO, se intenta leer nuevamente desde
    # Excel para traer la columna nueva desde la hoja Reprobacion.
    col_minimo_actual = _find_col_like(df, ["MINIMO", "MÍNIMO", "Minimo", "Mínimo", "minimo"])
    if not col_minimo_actual:
        try:
            df_excel = _read_excel("Reprobacion", usecols=None)
            if _find_col_like(df_excel, ["MINIMO", "MÍNIMO", "Minimo", "Mínimo", "minimo"]):
                df = df_excel
        except Exception:
            pass

    df = normalizar_columna_minimo(df)
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
    # Se usa la carga completa porque pEspecifico ya no se muestra en el detalle,
    # pero sigue siendo el criterio interno para detectar registros sin evaluación.
    df = cargar_reprobacion()
    if plantel_sel != "Todos":
        df = df[df["Plantel"] == plantel_sel].copy()

    if "pEspecifico" not in df.columns:
        return _preparar_columnas_detalle(df.iloc[0:0].copy())

    df_sin = df[df["pEspecifico"] == 0].copy()
    return _preparar_columnas_detalle(df_sin)


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


def _join_percentage_values(series):
    """
    Concatena los valores de pAlcanzado respetando el orden de los registros.

    No elimina valores repetidos, porque cada porcentaje debe conservar su
    correspondencia posicional con el módulo mostrado en
    MODULOS_NO_COMPETENTES.

    Ejemplo:
        MODULOS_NO_COMPETENTES: Módulo A | Módulo B
        PORCENTAJES_ALCANZADOS: 56.25% | 58%
    """
    values = []

    for value in series.tolist():
        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except Exception:
            pass

        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]

        if pd.notna(numeric):
            # Se muestran hasta dos decimales sin ceros innecesarios.
            text = f"{float(numeric):.2f}".rstrip("0").rstrip(".")
            values.append(f"{text}%")
            continue

        text = str(value).strip()
        if not text or text.lower() in ("nan", "none", "null"):
            continue

        # Respaldo para valores de texto que ya incluyan o no el símbolo %.
        values.append(text if text.endswith("%") else f"{text}%")

    return " | ".join(values)


def agregar_conteo_modulos_no_competentes(df, ordenar=True):
    """
    Agrega a cada registro académico dos columnas:
    - modulos_nc: cantidad de módulos/registros NO competentes del estudiante.
    - categoria_modulos_nc: 1, 2, 3... 10, 11 o más.

    Optimización: usa groupby().transform("size") para evitar crear un DataFrame
    auxiliar y hacer merge. Esto reduce memoria y tiempo en detalles grandes.
    """
    if df is None or getattr(df, "empty", True):
        base_cols = list(df.columns) if df is not None else []
        return pd.DataFrame(columns=base_cols + ["modulos_nc", "categoria_modulos_nc"])

    d = df.copy()
    d = d.drop(columns=["modulos_nc", "categoria_modulos_nc"], errors="ignore")

    if "matricula" not in d.columns:
        d["modulos_nc"] = 1
        d["categoria_modulos_nc"] = "1"
        return d

    group_cols = ["matricula"]
    if "Plantel" in d.columns:
        group_cols = ["Plantel", "matricula"]

    d["modulos_nc"] = (
        d.groupby(group_cols, dropna=False)["matricula"]
        .transform("size")
        .fillna(0)
        .astype(int)
    )
    d["categoria_modulos_nc"] = d["modulos_nc"].apply(_categoria_modulos_nc)

    if ordenar:
        sort_cols = [c for c in ["Plantel", "modulos_nc", "ESTUDIANTE", "matricula", "MODULO"] if c in d.columns]
        if sort_cols:
            ascending = [True] * len(sort_cols)
            if "modulos_nc" in sort_cols:
                ascending[sort_cols.index("modulos_nc")] = False
            d = d.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)

    return d


def filtrar_detalle_por_categorias_modulos(df, categorias):
    if df is None or getattr(df, "empty", True):
        d = agregar_conteo_modulos_no_competentes(df, ordenar=False)
    elif {"modulos_nc", "categoria_modulos_nc"}.issubset(df.columns):
        d = df.copy()
    else:
        d = agregar_conteo_modulos_no_competentes(df, ordenar=False)

    if d.empty or not categorias:
        return d.iloc[0:0].copy()

    categorias_norm = {str(c).strip() for c in categorias}
    return d[d["categoria_modulos_nc"].astype(str).isin(categorias_norm)].copy()


def construir_resumen_estudiantes_por_modulos(df_detalle):
    """
    Convierte el detalle académico a una vista de una fila por estudiante para
    identificación o impresión.

    La tabla incluye:
    - módulos NO competentes,
    - porcentaje alcanzado en cada módulo, y
    - docentes relacionados.

    Los módulos y sus porcentajes se concatenan con el separador | y conservan
    el mismo orden. Por ejemplo:

        MODULOS_NO_COMPETENTES: Módulo A | Módulo B
        PORCENTAJES_ALCANZADOS: 56.25% | 58%
    """
    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame()

    if {"modulos_nc", "categoria_modulos_nc"}.issubset(df_detalle.columns):
        d = df_detalle.copy()
    else:
        d = agregar_conteo_modulos_no_competentes(df_detalle, ordenar=False)

    if d.empty:
        return pd.DataFrame()

    if "matricula" not in d.columns:
        return ocultar_columnas_metricas_presentacion(d.copy())

    group_cols = ["matricula"]
    if "Plantel" in d.columns:
        group_cols = ["Plantel", "matricula"]

    # Se ordenan conjuntamente los registros antes de agrupar para asegurar que
    # cada porcentaje conserve la misma posición que su módulo correspondiente.
    sort_detail_cols = group_cols.copy()
    for col in ["MODULO", "DOCENTE"]:
        if col in d.columns and col not in sort_detail_cols:
            sort_detail_cols.append(col)

    if sort_detail_cols:
        d = d.sort_values(sort_detail_cols, kind="stable").reset_index(drop=True)

    agg = {}
    for col in ["ESTUDIANTE", "CARRERA", "grado", "cvegrupo", "modulos_nc", "categoria_modulos_nc"]:
        if col in d.columns:
            agg[col] = "first"

    if "MODULO" in d.columns:
        # No se eliminan duplicados para conservar la relación 1 a 1 con
        # PORCENTAJES_ALCANZADOS.
        agg["MODULO"] = lambda serie: " | ".join(
            str(value).strip()
            for value in serie.tolist()
            if pd.notna(value)
            and str(value).strip()
            and str(value).strip().lower() not in ("nan", "none", "null")
        )

    if "pAlcanzado" in d.columns:
        agg["pAlcanzado"] = _join_percentage_values

    if "DOCENTE" in d.columns:
        agg["DOCENTE"] = _join_unique_values

    resumen = d.groupby(group_cols, dropna=False, sort=False).agg(agg).reset_index()

    rename_map = {
        "MODULO": "MODULOS_NO_COMPETENTES",
        "pAlcanzado": "PORCENTAJES_ALCANZADOS",
        "DOCENTE": "DOCENTES_RELACIONADOS",
    }
    resumen = resumen.rename(columns=rename_map)

    orden = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "grado", "cvegrupo",
        "modulos_nc", "categoria_modulos_nc", "MODULOS_NO_COMPETENTES",
        "PORCENTAJES_ALCANZADOS", "DOCENTES_RELACIONADOS"
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

    return ocultar_columnas_metricas_presentacion(resumen)




def _clasificar_situacion_normativa(
    modulos_nc,
    modulos_intersemestrales,
    modulos_semestrales,
    modulos_sin_porcentaje=0,
):
    """
    Clasifica a cada estudiante separando dos decisiones:

    1. Si cumple el límite académico relacionado con la reinscripción.
    2. Qué tipo de regularización necesita para sus módulos pendientes.

    Los porcentajes faltantes se colocan en una categoría propia. Esto evita
    presentar como definitiva una ruta que todavía depende de validar datos.
    """
    def _entero(valor):
        try:
            return int(valor or 0)
        except Exception:
            return 0

    total = _entero(modulos_nc)
    inter = _entero(modulos_intersemestrales)
    sin_pct = _entero(modulos_sin_porcentaje)

    if total <= 0:
        return "Sin clasificación"

    # GRUPO 1: cumple el límite académico de hasta tres módulos.
    if total <= MAX_MODULOS_ASESORIA_INTERSEMESTRAL:
        if sin_pct > 0:
            return "Irregular - requiere validación de porcentaje"
        if inter == total:
            return "Intersemestral completo"
        if inter > 0:
            return "Irregular - ruta mixta"
        return "Irregular - asesoría semestral"

    # GRUPO 2: baja parcial. Primero se verifica si ya existen suficientes
    # módulos elegibles conocidos para poder quedar con un máximo de tres.
    if total <= MAX_MODULOS_BAJA_PARCIAL:
        necesarios_para_reducir_a_tres = max(
            total - MAX_MODULOS_ASESORIA_INTERSEMESTRAL,
            0,
        )
        intersemestrales_programables = min(
            inter,
            MAX_MODULOS_ASESORIA_INTERSEMESTRAL,
        )

        if intersemestrales_programables >= necesarios_para_reducir_a_tres:
            return "Baja parcial - rescate intersemestral posible"
        if sin_pct > 0:
            return "Baja parcial - requiere validación de porcentaje"
        if intersemestrales_programables > 0:
            return "Baja parcial - avance intersemestral parcial"
        return "Baja parcial - sin oportunidad intersemestral inmediata"

    return "No candidato a reinscripción"

def _descripcion_ruta_normativa(
    clasificacion,
    modulos_nc=0,
    modulos_intersemestrales=0,
    modulos_semestrales=0,
    modulos_sin_porcentaje=0,
    modulos_necesarios_rescate=0,
    modulos_intersemestrales_programables=0,
):
    """Construye una explicación personalizada y comprensible de la ruta."""
    def _entero(valor):
        try:
            return int(valor or 0)
        except Exception:
            return 0

    total = _entero(modulos_nc)
    inter = _entero(modulos_intersemestrales)
    sem = _entero(modulos_semestrales)
    sin_pct = _entero(modulos_sin_porcentaje)
    necesarios = _entero(modulos_necesarios_rescate)
    programables = _entero(modulos_intersemestrales_programables)
    clasificacion = str(clasificacion)

    if clasificacion == "Intersemestral completo":
        return (
            f"Adeuda {total} módulo(s). Todos alcanzan al menos {UMBRAL_ASESORIA_INTERSEMESTRAL:.0f}%, "
            "por lo que puede solicitar asesorías intersemestrales para todos, sujeto a programación, "
            "disponibilidad y acreditación. Por adeudar como máximo 3 módulos, cumple el límite académico "
            "ordinario para reinscripción."
        )

    if clasificacion == "Irregular - ruta mixta":
        return (
            f"Adeuda {total} módulo(s): {inter} puede(n) atenderse mediante asesoría intersemestral y "
            f"{sem + sin_pct} requiere(n) ruta semestral o validación. Cumple el límite académico ordinario "
            "para reinscripción porque adeuda como máximo 3 módulos."
        )

    if clasificacion == "Irregular - asesoría semestral":
        return (
            f"Adeuda {total} módulo(s) y ninguno alcanza {UMBRAL_ASESORIA_INTERSEMESTRAL:.0f}%. "
            "Puede solicitar reinscripción por encontrarse dentro del máximo de 3 adeudos y regularizar "
            "los módulos mediante asesorías semestrales, recursamiento u otro medio autorizado."
        )

    if clasificacion == "Irregular - requiere validación de porcentaje":
        return (
            f"Adeuda {total} módulo(s) y existen {sin_pct} registro(s) sin porcentaje alcanzado. "
            "Cumple el límite académico ordinario para reinscripción, pero antes de definir la asesoría "
            "debe validarse o capturarse el porcentaje faltante."
        )

    if clasificacion == "Baja parcial - rescate intersemestral posible":
        return (
            f"Adeuda {total} módulos y necesita acreditar al menos {necesarios} para quedar con 3. "
            f"Tiene {inter} módulo(s) elegible(s) y puede programar hasta {programables}. Si acredita al menos "
            f"{necesarios}, podría recuperar el límite académico ordinario para solicitar reinscripción. "
            "La clasificación señala una oportunidad de rescate, no una acreditación garantizada."
        )

    if clasificacion == "Baja parcial - avance intersemestral parcial":
        restantes = max(total - programables, 0)
        return (
            f"Adeuda {total} módulos y necesita acreditar {necesarios} para quedar con 3, pero solo puede "
            f"programar {programables} intersemestral(es). Aun acreditándolos conservaría aproximadamente "
            f"{restantes} módulo(s); requiere una ruta complementaria y, en su caso, valoración del Comité "
            "Técnico Escolar."
        )

    if clasificacion == "Baja parcial - requiere validación de porcentaje":
        return (
            f"Adeuda {total} módulos y se encuentra en baja parcial. Hay {sin_pct} módulo(s) sin porcentaje "
            "alcanzado; no debe descartarse al estudiante hasta validar esos datos, porque podrían modificar "
            "su oportunidad de rescate intersemestral."
        )

    if clasificacion == "Baja parcial - sin oportunidad intersemestral inmediata":
        return (
            f"Adeuda {total} módulos y ninguno alcanza {UMBRAL_ASESORIA_INTERSEMESTRAL:.0f}%. "
            "La intervención debe concentrarse en asesorías semestrales, recursamiento, ASCA u otro medio "
            "autorizado. No cumple todavía el límite académico ordinario de reinscripción."
        )

    if clasificacion == "No candidato a reinscripción":
        return (
            f"Adeuda {total} módulos. No es candidato a reinscripción ordinaria hasta reducir el adeudo "
            "a un máximo de 3. Puede continuar la regularización por los medios autorizados; esta condición "
            "no equivale automáticamente a baja definitiva."
        )

    return "No fue posible determinar una situación normativa."



def _construir_decision_academica(
    clasificacion,
    total,
    inter,
    sem,
    sin_pct,
    programables,
    necesarios,
):
    """Devuelve textos breves para las tablas y los concentrados."""
    if total <= 3:
        grupo = "GRUPO 1 — 1 a 3 módulos"
        cumple_limite = "Sí"
        condicion = (
            "Sí cumple el límite académico de hasta 3 módulos para solicitar reinscripción. "
            "Todavía debe cumplir los demás requisitos administrativos del plantel."
        )

        if clasificacion == "Intersemestral completo":
            oportunidad = "Intersemestral completo"
            resultado = "Todos sus módulos pendientes pueden presentarse en intersemestral."
            accion = "Solicitar reinscripción y programar sus asesorías intersemestrales."
            prioridad = "1 - Oportunidad inmediata"
        elif clasificacion == "Irregular - ruta mixta":
            oportunidad = "Asesorías combinadas"
            resultado = (
                f"Puede presentar {inter} módulo(s) en intersemestral y atender "
                f"{sem} módulo(s) mediante asesorías semestrales."
            )
            accion = "Solicitar reinscripción y programar asesorías intersemestrales y semestrales."
            prioridad = "2 - Seguimiento combinado"
        elif clasificacion == "Irregular - requiere validación de porcentaje":
            oportunidad = "Información académica por validar"
            resultado = f"Falta validar el porcentaje de {sin_pct} módulo(s) antes de definir la ruta."
            accion = "Validar los porcentajes faltantes y después asignar la asesoría correspondiente."
            prioridad = "1 - Validación urgente"
        else:
            oportunidad = "Asesorías semestrales"
            resultado = "Sus módulos pendientes deben atenderse mediante asesorías semestrales."
            accion = "Solicitar reinscripción y programar sus asesorías semestrales."
            prioridad = "2 - Atención semestral"

    elif total <= 6:
        grupo = "GRUPO 2 — 4 a 6 módulos"
        cumple_limite = "No"
        condicion = (
            "No cumple todavía el límite académico de reinscripción porque adeuda más de 3 módulos. "
            "Debe reducir el adeudo o seguir la ruta institucional autorizada."
        )

        if clasificacion == "Baja parcial - rescate intersemestral posible":
            oportunidad = "Puede quedar con 3 módulos"
            resultado = (
                f"Si acredita al menos {necesarios} de sus módulos intersemestrales, "
                "podría quedar dentro del límite académico de reinscripción."
            )
            accion = "Priorizar las intersemestrales y verificar el resultado antes de la reinscripción."
            prioridad = "1 - Rescate prioritario"
        elif clasificacion == "Baja parcial - requiere validación de porcentaje":
            oportunidad = "Información académica por validar"
            resultado = (
                f"Falta validar el porcentaje de {sin_pct} módulo(s); esos datos podrían cambiar "
                "su oportunidad de recuperación."
            )
            accion = "Validar los porcentajes antes de definir la estrategia de regularización."
            prioridad = "1 - Validación urgente"
        elif clasificacion == "Baja parcial - avance intersemestral parcial":
            oportunidad = "Reducción parcial del adeudo"
            resultado = (
                f"Puede presentar {programables} intersemestral(es), pero aun acreditándolas "
                "continuaría con más de 3 módulos pendientes."
            )
            accion = "Programar las intersemestrales y completar un plan semestral o valoración del CTE."
            prioridad = "2 - Plan complementario"
        else:
            oportunidad = "Otra ruta de regularización"
            resultado = "No tiene módulos elegibles para intersemestral con la información disponible."
            accion = "Definir asesorías semestrales, recursamiento, ASCA o la alternativa autorizada."
            prioridad = "3 - Atención prioritaria"

    else:
        grupo = "GRUPO 3 — 7 o más módulos"
        cumple_limite = "No"
        condicion = "No puede solicitar reinscripción ordinaria hasta reducir el adeudo a un máximo de 3 módulos."
        oportunidad = "Regularización previa a reinscripción"
        resultado = "Debe reducir primero el número total de módulos pendientes."
        accion = "Construir un plan integral de regularización y seguimiento individual."
        prioridad = "4 - Restricción de reinscripción"

    return {
        "GRUPO_ANALISIS": grupo,
        "CUMPLE_LIMITE_ACADEMICO_REINSCRIPCION": cumple_limite,
        "PUEDE_PRESENTAR_INTERSEMESTRAL": "Sí" if inter > 0 else "No",
        "PUEDE_TOMAR_ASESORIA_SEMESTRAL": (
            "Sí" if sem > 0 else ("Por definir" if sin_pct > 0 else "No")
        ),
        "CONDICION_REINSCRIPCION": condicion,
        "OPORTUNIDAD_REGULARIZACION": oportunidad,
        "RESULTADO_PROYECTADO": resultado,
        "ACCION_RECOMENDADA": accion,
        "PRIORIDAD_ATENCION": prioridad,
    }

def _join_all_text_values(series):
    """Concatena todos los valores no vacíos, conservando orden y duplicados."""
    values = []
    for value in series.tolist():
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if not text or text.lower() in ("nan", "none", "null"):
            continue
        values.append(text)
    return " | ".join(values)



def _join_detalle_modulo_normativo(grupo):
    """Construye Módulo (porcentaje - tipo de asesoría) en una sola celda."""
    partes = []
    for _, row in grupo.iterrows():
        modulo = str(row.get("MODULO", "")).strip()
        pct = pd.to_numeric(pd.Series([row.get("pAlcanzado")]), errors="coerce").iloc[0]
        if pd.isna(pct):
            pct_text = "Sin dato"
        else:
            pct_text = f"{float(pct):.2f}".rstrip("0").rstrip(".") + "%"
        tipo = str(row.get("TIPO_ASESORIA_MODULO", "")).strip()
        if modulo:
            partes.append(f"{modulo} ({pct_text} - {tipo})")
    return " | ".join(partes)

def construir_reporte_normativo_estudiantes(df_detalle):
    """
    Construye una fila por estudiante con la información necesaria para decidir:

    - A qué grupo pertenece: 1 a 3, 4 a 6 o 7 o más módulos.
    - Si cumple el límite académico ordinario para reinscripción.
    - Cuántos módulos puede presentar en asesoría intersemestral.
    - Cuántos módulos requieren asesoría semestral.
    - Si un estudiante de 4 a 6 puede reducir su adeudo a 3 mediante
      intersemestrales o únicamente lograr un avance parcial.

    Los porcentajes vacíos no se consideran automáticamente semestrales; se
    identifican por separado para que el plantel valide la información.
    """
    columnas_salida = [
        "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "grado", "cvegrupo",
        "GRUPO_ANALISIS", "modulos_nc", "modulos_intersemestrales",
        "modulos_semestrales", "modulos_sin_porcentaje",
        "modulos_intersemestrales_programables",
        "modulos_necesarios_para_reducir_a_3",
        "modulos_restantes_si_acredita_intersemestrales",
        "CUMPLE_LIMITE_ACADEMICO_REINSCRIPCION",
        "PUEDE_PRESENTAR_INTERSEMESTRAL",
        "PUEDE_TOMAR_ASESORIA_SEMESTRAL",
        "CONDICION_REINSCRIPCION",
        "OPORTUNIDAD_REGULARIZACION",
        "RESULTADO_PROYECTADO",
        "ACCION_RECOMENDADA",
        "PRIORIDAD_ATENCION",
        "CLASIFICACION_NORMATIVA", "RUTA_NORMATIVA",
        "MODULOS_INTERSEMESTRALES", "MODULOS_SEMESTRALES",
        "MODULOS_SIN_PORCENTAJE",
        "MODULOS_NO_COMPETENTES", "PORCENTAJES_ALCANZADOS",
        "TIPO_ASESORIA_POR_MODULO", "DOCENTES_RELACIONADOS", "DETALLE_NORMATIVO"
    ]

    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame(columns=columnas_salida)

    d = agregar_conteo_modulos_no_competentes(df_detalle, ordenar=False)
    if d.empty or "matricula" not in d.columns:
        return pd.DataFrame(columns=columnas_salida)

    if "pAlcanzado" not in d.columns:
        d["pAlcanzado"] = pd.NA

    d["__pAlcanzado_num__"] = pd.to_numeric(d["pAlcanzado"], errors="coerce")
    d["__sin_porcentaje__"] = d["__pAlcanzado_num__"].isna()
    d["__es_intersemestral__"] = d["__pAlcanzado_num__"].ge(UMBRAL_ASESORIA_INTERSEMESTRAL)
    d["__es_semestral__"] = (
        d["__pAlcanzado_num__"].notna()
        & d["__pAlcanzado_num__"].lt(UMBRAL_ASESORIA_INTERSEMESTRAL)
    )

    d["TIPO_ASESORIA_MODULO"] = "Sin porcentaje - validar"
    d.loc[d["__es_intersemestral__"], "TIPO_ASESORIA_MODULO"] = "Intersemestral"
    d.loc[d["__es_semestral__"], "TIPO_ASESORIA_MODULO"] = "Semestral"

    group_cols = ["matricula"]
    if "Plantel" in d.columns:
        group_cols = ["Plantel", "matricula"]

    sort_cols = [c for c in group_cols + ["MODULO", "DOCENTE"] if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols, kind="stable").reset_index(drop=True)

    rows = []
    for keys, grupo in d.groupby(group_cols, dropna=False, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)

        row = dict(zip(group_cols, keys))
        first = grupo.iloc[0]

        for col in ["ESTUDIANTE", "CARRERA", "grado", "cvegrupo"]:
            if col in grupo.columns:
                row[col] = first.get(col)

        total = int(pd.to_numeric(grupo["modulos_nc"], errors="coerce").fillna(0).iloc[0])
        inter = int(grupo["__es_intersemestral__"].sum())
        sem = int(grupo["__es_semestral__"].sum())
        sin_pct = int(grupo["__sin_porcentaje__"].sum())
        programables = min(inter, MAX_MODULOS_ASESORIA_INTERSEMESTRAL)
        necesarios = max(total - MAX_MODULOS_ASESORIA_INTERSEMESTRAL, 0) if 4 <= total <= 6 else 0
        restantes = max(total - programables, 0)

        clasificacion = _clasificar_situacion_normativa(
            total,
            inter,
            sem,
            modulos_sin_porcentaje=sin_pct,
        )

        row["modulos_nc"] = total
        row["modulos_intersemestrales"] = inter
        row["modulos_semestrales"] = sem
        row["modulos_sin_porcentaje"] = sin_pct
        row["modulos_intersemestrales_programables"] = programables
        row["modulos_necesarios_para_reducir_a_3"] = necesarios
        row["modulos_restantes_si_acredita_intersemestrales"] = restantes
        row["CLASIFICACION_NORMATIVA"] = clasificacion

        decision = _construir_decision_academica(
            clasificacion=clasificacion,
            total=total,
            inter=inter,
            sem=sem,
            sin_pct=sin_pct,
            programables=programables,
            necesarios=necesarios,
        )
        row.update(decision)

        row["RUTA_NORMATIVA"] = _descripcion_ruta_normativa(
            clasificacion,
            modulos_nc=total,
            modulos_intersemestrales=inter,
            modulos_semestrales=sem,
            modulos_sin_porcentaje=sin_pct,
            modulos_necesarios_rescate=necesarios,
            modulos_intersemestrales_programables=programables,
        )

        if "MODULO" in grupo.columns:
            row["MODULOS_NO_COMPETENTES"] = _join_all_text_values(grupo["MODULO"])
            row["MODULOS_INTERSEMESTRALES"] = _join_all_text_values(
                grupo.loc[grupo["__es_intersemestral__"], "MODULO"]
            )
            row["MODULOS_SEMESTRALES"] = _join_all_text_values(
                grupo.loc[grupo["__es_semestral__"], "MODULO"]
            )
            row["MODULOS_SIN_PORCENTAJE"] = _join_all_text_values(
                grupo.loc[grupo["__sin_porcentaje__"], "MODULO"]
            )
        else:
            row["MODULOS_NO_COMPETENTES"] = ""
            row["MODULOS_INTERSEMESTRALES"] = ""
            row["MODULOS_SEMESTRALES"] = ""
            row["MODULOS_SIN_PORCENTAJE"] = ""

        row["PORCENTAJES_ALCANZADOS"] = _join_percentage_values(grupo["pAlcanzado"])
        row["TIPO_ASESORIA_POR_MODULO"] = _join_all_text_values(grupo["TIPO_ASESORIA_MODULO"])

        if "DOCENTE" in grupo.columns:
            row["DOCENTES_RELACIONADOS"] = _join_unique_values(grupo["DOCENTE"])
        else:
            row["DOCENTES_RELACIONADOS"] = ""

        row["DETALLE_NORMATIVO"] = _join_detalle_modulo_normativo(grupo)
        rows.append(row)

    resumen = pd.DataFrame(rows)
    for col in columnas_salida:
        if col not in resumen.columns:
            resumen[col] = pd.NA

    resumen = resumen[columnas_salida]
    sort_cols = [c for c in ["Plantel", "PRIORIDAD_ATENCION", "modulos_nc", "ESTUDIANTE", "matricula"] if c in resumen.columns]
    if sort_cols:
        ascending = [True] * len(sort_cols)
        if "modulos_nc" in sort_cols:
            ascending[sort_cols.index("modulos_nc")] = False
        resumen = resumen.sort_values(sort_cols, ascending=ascending, kind="stable").reset_index(drop=True)

    return resumen


def construir_resumen_normativo(df_estudiantes):
    """Devuelve los valores utilizados por las tarjetas y el concentrado."""
    empty = {
        "total_nc": 0,
        "uno_a_tres": 0,
        "uno_a_tres_reinscripcion_ordinaria": 0,
        "uno_a_tres_con_intersemestral": 0,
        "intersemestral_completo": 0,
        "irregular_mixta": 0,
        "irregular_semestral": 0,
        "validar_porcentaje_1a3": 0,
        "cuatro_a_seis": 0,
        "cuatro_a_seis_con_intersemestral": 0,
        "baja_parcial": 0,
        "rescate_intersemestral_posible": 0,
        "avance_intersemestral_parcial": 0,
        "sin_oportunidad_intersemestral": 0,
        "validar_porcentaje_4a6": 0,
        "no_reinscripcion": 0,
        "irregulares_1a3": 0,
    }
    if df_estudiantes is None or getattr(df_estudiantes, "empty", True):
        return empty

    clas = df_estudiantes["CLASIFICACION_NORMATIVA"].astype(str)
    total_modulos = pd.to_numeric(df_estudiantes["modulos_nc"], errors="coerce").fillna(0)
    inter_modulos = pd.to_numeric(
        df_estudiantes.get("modulos_intersemestrales", 0),
        errors="coerce",
    ).fillna(0)

    mask_1a3 = total_modulos.between(1, MAX_MODULOS_ASESORIA_INTERSEMESTRAL)
    mask_4a6 = total_modulos.between(4, MAX_MODULOS_BAJA_PARCIAL)

    inter_completo = int((clas == "Intersemestral completo").sum())
    combinadas = int((clas == "Irregular - ruta mixta").sum())
    semestrales = int((clas == "Irregular - asesoría semestral").sum())
    validar_1a3 = int((clas == "Irregular - requiere validación de porcentaje").sum())

    rescate = int((clas == "Baja parcial - rescate intersemestral posible").sum())
    parcial = int((clas == "Baja parcial - avance intersemestral parcial").sum())
    otra_ruta = int((clas == "Baja parcial - sin oportunidad intersemestral inmediata").sum())
    validar_4a6 = int((clas == "Baja parcial - requiere validación de porcentaje").sum())
    no_reins = int((clas == "No candidato a reinscripción").sum())

    return {
        "total_nc": int(len(df_estudiantes)),
        "uno_a_tres": int(mask_1a3.sum()),
        "uno_a_tres_reinscripcion_ordinaria": int(mask_1a3.sum()),
        "uno_a_tres_con_intersemestral": int((mask_1a3 & inter_modulos.gt(0)).sum()),
        "intersemestral_completo": inter_completo,
        "irregular_mixta": combinadas,
        "irregular_semestral": semestrales,
        "validar_porcentaje_1a3": validar_1a3,
        "cuatro_a_seis": int(mask_4a6.sum()),
        "cuatro_a_seis_con_intersemestral": int((mask_4a6 & inter_modulos.gt(0)).sum()),
        "baja_parcial": int(mask_4a6.sum()),
        "rescate_intersemestral_posible": rescate,
        "avance_intersemestral_parcial": parcial,
        "sin_oportunidad_intersemestral": otra_ruta,
        "validar_porcentaje_4a6": validar_4a6,
        "no_reinscripcion": no_reins,
        "irregulares_1a3": combinadas + semestrales + validar_1a3,
    }


def filtrar_reporte_normativo(df_estudiantes, opcion):
    """Filtra la relación de estudiantes con nombres comprensibles para el usuario."""
    if df_estudiantes is None or getattr(df_estudiantes, "empty", True):
        return df_estudiantes.copy() if df_estudiantes is not None else pd.DataFrame()

    d = df_estudiantes.copy()
    clas = d["CLASIFICACION_NORMATIVA"].astype(str)
    total = pd.to_numeric(d["modulos_nc"], errors="coerce").fillna(0)
    inter = pd.to_numeric(d.get("modulos_intersemestrales", 0), errors="coerce").fillna(0)

    if opcion in ("Todos los estudiantes", "Reporte completo"):
        return d

    if opcion in (
        "GRUPO 1 — Adeudan de 1 a 3 módulos",
        "GRUPO 1 — Estudiantes con 1 a 3 módulos",
        "Estudiantes irregulares (1 a 3 módulos)",
    ):
        return d[total.between(1, 3)].copy()

    if opcion == "GRUPO 1 — Pueden presentar al menos una intersemestral":
        return d[total.between(1, 3) & inter.gt(0)].copy()

    if opcion in (
        "GRUPO 1 — Todos sus módulos son intersemestrales",
        "GRUPO 1 — Todos sus módulos pueden ir a intersemestral",
    ):
        return d[clas == "Intersemestral completo"].copy()

    if opcion in (
        "GRUPO 1 — Necesitan asesorías combinadas",
        "GRUPO 1 — Reinscripción ordinaria con ruta mixta",
    ):
        return d[clas == "Irregular - ruta mixta"].copy()

    if opcion in (
        "GRUPO 1 — Necesitan asesorías semestrales",
        "GRUPO 1 — Reinscripción ordinaria con ruta semestral",
    ):
        return d[clas == "Irregular - asesoría semestral"].copy()

    if opcion in (
        "GRUPO 1 — Información académica por validar",
        "GRUPO 1 — Requieren validar porcentajes",
    ):
        return d[clas == "Irregular - requiere validación de porcentaje"].copy()

    if opcion in (
        "GRUPO 2 — Adeudan de 4 a 6 módulos",
        "GRUPO 2 — Estudiantes con 4 a 6 módulos",
        "Baja parcial (4 a 6 módulos)",
    ):
        return d[total.between(4, 6)].copy()

    if opcion == "GRUPO 2 — Pueden presentar al menos una intersemestral":
        return d[total.between(4, 6) & inter.gt(0)].copy()

    if opcion in (
        "GRUPO 2 — Pueden quedar con 3 módulos",
        "GRUPO 2 — Rescate intersemestral posible",
        "Rescate intersemestral posible (4 a 6 módulos)",
    ):
        return d[clas == "Baja parcial - rescate intersemestral posible"].copy()

    if opcion in (
        "GRUPO 2 — Solo pueden reducir parcialmente el adeudo",
        "GRUPO 2 — Avance intersemestral parcial",
        "Avance intersemestral parcial (4 a 6 módulos)",
    ):
        return d[clas == "Baja parcial - avance intersemestral parcial"].copy()

    if opcion in (
        "GRUPO 2 — Necesitan otra ruta de regularización",
        "GRUPO 2 — Sin oportunidad intersemestral inmediata",
        "Sin oportunidad intersemestral inmediata (4 a 6 módulos)",
    ):
        return d[clas == "Baja parcial - sin oportunidad intersemestral inmediata"].copy()

    if opcion in (
        "GRUPO 2 — Información académica por validar",
        "GRUPO 2 — Requieren validar porcentajes",
    ):
        return d[clas == "Baja parcial - requiere validación de porcentaje"].copy()

    if opcion in (
        "7 o más — Deben regularizarse antes de reinscribirse",
        "7 o más — No candidatos a reinscripción ordinaria",
        "No candidatos a reinscripción (7 o más módulos)",
    ):
        return d[clas == "No candidato a reinscripción"].copy()

    if opcion == "Asesorías intersemestrales":
        return d[inter.gt(0)].copy()

    return d

def obtener_reporte_normativo_plantel(plantel_sel):
    """Obtiene el reporte normativo del plantel o el consolidado estatal."""
    detalle = obtener_detalle_no_competentes(plantel_sel)
    return construir_reporte_normativo_estudiantes(detalle)



def _columnas_reporte_normativo_presentacion(df):
    """Ordena y renombra todas las columnas técnicas para consulta avanzada."""
    if df is None:
        return pd.DataFrame()

    d = df.copy()
    rename_map = {
        "Plantel": "Plantel",
        "ESTUDIANTE": "Estudiante",
        "matricula": "Matrícula",
        "CARRERA": "Carrera",
        "grado": "Grado",
        "cvegrupo": "Grupo",
        "GRUPO_ANALISIS": "Grupo de análisis",
        "modulos_nc": "Módulos no competentes",
        "modulos_intersemestrales": "Módulos elegibles para intersemestral",
        "modulos_semestrales": "Módulos con ruta semestral",
        "modulos_sin_porcentaje": "Módulos sin porcentaje",
        "modulos_intersemestrales_programables": "Intersemestrales programables (máx. 3)",
        "modulos_necesarios_para_reducir_a_3": "Módulos que necesita acreditar para quedar con 3",
        "modulos_restantes_si_acredita_intersemestrales": "Módulos restantes si acredita los programables",
        "CUMPLE_LIMITE_ACADEMICO_REINSCRIPCION": "Cumple límite académico para reinscripción",
        "PUEDE_PRESENTAR_INTERSEMESTRAL": "Puede presentar intersemestral",
        "PUEDE_TOMAR_ASESORIA_SEMESTRAL": "Puede tomar asesoría semestral",
        "CONDICION_REINSCRIPCION": "Condición de reinscripción",
        "OPORTUNIDAD_REGULARIZACION": "Oportunidad de regularización",
        "RESULTADO_PROYECTADO": "Resultado proyectado",
        "ACCION_RECOMENDADA": "Acción recomendada",
        "PRIORIDAD_ATENCION": "Prioridad de atención",
        "CLASIFICACION_NORMATIVA": "Clasificación técnica",
        "RUTA_NORMATIVA": "Explicación técnica de la ruta",
        "MODULOS_INTERSEMESTRALES": "Módulos para intersemestral",
        "MODULOS_SEMESTRALES": "Módulos para semestral",
        "MODULOS_SIN_PORCENTAJE": "Módulos pendientes de validar",
        "MODULOS_NO_COMPETENTES": "Módulos no competentes (detalle)",
        "PORCENTAJES_ALCANZADOS": "Porcentajes alcanzados",
        "TIPO_ASESORIA_POR_MODULO": "Tipo de asesoría por módulo",
        "DOCENTES_RELACIONADOS": "Docentes relacionados",
        "DETALLE_NORMATIVO": "Detalle por módulo",
    }
    d = d.rename(columns=rename_map)
    orden = [c for c in rename_map.values() if c in d.columns]
    resto = [c for c in d.columns if c not in orden]
    return d[orden + resto]



def _columnas_reporte_sencillo(df, mostrar_plantel=True):
    """
    Presenta una relación compacta para lectura inmediata.

    La información técnica completa se conserva en el apartado desplegable, por
    lo que esta vista puede concentrarse en las decisiones que debe tomar el
    plantel sin perder datos ni cálculos.
    """
    columnas_vacias = [
        "Plantel", "Estudiante", "Matrícula", "Carrera", "Grado / Grupo",
        "Módulos pendientes", "Reinscripción", "Situación actual",
        "Asesorías identificadas", "Meta inmediata", "Qué debe hacer ahora",
        "Módulos y porcentajes",
    ]
    if df is None or getattr(df, "empty", True):
        columnas = columnas_vacias if mostrar_plantel else columnas_vacias[1:]
        return pd.DataFrame(columns=columnas)

    d = df.copy()

    def _num(row, col):
        try:
            value = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
            return int(value) if pd.notna(value) else 0
        except Exception:
            return 0

    def _texto_cantidad(cantidad, singular, plural):
        cantidad = int(cantidad or 0)
        return f"{cantidad} {singular if cantidad == 1 else plural}"

    def _reinscripcion(row):
        total = _num(row, "modulos_nc")
        clas = str(row.get("CLASIFICACION_NORMATIVA", ""))
        if 1 <= total <= 3:
            return "Sí: cumple el límite académico"
        if 4 <= total <= 6 and clas == "Baja parcial - rescate intersemestral posible":
            return "Después de acreditar lo necesario y quedar con 3"
        return "No todavía"

    def _situacion(row):
        clas = str(row.get("CLASIFICACION_NORMATIVA", ""))
        textos = {
            "Intersemestral completo": "Todos sus módulos pueden presentarse en intersemestral",
            "Irregular - ruta mixta": "Necesita combinar asesorías intersemestrales y semestrales",
            "Irregular - asesoría semestral": "Sus módulos deben atenderse mediante asesorías semestrales",
            "Irregular - requiere validación de porcentaje": "Faltan porcentajes para definir correctamente las asesorías",
            "Baja parcial - rescate intersemestral posible": "Puede reducir el adeudo hasta quedar con 3 módulos",
            "Baja parcial - avance intersemestral parcial": "Puede reducir el adeudo, pero todavía quedaría con más de 3 módulos",
            "Baja parcial - sin oportunidad intersemestral inmediata": "Necesita una ruta diferente a la intersemestral",
            "Baja parcial - requiere validación de porcentaje": "Faltan porcentajes para confirmar su oportunidad de recuperación",
            "No candidato a reinscripción": "Debe reducir el adeudo antes de solicitar reinscripción",
        }
        return textos.get(clas, str(row.get("OPORTUNIDAD_REGULARIZACION", "Por revisar")))

    def _asesorias(row):
        inter = _num(row, "modulos_intersemestrales")
        sem = _num(row, "modulos_semestrales")
        sin_pct = _num(row, "modulos_sin_porcentaje")
        partes = []
        if inter > 0:
            partes.append(_texto_cantidad(inter, "intersemestral", "intersemestrales"))
        if sem > 0:
            partes.append(_texto_cantidad(sem, "semestral", "semestrales"))
        if sin_pct > 0:
            partes.append(_texto_cantidad(sin_pct, "porcentaje por validar", "porcentajes por validar"))
        return " | ".join(partes) if partes else "Sin asesoría definida"

    def _meta(row):
        total = _num(row, "modulos_nc")
        necesarios = _num(row, "modulos_necesarios_para_reducir_a_3")
        sin_pct = _num(row, "modulos_sin_porcentaje")
        clas = str(row.get("CLASIFICACION_NORMATIVA", ""))

        if sin_pct > 0 and "validación" in clas:
            return _texto_cantidad(sin_pct, "porcentaje faltante por validar", "porcentajes faltantes por validar")
        if total <= 3:
            return "Regularizar los módulos pendientes"
        if 4 <= total <= 6:
            return _texto_cantidad(necesarios, "módulo por acreditar para quedar con 3", "módulos por acreditar para quedar con 3")
        return "Reducir el adeudo a un máximo de 3 módulos"

    def _grado_grupo(row):
        grado = row.get("grado", "")
        grupo = row.get("cvegrupo", "")
        grado = "" if pd.isna(grado) else str(grado).strip()
        grupo = "" if pd.isna(grupo) else str(grupo).strip()
        if grado and grupo:
            return f"{grado} / {grupo}"
        return grado or grupo

    d["Plantel_s"] = d.get("Plantel", "")
    d["Estudiante_s"] = d.get("ESTUDIANTE", "")
    d["Matrícula_s"] = d.get("matricula", "")
    d["Carrera_s"] = d.get("CARRERA", "")
    d["Grado / Grupo_s"] = d.apply(_grado_grupo, axis=1)
    d["Módulos pendientes_s"] = pd.to_numeric(d.get("modulos_nc", 0), errors="coerce").fillna(0).astype(int)
    d["Reinscripción_s"] = d.apply(_reinscripcion, axis=1)
    d["Situación actual_s"] = d.apply(_situacion, axis=1)
    d["Asesorías identificadas_s"] = d.apply(_asesorias, axis=1)
    d["Meta inmediata_s"] = d.apply(_meta, axis=1)
    d["Qué debe hacer ahora_s"] = d.get("ACCION_RECOMENDADA", "")
    d["Módulos y porcentajes_s"] = d.get("DETALLE_NORMATIVO", "")

    rename = {
        "Plantel_s": "Plantel",
        "Estudiante_s": "Estudiante",
        "Matrícula_s": "Matrícula",
        "Carrera_s": "Carrera",
        "Grado / Grupo_s": "Grado / Grupo",
        "Módulos pendientes_s": "Módulos pendientes",
        "Reinscripción_s": "Reinscripción",
        "Situación actual_s": "Situación actual",
        "Asesorías identificadas_s": "Asesorías identificadas",
        "Meta inmediata_s": "Meta inmediata",
        "Qué debe hacer ahora_s": "Qué debe hacer ahora",
        "Módulos y porcentajes_s": "Módulos y porcentajes",
    }
    salida = d[list(rename.keys())].rename(columns=rename)
    if not mostrar_plantel:
        salida = salida.drop(columns=["Plantel"], errors="ignore")
    return salida


def _columnas_concentrado_imprimible(df):
    """Devuelve una relación compacta y comprensible para impresión y seguimiento."""
    d = _columnas_reporte_sencillo(df, mostrar_plantel=True)
    columnas = [
        "Plantel", "Estudiante", "Matrícula", "Carrera", "Grado / Grupo",
        "Módulos pendientes", "Reinscripción", "Situación actual",
        "Asesorías identificadas", "Meta inmediata", "Qué debe hacer ahora",
        "Módulos y porcentajes",
    ]
    return d[[c for c in columnas if c in d.columns]].copy()

def construir_concentrado_por_plantel(df_estudiantes):
    """Construye un resumen por plantel con categorías que no se traslapan."""
    columnas = [
        "Plantel", "Total no competentes",
        "Grupo 1: 1 a 3", "G1: intersemestral completo",
        "G1: asesorías combinadas", "G1: asesorías semestrales",
        "Grupo 2: 4 a 6", "G2: pueden quedar con 3",
        "G2: reducción parcial", "G2: otra ruta",
        "Información por validar", "7 o más",
    ]
    if df_estudiantes is None or getattr(df_estudiantes, "empty", True):
        return pd.DataFrame(columns=columnas)

    d = df_estudiantes.copy()
    if "Plantel" not in d.columns:
        d["Plantel"] = "Ámbito seleccionado"

    rows = []
    for plantel, grupo in d.groupby("Plantel", dropna=False, sort=True):
        r = construir_resumen_normativo(grupo)
        rows.append({
            "Plantel": plantel,
            "Total no competentes": r["total_nc"],
            "Grupo 1: 1 a 3": r["uno_a_tres"],
            "G1: intersemestral completo": r["intersemestral_completo"],
            "G1: asesorías combinadas": r["irregular_mixta"],
            "G1: asesorías semestrales": r["irregular_semestral"],
            "Grupo 2: 4 a 6": r["cuatro_a_seis"],
            "G2: pueden quedar con 3": r["rescate_intersemestral_posible"],
            "G2: reducción parcial": r["avance_intersemestral_parcial"],
            "G2: otra ruta": r["sin_oportunidad_intersemestral"],
            "Información por validar": r["validar_porcentaje_1a3"] + r["validar_porcentaje_4a6"],
            "7 o más": r["no_reinscripcion"],
        })

    concentrado = pd.DataFrame(rows, columns=columnas)
    if len(concentrado) > 1:
        total = {col: "" for col in concentrado.columns}
        total["Plantel"] = "TOTAL ESTATAL"
        for col in concentrado.columns:
            if col != "Plantel":
                total[col] = int(pd.to_numeric(concentrado[col], errors="coerce").fillna(0).sum())
        concentrado = pd.concat([concentrado, pd.DataFrame([total])], ignore_index=True)
    return concentrado

def construir_resumen_categorias_modulos(df_detalle):
    if df_detalle is None or getattr(df_detalle, "empty", True):
        return pd.DataFrame(columns=["Módulos NO competentes", "Estudiantes", "Registros académicos"])

    if {"modulos_nc", "categoria_modulos_nc"}.issubset(df_detalle.columns):
        d = df_detalle.copy()
    else:
        d = agregar_conteo_modulos_no_competentes(df_detalle, ordenar=False)

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


def _normalizar_valor_grado_filtro(value):
    """Normaliza valores de grado para mostrarlos y compararlos en filtros."""
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]

    return text


def _orden_grado_filtro(value):
    """Ordena grados activos en forma natural: 1, 2, 3... y después texto."""
    text = _normalizar_valor_grado_filtro(value)
    sem_key = _sem_key(text)
    if sem_key is not None:
        return (0, int(sem_key), text)

    nums = re.findall(r"\d+", text)
    if nums:
        return (0, int(nums[0]), text)

    return (1, 999, _norm_txt(text))


def obtener_grados_activos_desde_detalle(df):
    """Devuelve los grados presentes en el detalle, incluyendo solo valores activos/no vacíos."""
    if df is None or getattr(df, "empty", True) or "grado" not in df.columns:
        return []

    grados = []
    for value in df["grado"].dropna().tolist():
        text = _normalizar_valor_grado_filtro(value)
        if not text or text.lower() in ("nan", "none", "null"):
            continue
        grados.append(text)

    grados = list(dict.fromkeys(grados))
    return sorted(grados, key=_orden_grado_filtro)


def filtrar_detalle_por_grado_activo(df, grado_sel):
    """Filtra el detalle por grado activo. La opción Todos conserva el comportamiento original."""
    if df is None or getattr(df, "empty", True):
        return df

    if not grado_sel or str(grado_sel).strip() == "Todos" or "grado" not in df.columns:
        return df.copy()

    objetivo = _normalizar_valor_grado_filtro(grado_sel)
    d = df.copy()
    valores_grado = d["grado"].apply(_normalizar_valor_grado_filtro)
    return d[valores_grado == objetivo].copy()


def render_seccion_impresion_por_modulos(plantel_sel, key_prefix="modulos_nc"):
    """
    Sección reutilizable para administradores y planteles.
    Permite filtrar e imprimir estudiantes por cantidad de módulos NO competentes:
    1, 2, 3... 10 y 11 o más.

    Actualización:
    - Agrega filtro de grado activo con opción Todos.
    - El filtro de grado se aplica antes del conteo por módulos para que la
      clasificación corresponda exactamente al grado seleccionado.
    """
    df_base = obtener_detalle_no_competentes(plantel_sel)

    st.markdown("---")
    st.subheader("Selecciona e imprime la relación de estudiantes clasificados según el número de módulos en los que no resultaron competentes.")
    st.caption(
        "Selecciona el grado activo y una o varias categorías. Ejemplo: si quieres atender a los estudiantes "
        "con 7 módulos no competentes, selecciona únicamente **7**. La tabla mostrará exactamente el filtro seleccionado."
    )

    if df_base is None or df_base.empty:
        st.info(f"ℹ️ No hay registros de NO competentes para **{plantel_sel}**.")
        return

    grados_disponibles = obtener_grados_activos_desde_detalle(df_base)
    opciones_grado = ["Todos"] + grados_disponibles

    if grados_disponibles:
        grado_sel = st.selectbox(
            "Grado activo",
            options=opciones_grado,
            index=0,
            key=f"{key_prefix}_{_safe_download_name(plantel_sel)}_grado_activo",
            help="Selecciona un grado específico o deja Todos para conservar la vista completa."
        )
    else:
        grado_sel = "Todos"
        st.info("ℹ️ No se detectó la columna o valores de grado; se muestra la información completa.")

    df_base_filtrado = filtrar_detalle_por_grado_activo(df_base, grado_sel)

    if df_base_filtrado is None or df_base_filtrado.empty:
        st.info(f"ℹ️ No hay registros de NO competentes para el grado activo **{grado_sel}**.")
        return

    df_con_conteo = agregar_conteo_modulos_no_competentes(df_base_filtrado, ordenar=False)
    resumen_categorias = construir_resumen_categorias_modulos(df_con_conteo)

    categorias_disponibles = sorted(
        df_con_conteo["categoria_modulos_nc"].dropna().astype(str).unique().tolist(),
        key=_orden_categoria_modulos_nc
    )

    seleccion = st.multiselect(
        "Cantidad de módulos NO competentes a identificar/imprimir",
        options=categorias_disponibles,
        default=categorias_disponibles,
        key=f"{key_prefix}_{_safe_download_name(plantel_sel)}_{_safe_download_name(grado_sel)}_categorias",
        help="Puedes seleccionar 1, 2, 3... 10 o 11 o más. También puedes combinar varias categorías."
    )

    if not seleccion:
        st.info("Selecciona al menos una categoría para mostrar e imprimir estudiantes.")
        return

    df_detalle_filtrado = filtrar_detalle_por_categorias_modulos(df_con_conteo, seleccion)
    df_resumen_estudiantes = construir_resumen_estudiantes_por_modulos(df_detalle_filtrado)

    estudiantes_unicos = (
        df_resumen_estudiantes["matricula"].nunique()
        if not df_resumen_estudiantes.empty and "matricula" in df_resumen_estudiantes.columns
        else len(df_resumen_estudiantes)
    )
    registros = len(df_detalle_filtrado)
    categorias_label = _label_categorias_modulos(seleccion)
    grado_label = str(grado_sel or "Todos")

    st.markdown(
        f"#### Resultado filtrado: **{estudiantes_unicos:,} estudiante(s)** | "
        f"**{registros:,} registro(s) académico(s)** | Grado activo: **{grado_label}** | "
        f"Categoría(s): **{categorias_label}**"
    )

    if df_detalle_filtrado.empty:
        st.info("No hay estudiantes para el grado y categoría seleccionados.")
        return

    st.caption(
        "Tabla final para identificación o impresión: una fila por estudiante con sus módulos, "
        "porcentajes alcanzados y docentes relacionados. Los módulos y porcentajes aparecen en el "
        "mismo orden y se separan con el símbolo |."
    )
    df_resumen_estudiantes = ocultar_columnas_metricas_presentacion(df_resumen_estudiantes)
    mostrar_dataframe_preview(df_resumen_estudiantes, height=430)
    render_botones_descarga_detalle(
        df_resumen_estudiantes,
        plantel_sel,
        tipo="resumen_por_modulos_no_competentes",
        key_prefix=f"{key_prefix}_resumen_{_safe_download_name(grado_label)}_{_safe_download_name(categorias_label)}"
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


def _normalizar_porcentaje_seguimiento_con_matricula(df_semana, matricula=0.0):
    """
    Normaliza una serie de porcentajes usando una matrícula conocida.

    Se usa para el comportamiento estatal porque la matrícula debe leerse desde
    la misma fila de la hoja Seguimiento, no desde la hoja Matricula por plantel.
    """
    if df_semana is None or getattr(df_semana, "empty", True) or "Porcentaje" not in df_semana.columns:
        return df_semana

    out = df_semana.copy()
    valores = pd.to_numeric(out["Porcentaje"], errors="coerce")

    max_abs = valores.abs().max(skipna=True)
    if pd.isna(max_abs):
        out["Porcentaje"] = 0.0
        return out

    try:
        matricula = float(matricula or 0)
    except Exception:
        matricula = 0.0

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
    cantidades_label = pd.to_numeric(df_semana["Cantidad"], errors="coerce").fillna(0).round().astype(int).astype(str)
    porcentajes_label = pd.to_numeric(df_semana["Porcentaje"], errors="coerce").fillna(0).map(lambda v: f"{float(v):.2f}%")
    df_semana["Etiqueta"] = cantidades_label + " - " + porcentajes_label
    return df_semana


def _filtrar_fila_estatal_seguimiento(df_seguimiento):
    """Localiza la fila CONALEP Estado de México dentro de la hoja Seguimiento."""
    if df_seguimiento is None or getattr(df_seguimiento, "empty", True):
        return pd.DataFrame()

    objetivo_norm = _norm_txt(SEGUIMIENTO_ESTATAL_NOMBRE)
    columnas_preferidas = [
        _find_col_like(df_seguimiento, ["Plantel"]),
        _find_col_like(df_seguimiento, ["Nombre", "Institución", "Institucion", "Entidad"]),
    ]
    columnas_preferidas = [c for c in columnas_preferidas if c is not None]

    columnas_busqueda = columnas_preferidas or list(df_seguimiento.columns)

    for col in columnas_busqueda:
        try:
            valores_norm = df_seguimiento[col].apply(_norm_txt)
            exact = df_seguimiento[valores_norm == objetivo_norm].copy()
            if not exact.empty:
                return exact

            contiene = df_seguimiento[
                valores_norm.apply(lambda v: bool(v) and (objetivo_norm in v or v in objetivo_norm))
            ].copy()
            if not contiene.empty:
                return contiene
        except Exception:
            continue

    return pd.DataFrame()


def _obtener_matricula_fila_seguimiento(df_fila):
    """Extrae la matrícula desde la fila estatal de Seguimiento."""
    if df_fila is None or getattr(df_fila, "empty", True):
        return 0.0

    col_matricula = _find_col_like(
        df_fila,
        [
            "matriculaTotal", "matrícula total", "matricula total",
            "Matrícula", "Matricula", "matricula", "MATRICULA",
        ],
    )

    if not col_matricula or col_matricula not in df_fila.columns:
        return 0.0

    valores = pd.to_numeric(df_fila[col_matricula], errors="coerce").fillna(0)
    if valores.empty:
        return 0.0

    # Normalmente existe una sola fila estatal; si hubiera más de una, se toma
    # el total acumulado para no perder información.
    return float(valores.sum())


@st.cache_data(show_spinner=False)
def obtener_seguimiento_estatal():
    """
    Devuelve el comportamiento estatal desde la hoja Seguimiento.

    La fuente es exclusivamente la fila que dice CONALEP Estado de México.
    De esa misma fila se toman:
    - matrícula,
    - columnas Sem X,
    - columnas Sem X %.
    """
    columnas_default = ["Semana", "Cantidad", "Porcentaje", "Etiqueta", "Semana_num"]

    df_seguimiento = cargar_seguimiento()
    if df_seguimiento is None or getattr(df_seguimiento, "empty", True):
        return pd.DataFrame(columns=columnas_default), 0.0

    df_estado = _filtrar_fila_estatal_seguimiento(df_seguimiento)
    if df_estado is None or df_estado.empty:
        return pd.DataFrame(columns=columnas_default), 0.0

    matricula_estatal = _obtener_matricula_fila_seguimiento(df_estado)
    mapping = _mapear_columnas_seguimiento(df_estado)
    if not mapping:
        return pd.DataFrame(columns=columnas_default), matricula_estatal

    rows = []
    for semana, meta in mapping.items():
        col_cantidad = meta.get("cantidad")
        col_porcentaje = meta.get("porcentaje")

        cantidad = 0
        porcentaje = 0.0

        if col_cantidad is not None and col_cantidad in df_estado.columns:
            cantidad = pd.to_numeric(df_estado[col_cantidad], errors="coerce").fillna(0).sum()

        if col_porcentaje is not None and col_porcentaje in df_estado.columns:
            porcentaje = pd.to_numeric(df_estado[col_porcentaje], errors="coerce").fillna(0).mean()

        rows.append({
            "Semana": semana,
            "Cantidad": int(round(float(cantidad))) if pd.notna(cantidad) else 0,
            "Porcentaje": float(porcentaje) if pd.notna(porcentaje) else 0.0,
            "Semana_num": meta.get("week_num") or 0,
        })

    df_semana = pd.DataFrame(rows)
    if df_semana.empty:
        return pd.DataFrame(columns=columnas_default), matricula_estatal

    df_semana = df_semana.sort_values("Semana_num").reset_index(drop=True)
    df_semana = _normalizar_porcentaje_seguimiento_con_matricula(df_semana, matricula_estatal)

    cantidades_label = pd.to_numeric(df_semana["Cantidad"], errors="coerce").fillna(0).round().astype(int).astype(str)
    porcentajes_label = pd.to_numeric(df_semana["Porcentaje"], errors="coerce").fillna(0).map(lambda v: f"{float(v):.2f}%")
    df_semana["Etiqueta"] = cantidades_label + " - " + porcentajes_label

    return df_semana, matricula_estatal


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




def _obtener_estilo_tarjeta_semaforo(nivel):
    """
    Devuelve la paleta visual de una tarjeta.

    Los colores son únicamente una ayuda visual para facilitar la lectura:
    - verde: ruta de regularización intersemestral disponible;
    - amarillo: requiere atención, seguimiento o regularización;
    - rojo: restricción académica o situación prioritaria;
    - azul: dato informativo, sin interpretación normativa adicional.
    """
    paletas = {
        "verde": {
            "fondo": "#ECFDF3",
            "borde": "#12B76A",
            "texto": "#067647",
            "punto": "#12B76A",
            "sombra": "rgba(18,183,106,0.22)",
            "etiqueta": "Ruta intersemestral",
        },
        "amarillo": {
            "fondo": "#FFFAEB",
            "borde": "#F79009",
            "texto": "#B54708",
            "punto": "#F79009",
            "sombra": "rgba(247,144,9,0.22)",
            "etiqueta": "Atención y seguimiento",
        },
        "rojo": {
            "fondo": "#FEF3F2",
            "borde": "#F04438",
            "texto": "#B42318",
            "punto": "#F04438",
            "sombra": "rgba(240,68,56,0.24)",
            "etiqueta": "Situación prioritaria",
        },
        "rojo_critico": {
            "fondo": "#FFF1F3",
            "borde": "#D92D20",
            "texto": "#912018",
            "punto": "#D92D20",
            "sombra": "rgba(217,45,32,0.30)",
            "etiqueta": "Restricción de reinscripción",
        },
        "azul": {
            "fondo": "#EFF8FF",
            "borde": "#2E90FA",
            "texto": "#175CD3",
            "punto": "#2E90FA",
            "sombra": "rgba(46,144,250,0.20)",
            "etiqueta": "Dato informativo",
        },
        "neutral": {
            "fondo": "#FFFFFF",
            "borde": "#D0D5DD",
            "texto": "#475467",
            "punto": "#98A2B3",
            "sombra": "rgba(16,24,40,0.08)",
            "etiqueta": "Información",
        },
    }
    return paletas.get(str(nivel or "neutral").strip().lower(), paletas["neutral"])


def _render_cards_resumen(items):
    """
    Renderiza tarjetas informativas.

    Conserva el comportamiento anterior y admite, de forma opcional, el campo
    ``semaforo`` con los valores verde, amarillo, rojo, rojo_critico, azul o
    neutral. Las tarjetas que no indiquen ese campo mantienen el estilo neutro.
    """
    if not items:
        return

    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        titulo = str(item.get("titulo", "")).strip()
        valor = str(item.get("valor", "")).strip()
        detalle = str(item.get("detalle", "")).strip()
        fundamento = str(item.get("fundamento", "")).strip()
        nivel = str(item.get("semaforo", "neutral")).strip().lower()
        estilo = _obtener_estilo_tarjeta_semaforo(nivel)
        etiqueta_semaforo = str(
            item.get("etiqueta_semaforo") or estilo.get("etiqueta", "Información")
        ).strip()

        fundamento_html = ""
        if fundamento:
            fundamento_html = (
                "<div style='font-size:11px;color:#184C3B;margin-top:10px;line-height:1.35;"
                "font-weight:700;border-top:1px solid rgba(16,24,40,0.12);padding-top:8px;'>"
                f"{escape(fundamento)}</div>"
            )

        indicador_html = ""
        if nivel != "neutral":
            indicador_html = (
                "<div style='display:flex;align-items:center;gap:7px;margin-bottom:10px;'>"
                f"<span style='width:11px;height:11px;border-radius:50%;background:{estilo['punto']};"
                f"box-shadow:0 0 0 4px {estilo['sombra']};display:inline-block;'></span>"
                f"<span style='font-size:10px;letter-spacing:.25px;text-transform:uppercase;"
                f"font-weight:800;color:{estilo['texto']};'>{escape(etiqueta_semaforo)}</span>"
                "</div>"
            )

        with col:
            if nivel == "neutral":
                # Se conserva exactamente el estilo previo para las tarjetas generales
                # del tablero que no forman parte del semáforo normativo.
                st.markdown(
                    f"""
                    <div style="border:1px solid #D0D5DD;border-radius:14px;padding:16px 14px;
                                background:#FFFFFF;min-height:148px;
                                box-shadow:0 1px 2px rgba(16,24,40,0.05);">
                        <div style="font-size:13px;color:#667085;margin-bottom:8px;font-weight:600;">{escape(titulo)}</div>
                        <div style="font-size:24px;color:#101828;font-weight:800;line-height:1.15;">{escape(valor)}</div>
                        <div style="font-size:12px;color:#667085;margin-top:10px;line-height:1.35;">{escape(detalle)}</div>
                        {fundamento_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div style="border:2px solid {estilo['borde']};border-radius:16px;padding:16px 14px;
                                background:{estilo['fondo']};min-height:178px;
                                box-shadow:0 5px 16px {estilo['sombra']};position:relative;overflow:hidden;">
                        <div style="position:absolute;left:0;top:0;bottom:0;width:7px;background:{estilo['borde']};"></div>
                        <div style="padding-left:5px;">
                            {indicador_html}
                            <div style="font-size:13px;color:{estilo['texto']};margin-bottom:8px;font-weight:750;line-height:1.25;">
                                {escape(titulo)}
                            </div>
                            <div style="font-size:28px;color:#101828;font-weight:850;line-height:1.05;">{escape(valor)}</div>
                            <div style="font-size:12px;color:#475467;margin-top:10px;line-height:1.4;">{escape(detalle)}</div>
                            {fundamento_html}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )




def render_tarjetas_normativas(resumen):
    """Muestra primero el total y después categorías claras que no deben sumarse dos veces."""
    st.markdown("#### 1. Panorama general")
    st.caption(
        "Primero se identifica cuántos módulos adeuda cada estudiante. Después se determina cómo puede regularizarlos."
    )
    _render_cards_resumen([
        {
            "titulo": "Total de estudiantes con módulos pendientes",
            "valor": f"{resumen.get('total_nc', 0):,}",
            "detalle": "Tienen al menos un módulo no acreditado.",
            "fundamento": "Seguimiento académico: artículos 100 a 103.",
            "semaforo": "azul",
            "etiqueta_semaforo": "Panorama general",
        },
        {
            "titulo": "Adeudan de 1 a 3 módulos",
            "valor": f"{resumen.get('uno_a_tres', 0):,}",
            "detalle": "Cumplen el límite académico de módulos para solicitar reinscripción.",
            "fundamento": "Artículo 68, fracción III.",
            "semaforo": "azul",
            "etiqueta_semaforo": "Grupo 1",
        },
        {
            "titulo": "Adeudan de 4 a 6 módulos",
            "valor": f"{resumen.get('cuatro_a_seis', 0):,}",
            "detalle": "Deben reducir el adeudo o seguir la ruta institucional autorizada.",
            "fundamento": "Artículos 73 y 75.",
            "semaforo": "amarillo",
            "etiqueta_semaforo": "Grupo 2",
        },
        {
            "titulo": "Adeudan 7 o más módulos",
            "valor": f"{resumen.get('no_reinscripcion', 0):,}",
            "detalle": "Deben regularizarse antes de solicitar reinscripción ordinaria.",
            "fundamento": "Artículo 75.",
            "semaforo": "rojo_critico",
            "etiqueta_semaforo": "Restricción de reinscripción",
        },
    ])

    # -------------------------
    # GRUPO 1
    # -------------------------
    total_g1 = int(resumen.get("uno_a_tres", 0) or 0)
    con_inter_g1 = int(resumen.get("uno_a_tres_con_intersemestral", 0) or 0)
    completo_g1 = int(resumen.get("intersemestral_completo", 0) or 0)
    combinadas_g1 = int(resumen.get("irregular_mixta", 0) or 0)
    semestrales_g1 = int(resumen.get("irregular_semestral", 0) or 0)
    validar_g1 = int(resumen.get("validar_porcentaje_1a3", 0) or 0)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown("#### 2. Grupo 1 — Estudiantes que adeudan de 1 a 3 módulos")
    st.caption(
        "Todos cumplen el límite académico de módulos para solicitar reinscripción. "
        "Las tarjetas siguientes muestran únicamente cómo deben regularizarse."
    )

    _render_cards_resumen([
        {
            "titulo": "Pueden solicitar reinscripción",
            "valor": f"{total_g1:,}",
            "detalle": (
                "Adeudan como máximo 3 módulos. También deben cumplir los demás requisitos "
                "administrativos del plantel."
            ),
            "fundamento": "Artículo 68, fracción III.",
            "semaforo": "azul",
            "etiqueta_semaforo": "Total del Grupo 1",
        }
    ])

    st.info(
        f"**{con_inter_g1:,} de {total_g1:,} estudiantes pueden presentar al menos un módulo en intersemestral.** "
        f"Este subtotal incluye a **{completo_g1:,}** con todos sus módulos intersemestrales y a "
        f"**{combinadas_g1:,}** que necesitan combinar asesorías. No debe sumarse nuevamente al total del grupo."
    )

    rutas_g1 = [
        {
            "titulo": "Intersemestral completo",
            "valor": f"{completo_g1:,}",
            "detalle": "Todos sus módulos pendientes pueden presentarse en el periodo intersemestral.",
            "fundamento": "Artículos 96, 97 y 98.",
            "semaforo": "verde",
            "etiqueta_semaforo": "Todos los módulos elegibles",
        },
        {
            "titulo": "Asesorías combinadas",
            "valor": f"{combinadas_g1:,}",
            "detalle": "Unos módulos van a intersemestral y otros deben atenderse durante el semestre.",
            "fundamento": "Artículos 96, 97, 98 y 99.",
            "semaforo": "amarillo",
            "etiqueta_semaforo": "Dos tipos de asesoría",
        },
        {
            "titulo": "Asesorías semestrales",
            "valor": f"{semestrales_g1:,}",
            "detalle": "Ninguno de sus módulos alcanza el porcentaje requerido para intersemestral.",
            "fundamento": "Artículos 96, 97 y 99.",
            "semaforo": "amarillo",
            "etiqueta_semaforo": "Atención durante el semestre",
        },
    ]
    if validar_g1 > 0:
        rutas_g1.append({
            "titulo": "Información pendiente de revisar",
            "valor": f"{validar_g1:,}",
            "detalle": "Faltan porcentajes y todavía no puede determinarse la asesoría correcta.",
            "fundamento": "Validar la información antes de canalizar.",
            "semaforo": "rojo",
            "etiqueta_semaforo": "Validación urgente",
        })
    _render_cards_resumen(rutas_g1)

    suma_g1 = completo_g1 + combinadas_g1 + semestrales_g1 + validar_g1
    st.caption(
        f"Distribución del Grupo 1: {completo_g1:,} + {combinadas_g1:,} + "
        f"{semestrales_g1:,} + {validar_g1:,} por validar = **{suma_g1:,} estudiantes**."
    )

    # -------------------------
    # GRUPO 2
    # -------------------------
    total_g2 = int(resumen.get("cuatro_a_seis", 0) or 0)
    con_inter_g2 = int(resumen.get("cuatro_a_seis_con_intersemestral", 0) or 0)
    rescate_g2 = int(resumen.get("rescate_intersemestral_posible", 0) or 0)
    parcial_g2 = int(resumen.get("avance_intersemestral_parcial", 0) or 0)
    otra_ruta_g2 = int(resumen.get("sin_oportunidad_intersemestral", 0) or 0)
    validar_g2 = int(resumen.get("validar_porcentaje_4a6", 0) or 0)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown("#### 3. Grupo 2 — Estudiantes que adeudan de 4 a 6 módulos")
    st.caption(
        "Estos estudiantes no cumplen todavía el límite académico de reinscripción. "
        "El objetivo es saber quién puede quedar con 3 módulos y quién necesita otra estrategia."
    )

    _render_cards_resumen([
        {
            "titulo": "Necesitan regularizarse antes de reinscribirse",
            "valor": f"{total_g2:,}",
            "detalle": "Adeudan de 4 a 6 módulos y requieren seguimiento individual.",
            "fundamento": "Artículos 73 y 75.",
            "semaforo": "amarillo",
            "etiqueta_semaforo": "Total del Grupo 2",
        }
    ])

    st.info(
        f"**{con_inter_g2:,} de {total_g2:,} estudiantes pueden presentar al menos un módulo en intersemestral.** "
        "El resultado depende de cuántos módulos necesitan acreditar para quedar con un máximo de 3."
    )

    rutas_g2 = [
        {
            "titulo": "Pueden quedar con 3 módulos",
            "valor": f"{rescate_g2:,}",
            "detalle": "Tienen suficientes módulos intersemestrales; si acreditan los necesarios, podrían solicitar reinscripción.",
            "fundamento": "Artículos 73, 75, 96, 97 y 98.",
            "semaforo": "verde",
            "etiqueta_semaforo": "Oportunidad prioritaria",
        },
        {
            "titulo": "Solo pueden reducir parcialmente el adeudo",
            "valor": f"{parcial_g2:,}",
            "detalle": "Pueden acreditar algunos módulos, pero todavía quedarían con más de 3.",
            "fundamento": "Requieren un plan complementario.",
            "semaforo": "amarillo",
            "etiqueta_semaforo": "Avance parcial",
        },
        {
            "titulo": "Necesitan otra ruta de regularización",
            "valor": f"{otra_ruta_g2:,}",
            "detalle": "No tienen módulos elegibles para intersemestral con la información disponible.",
            "fundamento": "Artículos 75, 96, 97 y 99.",
            "semaforo": "rojo",
            "etiqueta_semaforo": "Atención prioritaria",
        },
    ]
    if validar_g2 > 0:
        rutas_g2.append({
            "titulo": "Información pendiente de revisar",
            "valor": f"{validar_g2:,}",
            "detalle": "Faltan porcentajes que podrían cambiar la oportunidad de recuperación.",
            "fundamento": "Validar antes de descartar la ruta intersemestral.",
            "semaforo": "rojo",
            "etiqueta_semaforo": "Validación urgente",
        })
    _render_cards_resumen(rutas_g2)

    suma_g2 = rescate_g2 + parcial_g2 + otra_ruta_g2 + validar_g2
    st.caption(
        f"Distribución del Grupo 2: {rescate_g2:,} + {parcial_g2:,} + "
        f"{otra_ruta_g2:,} + {validar_g2:,} por validar = **{suma_g2:,} estudiantes**."
    )

def render_fundamento_normativo():
    """Explica la norma y la regla operativa de rescate utilizada por el tablero."""
    st.markdown("#### Fundamento normativo aplicado")
    st.markdown(
        """
- **Artículo 4:** define como estudiante irregular a quien, al concluir el periodo semestral, adeuda uno o más módulos.
- **Artículo 68, fracción III:** para la reinscripción ordinaria, la persona estudiante no debe adeudar más de tres módulos.
- **Artículos 96 y 97:** distinguen la regularización intersemestral para módulos con al menos 56% en el Modelo Académico 2023 y la regularización semestral para módulos con menos de 56%.
- **Artículo 98:** permite tomar Asesorías Complementarias Intersemestrales hasta por tres módulos.
- **Artículo 99:** permite tomar Asesorías Complementarias Semestrales hasta por tres módulos durante un periodo semestral.
- **Artículo 73:** reconoce tres tipos de baja: temporal, parcial y definitiva.
- **Artículo 75:** establece la baja parcial cuando se acumulan más de tres y hasta seis módulos no acreditados; también dispone que la persona puede regularizarse mediante asesorías complementarias y/o certificación CONALEP ASCA. Con más de seis módulos no es candidata a reinscripción hasta reducir el adeudo a un máximo de tres.
- **Artículos 100 a 103:** fundamentan el seguimiento permanente a estudiantes en riesgo de reprobación o abandono escolar.
        """
    )

    st.markdown("#### Regla operativa de rescate para 4 a 6 módulos")
    st.code(
        """módulos necesarios para quedar con 3 = módulos no competentes - 3
módulos intersemestrales programables = mínimo(módulos con pAlcanzado >= 56, 3)

Si programables >= necesarios:
    Rescate intersemestral posible
Si programables > 0 pero programables < necesarios:
    Avance intersemestral parcial
Si programables == 0:
    Sin oportunidad intersemestral inmediata""",
        language="text",
    )
    st.info(
        "Las etiquetas **Rescate intersemestral posible** y **Avance intersemestral parcial** son clasificaciones "
        "operativas para apoyar la toma de decisiones. No significan que el estudiante ya acreditó ni sustituyen la "
        "programación del plantel, la disponibilidad, la evaluación docente o las resoluciones del Comité Técnico Escolar."
    )
    st.warning(
        "La condición de 7 o más módulos se muestra como **No candidato a reinscripción**, no como baja definitiva automática. "
        "La baja definitiva se regula por causas diferentes."
    )



def render_seccion_normativa_plantel(plantel_sel, key_prefix="normativa"):
    """
    Renderiza la situación normativa sin alterar las demás funciones del tablero.

    La relación de estudiantes presenta una vista sencilla por defecto. La
    información técnica completa se conserva en un apartado desplegable.
    """
    if not plantel_sel:
        st.info("Selecciona un plantel o la opción Todos para consultar la clasificación normativa.")
        return

    ambito_original = str(plantel_sel).strip()
    es_estatal = ambito_original.lower() == "todos"
    ambito_consulta = "Todos" if es_estatal else ambito_original
    titulo_ambito = "ESTATAL" if es_estatal else ambito_original

    mensaje_carga = (
        "Calculando tarjetas normativas estatales..."
        if es_estatal
        else f"Calculando tarjetas normativas de {ambito_original}..."
    )
    with st.spinner(mensaje_carga):
        df_estudiantes = obtener_reporte_normativo_plantel(ambito_consulta)

    if df_estudiantes is None or df_estudiantes.empty:
        st.info(
            "No hay registros estatales de estudiantes no competentes."
            if es_estatal
            else f"No hay registros de estudiantes no competentes para **{ambito_original}**."
        )
        return

    resumen = construir_resumen_normativo(df_estudiantes)

    st.markdown("---")
    st.subheader(f"📚 Situación normativa y rutas de regularización — {titulo_ambito}")
    st.caption(
        "El Grupo 1 reúne a quienes adeudan de 1 a 3 módulos. El Grupo 2 reúne a quienes adeudan de 4 a 6. "
        "El porcentaje de cada módulo determina si corresponde asesoría intersemestral, semestral o validación."
    )

    tab_resumen, tab_relacion, tab_concentrado, tab_fundamento = st.tabs([
        "1. Resumen normativo",
        "2. Relación de estudiantes",
        "3. Concentrado para imprimir",
        "4. Fundamento normativo",
    ])

    with tab_resumen:
        render_tarjetas_normativas(resumen)

    with tab_relacion:
        st.markdown("#### Consulta rápida de estudiantes")
        st.caption(
            "La tabla sencilla muestra únicamente los datos necesarios para ubicar al estudiante, conocer su "
            "condición de reinscripción, identificar sus asesorías y definir la acción inmediata."
        )
        st.info(
            "En la columna **Reinscripción**, la palabra “Sí” significa únicamente que cumple el límite académico "
            "de adeudar como máximo 3 módulos. No sustituye los demás requisitos administrativos."
        )

        opcion = st.selectbox(
            "¿Qué estudiantes deseas consultar?",
            options=OPCIONES_REPORTE_NORMATIVO,
            index=0,
            key=f"{key_prefix}_{_safe_download_name(ambito_consulta)}_opcion_reporte",
            help="Selecciona el grupo o la situación que deseas revisar.",
        )

        df_filtrado = filtrar_reporte_normativo(df_estudiantes, opcion)
        df_sencillo = _columnas_reporte_sencillo(
            df_filtrado,
            mostrar_plantel=es_estatal,
        )

        etiqueta_relacion = "estatal" if es_estatal else f"del plantel {ambito_original}"
        st.markdown(f"##### {opcion}: **{len(df_filtrado):,} estudiante(s)** — ámbito {etiqueta_relacion}")

        if df_sencillo.empty:
            st.info("No hay estudiantes para esta selección.")
        else:
            mostrar_dataframe_preview(df_sencillo, height=520)

            with st.expander("🔎 Ver información técnica completa", expanded=False):
                st.caption(
                    "Este detalle conserva todos los campos de cálculo, clasificación normativa, módulos programables, "
                    "resultado proyectado, docentes y explicación técnica."
                )
                df_tecnico = _columnas_reporte_normativo_presentacion(df_filtrado)
                mostrar_dataframe_preview(df_tecnico, height=520)

    with tab_concentrado:
        st.markdown("#### Concentrado ejecutivo")
        st.caption(
            "Este apartado está preparado para seguimiento e impresión. Las categorías principales no se traslapan, "
            "por lo que pueden sumarse y compararse sin duplicar estudiantes."
        )

        concentrado_plantel = construir_concentrado_por_plantel(df_estudiantes)
        if not concentrado_plantel.empty:
            st.markdown("##### Resumen por plantel")
            st.dataframe(concentrado_plantel, use_container_width=True, height=330)

        opcion_impresion = st.selectbox(
            "¿Qué relación deseas incluir en el concentrado?",
            options=OPCIONES_REPORTE_NORMATIVO,
            index=0,
            key=f"{key_prefix}_{_safe_download_name(ambito_consulta)}_opcion_impresion",
        )
        df_impresion = filtrar_reporte_normativo(df_estudiantes, opcion_impresion)
        df_impresion_presentacion = _columnas_concentrado_imprimible(df_impresion)

        st.markdown(f"##### Relación para seguimiento: **{len(df_impresion):,} estudiante(s)**")
        if df_impresion_presentacion.empty:
            st.info("No hay estudiantes para la relación seleccionada.")
        else:
            mostrar_dataframe_preview(df_impresion_presentacion, height=520)

        nombre_ambito = _safe_download_name(ambito_consulta)
        nombre_opcion = _safe_download_name(opcion_impresion)
        excel_bytes = exportar_excel_reporte_normativo(
            df_estudiantes,
            ambito_consulta,
            opcion_impresion,
        )
        html_bytes = exportar_html_reporte_normativo(
            df_estudiantes,
            ambito_consulta,
            opcion_impresion,
        )

        col_excel, col_html = st.columns(2)
        with col_excel:
            st.download_button(
                "⬇️ Descargar concentrado Excel",
                data=excel_bytes,
                file_name=f"concentrado_regularizacion_{nombre_ambito}_{nombre_opcion}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key_prefix}_{nombre_ambito}_{nombre_opcion}_excel_normativo",
                use_container_width=True,
            )
        with col_html:
            st.download_button(
                "🖨️ Descargar versión imprimible",
                data=html_bytes,
                file_name=f"concentrado_regularizacion_{nombre_ambito}_{nombre_opcion}.html",
                mime="text/html",
                key=f"{key_prefix}_{nombre_ambito}_{nombre_opcion}_html_normativo",
                use_container_width=True,
            )

        st.caption(
            "Abre el archivo HTML en un navegador y utiliza Ctrl+P para imprimirlo o guardarlo como PDF."
        )

    with tab_fundamento:
        render_fundamento_normativo()

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


def construir_figura_seguimiento_estatal(show_title=True):
    seguimiento_estatal, matricula_estatal = obtener_seguimiento_estatal()

    if seguimiento_estatal is None or seguimiento_estatal.empty:
        return None, seguimiento_estatal, matricula_estatal

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=seguimiento_estatal["Semana"],
            y=seguimiento_estatal["Cantidad"],
            name="Cantidad",
            text=seguimiento_estatal["Etiqueta"],
            textposition="outside",
            textangle=-90,
            marker_color="#FFC107",
            cliponaxis=False,
            outsidetextfont=dict(size=LABEL_FONT_SIZE_ADMIN + 2, color="#2b2b2b"),
            hoverinfo="skip",
            hovertemplate="",
            customdata=seguimiento_estatal["Porcentaje"],
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=seguimiento_estatal["Semana"],
            y=seguimiento_estatal["Porcentaje"],
            name="% NO competencia estatal",
            mode="lines+markers",
            line=dict(color="#1f77b4", width=3),
            marker=dict(size=9),
            hoverinfo="skip",
            hovertemplate="",
        ),
        secondary_y=True,
    )

    max_cantidad = float(seguimiento_estatal["Cantidad"].max()) if not seguimiento_estatal.empty else 0
    max_porcentaje = float(seguimiento_estatal["Porcentaje"].max()) if not seguimiento_estatal.empty else 0

    fig.update_layout(
        title_text=f"Comportamiento estatal — {SEGUIMIENTO_ESTATAL_NOMBRE}" if show_title else "",
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

    return fig, seguimiento_estatal, matricula_estatal


def mostrar_grafica_seguimiento_estatal(show_title=True, show_footer=True):
    fig, seguimiento_estatal, matricula_estatal = construir_figura_seguimiento_estatal(show_title=show_title)

    if fig is None or seguimiento_estatal is None or seguimiento_estatal.empty:
        return False

    ultimo = seguimiento_estatal.iloc[-1]
    tendencia = _datos_tendencia_seguimiento(seguimiento_estatal)
    matricula_val = int(round(float(matricula_estatal or 0)))

    _render_cards_resumen([
        {
            "titulo": "Matrícula estatal",
            "valor": f"{matricula_val:,}",
            "detalle": f"Tomada de la fila {SEGUIMIENTO_ESTATAL_NOMBRE} en la hoja Seguimiento.",
        },
        {
            "titulo": "Último total estatal NO competente",
            "valor": f"{int(ultimo['Cantidad']):,}",
            "detalle": f"Dato de {ultimo['Semana']}.",
        },
        {
            "titulo": "Último porcentaje estatal",
            "valor": f"{float(ultimo['Porcentaje']):.2f}%",
            "detalle": f"Dato de {ultimo['Semana']}.",
        },
        {
            "titulo": "Tendencia estatal vs semana previa",
            "valor": tendencia["valor_card"],
            "detalle": tendencia["detalle_card"],
        },
    ])

    st.plotly_chart(fig, use_container_width=True)

    resumen = _resumen_tendencia_seguimiento(seguimiento_estatal)
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


def _resumen_normativo_dataframe(resumen):
    return pd.DataFrame([
        {"Indicador": "Total de estudiantes con módulos pendientes", "Cantidad": resumen.get("total_nc", 0)},
        {"Indicador": "GRUPO 1: adeudan de 1 a 3 módulos", "Cantidad": resumen.get("uno_a_tres", 0)},
        {"Indicador": "GRUPO 1: pueden solicitar reinscripción por número de módulos", "Cantidad": resumen.get("uno_a_tres_reinscripcion_ordinaria", 0)},
        {"Indicador": "GRUPO 1: pueden presentar al menos una intersemestral", "Cantidad": resumen.get("uno_a_tres_con_intersemestral", 0)},
        {"Indicador": "GRUPO 1: intersemestral completo", "Cantidad": resumen.get("intersemestral_completo", 0)},
        {"Indicador": "GRUPO 1: asesorías combinadas", "Cantidad": resumen.get("irregular_mixta", 0)},
        {"Indicador": "GRUPO 1: asesorías semestrales", "Cantidad": resumen.get("irregular_semestral", 0)},
        {"Indicador": "GRUPO 1: información por validar", "Cantidad": resumen.get("validar_porcentaje_1a3", 0)},
        {"Indicador": "GRUPO 2: adeudan de 4 a 6 módulos", "Cantidad": resumen.get("cuatro_a_seis", 0)},
        {"Indicador": "GRUPO 2: pueden presentar al menos una intersemestral", "Cantidad": resumen.get("cuatro_a_seis_con_intersemestral", 0)},
        {"Indicador": "GRUPO 2: pueden quedar con 3 módulos", "Cantidad": resumen.get("rescate_intersemestral_posible", 0)},
        {"Indicador": "GRUPO 2: reducción parcial del adeudo", "Cantidad": resumen.get("avance_intersemestral_parcial", 0)},
        {"Indicador": "GRUPO 2: necesitan otra ruta de regularización", "Cantidad": resumen.get("sin_oportunidad_intersemestral", 0)},
        {"Indicador": "GRUPO 2: información por validar", "Cantidad": resumen.get("validar_porcentaje_4a6", 0)},
        {"Indicador": "7 o más: deben regularizarse antes de reinscribirse", "Cantidad": resumen.get("no_reinscripcion", 0)},
    ])

def _ajustar_hoja_excel_normativa(writer, sheet_name, df, formato_titulo, formato_texto):
    """Aplica formato legible y listo para impresión a una hoja del concentrado."""
    worksheet = writer.sheets[sheet_name]
    if df is None:
        return

    for idx, col in enumerate(df.columns):
        try:
            longitudes = df[col].astype(str).str.len()
            max_len = max(len(str(col)), int(longitudes.quantile(0.90))) + 3 if len(longitudes) else len(str(col)) + 3
        except Exception:
            max_len = 20
        width = min(max(max_len, 12), 55)
        worksheet.set_column(idx, idx, width, formato_texto)

    worksheet.set_row(0, 34, formato_titulo)
    worksheet.freeze_panes(1, 0)
    if len(df.columns) > 0:
        worksheet.autofilter(0, 0, max(len(df), 1), len(df.columns) - 1)
        worksheet.set_landscape()
        worksheet.fit_to_pages(1, 0)
        worksheet.repeat_rows(0)
        worksheet.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)



def exportar_excel_reporte_normativo(df_estudiantes, plantel_sel, opcion):
    """Genera un libro completo con relaciones sencillas y una hoja de criterios."""
    resumen = construir_resumen_normativo(df_estudiantes)
    df_resumen = _resumen_normativo_dataframe(resumen)
    df_concentrado = construir_concentrado_por_plantel(df_estudiantes)

    vistas = {
        "RELACION_SELECCIONADA": filtrar_reporte_normativo(df_estudiantes, opcion),
        "GRUPO_1_1_A_3": filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Adeudan de 1 a 3 módulos"),
        "G1_CON_INTERSEM": filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Pueden presentar al menos una intersemestral"),
        "G1_INTERSEM_TOTAL": filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Todos sus módulos son intersemestrales"),
        "G1_ASES_COMBINADAS": filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Necesitan asesorías combinadas"),
        "G1_ASES_SEMESTRALES": filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Necesitan asesorías semestrales"),
        "GRUPO_2_4_A_6": filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Adeudan de 4 a 6 módulos"),
        "G2_CON_INTERSEM": filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Pueden presentar al menos una intersemestral"),
        "G2_PUEDEN_QUEDAR_3": filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Pueden quedar con 3 módulos"),
        "G2_REDUCCION_PARCIAL": filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Solo pueden reducir parcialmente el adeudo"),
        "G2_OTRA_RUTA": filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Necesitan otra ruta de regularización"),
        "VALIDAR_DATOS": pd.concat([
            filtrar_reporte_normativo(df_estudiantes, "GRUPO 1 — Información académica por validar"),
            filtrar_reporte_normativo(df_estudiantes, "GRUPO 2 — Información académica por validar"),
        ], ignore_index=True),
        "SIETE_O_MAS": filtrar_reporte_normativo(df_estudiantes, "7 o más — Deben regularizarse antes de reinscribirse"),
    }

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_resumen.to_excel(writer, index=False, sheet_name="RESUMEN")
        df_concentrado.to_excel(writer, index=False, sheet_name="CONCENTRADO_PLANTELES")

        workbook = writer.book
        formato_titulo = workbook.add_format({
            "bold": True, "font_color": "white", "bg_color": "#184C3B",
            "align": "center", "valign": "vcenter", "border": 1,
            "text_wrap": True,
        })
        formato_texto = workbook.add_format({
            "text_wrap": True, "valign": "top", "border": 1,
        })

        _ajustar_hoja_excel_normativa(writer, "RESUMEN", df_resumen, formato_titulo, formato_texto)
        _ajustar_hoja_excel_normativa(writer, "CONCENTRADO_PLANTELES", df_concentrado, formato_titulo, formato_texto)

        for sheet_name, df_vista in vistas.items():
            df_salida = _columnas_concentrado_imprimible(df_vista)
            hoja = sheet_name[:31]
            df_salida.to_excel(writer, index=False, sheet_name=hoja)
            _ajustar_hoja_excel_normativa(writer, hoja, df_salida, formato_titulo, formato_texto)

        criterios = pd.DataFrame([
            {
                "Grupo": "1 a 3 módulos",
                "Lectura sencilla": "Cumple el límite académico de módulos para solicitar reinscripción.",
                "Acción": "Asignar intersemestral, asesorías combinadas, semestral o validación según cada módulo.",
            },
            {
                "Grupo": "4 a 6 módulos",
                "Lectura sencilla": "No cumple todavía el límite académico de reinscripción.",
                "Acción": "Determinar si puede quedar con 3, reducir parcialmente o necesita otra ruta.",
            },
            {
                "Grupo": "7 o más módulos",
                "Lectura sencilla": "Debe reducir el adeudo antes de solicitar reinscripción ordinaria.",
                "Acción": "Preparar un plan integral de regularización.",
            },
            {
                "Grupo": "Criterio por módulo",
                "Lectura sencilla": f"pAlcanzado >= {UMBRAL_ASESORIA_INTERSEMESTRAL:.0f}%: intersemestral; menor: semestral.",
                "Acción": "Los porcentajes vacíos deben validarse antes de asignar una ruta.",
            },
        ])
        criterios.to_excel(writer, index=False, sheet_name="CRITERIOS")
        _ajustar_hoja_excel_normativa(writer, "CRITERIOS", criterios, formato_titulo, formato_texto)

        ws_resumen = writer.sheets["RESUMEN"]
        fila_meta = len(df_resumen) + 2
        ws_resumen.write(fila_meta, 0, "Ámbito seleccionado", formato_titulo)
        ws_resumen.write(fila_meta, 1, str(plantel_sel), formato_texto)
        ws_resumen.write(fila_meta + 1, 0, "Relación seleccionada", formato_titulo)
        ws_resumen.write(fila_meta + 1, 1, str(opcion), formato_texto)
        ws_resumen.write(fila_meta + 2, 0, "Fecha de generación", formato_titulo)
        ws_resumen.write(fila_meta + 2, 1, datetime.now().strftime("%Y-%m-%d %H:%M"), formato_texto)

    output.seek(0)
    return output.getvalue()


def exportar_html_reporte_normativo(df_estudiantes, plantel_sel, opcion):
    """Genera un concentrado HTML horizontal listo para imprimir o guardar como PDF."""
    resumen = construir_resumen_normativo(df_estudiantes)
    df_filtrado = filtrar_reporte_normativo(df_estudiantes, opcion)
    df_filtrado = _columnas_concentrado_imprimible(df_filtrado)
    df_concentrado = construir_concentrado_por_plantel(df_estudiantes)

    tarjetas = [
        ("Grupo 1: 1 a 3", resumen.get("uno_a_tres", 0)),
        ("G1 intersemestral completo", resumen.get("intersemestral_completo", 0)),
        ("G1 asesorías combinadas", resumen.get("irregular_mixta", 0)),
        ("G1 asesorías semestrales", resumen.get("irregular_semestral", 0)),
        ("Grupo 2: 4 a 6", resumen.get("cuatro_a_seis", 0)),
        ("G2 pueden quedar con 3", resumen.get("rescate_intersemestral_posible", 0)),
        ("G2 reducción parcial", resumen.get("avance_intersemestral_parcial", 0)),
        ("7 o más", resumen.get("no_reinscripcion", 0)),
    ]

    tarjetas_html = "".join(
        f"<div class='card'><div class='label'>{escape(str(titulo))}</div>"
        f"<div class='value'>{int(valor):,}</div></div>"
        for titulo, valor in tarjetas
    )

    tabla_concentrado = (
        "<p class='empty'>No hay información para el concentrado.</p>"
        if df_concentrado.empty
        else df_concentrado.to_html(index=False, border=0, escape=True)
    )
    tabla_estudiantes = (
        "<p class='empty'>No hay estudiantes para la clasificación seleccionada.</p>"
        if df_filtrado.empty
        else df_filtrado.to_html(index=False, border=0, escape=True)
    )

    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Concentrado de regularización - {escape(str(plantel_sel))}</title>
        <style>
          @page {{ size: landscape; margin: 8mm; }}
          @media print {{
            body {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
            thead {{ display:table-header-group; }}
            tr {{ page-break-inside:avoid; }}
            .page-break {{ page-break-before:always; }}
          }}
          body {{ font-family:Arial,Helvetica,sans-serif; color:#1d2939; margin:20px; }}
          h1 {{ color:#184C3B; margin-bottom:4px; }}
          h2 {{ color:#344054; margin-top:20px; font-size:17px; }}
          .meta {{ color:#667085; font-size:11px; margin-bottom:12px; }}
          .rule {{ background:#E8F3EF; border-left:5px solid #006B54; padding:11px; margin:12px 0; font-size:11px; }}
          .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:14px 0 18px 0; }}
          .card {{ border:1px solid #D0D5DD; border-radius:9px; padding:10px; background:#FFFFFF; }}
          .label {{ color:#667085; font-size:10px; font-weight:bold; min-height:25px; }}
          .value {{ color:#101828; font-size:22px; font-weight:800; margin-top:4px; }}
          table {{ border-collapse:collapse; width:100%; font-size:8px; }}
          th, td {{ border:1px solid #D0D5DD; padding:4px; vertical-align:top; word-break:break-word; }}
          th {{ background:#184C3B; color:white; text-align:left; }}
          tr:nth-child(even) td {{ background:#F9FAFB; }}
          .empty {{ padding:16px; background:#F9FAFB; border:1px solid #EAECF0; }}
          .footer {{ margin-top:14px; color:#667085; font-size:9px; }}
        </style>
      </head>
      <body>
        <h1>Concentrado de estudiantes con oportunidad de regularización</h1>
        <div class="meta">
          Ámbito: {escape(str(plantel_sel))} | Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} |
          Relación: {escape(str(opcion))}
        </div>
        <div class="rule">
          <strong>Cómo leer el reporte:</strong> el Grupo 1 reúne a quienes adeudan de 1 a 3 módulos y cumplen
          el límite académico de módulos para solicitar reinscripción. El Grupo 2 reúne a quienes adeudan de 4 a 6;
          en ellos se indica si pueden quedar con 3 módulos, si solo pueden reducir parcialmente el adeudo o si
          necesitan otra ruta. La acreditación y la reinscripción deben confirmarse por las instancias correspondientes.
        </div>
        <div class="cards">{tarjetas_html}</div>
        <h2>Concentrado por plantel</h2>
        {tabla_concentrado}
        <div class="page-break"></div>
        <h2>{escape(str(opcion))}: {len(df_filtrado):,} estudiante(s)</h2>
        {tabla_estudiantes}
        <div class="footer">Abra este archivo en un navegador y use Ctrl+P para imprimir o guardar como PDF.</div>
      </body>
    </html>
    """
    return html.encode("utf-8")

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
    df = preparar_detalle_no_competentes_presentacion(obtener_detalle_no_competentes(plantel_sel))
    return exportar_excel(df).getvalue()


@st.cache_data(show_spinner=False)
def generar_html_no_competentes(plantel_sel):
    df = preparar_detalle_no_competentes_presentacion(obtener_detalle_no_competentes(plantel_sel))
    return exportar_html_imprimible(
        df,
        titulo="Detalle de estudiantes con sus respectivos módulos NO competentes",
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
        titulo="Estudiantes agrupados por el número de módulos NO competentes",
        subtitulo="(Vista agrupada con TOTAL)",
        filename="agrupados_no_competentes.html",
    ).getvalue()


# =========================
# Función principal
# =========================
def mostrar_indicadores_academicos():
    st.title(construir_titulo_indicadores())
    st.session_state["_indicadores_dataframe_widget_counter"] = 0

    # Primero se identifica el tipo de usuario. Para administradores se difiere
    # la carga pesada de Reprobacion/resumen hasta que se presione Aplicar filtros.
    is_admin = bool(st.session_state.get("administrador", False))
    plantel_usuario = st.session_state.get("plantel_usuario") or st.session_state.get("plantel")
    es_plantel = bool(plantel_usuario) and not is_admin

    # La hoja Matricula es más ligera y permite poblar el filtro de planteles sin
    # calcular todavía todo el resumen de no competencia.
    df_matricula = cargar_matricula()

    permisos_codes = obtener_permisos_usuario_codigos()
    puede_enviar_email = (not es_plantel) and (PERM_SEND_EMAIL_CODE in permisos_codes)

    if not es_plantel:
        df_reprobacion = None

        if df_matricula is not None and not df_matricula.empty and "Plantel" in df_matricula.columns:
            planteles_disponibles = sorted(
                df_matricula["Plantel"].dropna().astype(str).str.strip().loc[lambda s: s.ne("")].unique().tolist()
            )
        else:
            # Respaldo ligero: catálogo de planteles. Solo si la hoja Matricula
            # no contiene nombres válidos.
            try:
                df_catalogo_planteles = cargar_planteles_sheet()
                col_plantel_catalogo = _find_col_like(df_catalogo_planteles, ["Plantel"])
                planteles_disponibles = sorted(
                    df_catalogo_planteles[col_plantel_catalogo]
                    .dropna().astype(str).str.strip().loc[lambda s: s.ne("")].unique().tolist()
                ) if col_plantel_catalogo else []
            except Exception:
                planteles_disponibles = []

        opciones_plantel = ["Todos"] + planteles_disponibles

        if "indicadores_admin_filtros_aplicados" not in st.session_state:
            st.session_state.indicadores_admin_filtros_aplicados = False
        if "indicadores_admin_plantel_aplicado" not in st.session_state:
            st.session_state.indicadores_admin_plantel_aplicado = None
        if "indicadores_admin_vista_aplicada" not in st.session_state:
            st.session_state.indicadores_admin_vista_aplicada = None

        vista_form = st.radio(
            "Visualización de la gráfica:",
            ["% NO competencia", "Total NO competentes", VISTA_COMPORTAMIENTO_ESTATAL],
            horizontal=True,
            key="indicadores_admin_vista_grafica",
        )
        es_vista_estatal = vista_form == VISTA_COMPORTAMIENTO_ESTATAL

        # La vista de comportamiento estatal usa exclusivamente la hoja
        # Seguimiento y conserva su comportamiento inmediato.
        if es_vista_estatal:
            st.markdown(f"### 📈 Comportamiento estatal — {SEGUIMIENTO_ESTATAL_NOMBRE}")
            if not mostrar_grafica_seguimiento_estatal(show_title=False, show_footer=True):
                st.info(
                    f"ℹ️ No hay datos estatales para **{SEGUIMIENTO_ESTATAL_NOMBRE}** en la hoja Seguimiento. "
                    "Verifica que exista una fila con ese nombre y columnas tipo Sem X y Sem X %."
                )
            return

        with st.form("filtros_indicadores_admin"):
            plantel_form = st.selectbox(
                "Selecciona un plantel",
                opciones_plantel,
                key="indicadores_admin_plantel_sel",
            )
            filtros_aplicados = st.form_submit_button("Aplicar filtros")

        if filtros_aplicados:
            st.session_state.indicadores_admin_filtros_aplicados = True
            st.session_state.indicadores_admin_plantel_aplicado = plantel_form
            st.session_state.indicadores_admin_vista_aplicada = vista_form

        if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
            st.info(
                "Selecciona **Todos** o un plantel específico y presiona **Aplicar filtros**. "
                "La gráfica, las tarjetas normativas y las tablas se cargarán únicamente después de confirmar el filtro."
            )
            return

        plantel_sel = st.session_state.get("indicadores_admin_plantel_aplicado") or "Todos"
        vista = st.session_state.get("indicadores_admin_vista_aplicada") or vista_form

        st.caption(f"Filtro aplicado: **{plantel_sel}**. Para cambiarlo, selecciona otra opción y presiona Aplicar filtros.")

        # Carga pesada diferida: se ejecuta solo después de Aplicar filtros.
        with st.spinner("Cargando indicadores académicos del filtro seleccionado..."):
            tabla = cargar_resumen()

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
            total_label = pd.to_numeric(
                tabla_ordenada["Total estudiantes no competentes"],
                errors="coerce"
            ).fillna(0).round().astype(int).astype(str)
            pct_label = pd.to_numeric(
                tabla_ordenada["% Estudiantes no competentes"],
                errors="coerce"
            ).fillna(0).map(lambda v: f"{float(v):.2f}%")
            tabla_ordenada["etiqueta"] = total_label + " - " + pct_label

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

            with st.expander(
                "📋 Distribución de estudiantes por cantidad de módulos NO competentes",
                expanded=False,
            ):
                st.caption(
                    "Consulta la distribución general por número de módulos. El renglón TOTAL conserva el mismo cálculo del tablero."
                )
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
                st.markdown(f"#### 👥 Total general de estudiantes NO competentes: **{total_general:,}**")
                st.markdown(f"#### 📊 Porcentaje respecto a la matrícula: **{porcentaje_promedio}%**")

            # La misma sección se usa para un plantel específico y para el
            # consolidado ESTATAL cuando el filtro se encuentra en Todos.
            render_seccion_normativa_plantel(
                plantel_sel,
                key_prefix="admin_normativa"
            )

        st.markdown("---")
        st.markdown("## 🔎 Consulta detallada")
        st.caption(
            "Abre únicamente el apartado que necesites. Los cálculos, filtros y tablas se conservan sin cambios."
        )

        if plantel_sel == "Todos":
            with st.expander("⚠️ Detalle general de estudiantes NO competentes", expanded=False):
                if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
                    st.info("Presiona **Aplicar filtros** para cargar el detalle general de todos los planteles.")
                else:
                    with st.spinner("Cargando detalle general de estudiantes NO competentes..."):
                        df_print = preparar_detalle_no_competentes_presentacion(obtener_detalle_no_competentes("Todos"))

                    total_nc_admin = (
                        df_print["matricula"].nunique()
                        if not df_print.empty and "matricula" in df_print.columns
                        else len(df_print)
                    )

                    st.caption(f"Total de estudiantes NO competentes: {total_nc_admin:,}")
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

            with st.expander("🚨 Estudiantes sin registro de calificaciones — Todos", expanded=False):
                if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
                    st.info("Presiona **Aplicar filtros** para cargar el detalle general de estudiantes sin registro.")
                else:
                    with st.spinner("Cargando estudiantes sin registro de calificaciones..."):
                        df_sin_registro = obtener_sin_registro_calificaciones("Todos")

                    total_sin_registro = (
                        df_sin_registro["matricula"].nunique()
                        if not df_sin_registro.empty and "matricula" in df_sin_registro.columns
                        else len(df_sin_registro)
                    )

                    st.caption(f"Total de estudiantes sin registro: {total_sin_registro:,}")
                    if df_sin_registro.empty:
                        st.info("ℹ️ No hay registros sin evaluación para **Todos**.")
                    else:
                        mostrar_dataframe_preview(df_sin_registro)
                        render_botones_descarga_detalle(
                            df_sin_registro,
                            "Todos",
                            tipo="sin_registro_calificaciones",
                            key_prefix="admin_todos_sr"
                        )

            with st.expander("🧭 Identificación por cantidad de módulos — Todos", expanded=False):
                if not st.session_state.get("indicadores_admin_filtros_aplicados", False):
                    st.info("Presiona **Aplicar filtros** para habilitar esta consulta.")
                else:
                    render_seccion_impresion_por_modulos(
                        "Todos",
                        key_prefix="admin_todos_modulos"
                    )
        else:
            df_print = preparar_detalle_no_competentes_presentacion(obtener_detalle_no_competentes(plantel_sel))

            fila_sel = tabla[tabla["Plantel"] == plantel_sel]
            if not fila_sel.empty and "Total estudiantes no competentes" in fila_sel.columns:
                total_nc_admin = int(fila_sel["Total estudiantes no competentes"].iloc[0])
            else:
                total_nc_admin = df_print["matricula"].nunique() if "matricula" in df_print.columns else len(df_print)

            with st.expander(f"⚠️ Detalle de estudiantes NO competentes — {plantel_sel}", expanded=False):
                st.caption(f"Total de estudiantes NO competentes: {total_nc_admin:,}")
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

            with st.expander(
                f"🚨 Estudiantes sin registro de calificaciones ({total_sin_registro}) — {plantel_sel}",
                expanded=False,
            ):
                if df_sin_registro.empty:
                    st.info(f"ℹ️ No hay registros sin evaluación para **{plantel_sel}**.")
                else:
                    mostrar_dataframe_preview(df_sin_registro)
                    render_botones_descarga_detalle(
                        df_sin_registro,
                        plantel_sel,
                        tipo="sin_registro_calificaciones",
                        key_prefix="admin_plantel_sr"
                    )

            with st.expander(f"🧭 Identificación por cantidad de módulos — {plantel_sel}", expanded=False):
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

    else:
        if not plantel_usuario:
            st.error("No se detectó el plantel del usuario en la sesión (plantel_usuario).")
            return

        # El usuario de plantel tiene un ámbito fijo; aquí sí se carga el resumen
        # directamente porque no requiere confirmar un filtro administrativo.
        tabla = cargar_resumen()
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

        render_seccion_normativa_plantel(
            plantel_usuario,
            key_prefix="plantel_normativa"
        )

        st.markdown("---")
        st.markdown("## 🔎 Consulta detallada del plantel")
        st.caption("Abre el apartado que necesites para evitar mostrar todas las tablas al mismo tiempo.")

        with st.expander(
            f"📋 Distribución por cantidad de módulos NO competentes — {plantel_usuario}",
            expanded=False,
        ):
            st.dataframe(tabla_filtrada, use_container_width=True)

        df_exportar = preparar_detalle_no_competentes_presentacion(obtener_detalle_no_competentes(plantel_usuario))

        with st.expander(
            f"⚠️ Detalle de estudiantes NO competentes — {plantel_usuario}",
            expanded=False,
        ):
            st.caption(f"Total de estudiantes NO competentes: {total_nc:,}")
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

        with st.expander(
            f"🚨 Estudiantes sin registro de calificaciones ({total_sin_registro_plantel})",
            expanded=False,
        ):
            if df_sin_registro_plantel.empty:
                st.info("ℹ️ No hay registros sin evaluación para este plantel.")
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

        with st.expander(
            f"🧭 Identificación por cantidad de módulos — {plantel_usuario}",
            expanded=False,
        ):
            render_seccion_impresion_por_modulos(
                plantel_usuario,
                key_prefix="plantel_modulos"
            )

