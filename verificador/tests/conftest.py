"""Fixtures compartilhadas pelos testes.

- `cliente`: API isolada com banco SQLite e pasta de uploads temporários (não toca em `data/`).
  Se a variável `VERIFICADOR_TESTE_POSTGRES_URL` existir, a MESMA suíte roda contra PostgreSQL
  (o CI faz isso com um contêiner postgres); as tabelas são esvaziadas antes de cada teste.
- `cliente_com_chave`: mesma API exigindo a chave `segredo-teste`.
- `arquivos_exemplo`: documentos fictícios de `exemplos/dados/` no formato do multipart.
- `analise`: análise já criada com todos os arquivos de exemplo (JSON do AnaliseDetalhe).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import Configuracao
from api.main import criar_app

PASTA_EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos" / "dados"

# campo do multipart -> arquivo de exemplo
ARQUIVOS = {
    "projeto": "projeto - Festival Cultura Viva.docx",
    "extratos_corrente": "extrato_conta_corrente.pdf",
    "extratos_investimento": "extrato_investimento.xlsx",
    "planilha_gastos": "planilha_gastos.xlsx",
    "planilha_previsto": "previsto_executado.csv",
    "planilha_rendimentos": "rendimentos.csv",
}


URL_POSTGRES_TESTE = os.getenv("VERIFICADOR_TESTE_POSTGRES_URL") or None
USANDO_POSTGRES = URL_POSTGRES_TESTE is not None


def _limpar_postgres() -> None:
    """Esvazia as tabelas do banco de teste (cada teste começa do zero, como no SQLite em tmp_path)."""
    from api.armazenamento import RepositorioPostgres
    repo = RepositorioPostgres(URL_POSTGRES_TESTE)
    with repo._conexao() as con:
        con.execute("TRUNCATE arquivos, analises RESTART IDENTITY CASCADE")


def _config(tmp_path: Path, **extra) -> Configuracao:
    if USANDO_POSTGRES:
        _limpar_postgres()
        extra.setdefault("database_url", URL_POSTGRES_TESTE)
    return Configuracao(caminho_db=tmp_path / "teste.db", pasta_uploads=tmp_path / "uploads", **extra)


@pytest.fixture
def config(tmp_path) -> Configuracao:
    return _config(tmp_path)


@pytest.fixture
def cliente(config) -> TestClient:
    with TestClient(criar_app(config)) as c:
        yield c


@pytest.fixture
def cliente_com_chave(tmp_path) -> TestClient:
    with TestClient(criar_app(_config(tmp_path, api_key="segredo-teste"))) as c:
        yield c


@pytest.fixture(scope="session")
def arquivos_exemplo() -> list[tuple[str, tuple[str, bytes]]]:
    return [(campo, (nome, (PASTA_EXEMPLOS / nome).read_bytes())) for campo, nome in ARQUIVOS.items()]


@pytest.fixture
def analise(cliente, arquivos_exemplo) -> dict:
    r = cliente.post("/api/v1/analises", files=arquivos_exemplo)
    assert r.status_code == 201, r.text
    return r.json()
