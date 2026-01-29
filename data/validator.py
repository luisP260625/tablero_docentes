from __future__ import annotations

from pathlib import Path
import re
import unicodedata
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATOS_XLSX = PROJECT_ROOT / "assets" / "Datos1.xlsx"

# Nombres “probables” (por si quieres mantener un estándar)
POSSIBLE_USERS_SHEETS = ["planteles", "plantel", "usuarios", "users"]
POSSIBLE_PERMS_SHEETS = ["permisos", "permiso", "permissions"]

# Si tu columna en usuarios/planteles se llama distinto, aquí se detecta por contenido
USER_COL_CANDIDATES = ["usuario", "user", "username"]
PASS_COL_CANDIDATES = ["contrasena", "contraseña", "password", "pass"]
PLANTEL_COL_CANDIDATES = ["plantel", "cct", "campus", "centro"]

# ✅ ampliado para detectar más variantes de columna de permisos
PERMIDS_COL_CANDIDATES = [
    "permisos", "permiso", "id_permiso", "id_permisos", "permisos_ids",
    "menus", "menu", "opciones", "opciones_menu", "menu_ids", "roles", "rol",
]


def _norm_text(s) -> str:
    s = str(s).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    lows = [_norm_text(c) for c in cols]
    for cand in candidates:
        cand_n = _norm_text(cand)
        for c, lc in zip(cols, lows):
            if lc == cand_n or cand_n in lc:
                return c
    return None


def _pick_sheet_by_name(xls: pd.ExcelFile, possible_names: list[str]) -> str | None:
    # match “normalizado” para soportar Planteles/PLANTELES/planteles
    sheet_map = {_norm_text(n): n for n in xls.sheet_names}
    for p in possible_names:
        p_n = _norm_text(p)
        if p_n in sheet_map:
            return sheet_map[p_n]
    return None


def _pick_sheet_by_columns(xls: pd.ExcelFile, must_have_cols: list[str]) -> str | None:
    # Escanea hojas buscando columnas mínimas
    for sh in xls.sheet_names:
        try:
            df_head = pd.read_excel(xls, sheet_name=sh, nrows=5, engine="openpyxl")
            df_head.columns = [str(c).strip() for c in df_head.columns]
            ok = True
            for col in must_have_cols:
                if _find_col(df_head, [col]) is None:
                    ok = False
                    break
            if ok:
                return sh
        except Exception:
            continue
    return None


def _parse_perm_tokens(value) -> tuple[list[int], set[str]]:
    """
    Soporta permisos en columna de usuarios en 2 formatos:

    1) Por ID: "1,2,10" / "1 | 2 | 10" / "1;2;10"
    2) Por clave: "MENU_DOCENTES_MODULOS, MENU_ACCESO_PLANTELES"

    Retorna:
      - lista de IDs (int)
      - set de claves (str en UPPER)
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return [], set()

    # Si viene numérico simple
    if isinstance(value, (int, float)) and not pd.isna(value):
        try:
            return [int(value)], set()
        except Exception:
            return [], set()

    s = str(value).strip()
    if not s:
        return [], set()

    parts = re.split(r"[,\|;\s]+", s)
    ids: list[int] = []
    codes: set[str] = set()

    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        if p.isdigit():
            ids.append(int(p))
            continue
        token = re.sub(r"[^A-Za-z0-9_]+", "", p)
        if token:
            codes.add(token.upper())

    return ids, codes


def _load_permissions_map(xls: pd.ExcelFile) -> dict[int, str]:
    # 1) intentar por nombre
    perms_sheet = _pick_sheet_by_name(xls, POSSIBLE_PERMS_SHEETS)

    # 2) si no, intentar por columnas
    if perms_sheet is None:
        perms_sheet = _pick_sheet_by_columns(xls, must_have_cols=["id", "permiso"])

    # Si no existe, devolvemos vacío (no truena login)
    if perms_sheet is None:
        return {}

    dfp = pd.read_excel(xls, sheet_name=perms_sheet, engine="openpyxl")
    dfp.columns = [str(c).strip() for c in dfp.columns]

    col_id = _find_col(dfp, ["id"])
    col_perm = _find_col(dfp, ["permiso", "permission"])

    if not col_id or not col_perm:
        raise ValueError("La hoja 'Permisos' debe tener columnas: Id y Permiso.")

    perm_map: dict[int, str] = {}
    for pid, pname in dfp[[col_id, col_perm]].dropna().itertuples(index=False):
        try:
            pid_int = int(pid)
        except Exception:
            continue
        perm_map[pid_int] = str(pname).strip().upper()

    return perm_map


def validar_usuario(usuario: str, contrasena: str):
    """
    Return:
      ok: bool
      plantel: str|None
      permisos_set: set[str]   # SIEMPRE claves (ej. MENU_DOCENTES_MODULOS)
      username: str|None
    """
    xls = pd.ExcelFile(DATOS_XLSX, engine="openpyxl")

    # 1) detectar hoja de usuarios
    users_sheet = _pick_sheet_by_name(xls, POSSIBLE_USERS_SHEETS)
    if users_sheet is None:
        users_sheet = _pick_sheet_by_columns(xls, must_have_cols=["usuario", "contrasena"])

    if users_sheet is None:
        raise ValueError(
            "No encontré la hoja de usuarios. Debe existir una hoja (ej. 'Planteles') "
            "que contenga columnas 'Usuario' y 'Contrasena/Contraseña'."
        )

    dfu = pd.read_excel(xls, sheet_name=users_sheet, engine="openpyxl")
    dfu.columns = [str(c).strip() for c in dfu.columns]

    col_user = _find_col(dfu, USER_COL_CANDIDATES)
    col_pass = _find_col(dfu, PASS_COL_CANDIDATES)
    col_plantel = _find_col(dfu, PLANTEL_COL_CANDIDATES)
    col_permids = _find_col(dfu, PERMIDS_COL_CANDIDATES)

    if not col_user or not col_pass:
        raise ValueError(
            f"En la hoja '{users_sheet}' no encontré columnas de Usuario/Contraseña. "
            "Asegúrate que se llamen 'Usuario' y 'Contrasena' (o similar)."
        )

    u = str(usuario).strip()
    p = str(contrasena).strip()

    dfu["_u"] = dfu[col_user].astype(str).str.strip()
    dfu["_p"] = dfu[col_pass].astype(str).str.strip()

    match = dfu[(dfu["_u"] == u) & (dfu["_p"] == p)]
    if match.empty:
        return False, None, set(), None

    row = match.iloc[0]

    plantel_val = None
    if col_plantel and not pd.isna(row.get(col_plantel)):
        plantel_val = str(row.get(col_plantel)).strip()
        if plantel_val == "":
            plantel_val = None

    # ✅ Permisos: SIEMPRE devolvemos claves (strings)
    perms_set: set[str] = set()
    if col_permids:
        perm_ids, perm_codes_direct = _parse_perm_tokens(row.get(col_permids))

        # 1) si ya venían claves directas, se agregan
        perms_set |= perm_codes_direct

        # 2) si venían IDs, se mapean con hoja Permisos (id -> Permiso)
        if perm_ids:
            perm_map = _load_permissions_map(xls)
            for pid in perm_ids:
                pname = perm_map.get(pid)
                if pname:
                    perms_set.add(pname)

    return True, plantel_val, perms_set, u
