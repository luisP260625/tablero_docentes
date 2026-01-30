from __future__ import annotations

from pathlib import Path
from datetime import datetime
import os
import pandas as pd

# --- Spaces deps ---
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from filelock import FileLock  # ✅ usar lock


# Ruta local (compatibilidad): <raiz_proyecto>/data/bitacora.csv
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE_PATH = (PROJECT_ROOT / "data" / "bitacora.csv").resolve()

# Lock local (evita escrituras simultáneas en la misma instancia)
LOCK_PATH = Path(os.getenv("BITACORA_LOCK_PATH", "/tmp/bitacora.lock"))


def _ensure_folder():
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _spaces_enabled() -> bool:
    return all(
        os.getenv(k)
        for k in ["SPACES_KEY", "SPACES_SECRET", "SPACES_REGION", "SPACES_ENDPOINT", "SPACES_BUCKET"]
    )


def _s3_client():
    return boto3.client(
        "s3",
        region_name=os.getenv("SPACES_REGION"),
        endpoint_url=os.getenv("SPACES_ENDPOINT"),
        aws_access_key_id=os.getenv("SPACES_KEY"),
        aws_secret_access_key=os.getenv("SPACES_SECRET"),
        config=Config(signature_version="s3v4"),
    )


def _bucket_key():
    bucket = os.getenv("SPACES_BUCKET")
    key = os.getenv("BITACORA_OBJECT_KEY", "bitacora/bitacora.csv")
    if not bucket:
        raise RuntimeError("Falta SPACES_BUCKET")
    return bucket, key


def _download_spaces_text() -> str:
    """Devuelve el contenido del CSV remoto (o '' si no existe)."""
    if not _spaces_enabled():
        return ""
    s3 = _s3_client()
    bucket, key = _bucket_key()
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8", errors="ignore")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return ""
        raise


def _upload_spaces_text(text: str) -> None:
    if not _spaces_enabled():
        return
    s3 = _s3_client()
    bucket, key = _bucket_key()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/csv",
    )


def _write_local(text: str) -> None:
    _ensure_folder()
    LOG_FILE_PATH.write_text(text, encoding="utf-8")


def _read_local() -> str:
    if not LOG_FILE_PATH.exists():
        return ""
    return LOG_FILE_PATH.read_text(encoding="utf-8", errors="ignore")


def _sync_from_spaces_to_local() -> None:
    """
    Descarga el CSV remoto y lo escribe localmente.
    Si no existe remoto, no hace nada.
    """
    remote = _download_spaces_text()
    if remote.strip():
        _write_local(remote)


def _detect_format_from_text(text: str) -> int:
    """
    0 = vacío/no existe
    2 = Usuario,FechaHora
    3 = Plantel,Usuario,FechaHora
    """
    if not text.strip():
        return 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        c = line.count(",")
        if c >= 2:
            return 3
        if c == 1:
            return 2
        return 2
    return 0


def _migrar_2_a_3_local():
    """
    Migra CSV viejo: Usuario,FechaHora  ->  Plantel,Usuario,FechaHora (Plantel vacío en históricos).
    Trabaja sobre el archivo local.
    """
    if not LOG_FILE_PATH.exists() or LOG_FILE_PATH.stat().st_size == 0:
        return

    df = pd.read_csv(LOG_FILE_PATH, header=None, dtype=str, engine="python").dropna(how="all")
    if df.empty or df.shape[1] < 2:
        return

    df = df.iloc[:, :2].copy()
    df.columns = ["Usuario", "FechaHora"]

    df_new = pd.DataFrame(
        {
            "Plantel": [""] * len(df),
            "Usuario": df["Usuario"].astype(str),
            "FechaHora": df["FechaHora"].astype(str),
        }
    )

    df_new.to_csv(LOG_FILE_PATH, index=False, header=False, encoding="utf-8")


def registrar_acceso(usuario: str, plantel: str | None = None) -> None:
    """
    Escribe una línea:
      Plantel,Usuario,YYYY-MM-DD HH:MM:SS
    y lo persiste en Spaces (sin reinicio por deploy).
    """
    _ensure_folder()

    with FileLock(str(LOCK_PATH)):  # ✅ lock
        # 1) Trae el archivo remoto (si existe) para no perder historial tras deploy
        _sync_from_spaces_to_local()

        # 2) Migra formato viejo si lo detecta
        local_text = _read_local()
        if _detect_format_from_text(local_text) == 2:
            _migrar_2_a_3_local()

        usuario_n = str(usuario).strip().upper()
        plantel_n = "GLOBAL" if plantel is None else str(plantel).strip()
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 3) Append local
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"{plantel_n},{usuario_n},{fecha}\n")
            f.flush()

        # 4) Sube el archivo completo a Spaces
        _upload_spaces_text(_read_local())


def obtener_bitacora_df() -> pd.DataFrame:
    """
    Devuelve DataFrame con columnas: Plantel, Usuario, FechaHora
    """
    _ensure_folder()

    with FileLock(str(LOCK_PATH)):  # ✅ lock al leer también
        _sync_from_spaces_to_local()

        if not LOG_FILE_PATH.exists() or LOG_FILE_PATH.stat().st_size == 0:
            return pd.DataFrame(columns=["Plantel", "Usuario", "FechaHora"])

        # Migra si sigue en formato viejo
        local_text = _read_local()
        if _detect_format_from_text(local_text) == 2:
            _migrar_2_a_3_local()

        df = pd.read_csv(
            LOG_FILE_PATH,
            header=None,
            names=["Plantel", "Usuario", "FechaHora"],
            dtype=str,
            engine="python",
        ).dropna(how="all")

        return df


def obtener_bitacora() -> list[dict]:
    return obtener_bitacora_df().to_dict(orient="records")


def contar_accesos() -> int:
    return len(obtener_bitacora_df())
