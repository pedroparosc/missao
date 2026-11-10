"""Regras de verificação da prestação de contas (passos 1 a 4 do documento de referência)."""
from __future__ import annotations

import difflib
import urllib.parse
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .utils import (cnpj_valido, contem, cpf_valido, formatar_brl, formatar_cnpj, formatar_data,
                    normalizar, so_digitos, vazio)

URL_NFSE_SP = "https://nfe.prefeitura.sp.gov.br/publico/verificacao.aspx"
URL_NFE = ("https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx?tipoConsulta=resumo"
           "&tipoConteudo=7PhJ+gAVw2g=&AspxAutoDetectCookieSupport=1")
URL_SATED = "https://www.satedsp.org.br/"

# Classificações de lançamentos
SMF = "Entrada SMF (Fazenda)"
OUTRA_ENTRADA = "Outra entrada"
APLICACAO = "Aplicação (p/ investimento)"
RESGATE = "Resgate (do investimento)"
RENDIMENTO = "Rendimento"
IMPOSTO = "Imposto/IOF/IR"
TARIFA = "Tarifa bancária"
SAQUE = "Saque/espécie"
ESTORNO = "Estorno/devolução"
GASTO = "Gasto"
CLASSIFICACOES = [SMF, OUTRA_ENTRADA, APLICACAO, RESGATE, RENDIMENTO, IMPOSTO, TARIFA, SAQUE,
                  ESTORNO, GASTO]

# Os repasses aparecem no extrato como "Secretaria Municipal da Fazenda" (nome completo ou abreviado).
# A comparação é por trecho de texto, sem acento e sem diferenciar maiúsculas.
PAL_SMF_PADRAO = ["SECRETARIA MUNICIPAL DA FAZENDA", "SECRETARIA MUNICIPAL DE FAZENDA", "SEC MUN FAZ",
                  "SEC MUN DA FAZ", "SEC MUNIC FAZ", "SECR MUN FAZ", "SECRETARIA MUN FAZ", "SMF",
                  "FAZENDA MUNICIPAL"]
PAL_APLIC = ["APLIC", "APL.", "APL ", "INVEST", "POUP", "RENDE FACIL", "CDB", "FUNDO", "TRANSF P/ POUP",
             "TRANSF. P/ INVEST", "BB RF", "LCA", "LCI", "TESOURO"]
PAL_RESG = ["RESG", "RESGATE", "RESG.", "REND FACIL"]
PAL_REND = ["RENDIMENTO", "REND ", "REND.", "JUROS", "REMUNERACAO", "RENDIMENTOS"]
PAL_IMPOSTO = ["IOF", "IRRF", "IMPOSTO", "IR S/", "I.R."]
PAL_TARIFA = ["TARIFA", "TAR ", "TAR.", "CESTA", "PACOTE SERV", "MANUTENCAO CONTA", "ANUIDADE"]
PAL_SAQUE = ["SAQUE", "SAQ ", "ESPECIE", "SAQ."]
PAL_ESTORNO = ["ESTORNO", "DEVOL", "EST "]
PAL_CACHE = ["CACHE", "ARTISTA", "MUSICO", "ATOR", "ATRIZ", "TECNICO", "ILUMINADOR", "SONOPLASTA",
             "PRODUTOR", "DIRETOR", "BAILARINO", "DANCARINO", "CENOGRAFO", "FIGURINISTA", "MAQUIADOR",
             "OFICINEIRO", "ARTE-EDUCADOR", "MONITOR", "COORDENADOR", "HONORARIO", "REMUNERACAO",
             "PRESTACAO DE SERVICO ARTISTICO", "INTERPRETE", "CONTRARREGRA", "ROADIE"]

ERRO, ALERTA, INFO = "Erro", "Alerta", "Informação"


@dataclass
class Config:
    nome_projeto: str = ""
    cnpj_entidade: str = ""
    inicio: date | None = None
    fim: date | None = None
    palavras_smf: list[str] = field(default_factory=lambda: list(PAL_SMF_PADRAO))
    tolerancia_dias: int = 5
    max_entradas_smf: int = 3


@dataclass
class Ocorrencia:
    gravidade: str
    categoria: str
    descricao: str
    referencia: str = ""


