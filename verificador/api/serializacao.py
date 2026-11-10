"""Conversão entre as estruturas do núcleo (pandas, `date`, NaN, numpy) e JSON.

O núcleo trabalha com `DataFrame`s cujas colunas de data contêm objetos `datetime.date`
(não `datetime64`). Para que uma análise salva possa ser **reprocessada** depois — por
exemplo, após o usuário corrigir a classificação de um lançamento — a ida e volta precisa
ser exata: as datas voltam como `date`, os nulos como `None` e os números como `float`.

Formato de um DataFrame serializado::

    {"colunas": ["data", "valor", ...], "registros": [{"data": "2026-03-02", "valor": 20000.0}, ...]}
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd

# Colunas que, em qualquer tabela do núcleo, guardam datas.
COLUNAS_DATA = frozenset({"data", "data_emissao", "data_planilha", "data_extrato", "inicio", "fim"})


def valor_json(v: Any) -> Any:
    """Converte um valor escalar para um tipo aceito pelo JSON.

    - `date`/`datetime`/`Timestamp` -> texto ISO (`AAAA-MM-DD`);
    - NaN/NaT/None -> None;
    - tipos numpy (int64, float64, bool_) -> tipos nativos do Python.
    """
    # NaT precisa vir antes: ele passa em isinstance(v, datetime).
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (list, dict, str, bytes)):
        v = v.item()  # numpy -> Python
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _data(v: Any) -> date | None:
    """Converte texto ISO (ou date/datetime) em `date`; vazio/NaN vira None.

    No pandas 3, `None` em coluna de texto vira NaN ao montar o DataFrame, por isso o `isna`.
    """
    if v is None or v is pd.NaT or (not isinstance(v, (date, str)) and pd.isna(v)) or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def df_para_json(df: pd.DataFrame | None) -> dict | None:
    """Serializa um DataFrame (ou None) no formato `{"colunas", "registros"}`."""
    if df is None:
        return None
    colunas = [str(c) for c in df.columns]
    registros = [{c: valor_json(v) for c, v in zip(colunas, linha)} for linha in df.itertuples(index=False, name=None)]
    return {"colunas": colunas, "registros": registros}


def json_para_df(obj: dict | None) -> pd.DataFrame | None:
    """Reconstrói o DataFrame salvo por `df_para_json`, devolvendo as datas como `date`."""
    if obj is None:
        return None
    df = pd.DataFrame(obj.get("registros") or [], columns=obj.get("colunas") or None)
    for c in df.columns:
        if c in COLUNAS_DATA:
            # dtype object para manter objetos `date` (como o núcleo espera), não datetime64.
            df[c] = pd.Series([_data(v) for v in df[c]], index=df.index, dtype=object)
    return df


def registros(df: pd.DataFrame | None) -> list[dict]:
    """Atalho para a API: só a lista de registros JSON (lista vazia se não houver tabela)."""
    j = df_para_json(df)
    return j["registros"] if j else []
