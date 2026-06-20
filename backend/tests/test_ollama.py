from backend.app.services.ollama import _generation_model_names, _model_names


def test_generation_model_names_excludes_embedding_only_models() -> None:
    payload = {
        "models": [
            {"name": "qwen2.5:3b", "capabilities": ["completion", "tools"]},
            {"name": "llama3.2:3b", "capabilities": ["completion"]},
            {"name": "embeddinggemma:latest", "capabilities": ["embedding"]},
        ]
    }

    assert _model_names(payload) == ["qwen2.5:3b", "llama3.2:3b", "embeddinggemma:latest"]
    assert _generation_model_names(payload) == ["qwen2.5:3b", "llama3.2:3b"]
