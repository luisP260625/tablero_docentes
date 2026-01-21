# views/historico_indicadores.py
from __future__ import annotations

from pathlib import Path
import re
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

SHEET_NAME = "Indicadores"
EXCEL_FILENAME = "Historico.xlsx"

# Columna con el nombre del indicador (serie)
INDICADOR_COL_NAME = "Indicadores Escolares"

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # /views -> raíz del proyecto
EXCEL_PATH = PROJECT_ROOT / "assets" / EXCEL_FILENAME


def _norm(x) -> str:
    return str(x).strip().lower()


def _is_invertido(indicador_nombre: str) -> bool:
    """
    Indicadores donde BAJAR es BUENO (verde) y SUBIR es MALO (rojo):
      - Abandono Escolar
      - Reprobación Semestral
    Soporta variantes como "(%)", espacios, mayúsculas, acentos.
    """
    s = _norm(indicador_nombre)
    s = re.sub(r"\s+", " ", s)

    # Detecta por "contiene" para tolerar "(%)", etc.
    if "abandono escolar" in s:
        return True
    if "reprobacion semestral" in s:
        return True
    # por si viene con acento raro o como "reprobación semestral"
    if "reprobación semestral" in s:
        return True

    return False


def _detect_header_row(raw: pd.DataFrame, max_rows: int = 40) -> int:
    """
    Busca la fila que parece encabezado detectando:
    - "Plantel"
    - "Indicadores Escolares"
    - y algún año tipo 2014/2015...
    """
    top = raw.head(max_rows).fillna("")
    for i in range(len(top)):
        row = [_norm(v) for v in top.iloc[i].tolist()]
        has_plantel = any("plantel" == v or "plantel" in v for v in row)
        has_ind = any("indicadores escolares" in v for v in row)
        has_year = any(re.fullmatch(r"\d{4}", re.sub(r"\.0$", "", str(v))) for v in row if v)
        if has_plantel and has_ind and has_year:
            return i
    return 0


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    new_cols = []
    for c in df.columns:
        cs = "" if pd.isna(c) else str(c).strip()
        cs = re.sub(r"\.0$", "", cs)  # 2014.0 -> 2014
        new_cols.append(cs)

    df = df.copy()
    df.columns = new_cols
    df = df.dropna(how="all")
    return df


@st.cache_data(show_spinner=False)
def _load_indicadores() -> tuple[pd.DataFrame | None, str | None]:
    if not EXCEL_PATH.exists():
        return None, f"No existe el archivo: {EXCEL_PATH}"

    try:
        raw = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=None, engine="openpyxl")
        header_row = _detect_header_row(raw)

        df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, header=header_row, engine="openpyxl")
        df = _clean_columns(df)
        return df, None
    except Exception as e:
        return None, str(e)


