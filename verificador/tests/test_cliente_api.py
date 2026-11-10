"""Testes do cliente HTTP (`cliente_api.py`) contra a API em memória (TestClient)."""
from datetime import date

import pandas as pd
import pytest

from cliente_api import ClienteAPI, ErroAPI, df_para_lancamentos

from .conftest import ARQUIVOS, PASTA_EXEMPLOS


def _transporte(test_client):
    """Adapta o TestClient do FastAPI à assinatura de transporte do ClienteAPI."""
    def enviar(metodo, url, corpo, cabecalhos):
        r = test_client.request(metodo, url, content=corpo, headers=cabecalhos)
        return r.status_code, dict(r.headers), r.content
    return enviar


@pytest.fixture
def api(cliente):
    return ClienteAPI("http://testserver", transporte=_transporte(cliente))


@pytest.fixture
def arquivos():
    return {campo: [(nome, (PASTA_EXEMPLOS / nome).read_bytes())] for campo, nome in ARQUIVOS.items()}


def test_fluxo_completo(api, arquivos):
    assert api.saude()["status"] == "ok"
    assert "Gasto" in api.parametros()["classificacoes"]
    det = api.criar(arquivos, {"nome_projeto": "Via cliente", "inicio": date(2026, 3, 1), "fim": "31/08/2026",
                               "palavras_smf": ["SECRETARIA MUNICIPAL DA FAZENDA"], "cnpj_entidade": ""})
    assert det["parametros"]["nome_projeto"] == "Via cliente"
    assert det["parametros"]["fim"] == "2026-08-31"
    id_ = det["id"]
    assert api.listar()["total"] == 1 and api.obter(id_)["id"] == id_

    cc = api.lancamentos(id_)["corrente"]
    cc[-1]["classificacao"] = "Gasto"
    assert api.salvar_lancamentos(id_, corrente=cc)["id"] == id_
    assert api.atualizar_parametros(id_, max_entradas_smf=4)["parametros"]["max_entradas_smf"] == 4
    assert api.relatorio(id_, "docx")[:2] == b"PK"
    assert "Relatório Descritivo" in api.relatorio(id_, "md").decode("utf-8")
    with pytest.raises(ValueError):
        api.relatorio(id_, "pdf")
    api.excluir(id_)
    with pytest.raises(ErroAPI) as e:
        api.obter(id_)
    assert e.value.status == 404 and "não encontrada" in e.value.detalhe


def test_envia_lancamentos_revisados(api, arquivos):
    df = pd.DataFrame([{"data": date(2026, 3, 2), "descricao": "SECRETARIA MUNICIPAL DA FAZENDA", "documento": "",
                        "valor": 1000.0, "saldo": float("nan"), "conta": "Ag 1", "arquivo": "x.pdf",
                        "classificacao": "Entrada SMF (Fazenda)"}])
    lanc = df_para_lancamentos(df)
    assert lanc[0]["data"] == "2026-03-02" and lanc[0]["saldo"] is None
    det = api.criar(arquivos, {}, {"corrente": lanc})
    assert det["resumo"]["total_smf"] == 1000.0
    assert df_para_lancamentos(pd.DataFrame()) == []


def test_erro_de_validacao_e_chave(cliente_com_chave, arquivos):
    sem_chave = ClienteAPI("http://testserver", transporte=_transporte(cliente_com_chave))
    with pytest.raises(ErroAPI) as e:
        sem_chave.listar()
    assert e.value.status == 401
    com_chave = ClienteAPI("http://testserver", api_key="segredo-teste", transporte=_transporte(cliente_com_chave))
    with pytest.raises(ErroAPI) as e:
        com_chave.criar({"extratos_corrente": [("x.exe", b"MZ")]})
    assert e.value.status == 415


def test_api_indisponivel():
    with pytest.raises(ErroAPI) as e:
        ClienteAPI("http://127.0.0.1:9", timeout=2).saude()
    assert e.value.status == 0


def test_do_ambiente(monkeypatch):
    monkeypatch.delenv("VERIFICADOR_API_URL", raising=False)
    assert ClienteAPI.do_ambiente() is None
    monkeypatch.setenv("VERIFICADOR_API_URL", "http://api:8000/")
    monkeypatch.setenv("VERIFICADOR_API_KEY", "k")
    c = ClienteAPI.do_ambiente()
    assert c.url_base == "http://api:8000" and c.api_key == "k"
