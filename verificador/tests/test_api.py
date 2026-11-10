"""Testes de contrato da API (todos os endpoints e códigos de erro)."""
import json

import pytest
from fastapi.testclient import TestClient

from api.config import Configuracao
from api.main import criar_app
from verificador.verificacoes import CLASSIFICACOES, OUTRA_ENTRADA, PAL_SMF_PADRAO, SMF

API = "/api/v1"


# =========================================================================== sistema
def test_saude(cliente):
    r = cliente.get(f"{API}/saude")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok" and j["versao"] == "1.1.0" and j["banco"] is True
    assert j["banco_tipo"] in ("sqlite", "postgres") and j["persistente"] is True


def test_parametros_padrao_iguais_ao_frontend(cliente):
    p = cliente.get(f"{API}/parametros").json()
    assert p["classificacoes"] == CLASSIFICACOES
    assert p["palavras_smf"] == PAL_SMF_PADRAO
    assert p["tolerancia_dias"] == 5 and p["max_entradas_smf"] == 3
    assert p["campos_arquivo"]["extratos_corrente"]["multiplo"] is True
    assert "docx" in p["campos_arquivo"]["projeto"]["extensoes"]


def test_openapi_publicado(cliente):
    esquema = cliente.get("/openapi.json").json()
    assert f"{API}/analises" in esquema["paths"]
    assert f"{API}/analises/{{analise_id}}/relatorio.docx" in esquema["paths"]


def test_config_do_ambiente(monkeypatch, tmp_path):
    for var in ("VERCEL", "DATABASE_URL", "POSTGRES_URL", "VERIFICADOR_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VERIFICADOR_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("VERIFICADOR_MAX_UPLOAD_MB", "2")
    monkeypatch.setenv("VERIFICADOR_CORS_ORIGINS", "http://a.com, http://b.com")
    monkeypatch.setenv("VERIFICADOR_API_KEY", "k")
    c = Configuracao.do_ambiente()
    assert c.caminho_db == tmp_path / "x.db" and c.max_upload_bytes == 2 * 1024 * 1024
    assert c.cors_origins == ["http://a.com", "http://b.com"] and c.api_key == "k"
    with TestClient(criar_app(Configuracao(caminho_db=c.caminho_db, pasta_uploads=tmp_path / "u"))) as cli:
        cli.get(f"{API}/saude")
    assert c.caminho_db.exists()  # banco criado no caminho indicado


# =========================================================================== segurança
def test_chave_de_api(cliente_com_chave, arquivos_exemplo):
    assert cliente_com_chave.get(f"{API}/saude").status_code == 200  # saúde é pública
    assert cliente_com_chave.get(f"{API}/analises").status_code == 401
    assert cliente_com_chave.get(f"{API}/analises", headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente_com_chave.get(f"{API}/analises", headers={"X-API-Key": "segredo-teste"}).status_code == 200


# =========================================================================== criação
def test_criar_analise_preenche_dados_do_projeto(analise):
    p = analise["parametros"]
    assert p["nome_projeto"] == "Festival Cultura Viva"
    assert p["cnpj_entidade"] == "12.345.678/0001-95"
    assert p["inicio"] == "2026-03-01" and p["fim"] == "2026-08-31"
    assert analise["projeto"]["rubricas"][0] == {"rubrica": "Cachês artísticos", "previsto": 30000.0}
    assert {a["campo"] for a in analise["arquivos"]} == {
        "projeto", "extratos_corrente", "extratos_investimento", "planilha_gastos", "planilha_previsto",
        "planilha_rendimentos"}
    assert all(len(a["sha256"]) == 64 for a in analise["arquivos"])


def test_criar_analise_parametros_informados_prevalecem(cliente, arquivos_exemplo):
    r = cliente.post(f"{API}/analises", files=arquivos_exemplo,
                     data={"nome_projeto": "Outro nome", "inicio": "01/04/2026", "fim": "2026-07-31",
                           "max_entradas_smf": "4", "palavras_smf": "SECRETARIA MUNICIPAL DA FAZENDA\n"})
    assert r.status_code == 201, r.text
    p = r.json()["parametros"]
    assert p["nome_projeto"] == "Outro nome" and p["inicio"] == "2026-04-01" and p["fim"] == "2026-07-31"
    assert p["max_entradas_smf"] == 4 and p["palavras_smf"] == ["SECRETARIA MUNICIPAL DA FAZENDA"]
    assert "Entradas da SMF acima do limite" not in {o["categoria"] for o in r.json()["ocorrencias"]}


def test_criar_analise_com_lancamentos_revisados(cliente, arquivos_exemplo, analise):
    cc = cliente.get(f"{API}/analises/{analise['id']}/lancamentos").json()["corrente"]
    for l in cc:
        if l["classificacao"] == SMF and l["data"] == "2026-06-10":
            l["classificacao"] = OUTRA_ENTRADA
    r = cliente.post(f"{API}/analises", files=arquivos_exemplo, data={"lancamentos": json.dumps({"corrente": cc})})
    assert r.status_code == 201, r.text
    assert r.json()["resumo"]["n_entradas_smf"] == 3


@pytest.mark.parametrize("data, trecho", [
    ({"inicio": "32/13/2026"}, "Data inválida"),
    ({"lancamentos": "{não é json"}, "JSON inválido"),
    ({"lancamentos": json.dumps({"corrente": [{"data": "2026-03-01", "valor": 1, "classificacao": "X"}]})},
     "classificação inválida"),
    ({"tolerancia_dias": "99"}, ""),
])
def test_criar_analise_dados_invalidos(cliente, arquivos_exemplo, data, trecho):
    r = cliente.post(f"{API}/analises", files=arquivos_exemplo, data=data)
    assert r.status_code == 422
    assert trecho in json.dumps(r.json(), ensure_ascii=False)


def test_criar_analise_sem_extrato_nem_planilha(cliente, arquivos_exemplo):
    so_projeto = [a for a in arquivos_exemplo if a[0] == "projeto"]
    r = cliente.post(f"{API}/analises", files=so_projeto)
    assert r.status_code == 422 and "ao menos um extrato" in r.json()["detail"]


def test_extensao_nao_aceita(cliente):
    r = cliente.post(f"{API}/analises", files=[("extratos_corrente", ("virus.exe", b"MZ..."))])
    assert r.status_code == 415 and ".exe" in r.json()["detail"]


def test_campo_unico_com_varios_arquivos(cliente, arquivos_exemplo):
    gastos = next(a for a in arquivos_exemplo if a[0] == "planilha_gastos")
    r = cliente.post(f"{API}/analises", files=[gastos, gastos])
    assert r.status_code == 422 and "apenas um arquivo" in r.json()["detail"]


def test_arquivo_grande_demais(tmp_path):
    cfg = Configuracao(caminho_db=tmp_path / "t.db", pasta_uploads=tmp_path / "u", max_upload_mb=1)
    with TestClient(criar_app(cfg)) as c:
        r = c.post(f"{API}/analises", files=[("planilha_gastos", ("g.csv", b"a;b\n" * 300_000))])
    assert r.status_code == 413


def test_aviso_de_leitura_nao_interrompe(cliente, arquivos_exemplo):
    arquivos = arquivos_exemplo + [("notas_fiscais", ("nota.xml", b"<nao-fecha"))]
    r = cliente.post(f"{API}/analises", files=arquivos)
    assert r.status_code == 201
    assert any("nota.xml" in a for a in r.json()["avisos_leitura"])


# =========================================================================== consulta
def test_listar_e_obter(cliente, analise):
    lista = cliente.get(f"{API}/analises").json()
    assert lista["total"] == 1
    item = lista["itens"][0]
    assert item["id"] == analise["id"] and item["nome_projeto"] == "Festival Cultura Viva"
    assert item["total_smf"] == 60000.0 and item["n_erros"] == analise["resumo"]["n_erros"]
    assert cliente.get(f"{API}/analises/{analise['id']}").json()["resumo"] == analise["resumo"]
    assert cliente.get(f"{API}/analises?limite=0").status_code == 422


def test_paginacao(cliente, arquivos_exemplo):
    for _ in range(3):
        cliente.post(f"{API}/analises", files=arquivos_exemplo)
    pagina = cliente.get(f"{API}/analises?limite=2&deslocamento=2").json()
    assert pagina["total"] == 3 and len(pagina["itens"]) == 1


@pytest.mark.parametrize("metodo, sufixo", [
    ("get", ""), ("get", "/lancamentos"), ("get", "/relatorio.docx"), ("get", "/relatorio.md"), ("delete", ""),
])
def test_analise_inexistente_404(cliente, metodo, sufixo):
    r = getattr(cliente, metodo)(f"{API}/analises/naoexiste{sufixo}")
    assert r.status_code == 404 and "não encontrada" in r.json()["detail"]


def test_put_patch_inexistente_404(cliente):
    assert cliente.put(f"{API}/analises/x/lancamentos", json={"corrente": []}).status_code == 404
    assert cliente.patch(f"{API}/analises/x/parametros", json={"tolerancia_dias": 1}).status_code == 404


# =========================================================================== revisão e recálculo
def test_reclassificar_lancamento_recalcula(cliente, analise):
    id_ = analise["id"]
    cc = cliente.get(f"{API}/analises/{id_}/lancamentos").json()["corrente"]
    assert len(cc) == 17 and all(l["classificacao"] in CLASSIFICACOES for l in cc)
    quarta = [l for l in cc if l["classificacao"] == SMF][-1]
    quarta["classificacao"] = OUTRA_ENTRADA
    r = cliente.put(f"{API}/analises/{id_}/lancamentos", json={"corrente": cc})
    assert r.status_code == 200
    novo = r.json()
    assert "Entradas da SMF acima do limite" not in {o["categoria"] for o in novo["ocorrencias"]}
    assert novo["resumo"]["total_smf"] == 50000.0
    # a alteração foi persistida
    salvo = cliente.get(f"{API}/analises/{id_}/lancamentos").json()["corrente"]
    assert sum(l["classificacao"] == SMF for l in salvo) == 3
    # conta omitida (investimento) não mudou
    assert len(cliente.get(f"{API}/analises/{id_}/lancamentos").json()["investimento"]) == 6


def test_put_lancamento_invalido(cliente, analise):
    r = cliente.put(f"{API}/analises/{analise['id']}/lancamentos",
                    json={"corrente": [{"data": "2026-03-01", "valor": 1, "classificacao": "Inventada"}]})
    assert r.status_code == 422


def test_patch_parametros(cliente, analise):
    id_ = analise["id"]
    r = cliente.patch(f"{API}/analises/{id_}/parametros", json={"max_entradas_smf": 4, "nome_projeto": "Renomeado"})
    assert r.status_code == 200
    j = r.json()
    assert j["parametros"]["max_entradas_smf"] == 4 and j["parametros"]["nome_projeto"] == "Renomeado"
    assert "Entradas da SMF acima do limite" not in {o["categoria"] for o in j["ocorrencias"]}
    assert cliente.get(f"{API}/analises").json()["itens"][0]["nome_projeto"] == "Renomeado"
    assert cliente.patch(f"{API}/analises/{id_}/parametros", json={"campo_inexistente": 1}).status_code == 422
    assert cliente.patch(f"{API}/analises/{id_}/parametros", json={"tolerancia_dias": -1}).status_code == 422


def test_patch_palavras_smf_reclassifica(cliente, analise):
    r = cliente.patch(f"{API}/analises/{analise['id']}/parametros", json={"palavras_smf": ["NADA BATE"]})
    assert r.json()["resumo"]["total_smf"] == 0.0
    assert "Entradas da SMF" in {o["categoria"] for o in r.json()["ocorrencias"] if o["gravidade"] == "Erro"}


def test_vigencia_alterada_gera_despesa_fora_do_prazo(cliente, analise):
    antes = sum(o["categoria"] == "Despesa fora do prazo" for o in analise["ocorrencias"])
    r = cliente.patch(f"{API}/analises/{analise['id']}/parametros", json={"fim": "2026-05-31"})
    depois = sum(o["categoria"] == "Despesa fora do prazo" for o in r.json()["ocorrencias"])
    assert depois > antes


# =========================================================================== relatórios e exclusão
def test_relatorios(cliente, analise):
    id_ = analise["id"]
    docx = cliente.get(f"{API}/analises/{id_}/relatorio.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert "relatorio_prestacao_contas_Festival_Cultura_Viva.docx" in docx.headers["content-disposition"]
    md = cliente.get(f"{API}/analises/{id_}/relatorio.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "Relatório Descritivo da Prestação de Contas" in md.text and "R$ 60.000,00" in md.text


def test_excluir(cliente, analise, config):
    id_ = analise["id"]
    em_disco = config.database_url is None  # no PostgreSQL os arquivos ficam no banco
    if em_disco:
        assert (config.pasta_uploads / id_).exists()
    assert cliente.delete(f"{API}/analises/{id_}").status_code == 204
    assert cliente.get(f"{API}/analises/{id_}").status_code == 404
    if em_disco:
        assert not (config.pasta_uploads / id_).exists()
