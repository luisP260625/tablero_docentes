# views/indicadores_academicos.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime
import os
import re
import smtplib
import unicodedata
from email.message import EmailMessage

# =========================
# CONFIG (tamaños de texto)
# =========================
LABEL_FONT_SIZE_ADMIN = 15     # <- tamaño etiquetas gráfica admin (prueba 9, 10, 11, 12)
LABEL_FONT_SIZE_PLANTEL = 15   # <- tamaño etiquetas gráfica plantel (prueba 9, 10, 11, 12)

# Multiplicador para dar "aire" arriba y que no se corte la etiqueta
Y_AXIS_PADDING_MULT = 1.35


# =========================
# Permisos (menú / acciones)
# =========================
# Recomendación: validar por CÓDIGO (columna "Permiso"), no por ID.
# Así, aunque cambie el número de ID, mientras el código siga igual,
# el permiso se mantiene estable.
PERM_SEND_EMAIL_CODE = "SEND_EMAIL_INDICADORES"


def _parse_perm_ids(raw) -> set[int]:
    """Convierte '1,2,3' o [1,'2'] a {1,2,3}."""
    if raw is None:
        return set()

    # lista/tuple/set
    if isinstance(raw, (list, tuple, set)):
        out = set()
        for it in raw:
            out |= _parse_perm_ids(it)
        return out

    # dict: intenta llaves típicas
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



@st.cache_data
def cargar_catalogo_permisos_xlsx() -> dict[int, str]:
    """Lee hoja 'Permisos' (id, Permiso) y devuelve {id: 'CODIGO_PERMISO'}."""
    try:
        df = pd.read_excel("assets/Datos1.xlsx", sheet_name="Permisos")
    except Exception:
        return {}

    def _find_col_exact(name: str):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_id = _find_col_exact("id")
    col_perm = _find_col_exact("Permiso")

    if col_id is None or col_perm is None:
        return {}

    cat: dict[int, str] = {}
    for _, row in df.iterrows():
        rid = row.get(col_id)
        rperm = row.get(col_perm)
        if pd.isna(rid) or pd.isna(rperm):
            continue
        # id puede venir como float si Excel lo interpreta así
        try:
            pid = int(str(rid).strip())
        except Exception:
            continue
        code = str(rperm).strip()
        if code:
            cat[pid] = code
    return cat


def _parse_perm_codes(raw, catalog: dict[int, str]) -> set[str]:
    """Convierte permisos en cualquier forma a set de CÓDIGOS.

    Acepta:
      - "1,2,3" (IDs) -> se mapea a códigos vía hoja 'Permisos'
      - "MENU_X,SEND_EMAIL_INDICADORES" (códigos)
      - listas/sets/tuplas mixtas
      - dicts con llaves típicas
    """
    if raw is None:
        return set()

    # lista/tuple/set
    if isinstance(raw, (list, tuple, set)):
        out: set[str] = set()
        for it in raw:
            out |= _parse_perm_codes(it, catalog)
        return out

    # dict: intenta llaves típicas
    if isinstance(raw, dict):
        out: set[str] = set()
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

    # separa por coma, punto y coma, pipe o espacios
    parts = re.split(r"[\s,;|]+", s)
    out: set[str] = set()
    for t in parts:
        t = t.strip()
        if not t:
            continue
        # token numérico => mapear a código si existe
        if t.isdigit():
            pid = int(t)
            code = catalog.get(pid)
            if code:
                out.add(code)
        else:
            # token ya es código
            out.add(t)
    return out


@st.cache_data
def cargar_permisos_usuarios_codigos_xlsx() -> dict[str, set[str]]:
    """Lee hoja 'Planteles' (Usuario, Permisos) y regresa {usuario: set(códigos)}.

    Nota: La columna Permisos puede contener IDs ("1,2,3") o códigos
    ("MENU_X,SEND_EMAIL_INDICADORES"). Si son IDs, se traducen usando hoja 'Permisos'.
    """
    try:
        df = pd.read_excel("assets/Datos1.xlsx", sheet_name="Planteles")
    except Exception:
        return {}

    catalog = cargar_catalogo_permisos_xlsx()

    def _find_col_exact(name: str):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_user = _find_col_exact("Usuario")
    col_perms = _find_col_exact("Permisos")

    if col_user is None or col_perms is None:
        return {}

    mapping: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        u = str(row.get(col_user, "")).strip()
        if not u or u.lower() in ("nan", "none"):
            continue
        mapping[u] = _parse_perm_codes(row.get(col_perms), catalog)

    return mapping


