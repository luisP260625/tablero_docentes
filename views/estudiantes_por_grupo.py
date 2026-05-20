# views/estudiantes_por_grupo.py
from __future__ import annotations

from pathlib import Path
import unicodedata
import pandas as pd
import streamlit as st


SHEET_NAME = "Grupos"
EXCEL_NAME = "Datos1.xlsx"


def _norm_txt(x) -> str:
    s = "" if x is None else str(x)
    s = s.strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def _find_col_like(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    low = [_norm_txt(c) for c in cols]

    for cand in candidates:
        c = _norm_txt(cand)
        for orig, lo in zip(cols, low):
            if lo == c or c in lo:
                return orig

    return None


def _sort_mixed(values: list):
    """Ordena lista que puede traer números/strings, por ejemplo semestres."""
    def key(v):
        s = str(v).strip()
        try:
            return (0, int(float(s)))
        except Exception:
            return (1, s)

    return sorted(values, key=key)


def _format_percent_entero(series: pd.Series) -> pd.Series:
    """
    Convierte una columna de porcentaje para mostrarla como número entero.

    Soporta valores como:
    - 25.7
    - 25.7%
    - 25,7%
    - 0.257 cuando Excel guarda el porcentaje como decimal

    Resultado:
    - 26
    """
    raw = series.copy()

    as_text = raw.astype(str).str.strip()
    has_percent_symbol = as_text.str.contains("%", regex=False).any()

    cleaned = (
        as_text
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace(r"[^\d\.\-]", "", regex=True)
    )

    numeric = pd.to_numeric(cleaned, errors="coerce")

    valid = numeric.dropna()

    # Si Excel guardó el porcentaje como decimal, por ejemplo 0.25 = 25%
    if not has_percent_symbol and not valid.empty:
        if valid.abs().max() <= 1:
            numeric = numeric * 100

    return numeric.round(0).astype("Int64")


@st.cache_data(show_spinner=False)
def _load_grupos() -> tuple[pd.DataFrame | None, str | None]:
    project_root = Path(__file__).resolve().parents[1]
    xlsx_path = project_root / "assets" / EXCEL_NAME

    if not xlsx_path.exists():
        return None, f"No existe el archivo: {xlsx_path}"

    try:
        df = pd.read_excel(xlsx_path, sheet_name=SHEET_NAME, engine="openpyxl")

        if df is None or df.empty:
            return None, f"La hoja '{SHEET_NAME}' está vacía."

        df.columns = [str(c).strip() for c in df.columns]

        return df, None

    except Exception as e:
        return None, str(e)


def mostrar_estudiantes_por_grupo():
    st.title("👥 Estudiantes por Grupo")
    st.caption("Fuente: assets/Datos1.xlsx → hoja 'Grupos'")

    df, err = _load_grupos()

    if err:
        st.error(f"❌ No se pudo leer la hoja '{SHEET_NAME}'. Detalle: {err}")
        return

    col_plantel = _find_col_like(df, ["Plantel"])
    col_semestre = _find_col_like(df, ["Semestre"])

    col_pct_reprobados = _find_col_like(
        df,
        [
            "% de reprobados",
            "% reprobados",
            "porcentaje de reprobados",
            "reprobados %",
            "porcentaje reprobados",
        ],
    )

    if not col_plantel or not col_semestre:
        st.error("❌ La hoja 'Grupos' debe contener las columnas: Plantel y Semestre.")
        st.write("Columnas detectadas:", list(df.columns))
        return

    # ==========
    # Filtros
    # ==========
    es_admin = bool(st.session_state.get("administrador", False))
    plantel_usuario = st.session_state.get("plantel_usuario")

    planteles = _sort_mixed(
        df[col_plantel]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if es_admin:
        plantel_sel = st.selectbox("🏫 Plantel", ["Todos"] + planteles, index=0)
    else:
        plantel_sel = str(plantel_usuario).strip() if plantel_usuario else ""

        if not plantel_sel:
            st.warning("No se detectó plantel del usuario en sesión.")
            plantel_sel = st.selectbox("🏫 Plantel", planteles, index=0)
        else:
            st.info(f"Plantel (asignado por acceso): **{plantel_sel}**")

    df_f = df.copy()

    if plantel_sel != "Todos":
        df_f = df_f[
            df_f[col_plantel].astype(str).str.strip()
            == str(plantel_sel).strip()
        ].copy()

    semestres = _sort_mixed(
        df_f[col_semestre]
        .dropna()
        .unique()
        .tolist()
    )

    semestre_sel = st.selectbox("🎓 Semestre", ["Todos"] + semestres, index=0)

    if semestre_sel != "Todos":
        df_f = df_f[
            df_f[col_semestre].astype(str).str.strip()
            == str(semestre_sel).strip()
        ].copy()

    # ==========
    # Resultados
    # ==========
    st.markdown("### 📋 Resultados")
    st.write(f"Registros: **{len(df_f):,}**")

    # Se crea una copia únicamente para visualización.
    # Así no se altera la información original filtrada.
    df_display = df_f.copy()

    column_config = {}

    if col_pct_reprobados and col_pct_reprobados in df_display.columns:
        df_display[col_pct_reprobados] = _format_percent_entero(
            df_display[col_pct_reprobados]
        )

        column_config[col_pct_reprobados] = st.column_config.NumberColumn(
            col_pct_reprobados,
            format="%d",
        )

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )