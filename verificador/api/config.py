"""Configuração do backend, lida de variáveis de ambiente.

| Variável                    | Padrão                          | Uso                                              |
|-----------------------------|---------------------------------|--------------------------------------------------|
| VERIFICADOR_DB              | <verificador>/data/verificador.db | Caminho do banco SQLite.                       |
| VERIFICADOR_UPLOADS         | <verificador>/data/uploads      | Pasta onde os arquivos originais são guardados.  |
| VERIFICADOR_MAX_UPLOAD_MB   | 25                              | Tamanho máximo de **cada** arquivo enviado.      |
| VERIFICADOR_API_KEY         | (vazio = sem autenticação)      | Chave exigida no cabeçalho `X-API-Key`.          |
| VERIFICADOR_CORS_ORIGINS    | http://localhost:8501           | Origens liberadas no CORS, separadas por vírgula.|

Em produção, defina sempre `VERIFICADOR_API_KEY` e restrinja `VERIFICADOR_CORS_ORIGINS`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Pasta "verificador/" (onde ficam app.py, api/ e o núcleo). Os dados padrão ficam em verificador/data/.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Configuracao:
    """Parâmetros de execução do backend. Imutável: crie outra instância para testes."""

    caminho_db: Path = RAIZ_PROJETO / "data" / "verificador.db"
    pasta_uploads: Path = RAIZ_PROJETO / "data" / "uploads"
    max_upload_mb: int = 25
    api_key: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8501"])

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def do_ambiente(cls) -> "Configuracao":
        """Monta a configuração a partir das variáveis de ambiente (com os padrões acima)."""
        padrao = cls()
        origens = os.getenv("VERIFICADOR_CORS_ORIGINS")
        return cls(
            caminho_db=Path(os.getenv("VERIFICADOR_DB", padrao.caminho_db)),
            pasta_uploads=Path(os.getenv("VERIFICADOR_UPLOADS", padrao.pasta_uploads)),
            max_upload_mb=int(os.getenv("VERIFICADOR_MAX_UPLOAD_MB", padrao.max_upload_mb)),
            api_key=os.getenv("VERIFICADOR_API_KEY") or None,
            cors_origins=([o.strip() for o in origens.split(",") if o.strip()] if origens is not None
                          else padrao.cors_origins),
        )
