"""Testes do deploy na Vercel (configuração, ponto de entrada, manifesto) e do frontend web."""
import importlib.util
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.armazenamento import Repositorio, RepositorioPostgres, criar_repositorio
from api.config import LIMITE_REQUISICAO_VERCEL_MB, Configuracao
from api.main import criar_app

from .conftest import ARQUIVOS, PASTA_EXEMPLOS, URL_POSTGRES_TESTE

RAIZ_REPO = Path(__file__).resolve().parents[2]
VARS = ("VERCEL", "DATABASE_URL", "POSTGRES_URL", "VERIFICADOR_DATABASE_URL", "VERIFICADOR_DB",
        "VERIFICADOR_UPLOADS", "VERIFICADOR_MAX_UPLOAD_MB")


@pytest.fixture
def ambiente_limpo(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


# =========================================================================== configuração
def test_config_local_padrao(ambiente_limpo):
    c = Configuracao.do_ambiente()
    assert c.database_url is None and c.disco_persistente and c.max_requisicao_mb is None
    assert c.max_upload_mb == 25 and isinstance(criar_repositorio(c), Repositorio)


def test_config_na_vercel_sem_banco_usa_tmp(ambiente_limpo):
    ambiente_limpo.setenv("VERCEL", "1")
    c = Configuracao.do_ambiente()
    assert c.caminho_db == Path("/tmp/verificador/verificador.db")
    assert c.max_upload_mb == 4 and c.max_requisicao_mb == LIMITE_REQUISICAO_VERCEL_MB
    assert not c.disco_persistente
    repo = criar_repositorio(c)
    assert repo.tipo == "sqlite" and repo.persistente is False


@pytest.mark.parametrize("variaveis, esperado", [
    ({"POSTGRES_URL": "postgresql://p"}, "postgresql://p"),
    ({"POSTGRES_URL": "postgresql://p", "DATABASE_URL": "postgresql://d"}, "postgresql://d"),
    ({"DATABASE_URL": "postgresql://d", "VERIFICADOR_DATABASE_URL": "postgresql://v"}, "postgresql://v"),
])
def test_config_url_do_banco(ambiente_limpo, variaveis, esperado):
    ambiente_limpo.setenv("VERCEL", "1")
    for k, v in variaveis.items():
        ambiente_limpo.setenv(k, v)
    c = Configuracao.do_ambiente()
    assert c.database_url == esperado
    repo = criar_repositorio(c)  # não conecta: a conexão só acontece no primeiro uso
    assert isinstance(repo, RepositorioPostgres) and repo.tipo == "postgres" and repo.persistente


def test_sql_postgres_usa_marcador_proprio():
    assert RepositorioPostgres._sql("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = %s AND b = %s"


def test_saude_e_parametros_informam_limites_da_vercel(tmp_path):
    cfg = Configuracao(caminho_db=tmp_path / "t.db", pasta_uploads=tmp_path / "u", disco_persistente=False,
                       max_upload_mb=4, max_requisicao_mb=LIMITE_REQUISICAO_VERCEL_MB)
    with TestClient(criar_app(cfg)) as c:
        s = c.get("/api/v1/saude").json()
        p = c.get("/api/v1/parametros").json()
    assert s["banco_tipo"] == "sqlite" and s["persistente"] is False
    assert p["max_requisicao_mb"] == 4.5 and p["max_upload_mb"] == 4


# =========================================================================== ponto de entrada e manifesto
def test_index_py_exporta_app_fastapi():
    spec = importlib.util.spec_from_file_location("index_vercel", RAIZ_REPO / "index.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    caminhos = set(modulo.app.openapi()["paths"])
    assert "/api/v1/saude" in caminhos and "/api/v1/analises" in caminhos


def test_pyproject_para_vercel():
    dados = tomllib.loads((RAIZ_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert dados["tool"]["vercel"]["entrypoint"] == "index:app"
    deps = " ".join(dados["project"]["dependencies"]).lower()
    for pacote in ("fastapi", "python-multipart", "pandas", "openpyxl", "pdfplumber", "python-docx", "psycopg"):
        assert pacote in deps, pacote
    assert "streamlit" not in deps  # Streamlit não roda na Vercel e deixaria a função enorme


# =========================================================================== frontend web
def test_frontend_web_servido_na_raiz(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Verificador de Prestação de Contas" in r.text
    for arquivo, tipo in (("/app.js", "javascript"), ("/estilo.css", "text/css")):
        r = cliente.get(arquivo)
        assert r.status_code == 200 and tipo in r.headers["content-type"], arquivo
    # a montagem na raiz não pode esconder a API nem a documentação
    assert cliente.get("/api/v1/saude").json()["status"] == "ok"
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200
    assert cliente.get("/api/v1/nao-existe").status_code == 404


def test_exemplos_servidos_para_o_botao_do_frontend(cliente):
    js = (PASTA_EXEMPLOS.parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    for nome in ARQUIVOS.values():
        assert nome in js, f"app.js não lista {nome}"
        r = cliente.get(f"/exemplos/{nome}")
        assert r.status_code == 200 and r.content == (PASTA_EXEMPLOS / nome).read_bytes(), nome


# =========================================================================== PostgreSQL (só no CI)
@pytest.mark.skipif(URL_POSTGRES_TESTE is None, reason="defina VERIFICADOR_TESTE_POSTGRES_URL para testar no PostgreSQL")
def test_repositorio_postgres_crud(config):
    repo = RepositorioPostgres(URL_POSTGRES_TESTE)
    assert repo.saudavel()
    res = {"resumo": {"total_smf": 1.0}}
    repo.criar("p1", {"nome_projeto": "P"}, {"x": 1}, res, nome_projeto="P")
    repo.criar("p2", {"nome_projeto": "Q"}, {"x": 2}, res, nome_projeto="Q")
    total, itens = repo.listar()
    assert total == 2 and [i["id"] for i in itens] == ["p2", "p1"]
    meta = repo.salvar_arquivo("p1", "extratos_corrente", "../../x.pdf", b"%PDF teste")
    assert meta["caminho"].startswith("db://") and meta["tamanho"] == 10
    with repo._conexao() as con:
        assert bytes(con.execute("SELECT conteudo FROM arquivos").fetchone()["conteudo"]) == b"%PDF teste"
    assert repo.atualizar("p1", n_erros=3) and repo.obter("p1")["n_erros"] == 3
    assert repo.excluir("p1") and repo.obter("p1") is None and repo.listar_arquivos("p1") == []
