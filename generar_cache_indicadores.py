import os
import re
import pandas as pd

EXCEL_PATH = "assets/Datos1.xlsx"
CACHE_DIR = "assets/cache_indicadores"

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(f"{CACHE_DIR}/detalle_por_plantel", exist_ok=True)

ENGINE = "calamine"


def slug(v: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(v).strip())


print("Leyendo hoja Reprobacion...")
df_reprobacion = pd.read_excel(
    EXCEL_PATH,
    sheet_name="Reprobacion",
    engine=ENGINE
)

for col in ["pEspecifico", "pAlcanzado", "pRelativo"]:
    if col in df_reprobacion.columns:
        df_reprobacion[col] = pd.to_numeric(df_reprobacion[col], errors="coerce")

df_reprobacion.to_parquet(f"{CACHE_DIR}/reprobacion.parquet", index=False)

print("Leyendo hoja Matricula...")
df_matricula = pd.read_excel(
    EXCEL_PATH,
    sheet_name="Matricula",
    engine=ENGINE
)

if "matriculaTotal" in df_matricula.columns:
    df_matricula["matriculaTotal"] = pd.to_numeric(
        df_matricula["matriculaTotal"], errors="coerce"
    ).fillna(0)

df_matricula.to_parquet(f"{CACHE_DIR}/matricula.parquet", index=False)

print("Construyendo resumen...")
if "Plantel" not in df_reprobacion.columns or "matricula" not in df_reprobacion.columns:
    raise ValueError("La hoja Reprobacion debe contener al menos las columnas 'Plantel' y 'matricula'.")

df_modulos = (
    df_reprobacion.groupby(["Plantel", "matricula"])
    .size()
    .reset_index(name="modulos_nc")
)

df_modulos["categoria"] = df_modulos["modulos_nc"].apply(lambda x: str(x) if x <= 10 else "11 o más")

resumen = (
    df_modulos.groupby(["Plantel", "categoria"])
    .size()
    .reset_index(name="total_estudiantes")
)

tabla = (
    resumen.pivot(index="Plantel", columns="categoria", values="total_estudiantes")
    .fillna(0)
    .astype(int)
    .reset_index()
)

if "Plantel" in df_matricula.columns:
    tabla = tabla.merge(df_matricula, on="Plantel", how="left")

if "matriculaTotal" not in tabla.columns:
    tabla["matriculaTotal"] = 0

tabla["matriculaTotal"] = pd.to_numeric(tabla["matriculaTotal"], errors="coerce").fillna(0)

columnas_excluir = {"Plantel", "matriculaTotal"}
columnas_nc = [c for c in tabla.columns if c not in columnas_excluir]

tabla["Total estudiantes no competentes"] = tabla[columnas_nc].sum(axis=1)

tabla["% Estudiantes no competentes"] = (
    (tabla["Total estudiantes no competentes"] / tabla["matriculaTotal"]) * 100
).replace([float("inf"), -float("inf")], 0).fillna(0).round(2)

tabla.to_parquet(f"{CACHE_DIR}/resumen.parquet", index=False)

print("Guardando detalle por plantel...")
for plantel, dfp in df_reprobacion.groupby("Plantel"):
    nombre = slug(plantel)
    dfp.to_parquet(f"{CACHE_DIR}/detalle_por_plantel/{nombre}.parquet", index=False)

print("Leyendo hoja Seguimiento...")
try:
    df_seguimiento = pd.read_excel(
        EXCEL_PATH,
        sheet_name="Seguimiento",
        engine=ENGINE
    )
    df_seguimiento.to_parquet(f"{CACHE_DIR}/seguimiento.parquet", index=False)
except Exception as e:
    print(f"No se pudo convertir Seguimiento: {e}")

print("Leyendo hoja Datos...")
try:
    df_datos = pd.read_excel(
        EXCEL_PATH,
        sheet_name="Datos",
        engine=ENGINE
    )
    df_datos.to_parquet(f"{CACHE_DIR}/datos.parquet", index=False)
except Exception as e:
    print(f"No se pudo convertir Datos: {e}")

print("Leyendo hoja Planteles...")
try:
    df_planteles = pd.read_excel(
        EXCEL_PATH,
        sheet_name="Planteles",
        engine=ENGINE
    )

    # Normalizar columnas problemáticas a texto
    for col in df_planteles.columns:
        if df_planteles[col].dtype == "object":
            df_planteles[col] = df_planteles[col].astype("string")

    # Limpieza extra para columnas típicas de esta hoja
    for col in ["Usuario", "Plantel", "Email", "Ccp", "Permisos"]:
        if col in df_planteles.columns:
            df_planteles[col] = df_planteles[col].astype("string").str.strip()

    df_planteles.to_parquet(f"{CACHE_DIR}/planteles.parquet", index=False)
except Exception as e:
    print(f"No se pudo convertir Planteles: {e}")

print("Leyendo hoja Permisos...")
try:
    df_permisos = pd.read_excel(
        EXCEL_PATH,
        sheet_name="Permisos",
        engine=ENGINE
    )
    df_permisos.to_parquet(f"{CACHE_DIR}/permisos.parquet", index=False)
except Exception as e:
    print(f"No se pudo convertir Permisos: {e}")

print("✅ Cache generado correctamente.")