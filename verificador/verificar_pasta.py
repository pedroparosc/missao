"""Executa a verificação sem interface, a partir de uma pasta com os documentos.

Uso:
    python verificar_pasta.py <pasta> --cnpj 12.345.678/0001-95 [--inicio 01/03/2026 --fim 31/08/2026]

Convenção de nomes na pasta (sem diferenciar maiúsculas):
    projeto - <nome>.*          arquivo do projeto
    *corrente*                  extrato(s) da conta corrente
    *invest* / *poupan* / *aplic*   extrato(s) da conta investimento
    *gasto*                     planilha de gastos
    *previsto*                  planilha previsto x executado
    *rendimento*                planilha de rendimentos
    *.xml / *nf* / *nota*       notas fiscais
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verificador import (carregar_extratos, carregar_notas, ler_planilha_gastos, ler_planilha_previsto,
                         ler_planilha_rendimentos, ler_projeto)
from verificador.relatorio import gerar_docx, gerar_markdown
from verificador.utils import cnpj_valido, formatar_cnpj, parse_data
from verificador.verificacoes import Config, classificar, verificar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", type=Path)
    ap.add_argument("--cnpj", default="")
    ap.add_argument("--inicio")
    ap.add_argument("--fim")
    ap.add_argument("--saida", type=Path, help="pasta de saída do relatório (padrão: a própria pasta)")
    a = ap.parse_args()

    arquivos = [p for p in a.pasta.iterdir() if p.is_file()]
    ler = lambda p: (p.name, p.read_bytes())
    nome = lambda p: p.name.lower()

    proj = next((p for p in arquivos if nome(p).startswith("projeto")), None)
    cc = [p for p in arquivos if "corrente" in nome(p)]
    inv = [p for p in arquivos if any(k in nome(p) for k in ("invest", "poupan", "aplic"))]
    gastos = next((p for p in arquivos if "gasto" in nome(p)), None)
    prev = next((p for p in arquivos if "previsto" in nome(p)), None)
    rend = next((p for p in arquivos if "rendimento" in nome(p)), None)
    usados = {proj, gastos, prev, rend, *cc, *inv}
    nfs = [p for p in arquivos if p not in usados and (p.suffix.lower() == ".xml" or "nf" in nome(p) or "nota" in nome(p))]

    projeto = ler_projeto(*ler(proj)) if proj else None
    cnpj = a.cnpj or (next((formatar_cnpj(c) for c in projeto.cnpjs if cnpj_valido(c)), "") if projeto else "")
    cfg = Config(nome_projeto=projeto.nome if projeto else a.pasta.name, cnpj_entidade=cnpj,
                 inicio=parse_data(a.inicio) if a.inicio else (projeto.inicio if projeto else None),
                 fim=parse_data(a.fim) if a.fim else (projeto.fim if projeto else None))

    df_cc, meta_cc, av1 = carregar_extratos([ler(p) for p in cc])
    df_inv, meta_inv, av2 = carregar_extratos([ler(p) for p in inv])
    g, av3 = ler_planilha_gastos(*ler(gastos)) if gastos else (None, [])
    pv, av4 = ler_planilha_previsto(*ler(prev)) if prev else (None, [])
    rd, av5 = ler_planilha_rendimentos(*ler(rend)) if rend else (None, [])
    nt, av6 = carregar_notas([ler(p) for p in nfs])
    for aviso in av1 + av2 + av3 + av4 + av5 + av6:
        print("AVISO:", aviso, file=sys.stderr)

    res = verificar(cfg, classificar(df_cc, "corrente", cfg.palavras_smf),
                    classificar(df_inv, "investimento", cfg.palavras_smf), meta_cc, meta_inv, g, pv, rd, nt,
                    projeto.rubricas if projeto else None, projeto.menciona_contrapartida if projeto else False)

    saida = a.saida or a.pasta
    md = gerar_markdown(res)
    (saida / "relatorio_prestacao_contas.md").write_text(md, encoding="utf-8")
    (saida / "relatorio_prestacao_contas.docx").write_bytes(gerar_docx(res))
    print(md)
    print(f"\nRelatórios salvos em {saida}", file=sys.stderr)


if __name__ == "__main__":
    main()
