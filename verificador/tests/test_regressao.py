"""Regressão: a API deve produzir exatamente o mesmo resultado que o motor usado pelo
frontend/CLI (chamada direta ao núcleo), com os dados de `exemplos/dados`.

Linha de base registrada no development_plan.md (tarefa 0.3).
"""
from collections import Counter

from verificador import (carregar_extratos, ler_planilha_gastos, ler_planilha_previsto, ler_planilha_rendimentos,
                         ler_projeto)
from verificador.leitores import COLUNAS_NF
from verificador.relatorio import gerar_markdown
from verificador.verificacoes import ALERTA, ERRO, Config, classificar, verificar

from .conftest import ARQUIVOS, PASTA_EXEMPLOS

import pandas as pd

LINHA_DE_BASE = {"total_smf": 60000.0, "n_entradas_smf": 4, "total_gasto": 46675.0, "total_rendimentos": 332.85,
                 "diferenca": 13325.0, "saldo_corrente": 6325.0, "saldo_investimento": 8332.85,
                 "n_erros": 14, "n_alertas": 5}


def _direto():
    """Mesma sequência de chamadas do verificar_pasta.py / app.py."""
    ler = lambda campo: (ARQUIVOS[campo], (PASTA_EXEMPLOS / ARQUIVOS[campo]).read_bytes())  # noqa: E731
    projeto = ler_projeto(*ler("projeto"))
    cfg = Config(nome_projeto=projeto.nome, cnpj_entidade="12.345.678/0001-95", inicio=projeto.inicio, fim=projeto.fim)
    cc, mcc, _ = carregar_extratos([ler("extratos_corrente")])
    inv, minv, _ = carregar_extratos([ler("extratos_investimento")])
    g, _ = ler_planilha_gastos(*ler("planilha_gastos"))
    pv, _ = ler_planilha_previsto(*ler("planilha_previsto"))
    rd, _ = ler_planilha_rendimentos(*ler("planilha_rendimentos"))
    return verificar(cfg, classificar(cc, "corrente", cfg.palavras_smf), classificar(inv, "investimento", cfg.palavras_smf),
                     mcc, minv, g, pv, rd, pd.DataFrame(columns=COLUNAS_NF), projeto.rubricas,
                     projeto.menciona_contrapartida)


def test_motor_direto_bate_com_linha_de_base():
    r = _direto()
    assert r.total_smf == LINHA_DE_BASE["total_smf"] and len(r.entradas_smf) == 4
    assert sum(o.gravidade == ERRO for o in r.ocorrencias) == LINHA_DE_BASE["n_erros"]
    assert sum(o.gravidade == ALERTA for o in r.ocorrencias) == LINHA_DE_BASE["n_alertas"]


def test_api_igual_ao_motor_direto(cliente, analise):
    r = _direto()
    resumo = analise["resumo"]
    for chave, valor in LINHA_DE_BASE.items():
        assert resumo[chave] == valor, chave
    # mesmas ocorrências (gravidade, categoria, descrição), na mesma ordem
    api = [(o["gravidade"], o["categoria"], o["descricao"]) for o in analise["ocorrencias"]]
    direto = [(o.gravidade, o.categoria, o.descricao) for o in r.ocorrencias]
    assert Counter(api) == Counter(direto)
    assert len(analise["conciliacao"]) == len(r.conciliacao)
    assert len(analise["checklist_manual"]) == len(r.checklist_manual)
    # relatório Markdown idêntico (exceto a linha com a data/hora da verificação)
    md_api = cliente.get(f"/api/v1/analises/{analise['id']}/relatorio.md").text
    sem_hora = lambda t: [l for l in t.splitlines() if not l.startswith("**Data da verificação")]  # noqa: E731
    assert sem_hora(md_api) == sem_hora(gerar_markdown(r))
