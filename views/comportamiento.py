# views/comportamiento.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Any, List

# ====== Nombres reales en tu Excel (Datos1.xlsx - hoja "Datos") ======
COL_PLANTEL_REAL = "Plantel"
COL_DOCENTE_REAL = "DOCENTE"
COL_SEMANA_REAL  = "Semana"


# ------------------ utilidades ------------------
def _to_pandas(df: Any) -> Optional[pd.DataFrame]:
    """
    Convierte df a pandas.DataFrame si viene en otro formato (p. ej. polars).
    """
    if df is None:
        return None
    if isinstance(df, pd.DataFrame):
        return df.copy()

    # Intento con polars
    try:
        import polars as pl  # type: ignore
        if isinstance(df, pl.DataFrame):
            return df.to_pandas()
    except Exception:
        pass

    # Intento genérico
    try:
        return pd.DataFrame(df)
    except Exception:
        return None


def _validar_columnas(base: pd.DataFrame, requeridas: List[str]) -> List[str]:
    """Devuelve lista de columnas faltantes respecto a 'requeridas'."""
    return [c for c in requeridas if c not in base.columns]


def _render_grafico_semanal(df_filtrado: pd.DataFrame, titulo: str = "") -> None:
    """
    Gráfico de barras categóricas por semana (NO histograma).
    - Solo muestra semanas existentes.
    - Color de barra #c3b08f.
    - Sin etiqueta de eje Y.
    - Etiquetas 'conteo - porcentaje' con margen para que no se salgan.
    """
    if df_filtrado is None or df_filtrado.shape[0] == 0:
        st.info("Sin datos para el filtro actual.")
        return

    df_plot = df_filtrado.copy()

    # Normaliza la columna 'semana' a entero (ya llega renombrada)
    if "semana" not in df_plot.columns:
        st.error("No se encontró la columna 'semana' en los datos.")
        return

    df_plot["semana"] = pd.to_numeric(df_plot["semana"], errors="coerce")
    df_plot = df_plot.dropna(subset=["semana"])
    if df_plot.shape[0] == 0:
        st.info("Sin datos para el filtro actual.")
        return

    df_plot["semana"] = df_plot["semana"].astype(int)

    conteo = df_plot["semana"].value_counts().sort_index()
    if conteo.shape[0] == 0:
        st.info("Sin datos para el filtro actual.")
        return

    semanas = conteo.index.to_list()   # p. ej. [5] o [5, 6]
    cantidades = conteo.values
    total = cantidades.sum()

    # --- Gráfico ---
    fig, ax = plt.subplots(figsize=(8, 4))

    # Color solicitado
    bar_color = "#c3b08f"
    ax.bar(semanas, cantidades, width=0.6, align="center", color=bar_color)

    # Título y ejes
    if titulo:
        ax.set_title(titulo)

    ax.set_xlabel("Semana")
    # ax.set_ylabel("Cantidad de registros")  # <- Eliminado a petición

    # Ticks solo de semanas existentes
    ax.set_xticks(semanas)

    # Margen superior para que las etiquetas no se salgan
    y_max = max(cantidades) if len(cantidades) > 0 else 0
    # Asegura ~20% de cabeza libre; mínimo +1 para casos de barra única
    margen = max(1, int(round(y_max * 0.2))) if y_max > 0 else 1
    ax.set_ylim(0, y_max + margen)

    # Etiquetas sobre cada barra, centradas, dentro del área del gráfico
    for x, y in zip(semanas, cantidades):
        pct = (y / total) if total else 0.0
        ax.annotate(
            f"{y} - {pct:.1%}",
            xy=(x, y),
            xytext=(0, 5),  # 5 puntos arriba del tope de la barra
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    # Opcional: limpiar bordes superiores/derechos para look más limpio
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    st.pyplot(fig)


# ------------------ interfaz pública ------------------
def mostrar(
    df: Any,
    plantel_usuario: Optional[str] = None,
    es_admin: bool = False,
) -> None:
    """
    Punto de entrada desde app.py
    - df: DataFrame (pandas o polars) con los datos completos.
    - plantel_usuario: plantel del usuario (si no es admin, se fija a éste).
    - es_admin: True si el usuario puede elegir cualquier plantel.
    """
    base = _to_pandas(df)
    if base is None or base.shape[0] == 0:
        st.warning("No hay datos para mostrar.")
        return

    # ---- Validación de columnas reales de tu archivo ----
    faltantes = _validar_columnas(
        base,
        [COL_PLANTEL_REAL, COL_DOCENTE_REAL, COL_SEMANA_REAL],
    )
    if faltantes:
        st.error("Faltan columnas requeridas en los datos: " + ", ".join(faltantes))
        with st.expander("Columnas disponibles en el DataFrame"):
            st.write(list(base.columns))
        return

    # ---------- selección de plantel ----------
    if es_admin:
        planteles = sorted(base[COL_PLANTEL_REAL].dropna().astype(str).unique().tolist())
        if planteles:
            default_idx = planteles.index(plantel_usuario) if plantel_usuario in planteles else 0
        else:
            planteles, default_idx = [""], 0

        sel_plantel = st.selectbox(
            "Selecciona un plantel",
            planteles,
            index=default_idx,
            key="cmp_sel_plantel_comportamiento",
        )
    else:
        # Usuario no admin: fijamos su plantel y lo mostramos bloqueado
        sel_plantel = plantel_usuario
        st.text_input("Plantel", sel_plantel or "", disabled=True, key="cmp_plantel_ro_comportamiento")

    df_plantel = base[base[COL_PLANTEL_REAL].astype(str) == str(sel_plantel)] if sel_plantel else base.copy()

    # ---------- selección de docente ----------
    docentes = sorted(df_plantel[COL_DOCENTE_REAL].dropna().astype(str).unique().tolist())
    if not docentes:
        st.info("No hay docentes para el plantel seleccionado.")
        return

    sel_docente = st.selectbox(
        "Selecciona un docente",
        docentes,
        key="cmp_sel_docente_comportamiento",
    )

    df_filtrado = df_plantel[df_plantel[COL_DOCENTE_REAL].astype(str) == str(sel_docente)].copy()

    # Renombra la columna de semana a 'semana' para el motor de la gráfica
    df_filtrado = df_filtrado.rename(columns={COL_SEMANA_REAL: "semana"})

    # ---------- gráfica semanal (barras categóricas + formato solicitado) ----------
    _render_grafico_semanal(df_filtrado, titulo=f"Comportamiento semanal - {sel_docente}")
