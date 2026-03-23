# views/indicadores_academicos_v2.py
import os
import re
import smtplib
import unicodedata
from io import BytesIO
from datetime import datetime
from email.message import EmailMessage

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =========================
# CONFIG
# =========================
LABEL_FONT_SIZE_ADMIN = 15
LABEL_FONT_SIZE_PLANTEL = 15
Y_AXIS_PADDING_MULT = 1.35

PERM_SEND_EMAIL_CODE = "SEND_EMAIL_INDICADORES"

EXCEL_PATH = "assets/Datos1.xlsx"
CACHE_DIR = "assets/cache_indicadores"
MAX_PREVIEW_ROWS = 500

USE_FAST_CACHE = os.getenv("USE_FAST_CACHE", "true").lower() == "true"

REPROBACION_COLS = [
    "Plantel", "ESTUDIANTE", "matricula", "CARRERA", "MODULO",
    "DOCENTE", "grado", "cvegrupo", "pEspecifico", "pAlcanzado", "pRelativo"
]

MATRICULA_COLS = ["Plantel", "matriculaTotal"]
METRICAS_ORDEN = ["pEspecifico", "pAlcanzado", "pRelativo"]


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


def mostrar_dataframe_preview(df, max_rows=MAX_PREVIEW_ROWS, height=360):
    total = len(df)
    if total > max_rows:
        st.caption(f"Mostrando los primeros {max_rows:,} de {total:,} registros. Usa la descarga para obtener el archivo completo.")
    st.dataframe(df.head(max_rows), use_container_width=True, height=height)


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
    return _read_fast_or_excel("seguimiento.parquet", "Seguimiento", usecols=None)


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
    if USE_FAST_CACHE and plantel_sel != "Todos":
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


@st.cache_data(show_spinner=False)
def obtener_seguimiento_plantel(plantel_usuario):
    df_seguimiento = cargar_seguimiento()
    df_plantel = df_seguimiento[df_seguimiento["Plantel"] == plantel_usuario].copy()

    columnas_cantidad = [col for col in df_plantel.columns if str(col).startswith("Sem ") and not str(col).endswith("%")]
    columnas_porcentaje = [
        col for col in df_plantel.columns
        if str(col).endswith("%") and str(col).replace(" %", "") in columnas_cantidad
    ]

    if not columnas_cantidad or not columnas_porcentaje:
        return pd.DataFrame(columns=["Semana", "Cantidad", "Porcentaje", "Etiqueta"])

    df_valores = df_plantel[columnas_cantidad].sum().reset_index()
    df_valores.columns = ["Semana", "Cantidad"]
    df_valores["Semana"] = df_valores["Semana"].astype(str).str.strip()

    df_porcentajes = df_plantel[columnas_porcentaje].mean().reset_index()
    df_porcentajes.columns = ["Semana", "Porcentaje"]
    df_porcentajes["Semana"] = df_porcentajes["Semana"].astype(str).str.replace(" %", "", regex=False).str.strip()

    df_semana = pd.merge(df_valores, df_porcentajes, on="Semana", how="inner")
    df_semana["Cantidad"] = pd.to_numeric(df_semana["Cantidad"], errors="coerce").fillna(0)
    df_semana["Porcentaje"] = pd.to_numeric(df_semana["Porcentaje"], errors="coerce").fillna(0).round(2)
    df_semana["Etiqueta"] = df_semana.apply(
        lambda r: f"{int(r['Cantidad'])} - {float(r['Porcentaje']):.1f}%",
        axis=1
    )
    return df_semana


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


def enviar_correo(destinatarios, asunto, cuerpo, cc=None):
    host, port, user, password, from_email, use_tls = _smtp_config()
    cc = cc or []

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = from_email
    msg["To"] = ", ".join(destinatarios)

    if cc:
        msg["Cc"] = ", ".join(cc)

    msg.set_content(cuerpo)

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

        asunto = f"Indicadores académicos - {p}"
        cuerpo = texto_correo_plantel(
            plantel=p,
            total_no_comp=total_no_comp,
            total_sin_calif=total_sin_calif,
            top_por_semestre=top_por_semestre,
            semana_modulos=semana_usada,
            mod_err=mod_err,
            top_docentes=top_docentes,
            semana_docentes=semana_docentes,
            doc_err=doc_err
        )

        borradores.append({
            "plantel": p,
            "to": destinatarios,
            "cc": cc_list,
            "subject": asunto,
            "body": cuerpo,
        })

    return borradores, sin_email


