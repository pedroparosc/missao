"""Leitura de extratos (PDF/CSV/XLSX), planilhas, arquivo do projeto e notas fiscais.

Todos os leitores recebem (nome_arquivo, bytes) para funcionar tanto com upload do
Streamlit quanto com arquivos lidos do disco.
"""
from __future__ import annotations

import difflib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .utils import normalizar, parse_data, parse_valor, so_digitos, vazio

COLUNAS_EXTRATO = ["data", "descricao", "documento", "valor", "saldo", "conta", "arquivo"]


@dataclass
class Extrato:
    arquivo: str
    lancamentos: pd.DataFrame
    contas: list[str] = field(default_factory=list)  # "Ag 1234 / CC 56789-0"
    saldo_anterior: float | None = None
    saldo_final: float | None = None
    avisos: list[str] = field(default_factory=list)


# =========================================================================== util
def _ext(nome: str) -> str:
    return nome.lower().rsplit(".", 1)[-1] if "." in nome else ""


def texto_pdf(conteudo: bytes) -> str:
    import pdfplumber

    partes = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for pag in pdf.pages:
            partes.append(pag.extract_text() or "")
    return "\n".join(partes)


def tabelas_pdf(conteudo: bytes) -> list[pd.DataFrame]:
    import pdfplumber

    tabelas = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for pag in pdf.pages:
            for t in pag.extract_tables() or []:
                linhas = [[(c or "").strip() for c in linha] for linha in t if linha]
                if len(linhas) >= 2:
                    tabelas.append(pd.DataFrame(linhas))
    return tabelas


def _ler_csv(conteudo: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    sep = max([";", ",", "\t", "|"], key=lambda s: sum(l.count(s) for l in texto.splitlines()[:30]))
    if primeira.count(sep) == 0 and sep != ";":
        sep = ";"
    return pd.read_csv(io.StringIO(texto), sep=sep, header=None, dtype=str,
                       engine="python", on_bad_lines="skip", skip_blank_lines=False)


def ler_tabela_bruta(nome: str, conteudo: bytes) -> list[pd.DataFrame]:
    """Lê o arquivo sem cabeçalho (header=None). Retorna uma lista de tabelas brutas."""
    ext = _ext(nome)
    if ext in ("xlsx", "xlsm", "xls"):
        folhas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, header=None, dtype=object)
        return [df for df in folhas.values() if not df.empty]
    if ext in ("csv", "txt"):
        return [_ler_csv(conteudo)]
    if ext == "pdf":
        return tabelas_pdf(conteudo)
    raise ValueError(f"Formato não suportado: {nome}")


SINONIMOS = {
    # extrato
    "data": ["data", "dt", "data lancamento", "data movimento", "data mov", "dt lancamento",
             "data pagamento", "data do pagamento", "dt pagamento", "data pgto"],
    "descricao": ["historico", "descricao", "lancamento", "historico/descricao", "detalhamento",
                  "descricao do item", "item", "objeto", "especificacao", "discriminacao",
                  "descricao da despesa", "despesa"],
    "documento": ["documento", "doc", "n doc", "no doc", "num doc", "numero documento", "nr doc",
                  "n documento", "documento fiscal", "nota fiscal", "nf", "n nf", "no nf",
                  "numero nf", "n da nota", "numero da nota", "nf/recibo", "n nota fiscal",
                  "comprovante", "n documento fiscal"],
    "valor": ["valor", "valor r$", "valor (r$)", "montante", "valor pago", "valor total",
              "valor executado", "valor da despesa", "vlr", "vl"],
    "debito": ["debito", "debitos", "saida", "saidas", "debito r$", "debito (r$)"],
    "credito": ["credito", "creditos", "entrada", "entradas", "credito r$", "credito (r$)"],
    "saldo": ["saldo", "saldo r$", "saldo (r$)", "saldo do dia"],
    "dc": ["d/c", "c/d", "tipo", "natureza", "deb/cred"],
    "agencia": ["agencia", "ag"],
    "conta": ["conta", "conta corrente", "n conta", "numero da conta", "c/c"],
    # planilha de gastos
    "fornecedor": ["fornecedor", "favorecido", "prestador", "emitente", "razao social",
                   "beneficiario", "credor", "nome do fornecedor", "pago a"],
    "cnpj": ["cnpj", "cpf", "cnpj/cpf", "cpf/cnpj", "cnpj fornecedor", "cnpj do fornecedor",
             "cnpj emitente", "cpf/cnpj do fornecedor", "documento do fornecedor"],
    "cnpj_tomador": ["cnpj tomador", "cnpj destinatario", "tomador", "destinatario",
                     "cnpj da entidade"],
    "rubrica": ["rubrica", "categoria", "natureza da despesa", "elemento de despesa", "meta",
                "etapa", "item orcamentario", "grupo", "classificacao"],
    "tipo_doc": ["tipo documento", "tipo de documento", "tipo doc", "especie", "tipo do documento"],
    "data_emissao": ["data emissao", "emissao", "data da nota", "data nf", "data de emissao",
                     "data do documento"],
    "forma_pagamento": ["forma pagamento", "forma de pagamento", "meio de pagamento", "pagamento"],
    # previsto x executado
    "previsto": ["previsto", "orcado", "aprovado", "valor previsto", "valor aprovado", "orcamento",
                 "valor orcado"],
    "executado": ["executado", "realizado", "gasto", "valor executado", "valor realizado",
                  "valor gasto"],
    # rendimentos
    "rendimento": ["rendimento", "rendimentos", "valor rendimento", "juros", "rendimento bruto",
                   "rendimento liquido"],
}