@dataclass
class Resultado:
    config: Config
    ocorrencias: list[Ocorrencia] = field(default_factory=list)
    total_smf: float = 0.0
    total_gasto: float = 0.0
    total_rendimentos: float = 0.0
    total_impostos_invest: float = 0.0
    total_tarifas: float = 0.0
    saldo_corrente: float | None = None
    saldo_investimento: float | None = None
    saldo_corrente_origem: str = ""
    saldo_investimento_origem: str = ""
    entradas_smf: pd.DataFrame = field(default_factory=pd.DataFrame)
    conciliacao: pd.DataFrame = field(default_factory=pd.DataFrame)
    previsto_executado: pd.DataFrame = field(default_factory=pd.DataFrame)
    checklist_manual: pd.DataFrame = field(default_factory=pd.DataFrame)
    contas_corrente: list[str] = field(default_factory=list)
    contas_investimento: list[str] = field(default_factory=list)
    total_gasto_planilha: float = 0.0

    @property
    def diferenca(self) -> float:
        return self.total_smf - self.total_gasto

    def add(self, gravidade, categoria, descricao, referencia=""):
        self.ocorrencias.append(Ocorrencia(gravidade, categoria, descricao, referencia))

    def tabela_ocorrencias(self) -> pd.DataFrame:
        ordem = {ERRO: 0, ALERTA: 1, INFO: 2}
        df = pd.DataFrame([o.__dict__ for o in self.ocorrencias],
                          columns=["gravidade", "categoria", "descricao", "referencia"])
        if not df.empty:
            df = df.sort_values("gravidade", key=lambda s: s.map(ordem), kind="stable").reset_index(drop=True)
        return df


# =========================================================================== classificação
def classificar_corrente(desc: str, valor: float, palavras_smf) -> str:
    if valor > 0:
        if contem(desc, PAL_ESTORNO):
            return ESTORNO
        if contem(desc, PAL_RESG):
            return RESGATE
        if contem(desc, PAL_REND):
            return RENDIMENTO
        if contem(desc, palavras_smf):
            return SMF
        if contem(desc, PAL_APLIC):
            return RESGATE
        return OUTRA_ENTRADA
    if contem(desc, PAL_RESG):
        return RESGATE
    if contem(desc, PAL_APLIC):
        return APLICACAO
    if contem(desc, PAL_TARIFA):
        return TARIFA
    if contem(desc, PAL_IMPOSTO):
        return IMPOSTO
    if contem(desc, PAL_SAQUE):
        return SAQUE
    return GASTO


def classificar_investimento(desc: str, valor: float) -> str:
    if valor > 0:
        if contem(desc, PAL_REND):
            return RENDIMENTO
        if contem(desc, PAL_ESTORNO):
            return ESTORNO
        return APLICACAO
    if contem(desc, PAL_IMPOSTO):
        return IMPOSTO
    if contem(desc, PAL_TARIFA):
        return TARIFA
    if contem(desc, PAL_SAQUE):
        return SAQUE
    return RESGATE


def classificar(df: pd.DataFrame, tipo_conta: str, palavras_smf) -> pd.DataFrame:
    df = df.copy()
    if tipo_conta == "corrente":
        df["classificacao"] = [classificar_corrente(d, v, palavras_smf) for d, v in zip(df["descricao"], df["valor"])]
    else:
        df["classificacao"] = [classificar_investimento(d, v) for d, v in zip(df["descricao"], df["valor"])]
    return df


# =========================================================================== verificação
def _fora_periodo(d, cfg: Config) -> str | None:
    if not isinstance(d, date):
        return None
    if cfg.inicio and d < cfg.inicio:
        return "antes do início da vigência"
    if cfg.fim and d > cfg.fim:
        return "após o fim da vigência"
    return None


def _saldo(extratos_meta: list[dict], lanc: pd.DataFrame) -> tuple[float | None, str]:
    """Saldo final somado por conta. Usa o saldo informado no extrato; senão calcula."""
    if lanc.empty:
        finais = [m["saldo_final"] for m in extratos_meta if m.get("saldo_final") is not None]
        return (finais[-1], "informado no extrato") if finais else (None, "")
    total, origens = 0.0, []
    for conta, grupo in lanc.groupby("conta", sort=False):
        metas = [m for m in extratos_meta if m["conta"] == conta]
        finais = [m for m in metas if m.get("saldo_final") is not None]
        g = grupo.sort_values("data", kind="stable")
        com_saldo = g.dropna(subset=["saldo"])
        if not com_saldo.empty:
            total += float(com_saldo["saldo"].iloc[-1])
            origens.append("informado no extrato")
        elif finais:
            # último arquivo em ordem cronológica
            total += float(finais[-1]["saldo_final"])
            origens.append("informado no extrato")
        else:
            inicial = next((m["saldo_anterior"] for m in metas if m.get("saldo_anterior") is not None), 0.0)
            total += inicial + float(grupo["valor"].sum())
            origens.append("calculado (saldo inicial + movimentação)")
    return total, "; ".join(dict.fromkeys(origens))


