"""
Тесты системы конфигурации:
  - загрузка дефолтного конфига
  - мержинг с локальным конфигом
  - корректность обязательных полей
"""

import tomllib
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest


CONFIG_ROOT = Path(__file__).parent.parent


def _load_default() -> dict:
    with open(CONFIG_ROOT / "config.default.toml", "rb") as f:
        return tomllib.load(f)


# ─── Структура конфига ────────────────────────────────────────────────────────

def test_default_config_loads():
    cfg = _load_default()
    assert cfg is not None


def test_default_config_has_model_section():
    cfg = _load_default()
    assert "model" in cfg


def test_default_config_has_rag_section():
    cfg = _load_default()
    assert "rag" in cfg


def test_default_config_model_fields():
    cfg = _load_default()
    model = cfg["model"]
    assert "llm" in model
    assert "embeddings" in model
    assert "temperature" in model
    assert "num_gpu" in model


def test_default_config_rag_fields():
    cfg = _load_default()
    rag = cfg["rag"]
    assert "chunk_size" in rag
    assert "chunk_overlap" in rag
    assert "retrieval_k" in rag


def test_default_config_temperature_range():
    cfg = _load_default()
    assert 0.0 <= cfg["model"]["temperature"] <= 1.0
    assert 0.0 <= cfg["model"]["chat_temperature"] <= 1.0


def test_default_config_chunk_sizes_sensible():
    cfg = _load_default()
    assert cfg["rag"]["chunk_size"] > cfg["rag"]["chunk_overlap"]
    assert cfg["rag"]["chunk_overlap"] >= 0


def test_default_config_retrieval_k_positive():
    cfg = _load_default()
    assert cfg["rag"]["retrieval_k"] > 0


# ─── Мержинг с локальным конфигом ────────────────────────────────────────────

def test_config_merge_overrides_llm(tmp_path):
    """Локальный конфиг должен переопределять модель."""
    local_content = b'[model]\nllm = "qwen2.5:14b"\nnum_gpu = -1\n'
    local_path = tmp_path / "config.local.toml"
    local_path.write_bytes(local_content)

    # Патчим _ROOT в config.py чтобы он смотрел в tmp_path
    with patch("config._ROOT", tmp_path):
        # Копируем дефолтный конфиг в tmp_path
        import shutil
        shutil.copy(CONFIG_ROOT / "config.default.toml", tmp_path / "config.default.toml")

        from config import _load
        cfg = _load()

    assert cfg["model"]["llm"] == "qwen2.5:14b"
    assert cfg["model"]["num_gpu"] == -1
    # Остальные поля должны остаться от дефолтного конфига
    assert "embeddings" in cfg["model"]


def test_config_merge_partial_override(tmp_path):
    """Локальный конфиг меняет только указанные ключи, остальные берутся из дефолтного."""
    local_content = b'[model]\nnum_gpu = -1\n'
    (tmp_path / "config.local.toml").write_bytes(local_content)

    import shutil
    shutil.copy(CONFIG_ROOT / "config.default.toml", tmp_path / "config.default.toml")

    with patch("config._ROOT", tmp_path):
        from config import _load
        cfg = _load()

    # num_gpu переопределён
    assert cfg["model"]["num_gpu"] == -1
    # llm берётся из дефолта
    assert cfg["model"]["llm"] == "llama3.1:8b"


def test_config_no_local_file(tmp_path):
    """Отсутствие config.local.toml не должно вызывать ошибку."""
    import shutil
    shutil.copy(CONFIG_ROOT / "config.default.toml", tmp_path / "config.default.toml")
    # config.local.toml НЕ создаём

    with patch("config._ROOT", tmp_path):
        from config import _load
        cfg = _load()

    assert cfg["model"]["llm"] == "llama3.1:8b"