def enviar_borradores(borradores):
    enviados = []
    fallidos = []
    for b in borradores:
        try:
            enviar_correo(b["to"], b["subject"], b["body"], cc=b.get("cc", []))
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

            st.subheader("📋 Estudiantes agrupados por módulos NO competentes")
            tabla_con_total = agregar_fila_total(tabla_vista)
            st.dataframe(tabla_con_total, use_container_width=True)

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

        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario].copy()

        if tabla_filtrada.empty:
            st.warning(f"No hay información disponible para el plantel {plantel_usuario}.")
            return

        tabla_filtrada["etiqueta"] = tabla_filtrada.apply(
            lambda r: f"{int(r['Total estudiantes no competentes'])} - {float(r['% Estudiantes no competentes']):.1f}%",
            axis=1
        )

        y_col = "% Estudiantes no competentes"
        ymax = float(tabla_filtrada[y_col].max()) if not tabla_filtrada.empty else 0

        fig = go.Figure(
            data=[
                go.Bar(
                    x=tabla_filtrada["Plantel"],
                    y=tabla_filtrada[y_col],
                    text=tabla_filtrada["etiqueta"],
                    textposition="outside",
                    textangle=-90,
                    marker_color="#FFC107",
                    cliponaxis=False,
                    outsidetextfont=dict(size=LABEL_FONT_SIZE_PLANTEL),
                    hoverinfo="skip",
                    hovertemplate="",
                )
            ]
        )

        fig.update_layout(
            title=f"Porcentaje de estudiantes NO competentes — {plantel_usuario}",
            xaxis_title="Plantel",
            yaxis_title="% de estudiantes NO competentes",
            height=520,
            showlegend=False,
            uniformtext=dict(minsize=LABEL_FONT_SIZE_PLANTEL, mode="show"),
            yaxis=dict(range=[0, ymax * Y_AXIS_PADDING_MULT if ymax else 1]),
            margin=dict(t=70),
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        vals = df_matricula[df_matricula["Plantel"] == plantel_usuario]["matriculaTotal"].values
        matricula_plantel = int(vals[0]) if len(vals) else 0
        st.markdown(f"### 🎓 Matrícula total del plantel {plantel_usuario}: **{matricula_plantel:,}**")

        if not tabla_filtrada.empty and "Total estudiantes no competentes" in tabla_filtrada.columns:
            total_nc = int(tabla_filtrada["Total estudiantes no competentes"].iloc[0])
        else:
            df_exportar_tmp = obtener_detalle_no_competentes(plantel_usuario)
            total_nc = df_exportar_tmp["matricula"].nunique() if "matricula" in df_exportar_tmp.columns else len(df_exportar_tmp)

        porcentaje_nc = float(tabla_filtrada["% Estudiantes no competentes"].iloc[0]) if "% Estudiantes no competentes" in tabla_filtrada.columns else 0.0
        st.markdown(f"### 👥 Total de estudiantes NO competentes: **{total_nc:,}**")
        st.markdown(f"### 📊 Porcentaje respecto a la matrícula: **{porcentaje_nc:.2f}%**")

        df_exportar = obtener_detalle_no_competentes(plantel_usuario)

        st.subheader(f"⚠️ Estudiantes NO competentes {total_nc} (Detalle)")
        if df_exportar.empty:
            st.info("ℹ️ No hay registros de NO competentes para este plantel.")
        else:
            mostrar_dataframe_preview(df_exportar)

            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button(
                    label="📤 Exportar estudiantes a Excel",
                    data=generar_excel_no_competentes(plantel_usuario),
                    file_name=f"estudiantes_{slug(plantel_usuario)}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_b:
                st.download_button(
                    label="🖨️ Descargar HTML para imprimir",
                    data=generar_html_no_competentes(plantel_usuario),
                    file_name=f"no_competentes_{slug(plantel_usuario)}.html",
                    mime="text/html",
                    use_container_width=True
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
            mostrar_dataframe_preview(df_sin_registro_plantel)

            st.download_button(
                label="📤 Sin registro de Calificaciones",
                data=generar_excel_sin_registro(plantel_usuario),
                file_name=f"sin_registro_calificaciones_{slug(plantel_usuario)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
