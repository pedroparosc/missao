"""Ponto de entrada da Vercel (função Python/ASGI).

A Vercel carrega a variável `app` deste arquivo (ver `[tool.vercel] entrypoint` no
pyproject.toml). O código da aplicação fica em `verificador/`, então ela é colocada no
`sys.path` antes de importar a API — os mesmos imports usados no uso local
(`uvicorn api.main:app` dentro de `verificador/`).

Teste local equivalente (na raiz do repositório):  uvicorn index:app --reload
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "verificador"))

from api.main import app  # noqa: E402,F401  (exportado para a Vercel)