def verificar(cfg: Config, corrente: pd.DataFrame, investimento: pd.DataFrame,
              meta_corrente: list[dict], meta_invest: list[dict], gastos: pd.DataFrame,
              previsto: pd.DataFrame, rendimentos_planilha: pd.DataFrame | None,
              notas: pd.DataFrame, rubricas_projeto: pd.DataFrame,
              menciona_contrapartida: bool = False) -> Resultado:
    r = Resultado(config=cfg)
    corrente = corrente.copy() if corrente is not None else pd.DataFrame()
    investimento = investimento.copy() if investimento is not None else pd.DataFrame()

    # ------------------------------------------------------------- contas (erro comum nº 5)
    r.contas_corrente = sorted({c for m in meta_corrente for c in (m["contas"] or [m["conta"]])})
    r.contas_investimento = sorted({c for m in meta_invest for c in (m["contas"] or [m["conta"]])})
    for nome, contas in (("conta corrente", r.contas_corrente), ("conta investimento", r.contas_investimento)):
        if len(contas) > 1:
            r.add(ERRO, "Extratos de mais de uma conta",
                  f"Os extratos da {nome} pertencem a {len(contas)} contas diferentes: " + "; ".join(contas) + ".")
    if not meta_corrente:
        r.add(ERRO, "Documentação", "Extrato da conta corrente específica não foi enviado.")
    if not meta_invest:
        r.add(ALERTA, "Documentação", "Extrato da conta de investimento não foi enviado — o recurso "
                                      "deve obrigatoriamente ser aplicado (SELIC/Poupança).")

    # ------------------------------------------------------------- entradas SMF (seção 4)
    if not corrente.empty:
        smf = corrente[corrente["classificacao"] == SMF].sort_values("data", kind="stable").reset_index(drop=True)
        r.entradas_smf = smf[["data", "descricao", "valor", "conta"]]
        r.total_smf = float(smf["valor"].sum())
        if smf.empty:
            r.add(ERRO, "Entradas da SMF", "Nenhuma entrada da SMF foi identificada no extrato da conta "
                  "corrente. Ajuste as palavras-chave ou a classificação manual dos lançamentos.")
        elif len(smf) > cfg.max_entradas_smf:
            extras = smf.iloc[cfg.max_entradas_smf:]
            lista = "; ".join(f"{formatar_data(d)} – {formatar_brl(v)}" for d, v in zip(extras["data"], extras["valor"]))
            r.add(ERRO, "Entradas da SMF acima do limite",
                  f"Foram identificadas {len(smf)} entradas da SMF (máximo {cfg.max_entradas_smf}). "
                  f"{len(extras)} entrada(s) a mais, totalizando {formatar_brl(extras['valor'].sum())}: {lista}.")
        for _, l in smf.iterrows():
            motivo = _fora_periodo(l["data"], cfg)
            if motivo:
                r.add(ALERTA, "Entradas da SMF", f"Entrada de {formatar_brl(l['valor'])} em {formatar_data(l['data'])} {motivo}.")

        outras = corrente[corrente["classificacao"] == OUTRA_ENTRADA]
        for _, l in outras.iterrows():
            r.add(ALERTA, "Pagamento cruzado / conta mista",
                  f"Crédito de outra origem na conta específica: {formatar_brl(l['valor'])} em "
                  f"{formatar_data(l['data'])} ({l['descricao']}). Verifique se não há mistura de recursos.",
                  l["arquivo"])

        # gastos efetivos
        saidas = corrente[corrente["classificacao"].isin([GASTO, TARIFA, SAQUE, IMPOSTO])]
        estornos = corrente[corrente["classificacao"] == ESTORNO]["valor"].sum()
        r.total_gasto = float(-saidas["valor"].sum() - estornos)
        r.total_tarifas = float(-corrente[corrente["classificacao"] == TARIFA]["valor"].sum())

        for _, l in corrente[corrente["classificacao"] == SAQUE].iterrows():
            r.add(ERRO, "Pagamento em espécie",
                  f"Saque/pagamento em espécie de {formatar_brl(-l['valor'])} em {formatar_data(l['data'])} "
                  f"({l['descricao']}) — exige justificativa legal e saque rastreado.", l["arquivo"])
        if r.total_tarifas > 0:
            r.add(ALERTA, "Tarifas bancárias",
                  f"Tarifas bancárias debitadas na conta específica: {formatar_brl(r.total_tarifas)}. "
                  "Verifique se são despesas admitidas pelo edital.")
        for _, l in saidas.iterrows():
            motivo = _fora_periodo(l["data"], cfg)
            if motivo:
                r.add(ERRO, "Despesa fora do prazo",
                      f"Débito de {formatar_brl(-l['valor'])} em {formatar_data(l['data'])} {motivo} ({l['descricao']}).",
                      l["arquivo"])

    # ------------------------------------------------------------- investimento / rendimentos
    rend_cc = float(corrente[corrente["classificacao"] == RENDIMENTO]["valor"].sum()) if not corrente.empty else 0.0
    if not investimento.empty:
        rend = investimento[investimento["classificacao"] == RENDIMENTO]
        r.total_rendimentos = float(rend["valor"].sum()) + rend_cc
        r.total_impostos_invest = float(-investimento[investimento["classificacao"] == IMPOSTO]["valor"].sum())
        if rend.empty:
            r.add(ALERTA, "Rendimentos", "Nenhum rendimento identificado no extrato de investimento. "
                  "Confirme se o recurso foi aplicado (SELIC/Poupança).")
        for _, l in investimento[investimento["classificacao"] == SAQUE].iterrows():
            r.add(ERRO, "Pagamento cruzado / conta mista",
                  f"Saída direta da conta de investimento sem passar pela conta corrente: "
                  f"{formatar_brl(-l['valor'])} em {formatar_data(l['data'])}.", l["arquivo"])
        # aplicações x resgates conferem com a conta corrente?
        if not corrente.empty:
            aplic_cc = float(-corrente[corrente["classificacao"] == APLICACAO]["valor"].sum())
            aplic_inv = float(investimento[investimento["classificacao"] == APLICACAO]["valor"].sum())
            resg_cc = float(corrente[corrente["classificacao"] == RESGATE]["valor"].sum())
            resg_inv = float(-investimento[investimento["classificacao"] == RESGATE]["valor"].sum())
            if abs(aplic_cc - aplic_inv) > 0.01:
                r.add(ALERTA, "Conciliação investimento",
                      f"Aplicações na conta corrente ({formatar_brl(aplic_cc)}) não batem com as entradas "
                      f"na conta investimento ({formatar_brl(aplic_inv)}). Diferença: {formatar_brl(aplic_cc - aplic_inv)}.")
            if abs(resg_cc - resg_inv) > 0.01:
                r.add(ALERTA, "Conciliação investimento",
                      f"Resgates creditados na conta corrente ({formatar_brl(resg_cc)}) não batem com os "
                      f"resgates da conta investimento ({formatar_brl(resg_inv)}). Diferença: {formatar_brl(resg_cc - resg_inv)}.")
    else:
        r.total_rendimentos = rend_cc

    if rendimentos_planilha is not None and not rendimentos_planilha.empty:
        tot_plan = float(rendimentos_planilha["valor"].sum())
        if abs(tot_plan - r.total_rendimentos) > 0.01:
            r.add(ERRO, "Rendimentos",
                  f"Planilha de rendimentos soma {formatar_brl(tot_plan)}, mas os extratos mostram "
                  f"{formatar_brl(r.total_rendimentos)} (diferença {formatar_brl(tot_plan - r.total_rendimentos)}).")
        else:
            r.add(INFO, "Rendimentos", f"Planilha de rendimentos confere com os extratos ({formatar_brl(tot_plan)}).")
    elif r.total_rendimentos > 0:
        r.add(ALERTA, "Rendimentos", "Há rendimentos nos extratos, mas a planilha de rendimentos não foi enviada.")

    if r.total_gasto > r.total_smf + r.total_rendimentos + 0.01:
        r.add(ERRO, "Saldo", f"Total gasto ({formatar_brl(r.total_gasto)}) supera o recebido da SMF somado aos "
              f"rendimentos ({formatar_brl(r.total_smf + r.total_rendimentos)}). Possível uso de recursos de outra fonte.")
    elif r.total_gasto > r.total_smf + 0.01:
        r.add(INFO, "Rendimentos", f"{formatar_brl(r.total_gasto - r.total_smf)} dos rendimentos foram "
              "utilizados no objeto do projeto (gasto acima do valor repassado pela SMF).")

    # ------------------------------------------------------------- saldos
    r.saldo_corrente, r.saldo_corrente_origem = _saldo(meta_corrente, corrente)
    r.saldo_investimento, r.saldo_investimento_origem = _saldo(meta_invest, investimento)

    # ------------------------------------------------------------- planilha de gastos
    if gastos is not None and not gastos.empty:
        r.total_gasto_planilha = float(gastos["valor"].sum())
        _verificar_documentos(r, cfg, gastos)
        r.conciliacao = _conciliar(r, cfg, corrente, gastos)
        if abs(r.total_gasto_planilha - r.total_gasto) > 0.01 and not corrente.empty:
            r.add(ERRO, "Conciliação bancária",
                  f"Total da planilha de gastos ({formatar_brl(r.total_gasto_planilha)}) difere do total de "
                  f"saídas do extrato ({formatar_brl(r.total_gasto)}). Diferença: "
                  f"{formatar_brl(r.total_gasto_planilha - r.total_gasto)}.")
    else:
        r.add(ERRO, "Documentação", "Planilha de gastos (resumo de cada gasto) não foi enviada.")

    # ------------------------------------------------------------- previsto x executado / nexo causal
    _verificar_orcamento(r, gastos, previsto, rubricas_projeto)

    # ------------------------------------------------------------- notas fiscais anexadas
    if notas is not None and not notas.empty:
        _verificar_notas(r, cfg, notas, gastos)

    if menciona_contrapartida:
        r.add(ALERTA, "Contrapartida", "O projeto menciona contrapartida. Verifique se a instituição "
              "comprovou a aplicação dos recursos próprios prometidos.")

    r.checklist_manual = _checklist(gastos, notas)
    return r