def obtener_permisos_usuario_codigos() -> set[str]:
    """Devuelve el set de CÓDIGOS de permisos del usuario logueado.

    Prioridad:
      1) session_state (si ya lo carga validator/app)
      2) hoja 'Planteles' (Usuario -> Permisos), traducido por hoja 'Permisos'
    """
    catalog = cargar_catalogo_permisos_xlsx()

    # 1) desde sesión (varios nombres posibles)
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

    # 2) desde Excel (Planteles)
    username = _get_username_from_session()
    if username:
        m = cargar_permisos_usuarios_codigos_xlsx()
        if username in m:
            return m[username]
        for u, codes in m.items():
            if u.lower() == username.lower():
                return codes

    return set()



def _get_username_from_session() -> str | None:
    """Intenta detectar el usuario logueado desde st.session_state (sin romper compatibilidad)."""
    for k in (
        "usuario", "username", "user", "Usuario", "USER", "login_user", "current_user",
        "user_name", "user_email", "email"
    ):
        v = st.session_state.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

        # en caso de que sea un dict/obj con username
        if isinstance(v, dict):
            for kk in ("usuario", "username", "user", "name", "email"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()

    return None


@st.cache_data
def cargar_permisos_usuarios_xlsx() -> dict[str, set[int]]:
    """Lee hoja 'Planteles' (Usuario, Permisos) y regresa {usuario: set(ids)}."""
    df = pd.read_excel("assets/Datos1.xlsx", sheet_name="Planteles")

    def _find_col_exact(name: str):
        for c in df.columns:
            if str(c).strip().lower() == name.lower():
                return c
        return None

    col_user = _find_col_exact("Usuario")
    col_perms = _find_col_exact("Permisos")

    if col_user is None or col_perms is None:
        # No romper la app si la hoja cambia: simplemente no hay permisos por XLSX
        return {}

    mapping: dict[str, set[int]] = {}
    for _, row in df.iterrows():
        u = str(row.get(col_user, "")).strip()
        if not u or u.lower() in ("nan", "none"):
            continue
        mapping[u] = _parse_perm_ids(row.get(col_perms))

    return mapping


def obtener_permisos_usuario() -> set[int]:
    """
    Devuelve el set de IDs de permisos del usuario logueado.
    Prioridad:
      1) session_state (si ya lo carga validator/app)
      2) hoja 'Planteles' (Usuario -> Permisos)
    """
    # 1) desde sesión (varios nombres posibles)
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

    # 2) desde Excel (Planteles)
    username = _get_username_from_session()
    if username:
        m = cargar_permisos_usuarios_xlsx()
        # match exact o case-insensitive
        if username in m:
            return m[username]
        for u, ids in m.items():
            if u.lower() == username.lower():
                return ids

    return set()

# =========================
# Carga de datos
# =========================
@st.cache_data
def cargar_datos():
    df_reprobacion = pd.read_excel("assets/Datos1.xlsx", sheet_name="Reprobacion")
    df_matricula = pd.read_excel(
        "assets/Datos1.xlsx", sheet_name="Matricula", usecols=["Plantel", "matriculaTotal"]
    )

    # ✅ NUEVO: hoja Datos (para % No competencia por módulo)
    try:
        df_datos = pd.read_excel("assets/Datos1.xlsx", sheet_name="Datos")
    except Exception:
        df_datos = None  # No romper si no existe

    return df_reprobacion, df_matricula, df_datos


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
# ✅ NUEVO: Helpers robustos para columnas (acentos, may/min, espacios)
# =========================
def _norm_txt(x) -> str:
    s = "" if x is None else str(x)
    s = s.strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def _find_col_like(df: pd.DataFrame, candidates: list[str]):
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
    """
    Convierte valores de SEMESTRE a entero (1,3,5,...).
    Soporta: 1, "1", "1er", "primero", "tercero", "quinto", etc.
    """
    if v is None:
        return None

    # numérico puro
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

    # palabras comunes
    if "prim" in s_norm:
        return 1
    if "terc" in s_norm:
        return 3
    if "quint" in s_norm:
        return 5

    # números dentro del texto
    nums = re.findall(r"\d+", str(v))
    return int(nums[0]) if nums else None


def modulo_mayor_porcentaje_no_competencia(df_datos: pd.DataFrame, plantel: str):
    """
    Retorna (modulo, pct_nc, semana_usada, err_msg)

    Cálculo idéntico al módulo views/no_competentes.py:
      pct_nc = (sum(NO COMPETENTES) / sum(TOTAL ALUMNOS)) * 100

    Si existe columna 'Semana', usa por defecto la semana más reciente (máximo).
    """
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

    # Filtrar plantel
    dfp = df[df[col_plantel].astype(str).str.strip() == str(plantel).strip()].copy()
    if dfp.empty:
        return None, None, None, "No hay registros en hoja 'Datos' para el plantel seleccionado."

    # Si hay Semana, tomar la más reciente
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

    # Asegurar numéricos
    dfp[col_nc] = pd.to_numeric(dfp[col_nc], errors="coerce").fillna(0)
    dfp[col_total] = pd.to_numeric(dfp[col_total], errors="coerce").fillna(0)

    # Agrupar
    g = dfp.groupby(col_mod, dropna=True).agg(
        NO_COMP=(col_nc, "sum"),
        TOTAL=(col_total, "sum"),
    ).reset_index()

    g = g[g["TOTAL"] > 0].copy()
    if g.empty:
        return None, None, semana_usada, "No fue posible calcular % (TOTAL ALUMNOS en 0 o vacío)."

    g["PCT"] = (g["NO_COMP"] / g["TOTAL"]) * 100.0

    # Orden por mayor %, desempate por NO_COMP, TOTAL, y nombre
    g[col_mod] = g[col_mod].astype(str).str.strip()
    g = g.sort_values(by=["PCT", "NO_COMP", "TOTAL", col_mod], ascending=[False, False, False, True])

    modulo = str(g.iloc[0][col_mod])
    pct = float(g.iloc[0]["PCT"])

    return modulo, round(pct, 2), semana_usada, None


# =========================
# ✅ NUEVO: Top 3 módulos por semestre (1,3,5) para el correo
# =========================
def top_modulos_porcentaje_no_competencia_por_semestre(
    df_datos: pd.DataFrame,
    plantel: str,
    semestres: tuple[int, ...] = (1, 3, 5),
    top_n: int = 3
):
    """
    Retorna (top_dict, semana_usada, err_msg)

    top_dict:
      {
        1: [(modulo, pct), (modulo, pct), (modulo, pct)],
        3: [...],
        5: [...]
      }

    pct = (sum(NO COMPETENTES) / sum(TOTAL ALUMNOS)) * 100
    Usa semana más reciente (si existe columna Semana).
    """
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

    # Filtrar plantel
    dfp = df[df[col_plantel].astype(str).str.strip() == str(plantel).strip()].copy()
    if dfp.empty:
        return {}, None, "No hay registros en hoja 'Datos' para el plantel seleccionado."

    # Si hay Semana, tomar la más reciente
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

    # Asegurar numéricos
    dfp[col_nc] = pd.to_numeric(dfp[col_nc], errors="coerce").fillna(0)
    dfp[col_total] = pd.to_numeric(dfp[col_total], errors="coerce").fillna(0)

    # Mapear semestre a número (1,3,5...)
    dfp["_SEM_KEY_"] = dfp[col_semestre].apply(_sem_key)

    top_dict: dict[int, list[tuple[str, float]]] = {}
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
# Email (SMTP)
# =========================
@st.cache_data
def cargar_emails_planteles():
    """
    Lee 'assets/Datos1.xlsx' hoja 'Planteles' y regresa un dict:
    {
      'Nombre Plantel': {
          'to': ['correo@..', ...],     # columna Email
          'cc': ['copia@..', ...],      # columna Ccp (opcional)
      }
    }
    """
    df = pd.read_excel("assets/Datos1.xlsx", sheet_name="Planteles")

    def _find_col(obj):
        for c in df.columns:
            if str(c).strip().lower() == obj.lower():
                return c
        return None

    col_plantel = _find_col("Plantel")
    col_email = _find_col("Email")
    col_ccp = _find_col("Ccp")  # <- NUEVO: CC

    if col_plantel is None or col_email is None:
        raise KeyError("La hoja 'Planteles' debe contener las columnas 'Plantel' y 'Email'.")

    mapping = {}
    for _, row in df.iterrows():
        plantel = str(row.get(col_plantel, "")).strip()
        email_raw = str(row.get(col_email, "")).strip()

        if not plantel or plantel.lower() in ("nan", "none"):
            continue

        # TO
        to_list = []
        if email_raw and email_raw.lower() not in ("nan", "none"):
            to_list = [e.strip() for e in re.split(r"[;,]+", email_raw) if e.strip()]

        # CC (Ccp)
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
    """
    destinatarios: lista TO
    cc: lista CC (Ccp)
    """
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


def contar_sin_calificaciones(df_reprobacion: pd.DataFrame, plantel: str) -> int:
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


def _formatear_top_por_semestre(top_dict: dict[int, list[tuple[str, float]]], semana_usada):
    """
    Devuelve string con:
      Semestre 1: 1) ... 2) ... 3) ...
      Semestre 3: ...
      Semestre 5: ...
    """
    orden = [1, 3, 5]
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


def texto_correo_plantel(
    plantel: str,
    total_no_comp: int,
    total_sin_calif: int,
    top_por_semestre: dict[int, list[tuple[str, float]]] | None,
    semana_usada,
    mod_err: str | None
) -> str:
    if top_por_semestre and any(len(v) > 0 for v in top_por_semestre.values()):
        extra = "\n" + _formatear_top_por_semestre(top_por_semestre, semana_usada) + "\n"
    else:
        extra = f"\nMódulos con MAYOR % de NO COMPETENCIA por semestre (plantel): No se pudo determinar con certeza. Motivo: {mod_err}\n"

    return (
        f"Estimado Plantel {plantel}:\n"
        "\nAnteponiendo un cordial saludo, al cierre del semestre ordinario del periodo 12526, "
        f"el plantel a su digno cargo registra {total_no_comp} estudiantes NO COMPETENTES y "
        f"{total_sin_calif} estudiantes SIN EVALUACIÓN en algún módulo.\n"
        "Agradecemos las estrategias y acciones implementadas para el seguimiento académico del estudiantado, "
        "e invitamos a continuar fortaleciendo las actividades necesarias para garantizar el cierre oportuno y "
        "adecuado del proceso de evaluación.\n"
        "\nA continuación, se presentan los módulos que registran el mayor porcentaje de NO COMPETENCIA en este cierre de semestre:\n"
        f"{extra}\n"
        "\nPara consultar información detallada, particular o completa sobre los avances y resultados del plantel, "
        "le invitamos a revisar el tablero institucional en el siguiente enlace:\n"
        "https://tablero-docentes.conalepmexacademica.app/\n"
        "\nSin otro particular, reciba un cordial saludo.\n"

    )


def construir_borradores_envio(
    plantel_sel: str,
    planteles_disponibles: list,
    tabla: pd.DataFrame,
    df_reprobacion: pd.DataFrame,
    df_datos: pd.DataFrame,
    emails_map: dict
):
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

        # ✅ NUEVO: Top 3 por semestre (1,3,5)
        top_por_semestre, semana_usada, mod_err = top_modulos_porcentaje_no_competencia_por_semestre(df_datos, p)

        asunto = f"Indicadores académicos - {p}"
        cuerpo = texto_correo_plantel(
            plantel=p,
            total_no_comp=total_no_comp,
            total_sin_calif=total_sin_calif,
            top_por_semestre=top_por_semestre,
            semana_usada=semana_usada,
            mod_err=mod_err
        )

        borradores.append({
            "plantel": p,
            "to": destinatarios,
            "cc": cc_list,
            "subject": asunto,
            "body": cuerpo,
        })

    return borradores, sin_email


def enviar_borradores(borradores: list):
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
# Vista principal
# =========================
def mostrar_indicadores_academicos():
    st.title("📊 Indicadores Académicos")

    df_reprobacion, df_matricula, df_datos = cargar_datos()

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
    # Rol / permisos
    # =========================
    is_admin = bool(st.session_state.get("administrador", False))
    plantel_usuario = st.session_state.get("plantel_usuario") or st.session_state.get("plantel")
    es_plantel = bool(plantel_usuario) and not is_admin

    permisos_codes = obtener_permisos_usuario_codigos()
    puede_enviar_email = (not es_plantel) and (PERM_SEND_EMAIL_CODE in permisos_codes)

    # =========================
    # USUARIO GLOBAL (Admin u otros)
    # =========================
    if not es_plantel:

        vista = st.radio(
            "Visualización de la gráfica:",
            ["% NO competencia", "Total NO competentes"],
            horizontal=True
        )

        # ✅ Orden: por % cuando se visualiza "% NO competencia"; por TOTAL cuando se visualiza "Total NO competentes"
        sort_col = "Total estudiantes no competentes" if vista == "Total NO competentes" else "% Estudiantes no competentes"
        tabla_ordenada = tabla.sort_values(by=sort_col, ascending=False).copy()

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

        total_general = int(tabla["Total estudiantes no competentes"].sum())
        total_matricula = float(tabla["matriculaTotal"].sum())
        porcentaje_promedio = round((total_general / total_matricula) * 100, 2) if total_matricula else 0
        st.markdown(f"### 👥 Total general de estudiantes NO competentes: **{total_general:,}**")
        st.markdown(f"### 📊 Porcentaje respecto a la matrícula: **{porcentaje_promedio}%**")

        st.markdown("---")
        st.subheader("🖨️ Imprimir / exportar NO competentes por plantel")

        planteles_disponibles = sorted(df_reprobacion["Plantel"].dropna().unique().tolist())
        opciones_plantel = ["Todos"] + planteles_disponibles
        plantel_sel = st.selectbox("Selecciona un plantel", opciones_plantel)

        columnas_base = ["ESTUDIANTE", "matricula", "CARRERA", "MODULO", "DOCENTE", "grado", "cvegrupo"]

        if plantel_sel == "Todos":
            df_print = df_reprobacion.copy()
        else:
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
        # Envío de correo (requiere permiso 10: SEND_EMAIL_INDICADORES)
        # =========================
        if puede_enviar_email:
            # =========================
            # Confirmación tipo ALERTA antes de enviar
            # =========================
            if "confirm_send_open" not in st.session_state:
                st.session_state.confirm_send_open = False
            if "email_send_result" not in st.session_state:
                st.session_state.email_send_result = None

            if st.button("📧 Enviar correo", key="btn_enviar_correo_indicadores"):
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

                borradores, sin_email = construir_borradores_envio(
                    plantel_sel=plantel_sel,
                    planteles_disponibles=planteles_disponibles,
                    tabla=tabla,
                    df_reprobacion=df_reprobacion,
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
                    if st.button("✅ De acuerdo", key="btn_confirmar_envio"):
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
                    if st.button("❌ Cancelar", key="btn_cancelar_envio"):
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
            st.info("ℹ️ Tu usuario no tiene permiso para enviar correos desde este módulo (permiso 10: SEND_EMAIL_INDICADORES).")


    # =========================
    # PLANTEL (no administrador)
    # =========================
    else:
        if not plantel_usuario:
            st.error("No se detectó el plantel del usuario en la sesión (plantel_usuario).")
            return


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
            xaxis_title="Semana",
            yaxis_title="Cantidad de estudiantes",
            height=520,
            showlegend=False,
            uniformtext=dict(minsize=LABEL_FONT_SIZE_PLANTEL, mode="show"),
            yaxis=dict(range=[0, ymax * Y_AXIS_PADDING_MULT if ymax else 1]),
            margin=dict(t=70),
        )

        st.plotly_chart(fig, use_container_width=True)

        tabla_filtrada = tabla[tabla["Plantel"] == plantel_usuario]
        st.subheader(f"📋 Estudiantes del plantel: {plantel_usuario}")
        st.dataframe(tabla_filtrada, use_container_width=True)

        vals = df_matricula[df_matricula["Plantel"] == plantel_usuario]["matriculaTotal"].values
        matricula_plantel = int(vals[0]) if len(vals) else 0
        st.markdown(f"### 🎓 Matrícula total del plantel {plantel_usuario}: **{matricula_plantel:,}**")

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
