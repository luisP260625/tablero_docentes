# views/comportamiento.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Any, List
import io
import unicodedata

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
    # sin etiqueta de eje Y

    # ticks/limites: solo semanas existentes
    ax.set_xticks(semanas)
    ax.set_xlim(min(semanas) - 0.5, max(semanas) + 0.5)

    # margen superior para que no se salgan las etiquetas
    y_max = max(no_comp) if no_comp else 0
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)

    # etiquetas “NO_COMP - %”
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

    ult_sem = int(pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").dropna().astype(int).max())
    df_u = df_docente[pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").astype("Int64") == ult_sem].copy()

    agg = (
        df_u.groupby([COL_MODULO, COL_SEMESTRE], dropna=False)[[COL_NO_COMP, COL_COMPET, COL_TOTAL]]
        .sum(numeric_only=True)
        .reset_index()
    )
    agg["porcentaje_no_comp"] = agg.apply(
        lambda r: (r[COL_NO_COMP] / r[COL_TOTAL] * 100) if r[COL_TOTAL] > 0 else 0.0, axis=1
    )

    # Renombrar a los encabezados solicitados
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
    semanas_df: pd.DataFrame,      # columnas: semana, no_comp, total
    tabla_modulos_df: pd.DataFrame # columnas renombradas: Modulo, semestre, no_com, competentes, total, porcentaje_no_comp
) -> bytes:
    """Crea un Excel con dos hojas: 'Comportamiento semanal' y 'Módulos última semana', más metadatos."""
    buffer = io.BytesIO()
    try:
        writer = pd.ExcelWriter(buffer, engine="xlsxwriter")
    except Exception:
        writer = pd.ExcelWriter(buffer)  # fallback

    with writer:
        # ---- Hoja 1: Comportamiento semanal ----
        hoja1 = "Comportamiento semanal"
        # metadatos
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
                "Valor": [plantel, docente, sem_min, sem_max, sem_list_str,
                          "El porcentaje corresponde a NO_COMP/TOTAL por semana."]
            }
        )
        meta1.to_excel(writer, sheet_name=hoja1, index=False, startrow=0)

        # cuerpo: semanas con % calculado
        if semanas_df is not None and not semanas_df.empty:
            semanas_out = semanas_df.copy()
            semanas_out["porcentaje_no_comp"] = semanas_out.apply(
                lambda r: (r["no_comp"] / r["total"] * 100) if r["total"] else 0.0, axis=1
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
            pass
        if semanas_df is not None and not semanas_df.empty:
            _auto_width_xlsx(ws1, semanas_out, start_col=0)

        # ---- Hoja 2: Módulos última semana ----
        hoja2 = "Módulos última semana"
        meta2 = pd.DataFrame({"Campo": ["Plantel", "Docente"], "Valor": [plantel, docente]})
        meta2.to_excel(writer, sheet_name=hoja2, index=False, startrow=0)
        startrow2 = len(meta2) + 2
        tabla_out = tabla_modulos_df.copy() if tabla_modulos_df is not None else pd.DataFrame()
        tabla_out.to_excel(writer, sheet_name=hoja2, index=False, startrow=startrow2)
        ws2 = writer.sheets[hoja2]
        try:
            ws2.write(0, 0, "Campo", fmt_bold)
            ws2.write(0, 1, "Valor", fmt_bold)
        except Exception:
            pass
        _auto_width_xlsx(ws2, tabla_out, start_col=0)

    buffer.seek(0)
    return buffer.getvalue()


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
      - Generar Excel con ambas secciones + semanas transcurridas.
    """
    base = _to_pandas(df)
    if base is None or base.shape[0] == 0:
        st.warning("No hay datos para mostrar.")
        return

    # Validación estricta de columnas
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
        default_idx = planteles.index(plantel_usuario) if plantel_usuario in planteles else 0
        sel_plantel = st.selectbox(
            "Selecciona un plantel", planteles, index=default_idx, key="cmp_sel_plantel_comportamiento"
        )
    else:
        sel_plantel = plantel_usuario
        st.text_input("Plantel", sel_plantel or "", disabled=True, key="cmp_plantel_ro_comportamiento")

    df_plantel = base[base[COL_PLANTEL].astype(str) == str(sel_plantel)].copy() if sel_plantel else base.copy()

    # ---------- selección de docente ----------
    docentes = sorted(df_plantel[COL_DOCENTE].dropna().astype(str).unique().tolist())
    if not docentes:
        st.info("No hay docentes para el plantel seleccionado.")
        return

    sel_docente = st.selectbox("Selecciona un docente", docentes, key="cmp_sel_docente_comportamiento")
    df_docente = df_plantel[df_plantel[COL_DOCENTE].astype(str) == str(sel_docente)].copy()

    # ================== Gráfica semanal (desde 'Datos') ==================
    # Agregamos por Semana: SUMA de NO_COMP y TOTAL
    df_docente[COL_SEMANA] = pd.to_numeric(df_docente[COL_SEMANA], errors="coerce").astype("Int64")
    sem = (
        df_docente
        .groupby(COL_SEMANA, dropna=False)[[COL_NO_COMP, COL_TOTAL]]
        .sum(numeric_only=True)
        .reset_index()
        .dropna(subset=[COL_SEMANA])
        .sort_values(COL_SEMANA)
    )
    sem = sem.rename(columns={COL_SEMANA: "semana", COL_NO_COMP: "no_comp", COL_TOTAL: "total"})
    _grafica_semanal(sem, titulo=f"Comportamiento semanal - {sel_docente}", color_hex="#c3b08f")

    # ================== Tabla de módulos (última semana) ==================
    st.markdown("**Módulos que ofrece el docente (última semana disponible)**")
    tabla = _tabla_modulos_ultima_semana(df_docente)
    st.dataframe(tabla, use_container_width=True)

    # ================== Botón Excel (docente) ==================
    docente_slug = _slugify_filename(sel_docente)
    nombre_excel = f"{docente_slug}_comportamiento.xlsx"
    excel_bytes = _excel_comportamiento_bytes(
        plantel=str(sel_plantel or ""),
        docente=str(sel_docente or ""),
        semanas_df=sem,
        tabla_modulos_df=tabla,
    )
    st.download_button(
        label="⬇️ Crear/Descargar Excel del docente",
        data=excel_bytes,
        file_name=nombre_excel,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Genera un Excel con el comportamiento semanal y la tabla de módulos de la última semana.",
        key="cmp_btn_excel_docente"
    )