def _verificar_documentos(r: Resultado, cfg: Config, g: pd.DataFrame):
    cnpj_ent = so_digitos(cfg.cnpj_entidade)
    for _, l in g.iterrows():
        ref = f"Item {l['item']} – {l['descricao'] or l['fornecedor']} ({formatar_brl(l['valor'])})"
        for campo, rotulo in (("data_emissao", "Documento emitido"), ("data", "Pagamento")):
            motivo = _fora_periodo(l[campo], cfg)
            if motivo:
                r.add(ERRO, "Despesa fora do prazo", f"{rotulo} em {formatar_data(l[campo])}, {motivo}.", ref)
        doc = so_digitos(l["cnpj"])
        tipo = normalizar(l["tipo_doc"])
        if not doc:
            if "cnpj" in g.columns and g["cnpj"].astype(str).str.strip().ne("").any():
                r.add(ALERTA, "Ausência de identificação", "Fornecedor sem CNPJ/CPF informado.", ref)
        elif len(doc) == 14 and not cnpj_valido(doc):
            r.add(ERRO, "Ausência de identificação", f"CNPJ do fornecedor inválido: {l['cnpj']}.", ref)
        elif len(doc) == 11 and not cpf_valido(doc):
            r.add(ERRO, "Ausência de identificação", f"CPF do fornecedor inválido: {l['cnpj']}.", ref)
        elif len(doc) not in (11, 14):
            r.add(ERRO, "Ausência de identificação", f"CNPJ/CPF do fornecedor mal formatado: {l['cnpj']}.", ref)
        tom = so_digitos(l["cnpj_tomador"])
        if cnpj_ent and tom and tom != cnpj_ent:
            r.add(ERRO, "Ausência de identificação",
                  f"Documento emitido para {formatar_cnpj(tom)}, e não para a entidade ({formatar_cnpj(cnpj_ent)}).", ref)
        if "NFC" in tipo or "CUPOM" in tipo or "CONSUMIDOR" in tipo:
            r.add(ERRO, "Ausência de identificação", "Nota fiscal ao consumidor (NFC-e/cupom) — normalmente "
                  "não identifica o CNPJ da instituição.", ref)
        if "RPA" in tipo or "RECIBO" in tipo or (len(doc) == 11 and "NF" not in tipo):
            r.add(ALERTA, "Recibo / RPA", "Pagamento a pessoa física por recibo/RPA — verificar se é legalmente "
                  "permitido e se há recolhimento de INSS/ISS.", ref)
        if contem(l["forma_pagamento"], ["DINHEIRO", "ESPECIE"]):
            r.add(ERRO, "Pagamento em espécie", "Pagamento declarado em dinheiro/espécie.", ref)
        if not str(l["documento"]).strip():
            r.add(ALERTA, "Documentação", "Gasto sem número de documento fiscal/recibo.", ref)

    # duplicidade de notas
    g2 = g.assign(_doc=g["documento"].map(lambda x: so_digitos(x).lstrip("0")),
                  _cnpj=g["cnpj"].map(so_digitos))
    g2 = g2[g2["_doc"] != ""]
    for (doc, cnpj), grupo in g2.groupby(["_doc", "_cnpj"]):
        if len(grupo) > 1:
            itens = ", ".join(str(i) for i in grupo["item"])
            r.add(ERRO, "Nota fiscal duplicada",
                  f"Documento nº {doc}{' do CNPJ ' + formatar_cnpj(cnpj) if cnpj else ''} aparece "
                  f"{len(grupo)} vezes (itens {itens}), somando {formatar_brl(grupo['valor'].sum())}.")
    # sequência de notas do mesmo fornecedor
    dups = g[g.duplicated(subset=["fornecedor", "valor", "data"], keep=False) & g["fornecedor"].ne("")]
    for _, grupo in dups.groupby(["fornecedor", "valor", "data"], dropna=False):
        if grupo["documento"].map(so_digitos).nunique() > 1 or grupo["documento"].eq("").all():
            r.add(ALERTA, "Possível duplicidade",
                  f"{len(grupo)} gastos iguais ({formatar_brl(grupo['valor'].iloc[0])}) com {grupo['fornecedor'].iloc[0]} "
                  f"em {formatar_data(grupo['data'].iloc[0])} (itens {', '.join(map(str, grupo['item']))}).")