def _find_plantel_col(cols) -> str | None:
    for c in cols:
        if "plantel" in _norm(c):
            return c
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace("%", "", regex=False)
    s = s.str.replace(",", "", regex=False).str.replace(" ", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _color_ultimo_tramo(y_prev: float, y_last: float, indicador: str) -> str:
    """
    Regla general:
      - Sube => verde
      - Baja => rojo
      - Igual => naranja

    Regla invertida (ABANDONO ESCOLAR y REPROBACION SEMESTRAL):
      - Baja => verde (mejora)
      - Sube => rojo (empeora)
      - Igual => naranja
    """
    if y_last == y_prev:
        return "orange"

    if _is_invertido(indicador):
        return "green" if y_last < y_prev else "red"

    return "green" if y_last > y_prev else "red"


def _build_fig_last_segment(years: list[str], values: list[float | None], title: str):
    """
    Línea completa (azul) + SOLO último tramo (penúltimo -> último) coloreado según regla.
    """
    pts = [(y, v) for y, v in zip(years, values) if pd.notna(v)]
    if not pts:
        return None

    xs = [p[0] for p in pts]
    ys = [float(p[1]) for p in pts]

    fig = go.Figure()

    # Línea completa
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            line=dict(color="#1f77b4", width=2),
            marker=dict(size=6, color="#1f77b4"),
            showlegend=False,
        )
    )

    # Último tramo coloreado
    if len(xs) >= 2:
        y_prev, y_last = ys[-2], ys[-1]
        c = _color_ultimo_tramo(y_prev, y_last, title)

        fig.add_trace(
            go.Scatter(
                x=xs[-2:],
                y=ys[-2:],
                mode="lines",
                line=dict(color=c, width=5),
                showlegend=False,
            )
        )

        # Punto final resaltado (opcional)
        fig.add_trace(
            go.Scatter(
                x=[xs[-1]],
                y=[ys[-1]],
                mode="markers",
                marker=dict(size=9, color=c),
                showlegend=False,
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Año",
        yaxis_title="Valor",
        margin=dict(l=10, r=10, t=45, b=10),
        height=300,
    )
    fig.update_xaxes(type="category", tickangle=-45)
    return fig


def mostrar(plantel_usuario: str | None = None, administrador: bool = False):
    """
    - Si administrador=True -> muestra selector de plantel (puede ver todo)
    - Si administrador=False y plantel_usuario viene definido -> fuerza ese plantel (sin selector)
    - Si no hay plantel_usuario -> fallback a selector (por seguridad)
    """
    st.title("📈 Histórico de Indicadores")

    df, err = _load_indicadores()
    if err:
        st.error(f"❌ No pude leer el Excel/hoja. Detalle: {err}")
        st.info(f"Ruta esperada: {EXCEL_PATH}")
        return

    plantel_col = _find_plantel_col(df.columns)
    if plantel_col is None:
        st.error("❌ No encontré la columna 'Plantel' en la hoja 'Indicadores'.")
        st.write("Columnas detectadas:", list(df.columns))
        return

    indicador_col = None
    for c in df.columns:
        if _norm(INDICADOR_COL_NAME) == _norm(c) or _norm(INDICADOR_COL_NAME) in _norm(c):
            indicador_col = c
            break

    if indicador_col is None:
        st.error(f"❌ No encontré la columna '{INDICADOR_COL_NAME}'.")
        st.write("Columnas detectadas:", list(df.columns))
        return

    # === Planteles disponibles ===
    planteles = sorted(df[plantel_col].dropna().astype(str).unique().tolist())
    if not planteles:
        st.warning("⚠️ No hay planteles (columna Plantel vacía).")
        return

    # ✅ Lógica solicitada:
    # - Admin: selectbox
    # - Plantel: plantel fijo (sin selectbox)
    plantel_sel = None

    if administrador or not plantel_usuario:
        plantel_sel = st.selectbox("Selecciona el plantel", options=planteles, index=0)
    else:
        plantel_sel = str(plantel_usuario).strip()
        st.info(f"👤 Vista Plantel: mostrando únicamente el plantel **{plantel_sel}**")

        # Validación: que el plantel exista exactamente en el Excel
        planteles_norm = [str(p).strip() for p in planteles]
        if plantel_sel not in planteles_norm:
            st.error("❌ Tu plantel no existe en el histórico (revisa que el nombre coincida exactamente en el Excel).")
            st.write("Planteles detectados:", planteles)
            return

    # Filtrar plantel
    dfp = df[df[plantel_col].astype(str).str.strip() == str(plantel_sel).strip()].copy()

    # Años (columnas 4 dígitos)
    real_year_cols = [c for c in dfp.columns if re.fullmatch(r"\d{4}", str(c).strip())]
    real_year_cols = sorted(real_year_cols, key=lambda x: int(str(x)))

    ordered_cols = [plantel_col, indicador_col] + [c for c in real_year_cols if c not in {plantel_col, indicador_col}]
    extras = [c for c in dfp.columns if c not in ordered_cols]
    dfp = dfp[ordered_cols + extras]

    # === Tabla ===
    st.dataframe(dfp, use_container_width=True, hide_index=True)

    # === Gráficas (3 por fila) ===
    st.subheader("📊 Tendencia por indicador")
    st.caption(
        "Solo el último tramo (ej. 2024→2025) se colorea. "
        "Regla invertida: ABANDONO ESCOLAR y REPROBACION SEMESTRAL (baja=verde, sube=rojo)."
    )

    indicador_order = dfp[indicador_col].dropna().astype(str).tolist()
    indicador_order = list(dict.fromkeys(indicador_order))  # unique manteniendo orden

    years = [str(c).strip() for c in real_year_cols]

    charts_rendered = 0
    cols = st.columns(3)

    for ind in indicador_order:
        df_rows = dfp[dfp[indicador_col].astype(str).str.strip() == str(ind).strip()]
        if df_rows.empty:
            continue

        values = []
        for y in real_year_cols:
            s = _coerce_numeric(df_rows[y])
            v = float(s.mean()) if s.notna().any() else None  # promedio por si hay duplicados
            values.append(v)

        fig = _build_fig_last_segment(years, values, title=str(ind))
        if fig is None:
            continue

        if charts_rendered % 3 == 0:
            cols = st.columns(3)

        with cols[charts_rendered % 3]:
            st.plotly_chart(fig, use_container_width=True)

        charts_rendered += 1

    if charts_rendered == 0:
        st.info("No hay valores numéricos para graficar en los años del plantel seleccionado.")
