"""Testes das regras de verificação (`verificador.verificacoes`) com dados mínimos montados à mão."""
from datetime import date

import pandas as pd
import pytest

from verificador.leitores import COLUNAS_EXTRATO, COLUNAS_NF
from verificador.verificacoes import (APLICACAO, ERRO, GASTO, OUTRA_ENTRADA, PAL_SMF_PADRAO, RESGATE, SAQUE, SMF,
                                      TARIFA, Config, classificar, classificar_corrente, verificar)

CONTA = "Ag 1234-5 / Conta 56789-0"
COLUNAS_GASTOS = ["item", "data", "data_emissao", "descricao", "fornecedor", "cnpj", "cnpj_tomador", "rubrica",
                  "documento", "tipo_doc", "valor", "forma_pagamento"]
CNPJ_FORN = "12.345.678/0001-95"


def extrato(*linhas, conta=CONTA) -> pd.DataFrame:
    """Linhas: (data, histórico, valor) -> DataFrame de extrato já classificado."""
    df = pd.DataFrame([{"data": d, "descricao": h, "documento": "", "valor": v, "saldo": None, "conta": conta,
                        "arquivo": "extrato.pdf"} for d, h, v in linhas], columns=COLUNAS_EXTRATO)
    return classificar(df, "corrente", PAL_SMF_PADRAO)


def meta(*contas):
    return [{"arquivo": "extrato.pdf", "conta": c, "contas": [c], "saldo_anterior": 0.0, "saldo_final": None, "n": 1}
            for c in (contas or (CONTA,))]


def gastos(*linhas) -> pd.DataFrame:
    """Linhas: (data, descrição, valor, documento)."""
    return pd.DataFrame([{"item": i, "data": d, "data_emissao": d, "descricao": desc, "fornecedor": "Fornecedor",
                          "cnpj": CNPJ_FORN, "cnpj_tomador": "", "rubrica": "", "documento": doc,
                          "tipo_doc": "NFS-e", "valor": v, "forma_pagamento": "PIX"}
                         for i, (d, desc, v, doc) in enumerate(linhas, 1)], columns=COLUNAS_GASTOS)


def rodar(cc, g=None, cfg=None, metas=None):
    cfg = cfg or Config(nome_projeto="Teste", cnpj_entidade="", inicio=date(2026, 3, 1), fim=date(2026, 8, 31))
    return verificar(cfg, cc, pd.DataFrame(), metas or meta(), [], g, None, None,
                     pd.DataFrame(columns=COLUNAS_NF), None)


def categorias(r, gravidade=None):
    return [o.categoria for o in r.ocorrencias if gravidade is None or o.gravidade == gravidade]


@pytest.mark.parametrize("historico, valor, esperado", [
    ("TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", 100, SMF),
    ("PIX RECEBIDO FULANO DE TAL", 100, OUTRA_ENTRADA),
    ("RESGATE POUPANCA", 100, RESGATE),
    ("APLICACAO POUPANCA", -100, APLICACAO),
    ("TARIFA PACOTE SERVICOS", -45, TARIFA),
    ("SAQUE CAIXA ELETRONICO", -500, SAQUE),
    ("PIX ENVIADO SOM TOTAL LTDA", -9800, GASTO),
])
def test_classificacao_conta_corrente(historico, valor, esperado):
    assert classificar_corrente(historico, valor, PAL_SMF_PADRAO) == esperado


def test_entradas_smf_acima_do_limite():
    cc = extrato(*[(date(2026, m, 2), "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", 10000.0) for m in (3, 4, 5, 6)])
    r = rodar(cc, gastos())
    assert r.total_smf == 40000.0
    oc = [o for o in r.ocorrencias if o.categoria == "Entradas da SMF acima do limite"]
    assert len(oc) == 1 and oc[0].gravidade == ERRO
    assert "1 entrada(s) a mais" in oc[0].descricao and "02/06/2026" in oc[0].descricao


def test_limite_smf_configuravel():
    cc = extrato(*[(date(2026, m, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 10000.0) for m in (3, 4, 5, 6)])
    cfg = Config(inicio=date(2026, 3, 1), fim=date(2026, 8, 31), max_entradas_smf=4)
    assert "Entradas da SMF acima do limite" not in categorias(rodar(cc, gastos(), cfg))


def test_sem_entrada_smf_e_erro():
    r = rodar(extrato((date(2026, 3, 5), "PIX ENVIADO X", -10.0)), gastos((date(2026, 3, 5), "x", 10.0, "1")))
    assert "Entradas da SMF" in categorias(r, ERRO)


def test_despesa_fora_do_prazo():
    cc = extrato((date(2026, 3, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 1000.0),
                 (date(2026, 9, 15), "PIX ENVIADO FORNECEDOR", -100.0))
    r = rodar(cc, gastos((date(2026, 9, 15), "Serviço", 100.0, "10")))
    assert "Despesa fora do prazo" in categorias(r, ERRO)


def test_conciliacao_status():
    cc = extrato((date(2026, 3, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 10000.0),
                 (date(2026, 3, 10), "PIX ENVIADO A 111", -1000.0),       # casa com o item 1
                 (date(2026, 3, 20), "PIX ENVIADO B 222", -950.0),        # valor divergente do item 2
                 (date(2026, 4, 1), "PIX ENVIADO C 333", -300.0))         # sem gasto na planilha
    g = gastos((date(2026, 3, 10), "Serviço A", 1000.0, "111"),
               (date(2026, 3, 20), "Serviço B", 1000.0, "222"))
    r = rodar(cc, g)
    status = dict(zip(r.conciliacao["descricao_planilha"].fillna(""), r.conciliacao["status"]))
    assert status["Serviço A"] == "Conciliado"
    assert status["Serviço B"] == "Valor divergente"
    assert "Sem comprovação na planilha" in set(r.conciliacao["status"])
    assert "Valor divergente" in categorias(r, ERRO)


def test_saque_e_credito_de_outra_origem():
    cc = extrato((date(2026, 3, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 1000.0),
                 (date(2026, 3, 3), "SAQUE CAIXA", -100.0),
                 (date(2026, 3, 4), "PIX RECEBIDO FULANO", 50.0))
    r = rodar(cc, gastos())
    assert "Pagamento em espécie" in categorias(r, ERRO)
    assert "Pagamento cruzado / conta mista" in categorias(r)


def test_extratos_de_mais_de_uma_conta():
    cc = extrato((date(2026, 3, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 1000.0))
    r = rodar(cc, gastos(), metas=meta(CONTA, "Ag 9999-0 / Conta 11111-1"))
    assert "Extratos de mais de uma conta" in categorias(r, ERRO)


def test_planilha_de_gastos_ausente():
    r = rodar(extrato((date(2026, 3, 2), "SECRETARIA MUNICIPAL DA FAZENDA", 1000.0)), None)
    assert any(o.categoria == "Documentação" and "Planilha de gastos" in o.descricao for o in r.ocorrencias)