def _conciliar(r: Resultado, cfg: Config, corrente: pd.DataFrame, gastos: pd.DataFrame) -> pd.DataFrame:
    """Casa cada gasto da planilha com uma saída do extrato (valor igual e data próxima)."""
    if corrente.empty:
        return pd.DataFrame()
    saidas = corrente[corrente["classificacao"].isin([GASTO, TARIFA, SAQUE, IMPOSTO])].copy()
    saidas["abs"] = -saidas["valor"]
    livres = set(saidas.index)
    tol = cfg.tolerancia_dias
    pares: dict[int, int] = {}

    def dist(dg, de):
        if isinstance(dg, date) and isinstance(de, date):
            return abs((dg - de).days)
        return 0

    ordem = gastos.sort_values("data", key=lambda s: s.map(lambda d: d if isinstance(d, date) else date.max), kind="stable")
    # 1ª passada: valor exato e data dentro da tolerância
    for gi, g in ordem.iterrows():
        cand = [(dist(g["data"], saidas.at[ei, "data"]), ei) for ei in livres
                if abs(saidas.at[ei, "abs"] - g["valor"]) < 0.005 and dist(g["data"], saidas.at[ei, "data"]) <= tol]
        if cand:
            ei = min(cand)[1]
            pares[gi] = ei
            livres.discard(ei)
    # 2ª passada: valor exato sem restrição de data
    for gi, g in ordem.iterrows():
        if gi in pares:
            continue
        cand = [(dist(g["data"], saidas.at[ei, "data"]), ei) for ei in livres
                if abs(saidas.at[ei, "abs"] - g["valor"]) < 0.005]
        if cand:
            d, ei = min(cand)
            pares[gi] = ei
            livres.discard(ei)
            r.add(ALERTA, "Conciliação bancária",
                  f"Gasto de {formatar_brl(g['valor'])} da planilha (item {g['item']}, data {formatar_data(g['data'])}) "
                  f"foi encontrado no extrato com data divergente ({formatar_data(saidas.at[ei, 'data'])}, {d} dias de diferença).")
    # 3ª passada: mesmo período, valores diferentes (divergência)
    divergentes: dict[int, int] = {}
    for gi, g in ordem.iterrows():
        if gi in pares:
            continue
        cand = []
        for ei in livres:
            e = saidas.loc[ei]
            if dist(g["data"], e["data"]) <= tol and g["valor"] > 0 and abs(e["abs"] - g["valor"]) / g["valor"] <= 0.15:
                mesmo_doc = so_digitos(g["documento"]) and so_digitos(g["documento"]) in so_digitos(e["documento"] + e["descricao"])
                cand.append((0 if mesmo_doc else 1, abs(e["abs"] - g["valor"]), ei))
        if cand:
            ei = min(cand)[2]
            divergentes[gi] = ei
            livres.discard(ei)
            e = saidas.loc[ei]
            r.add(ERRO, "Valor divergente",
                  f"Item {g['item']} ({g['descricao'] or g['fornecedor']}): planilha informa {formatar_brl(g['valor'])}, "
                  f"extrato mostra {formatar_brl(e['abs'])} em {formatar_data(e['data'])} "
                  f"(diferença {formatar_brl(g['valor'] - e['abs'])}).", e["arquivo"])

    linhas = []
    for gi, g in gastos.iterrows():
        ei = pares.get(gi, divergentes.get(gi))
        e = saidas.loc[ei] if ei is not None else None
        status = "Conciliado" if gi in pares else ("Valor divergente" if gi in divergentes else "Não encontrado no extrato")
        if e is not None and gi in pares:
            dg, de = so_digitos(g["documento"]), so_digitos(e["documento"])
            if dg and de and dg.lstrip("0") != de.lstrip("0") and dg not in so_digitos(e["descricao"]):
                status = "Conciliado (nº transação divergente)"
                r.add(ALERTA, "Número de transação divergente",
                      f"Item {g['item']}: documento na planilha {g['documento']}, no extrato {e['documento']} "
                      f"({formatar_brl(g['valor'])} em {formatar_data(e['data'])}).")
        linhas.append({
            "item": g["item"], "data_planilha": g["data"], "descricao_planilha": g["descricao"] or g["fornecedor"],
            "documento": g["documento"], "valor_planilha": g["valor"],
            "data_extrato": e["data"] if e is not None else None,
            "historico_extrato": e["descricao"] if e is not None else "",
            "valor_extrato": e["abs"] if e is not None else None, "status": status,
        })
        if e is None:
            r.add(ERRO, "Conciliação bancária",
                  f"Item {g['item']} ({g['descricao'] or g['fornecedor']}, {formatar_brl(g['valor'])}, "
                  f"{formatar_data(g['data'])}) não foi encontrado no extrato da conta corrente.")
    for ei in sorted(livres, key=lambda i: saidas.at[i, "data"] or date.min):
        e = saidas.loc[ei]
        linhas.append({
            "item": None, "data_planilha": None, "descricao_planilha": "", "documento": "",
            "valor_planilha": None, "data_extrato": e["data"], "historico_extrato": e["descricao"],
            "valor_extrato": e["abs"], "status": "Sem comprovação na planilha",
        })
        r.add(ERRO, "Conciliação bancária",
              f"Saída de {formatar_brl(e['abs'])} em {formatar_data(e['data'])} ({e['descricao']}) não consta "
              "na planilha de gastos.", e["arquivo"])
    return pd.DataFrame(linhas)


