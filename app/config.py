"""Application configuration (env-overridable via .env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Ollama (local LLM runtime)
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "llama3.2"
    # Low temperature keeps answers faithful to the documents (Ollama defaults to 0.8).
    llm_temperature: float = 0.1

    # Local embeddings (sentence-transformers).
    embed_model: str = "all-MiniLM-L6-v2"
    # Instruction prefix applied to QUERIES only (bge-style models want one; all-MiniLM
    # doesn't, so leave it blank).
    query_prefix: str = ""

    # Paths
    documents_dir: Path = BASE_DIR / "documents"
    storage_dir: Path = BASE_DIR / "storage"

    # Retrieval / chunking
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 4
    # Low floor to cut obvious noise (embedding sims for good matches can still be modest).
    min_score: float = 0.15
    # Also drop passages far below the best hit (relative gate), even if above the floor.
    relevance_margin: float = 0.15
    # Session uploads are the user's deliberate context for THIS chat, so guarantee they're
    # consulted: reserve up to this many upload chunks (above a tiny floor) regardless of
    # how the large vault scores.
    upload_reserve: int = 2
    upload_min_score: float = 0.05

    # Chat history
    history_turns: int = 6
    max_sessions: int = 100

    @property
    def chroma_dir(self) -> Path:
        return self.storage_dir / "chroma"

    @property
    def manifest_path(self) -> Path:
        return self.storage_dir / "manifest.json"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "chats.db"


settings = Settings()

# Ensure the folders we depend on exist (documents/ may already hold the user's files).
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.documents_dir.mkdir(parents=True, exist_ok=True)
