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

    # Local embeddings (sentence-transformers)
    embed_model: str = "all-MiniLM-L6-v2"

    # Paths
    documents_dir: Path = BASE_DIR / "documents"
    storage_dir: Path = BASE_DIR / "storage"

    # Retrieval / chunking
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 4
    # Minimum cosine similarity a passage must clear to count as relevant evidence.
    min_score: float = 0.35

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
