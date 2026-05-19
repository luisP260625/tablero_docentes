# views/comportamiento.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Any, List, Tuple
import io
import unicodedata
from datetime import datetime

# ====== Config Excel ======
EXCEL_PATH_DEFAULT = "assets/Datos1.xlsx"
SHEET_SEMCAPTURA = "SemCaptura"
SHEET_REPROBACION = "Reprobacion"

# ====== Nombres EXACTOS en tu Excel (hoja "Datos") ======
COL_PLANTEL   = "Plantel"
COL_DOCENTE   = "DOCENTE"
COL_SEMANA    = "Semana"
COL_MODULO    = "MODULO"
COL_SEMESTRE  = "SEMESTRE"
COL_NO_COMP   = "NO COMPETENTES"
COL_COMPET    = "COMPETENTES"
COL_TOTAL     = "TOTAL ALUMNOS"
COL_PCT_LABEL = "% de No competencia"   # solo informativa en Excel; recalculamos en app

# ====== Columnas requeridas en SemCaptura (según tu requerimiento) ======
SEMCAPTURA_COLS_REQUERIDAS = [
    "Modulo", "semestre", "grupo",
    "UAPRENDIZAJE", "RAPRENDIZAJE",
    "IEVALUAR", "IEVALUADOS", "PCAPTURA",
    "TOTALE", "ESTATUS"
]

# ------------------ utilidades ------------------
def _to_pandas(df: Any) -> Optional[pd.DataFrame]:
    """Convierte df (polars/pandas/lista de dicts) a pandas.DataFrame."""
    if df is None:
        return None

    if isinstance(df, pd.DataFrame):
        return df.copy()

    try:
        import polars as pl  # type: ignore
        if isinstance(df, pl.DataFrame):
            return df.to_pandas()
    except Exception:
        pass

    try:
        return pd.DataFrame(df)
    except Exception:
        return None


def _validar_columnas(base: pd.DataFrame, requeridas: List[str]) -> List[str]:
    return [c for c in requeridas if c not in base.columns]


def _norm_colname(s: str) -> str:
    """Normaliza nombres de columna para matching robusto (sin acentos, sin espacios, upper)."""
    if s is None:
        return ""

    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.strip().replace(" ", "").replace("_", "").replace(".", "").replace("-", "").upper()
    return s


def _norm_value(s: Any) -> str:
    """Normaliza valores para comparar textos de Excel de forma más segura."""
    if pd.isna(s):
        return ""

    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.strip().upper().split())


def _find_col(df: pd.DataFrame, nombres_posibles: List[str]) -> Optional[str]:
    """Busca una columna en df comparando con normalización."""
    if df is None or df.empty:
        return None

    mapa = {_norm_colname(c): c for c in df.columns}
    for nombre in nombres_posibles:
        key = _norm_colname(nombre)
        if key in mapa:
            return mapa[key]

    return None