def _casar_coluna(cabecalho: str, chave: str) -> float:
    h = normalizar(cabecalho).lower()
    h = re.sub(r"[^a-z0-9/ ]", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    if not h:
        return 0.0
    melhor = 0.0
    for s in SINONIMOS[chave]:
        if h == s:
            return 1.0
        if len(s) >= 4 and (h.startswith(s + " ") or h.endswith(" " + s)):
            melhor = max(melhor, 0.9)
        melhor = max(melhor, difflib.SequenceMatcher(None, h, s).ratio() * 0.85)
    return melhor


def mapear_colunas(cabecalhos: list[str], chaves: list[str]) -> dict[str, int]:
    """Associa cada chave lógica a um índice de coluna (atribuição gulosa pelo melhor escore)."""
    pares = []
    for i, c in enumerate(cabecalhos):
        for k in chaves:
            sc = _casar_coluna(c, k)
            if sc >= 0.72:
                pares.append((sc, k, i))
    # maior escore primeiro; em empate, a coluna mais à esquerda
    pares.sort(key=lambda p: (-p[0], p[2]))
    mapa: dict[str, int] = {}
    usadas: set[int] = set()
    for sc, k, i in pares:
        if k not in mapa and i not in usadas:
            mapa[k] = i
            usadas.add(i)
    return mapa


def localizar_cabecalho(bruto: pd.DataFrame, chaves: list[str], obrigatorias: list[list[str]],
                        max_linhas: int = 40) -> tuple[int, dict[str, int]] | None:
    """Procura nas primeiras linhas a que melhor funciona como cabeçalho."""
    melhor = None
    for idx in range(min(max_linhas, len(bruto))):
        linha = ["" if vazio(v) else str(v) for v in bruto.iloc[idx].tolist()]
        mapa = mapear_colunas(linha, chaves)
        if all(any(k in mapa for k in grupo) for grupo in obrigatorias):
            if melhor is None or len(mapa) > len(melhor[1]):
                melhor = (idx, mapa)
    return melhor


def _limpar(v) -> str:
    return "" if vazio(v) else " ".join(str(v).split())


def coluna_rotulo(cabecalho: list, dados: pd.DataFrame, mapa: dict[str, int], colunas_valor: list[str]) -> int | None:
    """Escolhe a coluna com o nome da rubrica.

    Usa a coluna cujo cabeçalho é exatamente "Rubrica"; senão, a primeira coluna (da esquerda
    para a direita, antes das colunas de valor) que contenha texto na maioria das linhas.
    Em PDFs o cabeçalho da 1ª coluna costuma vir vazio/mesclado, por isso não dá para confiar
    só no nome do cabeçalho.
    """
    for i, h in enumerate(cabecalho):
        if normalizar(_limpar(h)).startswith("RUBRICA"):
            return i
    limite = min([mapa[k] for k in colunas_valor if k in mapa] or [dados.shape[1]])
    for i in range(limite):
        vals = [_limpar(v) for v in dados.iloc[:, i].tolist()]
        vals = [v for v in vals if v]
        if not vals:
            continue
        textuais = sum(1 for v in vals if parse_valor(v) is None and re.search(r"[A-Za-zÀ-ÿ]{3,}", v))
        if textuais / len(vals) >= 0.6:
            return i
    return mapa.get("rubrica", mapa.get("descricao"))


def _texto_preambulo(bruto: pd.DataFrame, ate: int) -> str:
    linhas = []
    for i in range(min(ate, len(bruto))):
        linhas.append(" ".join(str(v) for v in bruto.iloc[i].tolist() if not vazio(v)))
    return "\n".join(linhas)


# =========================================================================== contas
_RE_AG = re.compile(r"AG(?:E|Ê)?N?C?I?A?\.?\s*(?:N[º°O.]?\s*)?[:\-]?\s*(\d{3,5}(?:-[\dX])?)", re.I)
_RE_CC = re.compile(
    r"CONTA(?:\s+CORRENTE|\s+POUPAN[CÇ]A|\s+INVESTIMENTO|\s+APLICA[CÇ][AÃ]O)?\s*(?:N[º°O.]?\s*)?[:\-]?\s*"
    r"(\d[\d.]{2,14}-?[\dX]?)", re.I)


def detectar_contas(texto: str) -> list[str]:
    t = texto.upper()
    agencias = list(dict.fromkeys(m.group(1) for m in _RE_AG.finditer(t)))
    contas = list(dict.fromkeys(m.group(1).replace(".", "") for m in _RE_CC.finditer(t)))
    contas = [c for c in contas if len(so_digitos(c)) >= 4]
    ag = agencias[0] if agencias else "?"
    return [f"Ag {ag} / Conta {c}" for c in contas]


def _periodo(texto: str) -> tuple[date | None, date | None]:
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s*(?:A|ATE|ATÉ|-|À)\s*(\d{2}/\d{2}/\d{4})", texto.upper())
    if m:
        return parse_data(m.group(1)), parse_data(m.group(2))
    return None, None


# =========================================================================== extratos
_PAL_SALDO = ("SALDO ANTERIOR", "SALDO INICIAL", "SALDO DO DIA", "SALDO FINAL", "SALDO EM",
              "SALDO ATUAL", "S A L D O", "SALDO DISPONIVEL", "SALDO BLOQUEADO", "SALDO TOTAL")
_PAL_NEG = ("PAGTO", "PAGAMENTO", "PIX ENVIADO", "PIX EMITIDO", "TED ENVIADA", "TRANSF ENVIADA",
            "TARIFA", "SAQUE", "DEBITO", "DEB ", "APLICACAO", "APLIC", "COMPRA", "IOF", "IRRF",
            "CHEQUE COMPENSADO", "CH COMPENSADO", "BOLETO", "TRANSFERENCIA ENVIADA", "ENVIO")
_PAL_POS = ("RECEBIDO", "PIX RECEB", "TED RECEB", "CREDITO", "RESGATE", "REND", "DEPOSITO",
            "JUROS", "ESTORNO", "TRANSF RECEBIDA", "TRANSFERENCIA RECEBIDA", "DEVOLUCAO")

_VAL = r"(?:\(?-?\s?R?\$?\s?\d{1,3}(?:\.\d{3})*,\d{2}\)?\s?[-+]?\s?[DC]?(?![\w]))"
_RE_LINHA = re.compile(
    rf"^\s*(?P<data>\d{{2}}/\d{{2}}(?:/\d{{2,4}})?)?\s*(?P<hist>.*?)\s*(?P<v1>{_VAL})(?:\s+(?P<v2>{_VAL}))?\s*$",
    re.I)


def _sinal_explicito(txt: str) -> bool:
    t = txt.strip().upper()
    return t.startswith("-") or t.startswith("(") or t.endswith("-") or t.endswith("D") or t.endswith("C") or t.endswith("+")


def ler_extrato_pdf(nome: str, conteudo: bytes) -> Extrato:
    texto = texto_pdf(conteudo)
    avisos = []
    ini, fim = _periodo(texto)
    anos = re.findall(r"\d{2}/\d{2}/(\d{4})", texto)
    ano_padrao = (ini.year if ini else (int(max(set(anos), key=anos.count)) if anos else None))

    linhas_out = []
    saldo_anterior = None
    ultimo_saldo = None
    data_atual = None
    sinal_incerto = []
    for linha in texto.splitlines():
        crua = linha.strip()
        if not crua:
            continue
        m = _RE_LINHA.match(crua)
        if not m:
            # continuação de descrição do lançamento anterior
            if (linhas_out and len(crua) < 70 and not re.search(r"\d{2}/\d{2}", crua)
                    and not any(p in normalizar(crua) for p in ("PAGINA", "TOTAL", "SALDO", "EXTRATO",
                                                               "AGENCIA", "CONTA", "SAC", "OUVIDORIA"))
                    and linhas_out[-1].get("_continuavel")):
                linhas_out[-1]["descricao"] += " " + crua
                linhas_out[-1]["_continuavel"] = False
            continue
        hist = m.group("hist").strip()
        hist_n = normalizar(hist)
        if m.group("data"):
            d = parse_data(m.group("data"), ano_padrao)
            if d:
                data_atual = d
        if any(p in hist_n for p in _PAL_SALDO) or hist_n in ("SALDO",):
            v = parse_valor(m.group("v2") or m.group("v1"))
            if "ANTERIOR" in hist_n or "INICIAL" in hist_n:
                if saldo_anterior is None:
                    saldo_anterior = v
            ultimo_saldo = v
            if linhas_out and m.group("v2") is None:
                linhas_out[-1]["saldo"] = v
            continue
        if data_atual is None or not hist:
            continue
        # documento numérico isolado no histórico (ex.: "PIX ENVIADO 123456")
        doc = ""
        md = re.search(r"\b(\d{4,})\b\s*$", hist)
        if md:
            doc = md.group(1)
        v1 = parse_valor(m.group("v1"))
        v2 = parse_valor(m.group("v2")) if m.group("v2") else None
        if v1 is None:
            continue
        explicito = _sinal_explicito(m.group("v1"))
        if not explicito:
            if any(p in hist_n for p in _PAL_NEG):
                v1 = -abs(v1)
            elif any(p in hist_n for p in _PAL_POS):
                v1 = abs(v1)
            else:
                sinal_incerto.append(len(linhas_out))
        linhas_out.append({"data": data_atual, "descricao": hist, "documento": doc, "valor": v1,
                           "saldo": v2, "_continuavel": True})
        if v2 is not None:
            ultimo_saldo = v2

    # resolve sinais incertos pela variação de saldo
    saldo_prev = saldo_anterior
    for i, l in enumerate(linhas_out):
        if i in sinal_incerto and saldo_prev is not None and l["saldo"] is not None:
            if abs((saldo_prev - abs(l["valor"])) - l["saldo"]) < 0.01:
                l["valor"] = -abs(l["valor"])
            sinal_incerto.remove(i)
        if l["saldo"] is not None:
            saldo_prev = l["saldo"]
    if sinal_incerto:
        avisos.append(f"{len(sinal_incerto)} lançamento(s) sem sinal claro (crédito/débito) — "
                      "foram considerados créditos. Confira na tabela.")

    df = pd.DataFrame([{k: v for k, v in l.items() if not k.startswith("_")} for l in linhas_out],
                      columns=["data", "descricao", "documento", "valor", "saldo"])
    if df.empty:
        avisos.append("Nenhum lançamento reconhecido no PDF. Se for um PDF escaneado (imagem), "
                      "exporte o extrato em Excel/CSV.")
    contas = detectar_contas(texto[:3000])
    return _finalizar_extrato(nome, df, contas, saldo_anterior, ultimo_saldo, avisos)


def ler_extrato_tabela(nome: str, conteudo: bytes) -> Extrato:
    avisos = []
    chaves = ["data", "descricao", "documento", "valor", "debito", "credito", "saldo", "dc",
              "agencia", "conta"]
    for bruto in ler_tabela_bruta(nome, conteudo):
        achado = localizar_cabecalho(bruto, chaves, [["data"], ["valor", "debito", "credito"]])
        if not achado:
            continue
        idx, mapa = achado
        preambulo = _texto_preambulo(bruto, idx)
        dados = bruto.iloc[idx + 1:].reset_index(drop=True)
        ini, _ = _periodo(preambulo)
        anos = re.findall(r"\d{2}/\d{2}/(\d{4})", preambulo)
        ano_padrao = ini.year if ini else (int(anos[0]) if anos else None)

        def col(k):
            return dados.iloc[:, mapa[k]] if k in mapa else pd.Series([None] * len(dados))

        linhas = []
        saldo_anterior = None
        ultimo_saldo = None
        contas_col = set()
        for i in range(len(dados)):
            hist = "" if vazio(col("descricao")[i]) else str(col("descricao")[i]).strip()
            hist_n = normalizar(hist)
            d = parse_data(col("data")[i], ano_padrao)
            saldo = parse_valor(col("saldo")[i])
            if "valor" in mapa:
                v = parse_valor(col("valor")[i])
                if v is not None and "dc" in mapa:
                    dc = normalizar(col("dc")[i])
                    if dc.startswith("D"):
                        v = -abs(v)
                    elif dc.startswith("C"):
                        v = abs(v)
            else:
                deb = parse_valor(col("debito")[i])
                cred = parse_valor(col("credito")[i])
                v = None
                if deb not in (None, 0):
                    v = -abs(deb)
                elif cred not in (None, 0):
                    v = abs(cred)
            if any(p in hist_n for p in _PAL_SALDO):
                val = saldo if saldo is not None else v
                if ("ANTERIOR" in hist_n or "INICIAL" in hist_n) and saldo_anterior is None:
                    saldo_anterior = val
                if val is not None:
                    ultimo_saldo = val
                continue
            if d is None or v is None or v == 0:
                continue
            if "agencia" in mapa or "conta" in mapa:
                contas_col.add(f"Ag {col('agencia')[i] if 'agencia' in mapa else '?'} / Conta {col('conta')[i]}")
            doc = "" if vazio(col("documento")[i]) else str(col("documento")[i]).strip()
            linhas.append({"data": d, "descricao": hist, "documento": doc, "valor": v, "saldo": saldo})
            if saldo is not None:
                ultimo_saldo = saldo
        df = pd.DataFrame(linhas, columns=["data", "descricao", "documento", "valor", "saldo"])
        contas = sorted(contas_col) or detectar_contas(preambulo)
        return _finalizar_extrato(nome, df, contas, saldo_anterior, ultimo_saldo, avisos)
    return Extrato(nome, pd.DataFrame(columns=COLUNAS_EXTRATO), avisos=[
        "Não encontrei o cabeçalho do extrato (colunas de Data e Valor/Débito/Crédito)."])


def _finalizar_extrato(nome, df, contas, saldo_anterior, ultimo_saldo, avisos) -> Extrato:
    conta_id = contas[0] if len(contas) == 1 else (" | ".join(contas) if contas else nome)
    df = df.copy()
    df["conta"] = conta_id
    df["arquivo"] = nome
    df["documento"] = df["documento"].fillna("").astype(str)
    if not contas:
        avisos.append("Agência/conta não identificadas no arquivo (será usado o nome do arquivo).")
    return Extrato(nome, df[COLUNAS_EXTRATO], contas, saldo_anterior, ultimo_saldo, avisos)


def ler_extrato(nome: str, conteudo: bytes) -> Extrato:
    if _ext(nome) == "pdf":
        ext = ler_extrato_pdf(nome, conteudo)
        if ext.lancamentos.empty:  # tenta tabelas do PDF
            alt = ler_extrato_tabela(nome, conteudo)
            if not alt.lancamentos.empty:
                return alt
        return ext
    return ler_extrato_tabela(nome, conteudo)


# =========================================================================== planilhas
def _ler_planilha(nome, conteudo, chaves, obrigatorias) -> tuple[pd.DataFrame, dict, list[str], list]:
    """Retorna (dados, mapa de colunas, avisos, cabeçalho). Junta tabelas de várias páginas/abas compatíveis."""
    partes = []
    mapa_final = None
    cabecalho: list = []
    for bruto in ler_tabela_bruta(nome, conteudo):
        achado = localizar_cabecalho(bruto, chaves, obrigatorias)
        if achado:
            idx, mapa = achado
            if mapa_final is None:
                mapa_final = mapa
                cabecalho = bruto.iloc[idx].tolist()
                partes.append(bruto.iloc[idx + 1:])
            elif mapa == mapa_final:
                partes.append(bruto.iloc[idx + 1:])
        elif mapa_final is not None and bruto.shape[1] == partes[0].shape[1]:
            partes.append(bruto)  # continuação de tabela em outra página do PDF
    if mapa_final is None:
        return pd.DataFrame(), {}, [f"{nome}: não encontrei as colunas esperadas ({', '.join(chaves[:4])}...)."], []
    dados = pd.concat(partes, ignore_index=True)
    return dados, mapa_final, [], cabecalho


def _total_linha(*vals) -> bool:
    return any(normalizar(v).startswith(("TOTAL", "SUBTOTAL", "SOMA")) for v in vals if not vazio(v))


def ler_planilha_gastos(nome: str, conteudo: bytes) -> tuple[pd.DataFrame, list[str]]:
    chaves = ["data", "data_emissao", "descricao", "fornecedor", "cnpj", "cnpj_tomador", "rubrica",
              "documento", "tipo_doc", "valor", "forma_pagamento"]
    dados, mapa, avisos, _ = _ler_planilha(nome, conteudo, chaves, [["valor"], ["data", "data_emissao", "documento", "descricao", "fornecedor"]])
    cols = ["item", "data", "data_emissao", "descricao", "fornecedor", "cnpj", "cnpj_tomador", "rubrica",
            "documento", "tipo_doc", "valor", "forma_pagamento"]
    if dados.empty:
        return pd.DataFrame(columns=cols), avisos
    linhas = []
    for i in range(len(dados)):
        r = {k: (None if k not in mapa or vazio(dados.iloc[i, mapa[k]]) else dados.iloc[i, mapa[k]]) for k in chaves}
        if _total_linha(*r.values()):
            continue
        v = parse_valor(r["valor"])
        if v is None or v == 0:
            continue
        linhas.append({
            "item": len(linhas) + 1,
            "data": parse_data(r["data"]),
            "data_emissao": parse_data(r["data_emissao"]),
            "descricao": str(r["descricao"] or "").strip(),
            "fornecedor": str(r["fornecedor"] or "").strip(),
            "cnpj": str(r["cnpj"] or "").strip(),
            "cnpj_tomador": str(r["cnpj_tomador"] or "").strip(),
            "rubrica": str(r["rubrica"] or "").strip(),
            "documento": str(r["documento"] or "").strip(),
            "tipo_doc": str(r["tipo_doc"] or "").strip(),
            "valor": abs(v),
            "forma_pagamento": str(r["forma_pagamento"] or "").strip(),
        })
    faltando = [k for k in ("data", "documento", "cnpj") if k not in mapa]
    if faltando:
        avisos.append(f"Planilha de gastos sem coluna(s): {', '.join(faltando)} — verificações dependentes serão limitadas.")
    return pd.DataFrame(linhas, columns=cols), avisos


def ler_planilha_previsto(nome: str, conteudo: bytes) -> tuple[pd.DataFrame, list[str]]:
    chaves = ["rubrica", "descricao", "previsto", "executado"]
    dados, mapa, avisos, cab = _ler_planilha(nome, conteudo, chaves, [["previsto"]])
    if dados.empty:
        return pd.DataFrame(columns=["rubrica", "previsto", "executado"]), avisos
    col_rub = coluna_rotulo(cab, dados, mapa, ["previsto", "executado"])
    if col_rub is None:
        return pd.DataFrame(columns=["rubrica", "previsto", "executado"]), avisos + [
            f"{nome}: não encontrei a coluna com o nome das rubricas."]
    linhas = []
    for i in range(len(dados)):
        rub = _limpar(dados.iloc[i, col_rub])
        if not rub or _total_linha(rub):
            continue
        prev = parse_valor(dados.iloc[i, mapa["previsto"]])
        exe = parse_valor(dados.iloc[i, mapa["executado"]]) if "executado" in mapa else None
        if prev is None and exe is None:
            continue
        linhas.append({"rubrica": str(rub).strip(), "previsto": prev or 0.0, "executado": exe})
    return pd.DataFrame(linhas, columns=["rubrica", "previsto", "executado"]), avisos


def ler_planilha_rendimentos(nome: str, conteudo: bytes) -> tuple[pd.DataFrame, list[str]]:
    chaves = ["data", "descricao", "rendimento", "valor"]
    dados, mapa, avisos, _ = _ler_planilha(nome, conteudo, chaves, [["rendimento", "valor"]])
    if dados.empty:
        return pd.DataFrame(columns=["data", "descricao", "valor"]), avisos
    kv = "rendimento" if "rendimento" in mapa else "valor"
    linhas = []
    for i in range(len(dados)):
        vals = [dados.iloc[i, j] for j in mapa.values()]
        if _total_linha(*vals):
            continue
        v = parse_valor(dados.iloc[i, mapa[kv]])
        if v is None:
            continue
        linhas.append({
            "data": parse_data(dados.iloc[i, mapa["data"]]) if "data" in mapa else None,
            "descricao": str(dados.iloc[i, mapa["descricao"]]) if "descricao" in mapa else "",
            "valor": v,
        })
    return pd.DataFrame(linhas, columns=["data", "descricao", "valor"]), avisos


# =========================================================================== projeto
@dataclass
class Projeto:
    arquivo: str
    nome: str = ""
    texto: str = ""
    cnpjs: list[str] = field(default_factory=list)
    inicio: date | None = None
    fim: date | None = None
    valor_total: float | None = None
    rubricas: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["rubrica", "previsto"]))
    menciona_contrapartida: bool = False


