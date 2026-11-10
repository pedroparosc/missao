"""Configuração do backend, lida de variáveis de ambiente.

| Variável                    | Padrão                            | Uso                                              |
|-----------------------------|-----------------------------------|--------------------------------------------------|
| VERIFICADOR_DATABASE_URL    | (vazio)                           | URL PostgreSQL. Se vazia, usa também `DATABASE_URL` ou `POSTGRES_URL` (criadas pela integração Neon da Vercel). Sem nenhuma, usa SQLite. |
| VERIFICADOR_DB              | <verificador>/data/verificador.db | Caminho do banco SQLite.                         |
| VERIFICADOR_UPLOADS         | <verificador>/data/uploads        | Pasta dos arquivos originais (só SQLite).        |
| VERIFICADOR_MAX_UPLOAD_MB   | 25 (4 na Vercel)                  | Tamanho máximo de **cada** arquivo enviado.      |
| VERIFICADOR_API_KEY         | (vazio = sem autenticação)        | Chave exigida no cabeçalho `X-API-Key`.          |
| VERIFICADOR_CORS_ORIGINS    | http://localhost:8501             | Origens liberadas no CORS, separadas por vírgula.|

Na **Vercel** (variável `VERCEL` presente, definida pela própria plataforma):
- o disco é somente leitura, exceto `/tmp`, que é temporário. Sem banco PostgreSQL, o SQLite vai
  para `/tmp` e `/saude` informa `persistente: false`;
- a requisição inteira tem limite de 4,5 MB, informado ao frontend em `/parametros`.

Em produção, defina sempre `VERIFICADOR_API_KEY` e restrinja `VERIFICADOR_CORS_ORIGINS`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Pasta "verificador/" (onde ficam app.py, api/ e o núcleo). Os dados padrão ficam em verificador/data/.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

# Limite de corpo de requisição das Vercel Functions (MB).
LIMITE_REQUISICAO_VERCEL_MB = 4.5


@dataclass(frozen=True)
class Configuracao:
    """Parâmetros de execução do backend. Imutável: crie outra instância para testes."""

    caminho_db: Path = RAIZ_PROJETO / "data" / "verificador.db"
    pasta_uploads: Path = RAIZ_PROJETO / "data" / "uploads"
    max_upload_mb: int = 25
    api_key: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8501"])
    database_url: str | None = None
    disco_persistente: bool = True
    max_requisicao_mb: float | None = None  # limite total da requisição imposto pela plataforma

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def do_ambiente(cls) -> "Configuracao":
        """Monta a configuração a partir das variáveis de ambiente (com os padrões acima)."""
        padrao = cls()
        em_vercel = bool(os.getenv("VERCEL"))
        tmp = Path("/tmp/verificador")
        origens = os.getenv("VERIFICADOR_CORS_ORIGINS")
        url = (os.getenv("VERIFICADOR_DATABASE_URL") or os.getenv("DATABASE_URL")
               or os.getenv("POSTGRES_URL") or None)
        return cls(
            caminho_db=Path(os.getenv("VERIFICADOR_DB") or (tmp / "verificador.db" if em_vercel else padrao.caminho_db)),
            pasta_uploads=Path(os.getenv("VERIFICADOR_UPLOADS") or (tmp / "uploads" if em_vercel else padrao.pasta_uploads)),
            max_upload_mb=int(os.getenv("VERIFICADOR_MAX_UPLOAD_MB") or (4 if em_vercel else padrao.max_upload_mb)),
            api_key=os.getenv("VERIFICADOR_API_KEY") or None,
            cors_origins=([o.strip() for o in origens.split(",") if o.strip()] if origens is not None
                          else padrao.cors_origins),
            database_url=url,
            disco_persistente=not em_vercel,
            max_requisicao_mb=LIMITE_REQUISICAO_VERCEL_MB if em_vercel else None,
        )