def _casar_rubrica(nome: str, lista: list[str]) -> str | None:
    n = normalizar(nome)
    if not n:
        return None
    norm = {normalizar(x): x for x in lista}
    if n in norm:
        return norm[n]
    for k, v in norm.items():
        if n in k or k in n:
            return v
    m = difflib.get_close_matches(n, list(norm), n=1, cutoff=0.75)
    return norm[m[0]] if m else None


def _verificar_orcamento(r: Resultado, gastos, previsto: pd.DataFrame, rubricas_projeto: pd.DataFrame):
    base = previsto if previsto is not None and not previsto.empty else None
    if base is None and rubricas_projeto is not None and not rubricas_projeto.empty:
        base = rubricas_projeto.assign(executado=None)
    if base is None:
        r.add(ALERTA, "Nexo causal", "Sem planilha de previsto x executado nem rubricas no arquivo do projeto: "
              "a adequação orçamentária deve ser conferida manualmente.")
        return
    base = base.copy()
    tem_rubrica = gastos is not None and not gastos.empty and gastos["rubrica"].astype(str).str.strip().ne("").any()
    exec_calc = {}
    if tem_rubrica:
        rubricas = base["rubrica"].tolist()
        for _, g in gastos.iterrows():
            alvo = _casar_rubrica(g["rubrica"], rubricas)
            if alvo is None:
                r.add(ERRO, "Nexo causal",
                      f"Item {g['item']} ({g['descricao'] or g['fornecedor']}, {formatar_brl(g['valor'])}) está na "
                      f"rubrica \"{g['rubrica'] or '(vazia)'}\", que não consta no plano de trabalho/orçamento aprovado.")
            else:
                exec_calc[alvo] = exec_calc.get(alvo, 0.0) + g["valor"]
    base["executado_planilha_gastos"] = base["rubrica"].map(lambda x: exec_calc.get(x)) if tem_rubrica else None
    base["executado_final"] = [
        e if e is not None and not pd.isna(e) else (c if c is not None and not pd.isna(c) else 0.0)
        for e, c in zip(base["executado"], base["executado_planilha_gastos"])]
    base["diferenca"] = base["previsto"] - base["executado_final"]
    base["situacao"] = base["diferenca"].map(lambda d: "Excedente" if d < -0.01 else ("Economia" if d > 0.01 else "Conforme"))
    r.previsto_executado = base

    for _, l in base.iterrows():
        if l["situacao"] == "Excedente":
            pct = (-l["diferenca"] / l["previsto"] * 100) if l["previsto"] else 0
            r.add(ALERTA, "Previsto x executado",
                  f"Rubrica \"{l['rubrica']}\": executado {formatar_brl(l['executado_final'])} supera o previsto "
                  f"{formatar_brl(l['previsto'])} em {formatar_brl(-l['diferenca'])} ({pct:.1f}%).")
        e, c = l["executado"], l["executado_planilha_gastos"]
        if tem_rubrica and e is not None and not pd.isna(e) and abs(e - (c or 0)) > 0.01:
            r.add(ERRO, "Previsto x executado",
                  f"Rubrica \"{l['rubrica']}\": planilha previsto x executado informa {formatar_brl(e)}, mas a "
                  f"planilha de gastos soma {formatar_brl(c or 0)}.")
    economia = base.loc[base["situacao"] == "Economia", "diferenca"].sum()
    excesso = -base.loc[base["situacao"] == "Excedente", "diferenca"].sum()
    r.add(INFO, "Previsto x executado",
          f"Total previsto {formatar_brl(base['previsto'].sum())}; executado {formatar_brl(base['executado_final'].sum())}; "
          f"economias {formatar_brl(economia)}; excedentes {formatar_brl(excesso)}.")