def texto_docx(conteudo: bytes) -> tuple[str, list[pd.DataFrame]]:
    import docx

    d = docx.Document(io.BytesIO(conteudo))
    texto = "\n".join(p.text for p in d.paragraphs)
    tabelas = []
    for t in d.tables:
        linhas = [[c.text.strip() for c in r.cells] for r in t.rows]
        if len(linhas) >= 2:
            tabelas.append(pd.DataFrame(linhas))
            texto += "\n" + "\n".join(" | ".join(l) for l in linhas)
    return texto, tabelas


def ler_projeto(nome: str, conteudo: bytes) -> Projeto:
    ext = _ext(nome)
    tabelas: list[pd.DataFrame] = []
    if ext == "pdf":
        texto = texto_pdf(conteudo)
        tabelas = tabelas_pdf(conteudo)
    elif ext == "docx":
        texto, tabelas = texto_docx(conteudo)
    elif ext in ("xlsx", "xlsm", "xls", "csv"):
        tabelas = ler_tabela_bruta(nome, conteudo)
        texto = "\n".join(" | ".join(str(v) for v in r if not vazio(v))
                          for t in tabelas for r in t.itertuples(index=False))
    else:
        texto = conteudo.decode("utf-8", errors="ignore")

    p = Projeto(arquivo=nome, texto=texto)
    m = re.match(r"\s*projeto\s*-\s*(.+?)\.\w+$", nome, re.I)
    p.nome = m.group(1).strip() if m else nome.rsplit(".", 1)[0]
    p.cnpjs = list(dict.fromkeys(re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto)))
    tu = normalizar(texto)
    mv = re.search(r"VIGENCIA[^0-9]{0,60}(\d{2}/\d{2}/\d{4})\D{1,15}(\d{2}/\d{2}/\d{4})", tu) or \
        re.search(r"PERIODO DE EXECUCAO[^0-9]{0,60}(\d{2}/\d{2}/\d{4})\D{1,15}(\d{2}/\d{2}/\d{4})", tu) or \
        re.search(r"(\d{2}/\d{2}/\d{4})\s*(?:A|ATE|-)\s*(\d{2}/\d{2}/\d{4})", tu)
    if mv:
        p.inicio, p.fim = parse_data(mv.group(1)), parse_data(mv.group(2))
    mt = re.search(r"VALOR TOTAL[^0-9]{0,40}(\d{1,3}(?:\.\d{3})*,\d{2})", tu)
    if mt:
        p.valor_total = parse_valor(mt.group(1))
    p.menciona_contrapartida = "CONTRAPARTIDA" in tu

    for bruto in tabelas:
        achado = localizar_cabecalho(bruto, ["rubrica", "descricao", "previsto", "valor"],
                                     [["rubrica", "descricao"], ["previsto", "valor"]])
        if not achado:
            continue
        idx, mapa = achado
        kv = "previsto" if "previsto" in mapa else "valor"
        dados = bruto.iloc[idx + 1:].reset_index(drop=True)
        col_rub = coluna_rotulo(bruto.iloc[idx].tolist(), dados, mapa, [kv])
        if col_rub is None:
            continue
        linhas = []
        for i in range(len(dados)):
            rub, val = _limpar(dados.iloc[i, col_rub]), parse_valor(dados.iloc[i, mapa[kv]])
            if not rub or val is None or _total_linha(rub):
                continue
            linhas.append({"rubrica": rub, "previsto": val})
        if linhas:
            p.rubricas = pd.DataFrame(linhas)
            break
    return p


