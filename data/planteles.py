from __future__ import annotations

from pathlib import Path
import pandas as pd

SHEET_NAME = "Planteles"
COLUMNS = ["Plantel", "Usuario", "Contrasena", "Email"]

# Ruta por defecto: /assets/Datos1.xlsx
DEFAULT_EXCEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "Datos1.xlsx"


def cargar_planteles(excel_path: str | Path = DEFAULT_EXCEL_PATH) -> pd.DataFrame:
    """
    Lee la hoja 'Planteles' de Datos1.xlsx y devuelve un DataFrame con:
    Plantel, Usuario, Contrasena, Email
    """
    path = Path(excel_path)

    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo Excel: {path}")

    df = pd.read_excel(path, sheet_name=SHEET_NAME, engine="openpyxl")

    # Normaliza encabezados por si hay espacios
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Faltan columnas en la hoja '{SHEET_NAME}': {missing}. "
            f"Columnas disponibles: {list(df.columns)}"
        )

    df = df[COLUMNS].copy()

    # Asegura strings y limpia nulos/espacios
    for col in COLUMNS:
        df[col] = df[col].astype(str).fillna("").str.strip()

    return df