def _verificar_notas(r: Resultado, cfg: Config, notas: pd.DataFrame, gastos):
    cnpj_ent = so_digitos(cfg.cnpj_entidade)
    for _, n in notas.iterrows():
        ref = n["arquivo"]
        motivo = _fora_periodo(n["data_emissao"], cfg)
        if motivo:
            r.add(ERRO, "Despesa fora do prazo", f"Nota fiscal emitida em {formatar_data(n['data_emissao'])}, {motivo}.", ref)
        dest = so_digitos(n["cnpj_destinatario"])
        if cnpj_ent and dest and dest != cnpj_ent:
            r.add(ERRO, "Ausência de identificação",
                  f"Nota emitida para {formatar_cnpj(dest)}, não para a entidade ({formatar_cnpj(cnpj_ent)}).", ref)
        if cnpj_ent and not dest and n["tipo"] != "imagem":
            r.add(ALERTA, "Ausência de identificação", "Não foi possível identificar o CNPJ do tomador/destinatário na nota.", ref)
        if n["tipo"] == "NFC-e":
            r.add(ERRO, "Ausência de identificação", "Nota fiscal ao consumidor (NFC-e).", ref)
        if n["cnpj_emitente"] and not cnpj_valido(n["cnpj_emitente"]) and not cpf_valido(n["cnpj_emitente"]):
            r.add(ERRO, "Ausência de identificação", f"CNPJ do emitente inválido: {n['cnpj_emitente']}.", ref)
        # nota consta na planilha?
        if gastos is not None and not gastos.empty and n["numero"]:
            num = str(n["numero"]).lstrip("0")
            achou = gastos[gastos["documento"].map(lambda d: so_digitos(d).lstrip("0") == num)]
            if achou.empty:
                r.add(ALERTA, "Documentação", f"Nota nº {n['numero']} anexada não aparece na planilha de gastos.", ref)
            elif n["valor"] is not None and all(abs(v - n["valor"]) > 0.01 for v in achou["valor"]):
                r.add(ERRO, "Valor divergente",
                      f"Nota nº {n['numero']} tem valor {formatar_brl(n['valor'])}, planilha informa "
                      f"{', '.join(formatar_brl(v) for v in achou['valor'])}.", ref)
    nums = notas[notas["numero"].astype(str).str.strip() != ""]
    for (num, em), grupo in nums.groupby([nums["numero"].astype(str).str.lstrip("0"), nums["cnpj_emitente"].map(so_digitos)]):
        if len(grupo) > 1:
            r.add(ERRO, "Nota fiscal duplicada", f"Nota nº {num} anexada {len(grupo)} vezes: {', '.join(grupo['arquivo'])}.")