# =========================================================================== notas fiscais
COLUNAS_NF = ["arquivo", "tipo", "numero", "chave", "data_emissao", "cnpj_emitente",
              "cnpj_destinatario", "valor"]


def _xml_nf(nome: str, conteudo: bytes) -> dict | None:
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return None

    def achar(caminho_tags: list[str]):
        for el in raiz.iter():
            if el.tag.split("}")[-1] == caminho_tags[-1]:
                return el.text
        return None

    inf = next((el for el in raiz.iter() if el.tag.split("}")[-1] == "infNFe"), None)
    chave = so_digitos(inf.get("Id")) if inf is not None else ""
    emit = dest = None
    for el in raiz.iter():
        tag = el.tag.split("}")[-1]
        if tag == "emit" and emit is None:
            emit = next((c.text for c in el if c.tag.split("}")[-1] in ("CNPJ", "CPF")), None)
        if tag == "dest" and dest is None:
            dest = next((c.text for c in el if c.tag.split("}")[-1] in ("CNPJ", "CPF")), None)
    return {
        "arquivo": nome, "tipo": "NF-e" if inf is not None else "NFS-e",
        "numero": achar(["nNF"]) or achar(["Numero"]) or achar(["NumeroNFe"]) or "",
        "chave": chave,
        "data_emissao": parse_data(achar(["dhEmi"]) or achar(["dEmi"]) or achar(["DataEmissao"]) or achar(["DataEmissaoNFe"])),
        "cnpj_emitente": emit or achar(["CNPJPrestador"]) or "",
        "cnpj_destinatario": dest or achar(["CNPJTomador"]) or "",
        "valor": parse_valor(achar(["vNF"]) or achar(["ValorServicos"]) or achar(["ValorServicosNFe"])),
    }


