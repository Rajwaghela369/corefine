"""Settings read from backend/.env. Nothing here is ever sent to the frontend or the sandbox.

Two modes:
  cloud  every managed-service key is required; a missing key fails startup with its name.
  local  dev/test fallback with no cloud accounts: files on disk, SQLite, local Qdrant,
         subprocess runner. ANTHROPIC_API_KEY is still needed for real LLM calls.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

CLOUD_REQUIRED = (
    "ANTHROPIC_API_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "S3_BUCKET",
    "DATABASE_URL",
    "QDRANT_URL", "QDRANT_API_KEY",
    "DAYTONA_API_KEY",
)


class MissingSettingError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", case_sensitive=True)

    COREFINE_MODE: Literal["cloud", "local"] = "local"

    ANTHROPIC_API_KEY: str = ""
    # Spec: Sonnet-class for Planner/Coder/Analyst, Haiku-class for chat summaries and routing
    MODEL_MAIN: str = "claude-sonnet-5-5"
    MODEL_FAST: str = "claude-haiku-5-5"
    LLM_SERVER_FALLBACKS: bool = True  # fallbacks: "default" on refusals (Claude API only)

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = ""
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""  # S3-compatible store (e.g. Neon); empty means AWS

    DATABASE_URL: str = ""

    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384
    EMBED_PROVIDER: Literal["qdrant_cloud", "fastembed"] = "fastembed"

    DAYTONA_API_KEY: str = ""
    DAYTONA_API_URL: str = ""
    DAYTONA_SNAPSHOT: str = "corefine-sci"

    # All-electron DFT codes (input generation and local checks). Unset = that code is skipped.
    EXCITING_ROOT: Path | None = None        # exciting source tree: species/ and xml/schema/
    QUESTAAL_BIN: Path | None = None         # folder with blm, lmfa, lmchk, lmf
    QUESTAAL_LIB_ROOT: Path | None = None    # Spack opt/ tree whose lib dirs Questaal binaries need
    EXCITING_BIN: Path | None = None         # exciting executable for local runs (exciting_smp or exciting_serial)
    TOOLS_DIR: Path = BACKEND_DIR / ".local" / "tools"   # codes and data CoRefine installs itself (no root)
    QE_PSEUDO_DIR: Path | None = None        # Quantum ESPRESSO .UPF files (any library, e.g. SSSP)
    VASP_PP_PATH: Path | None = None         # licensed VASP POTCARs: <path>/potpaw_PBE/<El>/POTCAR
    COMPUTE_CONFIG: Path = BACKEND_DIR / "compute.yaml"   # where calculations may run (local, Slurm clusters)
    MP_API_KEY: str = ""                     # optional; Materials Project works without it via OPTIMADE

    LOCAL_DATA_DIR: Path = BACKEND_DIR / ".local"
    SEED_DATA_DIR: Path = REPO_DIR / "data"
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Hard limits from the spec; each failure names the limit
    STEP_TIMEOUT_S: int = 120
    MAX_ATTEMPTS: int = 3
    MAX_STEPS: int = 6
    MAX_OUTPUT_BYTES: int = 50 * 1024 * 1024
    SUCCESS_TARGET_A: float = 0.0005

    @model_validator(mode="after")
    def _require_cloud_keys(self):
        if self.COREFINE_MODE == "cloud":
            missing = [k for k in CLOUD_REQUIRED if not getattr(self, k)]
            if missing:
                raise MissingSettingError(f"missing required settings: {', '.join(missing)}")
        return self

    @property
    def is_cloud(self) -> bool:
        return self.COREFINE_MODE == "cloud"

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            # Neon gives postgres://; SQLAlchemy wants the psycopg 3 driver named
            url = self.DATABASE_URL.replace("postgres://", "postgresql://", 1)
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return f"sqlite:///{self.LOCAL_DATA_DIR / 'corefine.db'}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return s
