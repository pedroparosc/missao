"""Verificador de Prestação de Contas — leitura de documentos, verificações e relatório."""
from __future__ import annotations

import pandas as pd

from .leitores import (COLUNAS_EXTRATO, COLUNAS_NF, ler_extrato, ler_nota_fiscal, ler_planilha_gastos,
                       ler_planilha_previsto, ler_planilha_rendimentos, ler_projeto)


def carregar_extratos(arquivos: list[tuple[str, bytes]]):
    """Lê vários extratos. Retorna (lançamentos, metadados por arquivo, avisos)."""
    frames, metas, avisos = [], [], []
    for nome, conteudo in arquivos:
        try:
            e = ler_extrato(nome, conteudo)
        except Exception as exc:  # arquivo corrompido, formato inesperado...
            avisos.append(f"{nome}: erro ao ler ({exc}).")
            continue
        frames.append(e.lancamentos)
        conta = e.lancamentos["conta"].iloc[0] if not e.lancamentos.empty else nome
        metas.append({"arquivo": nome, "conta": conta, "contas": e.contas,
                      "saldo_anterior": e.saldo_anterior, "saldo_final": e.saldo_final,
                      "n": len(e.lancamentos)})
        avisos += [f"{nome}: {a}" for a in e.avisos]
    frames = [f for f in frames if not f.empty]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUNAS_EXTRATO)
    if not df.empty:
        df = df.sort_values("data", kind="stable").reset_index(drop=True)
    return df, metas, avisos


def carregar_notas(arquivos: list[tuple[str, bytes]]):
    linhas, avisos = [], []
    for nome, conteudo in arquivos:
        try:
            n = ler_nota_fiscal(nome, conteudo)
            if n:
                linhas.append(n)
            else:
                avisos.append(f"{nome}: não reconhecido como nota fiscal.")
        except Exception as exc:
            avisos.append(f"{nome}: erro ao ler ({exc}).")
    return pd.DataFrame(linhas, columns=COLUNAS_NF), avisos