def _pdf_nf(nome: str, conteudo: bytes) -> dict:
    texto = texto_pdf(conteudo)
    tu = normalizar(texto)
    chave = re.search(r"((?:\d{4}\s?){11})", texto)
    chave = so_digitos(chave.group(1)) if chave else ""
    cnpjs = re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    num = re.search(r"(?:N[º°O.]?\s*(?:DA\s+)?(?:NOTA|NFS-?E|NF-?E)?|NUMERO DA NOTA|NOTA FISCAL N[º°O.]?)\s*[:\-]?\s*(\d{1,9})", tu)
    data = re.search(r"(?:EMISSAO|DATA E HORA DA EMISSAO|DATA DE EMISSAO)[^0-9]{0,20}(\d{2}/\d{2}/\d{4})", tu)
    valor = re.search(r"VALOR (?:TOTAL DA NOTA|TOTAL DO SERVICO|TOTAL DOS SERVICOS|TOTAL|DA NOTA|LIQUIDO)[^0-9]{0,25}(\d{1,3}(?:\.\d{3})*,\d{2})", tu)
    tipo = "NFS-e" if ("PRESTADOR" in tu or "NFS-E" in tu or "SERVICO" in tu) else ("NFC-e" if "NFC-E" in tu or "CONSUMIDOR" in tu else "NF-e")
    return {
        "arquivo": nome, "tipo": tipo, "numero": num.group(1) if num else "",
        "chave": chave if len(chave) == 44 else "",
        "data_emissao": parse_data(data.group(1)) if data else None,
        "cnpj_emitente": cnpjs[0] if cnpjs else "",
        "cnpj_destinatario": cnpjs[1] if len(cnpjs) > 1 else "",
        "valor": parse_valor(valor.group(1)) if valor else None,
    }


def ler_nota_fiscal(nome: str, conteudo: bytes) -> dict | None:
    ext = _ext(nome)
    if ext == "xml":
        return _xml_nf(nome, conteudo)
    if ext == "pdf":
        return _pdf_nf(nome, conteudo)
    return {"arquivo": nome, "tipo": "imagem", "numero": "", "chave": "", "data_emissao": None,
            "cnpj_emitente": "", "cnpj_destinatario": "", "valor": None}