def _seleccionar_columnas_case_insensitive(df: pd.DataFrame, cols_deseadas: List[str]) -> pd.DataFrame:
    """
    Selecciona columnas aunque en Excel vengan con diferente casing/espacios.
    Devuelve un DF con las columnas renombradas exactamente como cols_deseadas (si existen).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=cols_deseadas)

    mapa = {_norm_colname(c): c for c in df.columns}
    seleccion = {}

    for c in cols_deseadas:
        key = _norm_colname(c)
        if key in mapa:
            seleccion[c] = mapa[key]

    out = df[[seleccion[c] for c in cols_deseadas if c in seleccion]].copy()
    ren = {seleccion[k]: k for k in seleccion}
    out = out.rename(columns=ren)

    for c in cols_deseadas:
        if c not in out.columns:
            out[c] = pd.NA

    return out[cols_deseadas]


def _drop_columns_by_norm(df: pd.DataFrame, cols_a_eliminar: List[str]) -> pd.DataFrame:
    """Elimina columnas por nombre normalizado, por ejemplo status/estatus aunque vengan en mayúsculas."""
    if df is None or df.empty:
        return df

    keys_eliminar = {_norm_colname(c) for c in cols_a_eliminar}
    columnas_finales = [c for c in df.columns if _norm_colname(c) not in keys_eliminar]
    return df[columnas_finales].copy()


def _rename_column_by_norm(df: pd.DataFrame, nombre_actual: str, nombre_nuevo: str) -> pd.DataFrame:
    """Renombra una columna usando matching robusto."""
    if df is None or df.empty:
        return df

    actual_key = _norm_colname(nombre_actual)
    renames = {}

    for c in df.columns:
        if _norm_colname(c) == actual_key:
            renames[c] = nombre_nuevo

    if renames:
        df = df.rename(columns=renames)

    return df


def _as_numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _current_week_from_docente(df_docente: pd.DataFrame) -> Optional[int]:
    """Obtiene la última semana disponible del docente en la hoja Datos."""
    if df_docente is None or df_docente.empty or COL_SEMANA not in df_docente.columns:
        return None

    semanas = pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").dropna()
    if semanas.empty:
        return None

    return int(semanas.max())


def _set_index_consecutivo(df: pd.DataFrame, inicio: int = 1) -> pd.DataFrame:
    """
    Hace que el número que Streamlit muestra antes de la primera columna
    sea consecutivo: 1, 2, 3 ... n.
    """
    if df is None:
        return pd.DataFrame()

    out = df.copy().reset_index(drop=True)
    out.index = range(inicio, inicio + len(out))
    out.index.name = ""
    return out


def _grafica_semanal(sem_df: pd.DataFrame, titulo: str, color_hex: str = "#c3b08f") -> None:
    """
    Dibuja barras por semana con etiqueta 'NO_COMP - %' calculada como
    suma(NO COMPETENTES)/suma(TOTAL ALUMNOS) de cada semana.
    """
    if sem_df is None or sem_df.shape[0] == 0:
        st.info("Sin datos para la gráfica.")
        return

    semanas = sem_df["semana"].astype(int).tolist()
    no_comp = sem_df["no_comp"].astype(int).tolist()
    total   = sem_df["total"].astype(int).tolist()
    porcent = [(n / t) if t else 0.0 for n, t in zip(no_comp, total)]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(semanas, no_comp, width=0.6, align="center", color=color_hex, edgecolor=color_hex)

    if titulo:
        ax.set_title(titulo)

    ax.set_xlabel("Semana")
    ax.set_xticks(semanas)
    ax.set_xlim(min(semanas) - 0.5, max(semanas) + 0.5)

    y_max = max(no_comp) if no_comp else 0
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)

    LABEL_FONTSIZE = 8
    for i, bar in enumerate(bars):
        ax.annotate(
            f"{no_comp[i]} - {porcent[i]*100:.1f}%",
            xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            rotation=90,
            fontsize=LABEL_FONTSIZE,
        )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    st.pyplot(fig)


def _tabla_modulos_ultima_semana(df_docente: pd.DataFrame) -> pd.DataFrame:
    """Devuelve tabla con columnas solicitadas para la última semana disponible."""
    if df_docente is None or df_docente.shape[0] == 0:
        return pd.DataFrame(columns=["Modulo", "semestre", "no_com", "competentes", "total", "porcentaje_no_comp"])

    ult_sem = _current_week_from_docente(df_docente)
    if ult_sem is None:
        return pd.DataFrame(columns=["Modulo", "semestre", "no_com", "competentes", "total", "porcentaje_no_comp"])

    df_u = df_docente[pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").astype("Int64") == ult_sem].copy()

    agg = (
        df_u.groupby([COL_MODULO, COL_SEMESTRE], dropna=False)[[COL_NO_COMP, COL_COMPET, COL_TOTAL]]
        .sum(numeric_only=True)
        .reset_index()
    )

    agg["porcentaje_no_comp"] = agg.apply(
        lambda r: (r[COL_NO_COMP] / r[COL_TOTAL] * 100) if r[COL_TOTAL] > 0 else 0.0,
        axis=1
    )

    agg = agg.rename(columns={
        COL_MODULO: "Modulo",
        COL_SEMESTRE: "semestre",
        COL_NO_COMP: "no_com",
        COL_COMPET: "competentes",
        COL_TOTAL:  "total",
    })

    agg = agg[["Modulo", "semestre", "no_com", "competentes", "total", "porcentaje_no_comp"]]
    agg["porcentaje_no_comp"] = agg["porcentaje_no_comp"].round(1)

    return agg


# ====== helpers Excel ======
def _slugify_filename(text: str) -> str:
    """Convierte 'José Pérez / 3A' -> 'Jose_Perez__3A' y limpia caracteres inválidos."""
    if not isinstance(text, str):
        text = str(text or "")

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text).strip("_")


def _auto_width_xlsx(ws, df: pd.DataFrame, start_col=0):
    """Ajusta el ancho de columnas en xlsxwriter según contenido."""
    for idx, col in enumerate(df.columns, start=start_col):
        try:
            max_len_vals = df[col].astype(str).map(len).max() if not df.empty else 0
        except Exception:
            max_len_vals = 0

        header_len = len(str(col))
        width = min(max(max_len_vals, header_len) + 2, 60)

        try:
            ws.set_column(idx, idx, width)
        except Exception:
            pass


def _excel_comportamiento_bytes(
    *,
    plantel: str,
    docente: str,
    semanas_df: pd.DataFrame,
    tabla_modulos_df: pd.DataFrame
) -> bytes:
    """
    Se conserva por compatibilidad, aunque ya no se muestra el botón
    Crear/Descargar Excel del docente.
    """
    buffer = io.BytesIO()

    try:
        writer = pd.ExcelWriter(buffer, engine="xlsxwriter")
    except Exception:
        writer = pd.ExcelWriter(buffer)

    with writer:
        hoja1 = "Comportamiento semanal"

        if semanas_df is not None and not semanas_df.empty:
            semanas_ord = semanas_df["semana"].dropna().astype(int).sort_values().tolist()
            sem_min = min(semanas_ord)
            sem_max = max(semanas_ord)
            sem_list_str = ", ".join(str(s) for s in semanas_ord)
        else:
            sem_min = ""
            sem_max = ""
            sem_list_str = ""

        meta1 = pd.DataFrame(
            {
                "Campo": ["Plantel", "Docente", "Semana mínima", "Semana máxima", "Semanas con datos", "Nota"],
                "Valor": [
                    plantel,
                    docente,
                    sem_min,
                    sem_max,
                    sem_list_str,
                    "El porcentaje corresponde a NO_COMP/TOTAL por semana."
                ],
            }
        )

        meta1.to_excel(writer, sheet_name=hoja1, index=False, startrow=0)

        if semanas_df is not None and not semanas_df.empty:
            semanas_out = semanas_df.copy()
            semanas_out["porcentaje_no_comp"] = semanas_out.apply(
                lambda r: (r["no_comp"] / r["total"] * 100) if r["total"] else 0.0,
                axis=1
            ).round(1)

            semanas_out = semanas_out[["semana", "no_comp", "total", "porcentaje_no_comp"]]
            startrow = len(meta1) + 2
            semanas_out.to_excel(writer, sheet_name=hoja1, index=False, startrow=startrow)

        wb = writer.book
        ws1 = writer.sheets[hoja1]

        try:
            fmt_bold = wb.add_format({"bold": True, "font_size": 12})
            ws1.write(0, 0, "Campo", fmt_bold)
            ws1.write(0, 1, "Valor", fmt_bold)
        except Exception:
            fmt_bold = None

        if semanas_df is not None and not semanas_df.empty:
            _auto_width_xlsx(ws1, semanas_out, start_col=0)

        hoja2 = "Módulos última semana"
        meta2 = pd.DataFrame({"Campo": ["Plantel", "Docente"], "Valor": [plantel, docente]})
        meta2.to_excel(writer, sheet_name=hoja2, index=False, startrow=0)

        startrow2 = len(meta2) + 2
        tabla_out = tabla_modulos_df.copy() if tabla_modulos_df is not None else pd.DataFrame()
        tabla_out.to_excel(writer, sheet_name=hoja2, index=False, startrow=startrow2)

        ws2 = writer.sheets[hoja2]

        try:
            if fmt_bold is not None:
                ws2.write(0, 0, "Campo", fmt_bold)
                ws2.write(0, 1, "Valor", fmt_bold)
        except Exception:
            pass

        _auto_width_xlsx(ws2, tabla_out, start_col=0)

    buffer.seek(0)
    return buffer.getvalue()


# =========================
# Cargar hojas auxiliares
# =========================
@st.cache_data
def _cargar_hoja_excel(excel_path: str, sheet_name: str) -> pd.DataFrame:
    """
    Carga una hoja de Excel de forma robusta:
    - intenta el nombre exacto;
    - si falla, busca por nombre normalizado, por ejemplo Reprobación/Reprobacion.
    """
    try:
        return pd.read_excel(excel_path, sheet_name=sheet_name)
    except Exception:
        pass

    try:
        xls = pd.ExcelFile(excel_path)
        objetivo = _norm_colname(sheet_name)

        for hoja in xls.sheet_names:
            if _norm_colname(hoja) == objetivo:
                return pd.read_excel(excel_path, sheet_name=hoja)
    except Exception:
        pass

    return pd.DataFrame()


@st.cache_data
def _cargar_semcaptura(excel_path: str) -> pd.DataFrame:
    return _cargar_hoja_excel(excel_path, SHEET_SEMCAPTURA)


@st.cache_data
def _cargar_reprobacion(excel_path: str) -> pd.DataFrame:
    return _cargar_hoja_excel(excel_path, SHEET_REPROBACION)


def _preparar_semcaptura_docente(
    semcaptura_raw: pd.DataFrame,
    *,
    sel_docente: str,
    sel_plantel: Optional[str]
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra SemCaptura por docente y plantel.
    Retorna:
    - DataFrame listo para mostrar.
    - Mensaje de error/información si aplica.
    """
    if semcaptura_raw is None or semcaptura_raw.empty:
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'SemCaptura' o está vacía."

    col_docente_real = _find_col(semcaptura_raw, [COL_DOCENTE, "Docente"])
    if not col_docente_real:
        return pd.DataFrame(), "La hoja 'SemCaptura' no contiene una columna DOCENTE para poder filtrar."

    df_sc = semcaptura_raw[
        semcaptura_raw[col_docente_real].apply(_norm_value) == _norm_value(sel_docente)
    ].copy()

    col_plantel_real = _find_col(semcaptura_raw, [COL_PLANTEL, "Plantel"])
    if col_plantel_real and sel_plantel:
        df_sc = df_sc[
            df_sc[col_plantel_real].apply(_norm_value) == _norm_value(sel_plantel)
        ].copy()

    if df_sc.empty:
        return pd.DataFrame(), f"ℹ️ No hay registros en 'SemCaptura' para el docente **{sel_docente}**."

    df_sc_out = _seleccionar_columnas_case_insensitive(df_sc, SEMCAPTURA_COLS_REQUERIDAS)

    return df_sc_out.reset_index(drop=True), None


