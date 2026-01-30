from pathlib import Path
from io import BytesIO
import streamlit as st
import pandas as pd

from data.logger import obtener_bitacora_df


# ========= CONFIG (TU CASO) =========
CATALOGO_EXCEL_PATH = Path("assets/Datos1.xlsx")
CATALOGO_SHEET_NAME = "Planteles"
COL_PLANTEL = "Plantel"
COL_USUARIO = "Usuario"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _abs(p: Path) -> Path:
    return p if p.is_absolute() else (_project_root() / p).resolve()


def _sheet_match(xls: pd.ExcelFile, wanted: str) -> str | None:
    w = wanted.strip().lower()
    for s in xls.sheet_names:
        if s.strip().lower() == w:
            return s
    return None


@st.cache_data(ttl=600, show_spinner=False)
def _load_catalogo() -> pd.DataFrame:
    excel_path = _abs(CATALOGO_EXCEL_PATH)
    if not excel_path.exists():
        return pd.DataFrame(columns=[COL_PLANTEL, COL_USUARIO])

    try:
        xls = pd.ExcelFile(excel_path)
        sheet = _sheet_match(xls, CATALOGO_SHEET_NAME)
        if not sheet:
            return pd.DataFrame(columns=[COL_PLANTEL, COL_USUARIO])

        df = pd.read_excel(excel_path, sheet_name=sheet, dtype=str).fillna("")
        df.columns = [str(c).strip() for c in df.columns]

        if COL_PLANTEL not in df.columns or COL_USUARIO not in df.columns:
            return pd.DataFrame(columns=[COL_PLANTEL, COL_USUARIO])

        out = df[[COL_PLANTEL, COL_USUARIO]].copy()
        out[COL_PLANTEL] = out[COL_PLANTEL].astype(str).str.strip()
        out[COL_USUARIO] = out[COL_USUARIO].astype(str).str.strip().str.upper()

        out = out[(out[COL_PLANTEL] != "") & (out[COL_USUARIO] != "")]
        out = out[~out[COL_PLANTEL].str.lower().isin(["nan", "none"])]
        out = out[~out[COL_USUARIO].str.lower().isin(["nan", "none"])]

        out = out.drop_duplicates(subset=[COL_PLANTEL, COL_USUARIO]).sort_values([COL_PLANTEL, COL_USUARIO])
        return out

    except Exception:
        return pd.DataFrame(columns=[COL_PLANTEL, COL_USUARIO])


def _load_logs() -> pd.DataFrame:
    df = obtener_bitacora_df()
    if df is None or df.empty:
        return pd.DataFrame(columns=["Plantel", "Usuario", "FechaHora"])

    df = df.copy()
    for col in ["Plantel", "Usuario", "FechaHora"]:
        if col not in df.columns:
            df[col] = ""

    df["Plantel"] = df["Plantel"].fillna("").astype(str).str.strip()
    df["Usuario"] = df["Usuario"].fillna("").astype(str).str.strip().str.upper()
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")

    df.loc[df["Plantel"].str.lower().isin(["nan", "none"]), "Plantel"] = ""
    df = df.dropna(subset=["FechaHora"])
    df = df[df["Usuario"] != ""]
    df = df.sort_values("FechaHora", ascending=False)

    return df[["Plantel", "Usuario", "FechaHora"]]


def _map_plantel(df_logs: pd.DataFrame, df_cat: pd.DataFrame) -> pd.DataFrame:
    """
    Si el log trae Plantel vacío o GLOBAL, infiere Plantel por Usuario usando catálogo.
    Si el usuario no está en catálogo => GLOBAL.
    """
    df = df_logs.copy()

    if df_cat.empty:
        df["Plantel_final"] = df["Plantel"].replace("", "GLOBAL")
        df.loc[df["Plantel_final"].str.upper().isin(["NAN", "NONE"]), "Plantel_final"] = "GLOBAL"
        return df

    user_to_plantel = (
        df_cat.drop_duplicates(subset=[COL_USUARIO])
        .set_index(COL_USUARIO)[COL_PLANTEL]
        .to_dict()
    )

    plantel_log = df["Plantel"].fillna("").astype(str).str.strip()
    no_valido = (
        (plantel_log == "")
        | (plantel_log.str.upper() == "GLOBAL")
        | (plantel_log.str.lower().isin(["nan", "none"]))
    )

    df["Plantel_final"] = plantel_log
    df.loc[no_valido, "Plantel_final"] = df.loc[no_valido, "Usuario"].map(user_to_plantel).fillna("GLOBAL")

    df["Plantel_final"] = df["Plantel_final"].fillna("GLOBAL").astype(str).str.strip()
    df.loc[df["Plantel_final"] == "", "Plantel_final"] = "GLOBAL"
    return df


def _export_excel(df: pd.DataFrame, sheet_name: str) -> BytesIO:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    buffer.seek(0)
    return buffer


