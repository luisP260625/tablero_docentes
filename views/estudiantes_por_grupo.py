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
    """Ordena lista que puede traer números/strings (ej. semestres)."""
    def key(v):
        s = str(v).strip()
        try:
            return (0, int(float(s)))
        except Exception:
            return (1, s)
    return sorted(values, key=key)


@st.cache_data(show_spinner=False)
def _load_grupos() -> tuple[pd.DataFrame | None, str | None]:
    project_root = Path(__file__).resolve().parents[1]  # /views -> raíz del proyecto
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

    if not col_plantel or not col_semestre:
        st.error("❌ La hoja 'Grupos' debe contener las columnas: Plantel y Semestre.")
        st.write("Columnas detectadas:", list(df.columns))
        return

    # ==========
    # Filtros
    # ==========
    es_admin = bool(st.session_state.get("administrador", False))
    plantel_usuario = st.session_state.get("plantel_usuario")

    # Plantel: Admin elige, Plantel se fuerza
    planteles = _sort_mixed(df[col_plantel].dropna().astype(str).unique().tolist())

    if es_admin:
        plantel_sel = st.selectbox("🏫 Plantel", ["Todos"] + planteles, index=0)
    else:
        # Rol plantel: forzamos
        plantel_sel = str(plantel_usuario).strip() if plantel_usuario else ""
        if not plantel_sel:
            st.warning("No se detectó plantel del usuario en sesión.")
            plantel_sel = st.selectbox("🏫 Plantel", planteles, index=0)  # fallback
        else:
            st.info(f"Plantel (asignado por acceso): **{plantel_sel}**")

    # Filtrar por plantel
    df_f = df.copy()
    if plantel_sel != "Todos":
        df_f = df_f[df_f[col_plantel].astype(str).str.strip() == str(plantel_sel).strip()].copy()

    # Semestre depende del plantel filtrado
    semestres = _sort_mixed(df_f[col_semestre].dropna().unique().tolist())
    semestre_sel = st.selectbox("🎓 Semestre", ["Todos"] + semestres, index=0)

    if semestre_sel != "Todos":
        df_f = df_f[df_f[col_semestre].astype(str).str.strip() == str(semestre_sel).strip()].copy()

    # ==========
    # Resultados
    # ==========
    st.markdown("### 📋 Resultados")
    st.write(f"Registros: **{len(df_f):,}**")

    st.dataframe(df_f, use_container_width=True, hide_index=True)

    # Descarga rápida
    st.download_button(
        "⬇️ Descargar Excel filtrado",
        data=df_f.to_csv(index=False).encode("utf-8"),
        file_name="estudiantes_por_grupo_filtrado.csv",
        mime="text/csv",
        use_container_width=True,
    )