def _preparar_reprobacion_docente(
    reprobacion_raw: pd.DataFrame,
    *,
    sel_docente: str,
    sel_plantel: Optional[str],
    semana_actual: Optional[int]
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Filtra la hoja Reprobacion por docente, plantel y semana actual.

    Ajustes solicitados:
    - El título se genera aparte con el conteo.
    - No mostrar campo status/estatus.
    - Campo MINIMO se renombra a 'Porcentaje Mínimo para aprobar'.
    - El índice visible de la tabla debe iniciar en 1 y ser consecutivo hasta n.
    """
    if reprobacion_raw is None or reprobacion_raw.empty:
        return pd.DataFrame(), "ℹ️ No se encontró información en la hoja 'Reprobacion' o está vacía."

    col_docente_real = _find_col(reprobacion_raw, [COL_DOCENTE, "Docente"])
    if not col_docente_real:
        return pd.DataFrame(), "La hoja 'Reprobacion' no contiene una columna DOCENTE para poder filtrar."

    df_rep = reprobacion_raw[
        reprobacion_raw[col_docente_real].apply(_norm_value) == _norm_value(sel_docente)
    ].copy()

    col_plantel_real = _find_col(reprobacion_raw, [COL_PLANTEL, "Plantel"])
    if col_plantel_real and sel_plantel:
        df_rep = df_rep[
            df_rep[col_plantel_real].apply(_norm_value) == _norm_value(sel_plantel)
        ].copy()

    # Si existe columna Semana en Reprobacion, se filtra por la semana actual del docente.
    col_semana_real = _find_col(reprobacion_raw, [COL_SEMANA, "Semana"])
    if col_semana_real and semana_actual is not None:
        df_rep = df_rep[
            pd.to_numeric(df_rep[col_semana_real], errors="coerce").astype("Int64") == int(semana_actual)
        ].copy()

    if df_rep.empty:
        if semana_actual is not None:
            return pd.DataFrame(), (
                f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}** "
                f"en la semana **{semana_actual}**."
            )
        return pd.DataFrame(), f"ℹ️ No hay registros en 'Reprobacion' para el docente **{sel_docente}**."

    # No mostrar status/estatus.
    df_rep = _drop_columns_by_norm(df_rep, ["status", "estatus"])

    # MINIMO debe decir Porcentaje Mínimo para aprobar.
    df_rep = _rename_column_by_norm(
        df_rep,
        "MINIMO",
        "Porcentaje Mínimo para aprobar"
    )

    # El número antes de Plantel debe ser consecutivo desde 1 hasta n.
    df_rep = _set_index_consecutivo(df_rep, inicio=1)

    return df_rep, None


def _contar_estudiantes_no_competentes(df_rep_out: pd.DataFrame) -> int:
    """
    Cuenta estudiantes para el encabezado.
    Si existe matrícula, cuenta matrículas únicas; si no existe, cuenta filas.
    """
    if df_rep_out is None or df_rep_out.empty:
        return 0

    col_matricula = _find_col(df_rep_out, ["matricula", "matrícula", "MATRICULA"])
    if col_matricula:
        return int(df_rep_out[col_matricula].dropna().astype(str).str.strip().nunique())

    return int(len(df_rep_out))


# ------------------ interfaz pública ------------------
def mostrar(
    df: Any,
    plantel_usuario: Optional[str] = None,
    es_admin: bool = False,
) -> None:
    """
    Usa EXCLUSIVAMENTE la hoja 'Datos' (df) para:
      - Graficar NO COMPETENTES por semana (% sobre TOTAL).
      - Mostrar la tabla de módulos del docente (última semana).

    Además:
      - Mostrar tabla SemCaptura filtrada por docente/plantel.
      - Mostrar tabla Reprobacion filtrada por docente/plantel/semana actual.
    """
    base = _to_pandas(df)

    if base is None or base.shape[0] == 0:
        st.warning("No hay datos para mostrar.")
        return

    # Validación estricta de columnas (hoja Datos)
    faltantes = _validar_columnas(
        base,
        [COL_PLANTEL, COL_DOCENTE, COL_SEMANA, COL_NO_COMP, COL_COMPET, COL_TOTAL, COL_MODULO, COL_SEMESTRE]
    )

    if faltantes:
        st.error("Faltan columnas requeridas en 'Datos': " + ", ".join(faltantes))

        with st.expander("Columnas disponibles"):
            st.write(list(base.columns))

        return

    # ---------- selección de plantel ----------
    if es_admin:
        planteles = sorted(base[COL_PLANTEL].dropna().astype(str).unique().tolist())

        if not planteles:
            st.info("No hay planteles disponibles.")
            return

        default_idx = planteles.index(plantel_usuario) if plantel_usuario in planteles else 0

        sel_plantel = st.selectbox(
            "Selecciona un plantel",
            planteles,
            index=default_idx,
            key="cmp_sel_plantel_comportamiento"
        )
    else:
        sel_plantel = plantel_usuario
        st.text_input(
            "Plantel",
            sel_plantel or "",
            disabled=True,
            key="cmp_plantel_ro_comportamiento"
        )

    df_plantel = base[base[COL_PLANTEL].astype(str) == str(sel_plantel)].copy() if sel_plantel else base.copy()

    # ---------- selección de docente ----------
    docentes = sorted(df_plantel[COL_DOCENTE].dropna().astype(str).unique().tolist())

    if not docentes:
        st.info("No hay docentes para el plantel seleccionado.")
        return

    sel_docente = st.selectbox(
        "Selecciona un docente",
        docentes,
        key="cmp_sel_docente_comportamiento"
    )

    df_docente = df_plantel[df_plantel[COL_DOCENTE].astype(str) == str(sel_docente)].copy()

    # ================== Gráfica semanal (desde 'Datos') ==================
    df_docente[COL_SEMANA] = pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").astype("Int64")

    sem = (
        df_docente
        .groupby(COL_SEMANA, dropna=False)[[COL_NO_COMP, COL_TOTAL]]
        .sum(numeric_only=True)
        .reset_index()
        .dropna(subset=[COL_SEMANA])
        .sort_values(COL_SEMANA)
    )

    sem = sem.rename(columns={
        COL_SEMANA: "semana",
        COL_NO_COMP: "no_comp",
        COL_TOTAL: "total"
    })

    _grafica_semanal(
        sem,
        titulo=f"Comportamiento semanal - {sel_docente}",
        color_hex="#c3b08f"
    )

    # ================== Tabla de módulos (última semana) ==================
    st.markdown("**Módulos que ofrece el docente (última semana disponible)**")

    tabla = _tabla_modulos_ultima_semana(df_docente)
    st.dataframe(tabla, use_container_width=True)

    # IMPORTANTE:
    # Se eliminó el apartado "Resumen del docente seleccionado".
    # Se eliminó el botón "Crear/Descargar Excel del docente".

    # ================== Tabla SemCaptura ==================
    st.markdown("---")
    st.subheader("📋 Porcentaje de captura de evaluaciones.")

    semcaptura_raw = _cargar_semcaptura(EXCEL_PATH_DEFAULT)
    df_sc_out, msg_sc = _preparar_semcaptura_docente(
        semcaptura_raw,
        sel_docente=str(sel_docente or ""),
        sel_plantel=str(sel_plantel or "") if sel_plantel else None,
    )

    if msg_sc:
        if msg_sc.startswith("La hoja"):
            st.error(msg_sc)

            if semcaptura_raw is not None and not semcaptura_raw.empty:
                with st.expander("Columnas disponibles en SemCaptura"):
                    st.write(list(semcaptura_raw.columns))
        else:
            st.info(msg_sc)
    else:
        st.dataframe(df_sc_out, use_container_width=True, height=380)

    # IMPORTANTE:
    # Se eliminó el botón "Descarga Porcentaje de Captura",
    # porque la tabla de Streamlit permite descargar datos desde el menú de la tabla.

    # ================== Tabla Reprobacion ==================
    semana_actual = _current_week_from_docente(df_docente)
    semana_texto = str(semana_actual) if semana_actual is not None else "actual"

    reprobacion_raw = _cargar_reprobacion(EXCEL_PATH_DEFAULT)
    df_rep_out, msg_rep = _preparar_reprobacion_docente(
        reprobacion_raw,
        sel_docente=str(sel_docente or ""),
        sel_plantel=str(sel_plantel or "") if sel_plantel else None,
        semana_actual=semana_actual,
    )

    if msg_rep:
        st.info(msg_rep)
        return

    no_estudiantes = _contar_estudiantes_no_competentes(df_rep_out)

    st.markdown(
        f"### 📋 {no_estudiantes} Estudiantes NO Competentes en la semana {semana_texto}"
    )

    # El índice de esta tabla queda como 1, 2, 3... n
    # para evitar que aparezcan índices originales como 20993, 21023, etc.
    st.dataframe(df_rep_out, use_container_width=True, height=420)