def _make_table_ingresos_por_usuario(df_map: pd.DataFrame, catalog_users: set[str]) -> pd.DataFrame:
    df = df_map[df_map["Usuario"].isin(list(catalog_users))].copy()
    if df.empty:
        return pd.DataFrame(columns=["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"])

    out = (
        df.groupby(["Plantel_final", "Usuario"])
        .agg(
            TotalIngresos=("Usuario", "count"),
            UltimoIngreso=("FechaHora", "max"),
        )
        .reset_index()
        .rename(columns={"Plantel_final": "Plantel"})
        .sort_values(["Plantel", "Usuario"])
    )

    out["UltimoIngreso"] = out["UltimoIngreso"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"]]


def _make_table_sin_ingreso(df_cat: pd.DataFrame, df_map: pd.DataFrame) -> pd.DataFrame:
    """
    “Sin ingreso” se calcula a nivel usuario plantel:
    - Usuarios del catálogo que NO aparecen en logs
    """
    if df_cat.empty:
        return pd.DataFrame(columns=["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"])

    catalog_users = set(df_cat[COL_USUARIO].unique().tolist())
    users_con_ingreso = set(df_map["Usuario"].unique().tolist()) & catalog_users
    users_sin = sorted(list(catalog_users - users_con_ingreso))

    if not users_sin:
        return pd.DataFrame(columns=["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"])

    base = df_cat[df_cat[COL_USUARIO].isin(users_sin)].copy()
    base = base.rename(columns={COL_PLANTEL: "Plantel", COL_USUARIO: "Usuario"})
    base["TotalIngresos"] = 0
    base["UltimoIngreso"] = ""
    base = base.sort_values(["Plantel", "Usuario"])
    return base[["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"]]


def _make_table_otros_usuarios(df_map: pd.DataFrame, catalog_users: set[str]) -> pd.DataFrame:
    df = df_map[~df_map["Usuario"].isin(list(catalog_users))].copy()
    if df.empty:
        return pd.DataFrame(columns=["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"])

    out = (
        df.groupby(["Plantel_final", "Usuario"])
        .agg(
            TotalIngresos=("Usuario", "count"),
            UltimoIngreso=("FechaHora", "max"),
        )
        .reset_index()
        .rename(columns={"Plantel_final": "Plantel"})
        .sort_values(["Plantel", "Usuario"])
    )

    out["UltimoIngreso"] = out["UltimoIngreso"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"]]


def _count_planteles_con_ingreso(df_cat: pd.DataFrame, df_map: pd.DataFrame) -> int:
    """
    Plantel con ingreso = al menos un usuario de ese plantel aparece en logs.
    """
    if df_cat.empty or df_map.empty:
        return 0

    catalog_users = set(df_cat[COL_USUARIO].unique().tolist())
    users_con_ingreso = set(df_map["Usuario"].unique().tolist()) & catalog_users
    planteles_con = df_cat[df_cat[COL_USUARIO].isin(list(users_con_ingreso))][COL_PLANTEL].unique().tolist()
    return len(set(planteles_con))


def _count_planteles_sin_ingreso(df_cat: pd.DataFrame, df_map: pd.DataFrame) -> int:
    """
    Plantel sin ingreso = ninguno de sus usuarios aparece en logs.
    """
    if df_cat.empty:
        return 0

    total_planteles = set(df_cat[COL_PLANTEL].unique().tolist())
    con = _count_planteles_con_ingreso(df_cat, df_map)

    # Para obtener el set real, no solo el número:
    catalog_users = set(df_cat[COL_USUARIO].unique().tolist())
    users_con_ingreso = set(df_map["Usuario"].unique().tolist()) & catalog_users
    planteles_con = set(df_cat[df_cat[COL_USUARIO].isin(list(users_con_ingreso))][COL_PLANTEL].unique().tolist())

    planteles_sin = total_planteles - planteles_con
    return len(planteles_sin)


def mostrar():
    st.title("Bitácora de Conexiones")

    df_cat = _load_catalogo()
    df_logs = _load_logs()

    if df_logs.empty:
        st.info("Aún no hay registros en la bitácora.")
        return

    df_map = _map_plantel(df_logs, df_cat)
    catalog_users = set(df_cat[COL_USUARIO].unique().tolist()) if not df_cat.empty else set()

    # Tablas
    df_con = _make_table_ingresos_por_usuario(df_map, catalog_users)
    df_sin = _make_table_sin_ingreso(df_cat, df_map) if not df_cat.empty else pd.DataFrame(
        columns=["Plantel", "Usuario", "TotalIngresos", "UltimoIngreso"]
    )
    df_otros = _make_table_otros_usuarios(df_map, catalog_users)

    # Contadores arriba (motivación)
    total_con = _count_planteles_con_ingreso(df_cat, df_map) if not df_cat.empty else 0
    total_sin = _count_planteles_sin_ingreso(df_cat, df_map) if not df_cat.empty else 0

    c1, c2 = st.columns(2)
    c1.metric("Total de planteles con ingreso", total_con)
    c2.metric("Total de planteles sin ingreso", total_sin)

    # Menú horizontal (tabs)
    tabs = st.tabs(["Planteles con ingreso", "Planteles sin ingreso", "Otros usuarios"])

    with tabs[0]:
        st.subheader("Planteles con ingreso")
        st.dataframe(df_con, use_container_width=True, hide_index=True)

        st.download_button(
            "Descargar Excel",
            data=_export_excel(df_con, "Planteles_con_ingreso"),
            file_name="planteles_con_ingreso.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=df_con.empty,
        )

    with tabs[1]:
        st.subheader("Planteles sin ingreso")

        if df_cat.empty:
            st.warning("No se puede calcular 'sin ingreso' porque no se encontró el catálogo en assets/Datos1.xlsx.")
            st.dataframe(df_sin, use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_sin, use_container_width=True, hide_index=True)

        st.download_button(
            "Descargar Excel",
            data=_export_excel(df_sin, "Planteles_sin_ingreso"),
            file_name="planteles_sin_ingreso.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=df_sin.empty,
        )

    with tabs[2]:
        st.subheader("Otros usuarios")
        st.dataframe(df_otros, use_container_width=True, hide_index=True)

        st.download_button(
            "Descargar Excel",
            data=_export_excel(df_otros, "Otros_usuarios"),
            file_name="otros_usuarios.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=df_otros.empty,
        )
