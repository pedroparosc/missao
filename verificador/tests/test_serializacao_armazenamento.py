"""Testes da serialização DataFrame <-> JSON e do repositório SQLite/arquivos."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from api.armazenamento import Repositorio, nome_seguro
from api.serializacao import df_para_json, json_para_df, valor_json


# =========================================================================== serialização
def test_valor_json():
    assert valor_json(date(2026, 3, 2)) == "2026-03-02"
    assert valor_json(pd.Timestamp("2026-03-02 10:00")) == "2026-03-02"
    assert valor_json(float("nan")) is None
    assert valor_json(pd.NaT) is None
    assert valor_json(np.int64(3)) == 3 and isinstance(valor_json(np.int64(3)), int)
    assert valor_json(np.float64(1.5)) == 1.5
    assert valor_json("texto") == "texto"


def test_ida_e_volta_preserva_datas_e_nulos():
    df = pd.DataFrame({"data": [date(2026, 3, 2), None], "descricao": ["A", ""],
                       "valor": [10.5, -3.0], "saldo": [100.0, float("nan")]})
    df["data"] = df["data"].astype(object)
    volta = json_para_df(df_para_json(df))
    assert volta["data"].tolist() == [date(2026, 3, 2), None]
    assert isinstance(volta["data"].iloc[0], date)
    assert volta["valor"].tolist() == [10.5, -3.0]
    assert math.isnan(volta["saldo"].iloc[1]) or volta["saldo"].iloc[1] is None
    assert_frame_equal(volta[["descricao", "valor"]], df[["descricao", "valor"]])


def test_dataframe_vazio_e_none():
    assert df_para_json(None) is None and json_para_df(None) is None
    volta = json_para_df(df_para_json(pd.DataFrame(columns=["data", "valor"])))
    assert volta.empty and list(volta.columns) == ["data", "valor"]


# =========================================================================== repositório
@pytest.fixture
def repo(tmp_path) -> Repositorio:
    return Repositorio(tmp_path / "db" / "t.db", tmp_path / "uploads")


def test_crud(repo):
    assert not (repo.caminho_db.exists())  # nada é criado antes do primeiro uso
    res = {"resumo": {"total_smf": 1.0, "total_gasto": 0.5, "total_rendimentos": 0.0, "diferenca": 0.5}}
    repo.criar("a1", {"nome_projeto": "P"}, {"x": 1}, res, nome_projeto="P", n_erros=2)
    repo.criar("a2", {"nome_projeto": "Q"}, {"x": 2}, res, nome_projeto="Q")
    assert repo.saudavel()
    a = repo.obter("a1")
    assert a["parametros"] == {"nome_projeto": "P"} and a["insumos"] == {"x": 1} and a["n_erros"] == 2
    total, itens = repo.listar()
    assert total == 2 and [i["id"] for i in itens] == ["a2", "a1"]  # mais recente primeiro
    assert repo.atualizar("a1", n_alertas=7, parametros={"nome_projeto": "P2"})
    assert repo.obter("a1")["n_alertas"] == 7 and repo.obter("a1")["parametros"]["nome_projeto"] == "P2"
    assert not repo.atualizar("nao-existe", n_alertas=1)
    with pytest.raises(ValueError):
        repo.atualizar("a1", id="hack")
    assert repo.excluir("a1") and repo.obter("a1") is None and not repo.excluir("a1")


@pytest.mark.parametrize("nome, esperado", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\Windows\\win.ini", "win.ini"),
    ("extrato março.pdf", "extrato março.pdf"),
    ("a<b>c:d|e?.pdf", "a_b_c_d_e_.pdf"),
    ("...", "arquivo"),
    ("", "arquivo"),
])
def test_nome_seguro(nome, esperado):
    assert nome_seguro(nome) == esperado


def test_nome_seguro_limita_tamanho_e_preserva_extensao():
    n = nome_seguro("x" * 300 + ".pdf")
    assert len(n) <= 120 and n.endswith(".pdf")


def test_salvar_arquivo_confinado_e_exclusao_remove_pasta(repo):
    repo.criar("abc123", {}, {}, {"resumo": {}})
    meta = repo.salvar_arquivo("abc123", "extratos_corrente", "../../fora.pdf", b"%PDF-1.4 teste")
    pasta = (repo.pasta_uploads / "abc123").resolve()
    assert meta["caminho"].startswith(str(pasta))
    assert meta["tamanho"] == 14 and len(meta["sha256"]) == 64
    assert [a["nome_original"] for a in repo.listar_arquivos("abc123")] == ["../../fora.pdf"]
    repo.excluir("abc123")
    assert not pasta.exists() and repo.listar_arquivos("abc123") == []