def _checklist(gastos, notas) -> pd.DataFrame:
    """Itens que exigem conferência humana: autenticidade das notas e economicidade."""
    linhas = []
    if notas is not None and not notas.empty:
        for _, n in notas.iterrows():
            url = URL_NFSE_SP if n["tipo"] == "NFS-e" else URL_NFE
            linhas.append({"tipo": "Autenticidade da nota fiscal",
                           "item": f"{n['tipo']} nº {n['numero'] or '?'} ({n['arquivo']})",
                           "dados_para_consulta": (f"Chave: {n['chave']}" if n["chave"] else
                                                   f"CNPJ prestador: {formatar_cnpj(n['cnpj_emitente'])}"),
                           "link": url})
    if gastos is not None and not gastos.empty:
        for _, g in gastos.iterrows():
            texto = f"{g['descricao']} {g['rubrica']} {g['fornecedor']}"
            termo = g["descricao"] or g["rubrica"] or g["fornecedor"]
            if not termo:
                continue
            if contem(texto, PAL_CACHE):
                linhas.append({"tipo": "Economicidade – remuneração (SATED SP)",
                               "item": f"Item {g['item']} – {termo} ({formatar_brl(g['valor'])})",
                               "dados_para_consulta": "Comparar com piso/tabela de cachês do SATED SP",
                               "link": URL_SATED})
            else:
                q = urllib.parse.quote_plus(f"preço {termo}")
                linhas.append({"tipo": "Economicidade – preço de mercado",
                               "item": f"Item {g['item']} – {termo} ({formatar_brl(g['valor'])})",
                               "dados_para_consulta": "Comparar com preços de mercado",
                               "link": f"https://www.google.com/search?q={q}"})
    return pd.DataFrame(linhas, columns=["tipo", "item", "dados_para_consulta", "link"])
