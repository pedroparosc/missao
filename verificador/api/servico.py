"""Serviço de análise: orquestra o núcleo de domínio e o repositório.

Fluxo (espelha o `app.py` do Streamlit):

1. **Leitura** (`ler_documentos`): cada campo de upload é lido pela função correspondente do
   núcleo; erros de leitura viram *avisos* (não interrompem a análise).
2. **Parâmetros** (`montar_parametros`): o que o cliente não informou (nome, CNPJ, vigência)
   é completado com o que foi extraído do arquivo "projeto - [nome]" — igual ao
   pré-preenchimento da barra lateral.
3. **Classificação**: `verificacoes.classificar` rotula cada lançamento (Entrada SMF, Gasto...).
   O cliente pode enviar lançamentos já revisados, que substituem a classificação automática.
4. **Verificação** (`executar`): `verificacoes.verificar` aplica os Passos 1–3.
5. **Persistência**: insumos (JSON), resultado e arquivos originais vão para o repositório.

Após correções (lançamentos ou parâmetros), `reprocessar` refaz os passos 3–5 a partir
dos insumos salvos, sem reler os arquivos.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from verificador import (carregar_extratos, carregar_notas, ler_planilha_gastos, ler_planilha_previsto,
                         ler_planilha_rendimentos, ler_projeto)
from verificador.leitores import COLUNAS_EXTRATO, COLUNAS_NF
from verificador.relatorio import gerar_docx, gerar_markdown
from verificador.utils import cnpj_valido, formatar_cnpj
from verificador.verificacoes import ALERTA, ERRO, INFO, Config, Resultado, classificar, verificar

from .armazenamento import Repositorio
from .serializacao import df_para_json, json_para_df, registros, valor_json


# =========================================================================== erros de domínio
class ErroServico(Exception):
    """Erro previsto do serviço; `status` é o código HTTP correspondente."""
    status = 400

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class AnaliseNaoEncontrada(ErroServico):
    status = 404


class ArquivoNaoSuportado(ErroServico):
    status = 415


class ArquivoGrandeDemais(ErroServico):
    status = 413


class DadosInsuficientes(ErroServico):
    status = 422


# =========================================================================== campos de upload
@dataclass(frozen=True)
class CampoUpload:
    extensoes: frozenset[str]
    multiplo: bool
    descricao: str


# Mesmos campos e extensões dos `st.file_uploader` do app.py.
CAMPOS_ARQUIVO: dict[str, CampoUpload] = {
    "projeto": CampoUpload(frozenset({"pdf", "docx", "xlsx", "xls", "csv", "txt"}), False,
                           "Arquivo do projeto (“projeto - [nome do projeto]”)"),
    "extratos_corrente": CampoUpload(frozenset({"pdf", "csv", "xlsx", "xls"}), True,
                                     "Extratos da conta corrente específica"),
    "extratos_investimento": CampoUpload(frozenset({"pdf", "csv", "xlsx", "xls"}), True,
                                         "Extratos da conta investimento"),
    "planilha_gastos": CampoUpload(frozenset({"xlsx", "xls", "csv", "pdf"}), False,
                                   "Planilha de gastos (resumo de cada gasto)"),
    "planilha_previsto": CampoUpload(frozenset({"xlsx", "xls", "csv", "pdf"}), False,
                                     "Planilha previsto x executado (opcional)"),
    "planilha_rendimentos": CampoUpload(frozenset({"xlsx", "xls", "csv", "pdf"}), False,
                                        "Planilha de rendimentos da aplicação (opcional)"),
    "notas_fiscais": CampoUpload(frozenset({"xml", "pdf", "png", "jpg", "jpeg"}), True,
                                 "Notas fiscais anexadas (opcional)"),
}

Arquivos = dict[str, list[tuple[str, bytes]]]  # campo -> [(nome, conteúdo), ...]


def validar_arquivos(arquivos: Arquivos, max_bytes: int) -> None:
    """Confere campo, quantidade, extensão e tamanho de cada arquivo enviado."""
    for campo, lista in arquivos.items():
        regra = CAMPOS_ARQUIVO.get(campo)
        if regra is None:
            raise DadosInsuficientes(f"Campo de arquivo desconhecido: {campo}.")
        if len(lista) > 1 and not regra.multiplo:
            raise DadosInsuficientes(f"O campo '{campo}' aceita apenas um arquivo.")
        for nome, conteudo in lista:
            ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
            if ext not in regra.extensoes:
                raise ArquivoNaoSuportado(f"{nome}: extensão '.{ext}' não aceita em '{campo}' "
                                          f"(aceitas: {', '.join(sorted(regra.extensoes))}).")
            if len(conteudo) > max_bytes:
                raise ArquivoGrandeDemais(f"{nome}: {len(conteudo) / 1048576:.1f} MB excede o limite de "
                                          f"{max_bytes // 1048576} MB por arquivo.")
    if not any(arquivos.get(c) for c in ("extratos_corrente", "extratos_investimento", "planilha_gastos")):
        # Mesma regra do frontend: "Envie ao menos os extratos e a planilha de gastos".
        raise DadosInsuficientes("Envie ao menos um extrato (corrente ou investimento) ou a planilha de gastos.")


# =========================================================================== leitura
def _projeto_json(p) -> dict | None:
    if p is None:
        return None
    return {"arquivo": p.arquivo, "nome": p.nome, "cnpjs": list(p.cnpjs), "inicio": valor_json(p.inicio),
            "fim": valor_json(p.fim), "valor_total": p.valor_total,
            "menciona_contrapartida": bool(p.menciona_contrapartida), "rubricas": df_para_json(p.rubricas)}


def ler_documentos(arquivos: Arquivos) -> dict[str, Any]:
    """Lê todos os documentos com o núcleo e devolve os **insumos** serializados + avisos.

    Os lançamentos ainda não estão classificados aqui (a classificação depende dos parâmetros).
    """
    avisos: list[str] = []
    um = lambda campo: (arquivos.get(campo) or [None])[0]  # noqa: E731 — primeiro arquivo do campo

    projeto = None
    if (arq := um("projeto")) is not None:
        try:
            projeto = ler_projeto(*arq)
        except Exception as exc:  # documento corrompido/formato inesperado: vira aviso, como no app
            avisos.append(f"{arq[0]}: erro ao ler o projeto ({exc}).")

    cc, meta_cc, av = carregar_extratos(arquivos.get("extratos_corrente") or [])
    avisos += av
    inv, meta_inv, av = carregar_extratos(arquivos.get("extratos_investimento") or [])
    avisos += av

    def planilha(campo, leitor):
        arq = um(campo)
        if arq is None:
            return None
        try:
            df, av_ = leitor(*arq)
        except Exception as exc:
            avisos.append(f"{arq[0]}: erro ao ler ({exc}).")
            return None
        avisos.extend(av_)
        return df

    gastos = planilha("planilha_gastos", ler_planilha_gastos)
    previsto = planilha("planilha_previsto", ler_planilha_previsto)
    rendimentos = planilha("planilha_rendimentos", ler_planilha_rendimentos)
    notas, av = carregar_notas(arquivos.get("notas_fiscais") or []) if arquivos.get("notas_fiscais") \
        else (pd.DataFrame(columns=COLUNAS_NF), [])
    avisos += av

    return {
        "corrente": df_para_json(cc), "investimento": df_para_json(inv),
        "meta_corrente": [{k: valor_json(v) if not isinstance(v, list) else v for k, v in m.items()} for m in meta_cc],
        "meta_investimento": [{k: valor_json(v) if not isinstance(v, list) else v for k, v in m.items()} for m in meta_inv],
        "gastos": df_para_json(gastos), "previsto": df_para_json(previsto),
        "rendimentos": df_para_json(rendimentos), "notas": df_para_json(notas),
        "projeto": _projeto_json(projeto), "avisos_leitura": avisos,
    }


# =========================================================================== parâmetros
def montar_parametros(informados: dict[str, Any], projeto: dict | None) -> dict[str, Any]:
    """Completa os parâmetros não informados com os dados do arquivo do projeto (RF-02).

    Regra igual à da barra lateral do app: nome do projeto, primeiro CNPJ **válido** encontrado
    e vigência (início/fim).
    """
    p = dict(informados)
    if projeto:
        if not p.get("nome_projeto"):
            p["nome_projeto"] = projeto.get("nome") or ""
        if not p.get("cnpj_entidade"):
            validos = [c for c in projeto.get("cnpjs") or [] if cnpj_valido(c)]
            p["cnpj_entidade"] = formatar_cnpj(validos[0]) if validos else ""
        if not p.get("inicio") and projeto.get("inicio"):
            p["inicio"] = projeto["inicio"]
        if not p.get("fim") and projeto.get("fim"):
            p["fim"] = projeto["fim"]
    return {k: valor_json(v) if isinstance(v, date) else v for k, v in p.items()}


def _config(parametros: dict[str, Any]) -> Config:
    """Converte os parâmetros persistidos (JSON) na `Config` do núcleo."""
    d = lambda v: date.fromisoformat(v) if isinstance(v, str) and v else (v or None)  # noqa: E731
    return Config(nome_projeto=parametros.get("nome_projeto") or "",
                  cnpj_entidade=parametros.get("cnpj_entidade") or "",
                  inicio=d(parametros.get("inicio")), fim=d(parametros.get("fim")),
                  palavras_smf=list(parametros.get("palavras_smf") or []),
                  tolerancia_dias=int(parametros.get("tolerancia_dias", 5)),
                  max_entradas_smf=int(parametros.get("max_entradas_smf", 3)))


# =========================================================================== verificação
def _extrato_df(obj: dict | None) -> pd.DataFrame:
    df = json_para_df(obj)
    if df is None or df.empty:
        return pd.DataFrame(columns=[*COLUNAS_EXTRATO, "classificacao"])
    for c in ("descricao", "documento", "conta", "arquivo"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)
    df["valor"] = df["valor"].astype(float)
    df["saldo"] = pd.to_numeric(df["saldo"], errors="coerce")
    return df


def classificar_insumos(insumos: dict, palavras_smf: list[str]) -> dict:
    """Aplica a classificação automática do núcleo aos lançamentos das duas contas."""
    novo = dict(insumos)
    for chave, tipo in (("corrente", "corrente"), ("investimento", "investimento")):
        df = _extrato_df(insumos.get(chave))
        novo[chave] = df_para_json(classificar(df, tipo, palavras_smf) if not df.empty else df)
    return novo


def executar(parametros: dict, insumos: dict) -> Resultado:
    """Roda `verificacoes.verificar` com os insumos persistidos — mesma chamada do app.py."""
    projeto = insumos.get("projeto") or {}
    rubricas = json_para_df(projeto.get("rubricas")) if projeto else None
    notas = json_para_df(insumos.get("notas"))
    return verificar(
        _config(parametros), _extrato_df(insumos.get("corrente")), _extrato_df(insumos.get("investimento")),
        insumos.get("meta_corrente") or [], insumos.get("meta_investimento") or [],
        json_para_df(insumos.get("gastos")), json_para_df(insumos.get("previsto")),
        json_para_df(insumos.get("rendimentos")),
        notas if notas is not None else pd.DataFrame(columns=COLUNAS_NF),
        rubricas, bool(projeto.get("menciona_contrapartida")) if projeto else False)


def resultado_json(r: Resultado) -> dict[str, Any]:
    """Serializa o `Resultado` do núcleo para persistência e resposta da API."""
    oc = r.tabela_ocorrencias()
    n = lambda g: sum(o.gravidade == g for o in r.ocorrencias)  # noqa: E731
    return {
        "resumo": {k: (v + 0.0 if isinstance(v, float) else v) for k, v in {  # +0.0 normaliza "-0.0"
            "total_smf": r.total_smf, "n_entradas_smf": int(len(r.entradas_smf)),
            "total_gasto": r.total_gasto, "total_rendimentos": r.total_rendimentos, "diferenca": r.diferenca,
            "total_gasto_planilha": r.total_gasto_planilha, "total_impostos_invest": r.total_impostos_invest,
            "total_tarifas": r.total_tarifas,
            "saldo_corrente": valor_json(r.saldo_corrente), "saldo_corrente_origem": r.saldo_corrente_origem,
            "saldo_investimento": valor_json(r.saldo_investimento),
            "saldo_investimento_origem": r.saldo_investimento_origem,
            "n_erros": n(ERRO), "n_alertas": n(ALERTA), "n_informacoes": n(INFO),
        }.items()},
        "contas_corrente": list(r.contas_corrente), "contas_investimento": list(r.contas_investimento),
        "ocorrencias": registros(oc),
        "entradas_smf": registros(r.entradas_smf), "conciliacao": registros(r.conciliacao),
        "previsto_executado": registros(r.previsto_executado), "checklist_manual": registros(r.checklist_manual),
    }


# =========================================================================== serviço
class ServicoAnalises:
    """Casos de uso expostos pelas rotas. Não conhece HTTP — só o repositório e o núcleo."""

    def __init__(self, repo: Repositorio, max_upload_bytes: int):
        self.repo = repo
        self.max_upload_bytes = max_upload_bytes

    # -------------------------------------------------------------- consulta
    def _obter(self, id_: str) -> dict:
        a = self.repo.obter(id_)
        if a is None:
            raise AnaliseNaoEncontrada(f"Análise '{id_}' não encontrada.")
        return a

    def detalhe(self, id_: str) -> dict[str, Any]:
        """Monta o `AnaliseDetalhe` (todas as abas do frontend)."""
        a = self._obter(id_)
        ins = a["insumos"]
        proj = ins.get("projeto")
        if proj:
            proj = {**proj, "rubricas": (proj.get("rubricas") or {}).get("registros", [])}
        tab = lambda chave: (ins.get(chave) or {}).get("registros", [])  # noqa: E731
        return {
            "id": a["id"], "criado_em": a["criado_em"], "atualizado_em": a["atualizado_em"],
            "parametros": a["parametros"], **a["resultado"],
            "avisos_leitura": ins.get("avisos_leitura", []),
            "arquivos": self.repo.listar_arquivos(id_), "projeto": proj,
            "dados_lidos": {"gastos": tab("gastos"), "previsto": tab("previsto"),
                            "rendimentos": tab("rendimentos"), "notas": tab("notas")},
        }

    def listar(self, limite: int, deslocamento: int) -> dict[str, Any]:
        total, linhas = self.repo.listar(limite, deslocamento)
        itens = []
        for l in linhas:
            res = l["resultado"]["resumo"]
            itens.append({k: l[k] for k in ("id", "criado_em", "atualizado_em", "nome_projeto", "cnpj_entidade",
                                            "n_erros", "n_alertas")}
                         | {k: res[k] for k in ("total_smf", "total_gasto", "total_rendimentos", "diferenca")})
        return {"total": total, "itens": itens}

    def lancamentos(self, id_: str) -> dict[str, list[dict]]:
        ins = self._obter(id_)["insumos"]
        return {"corrente": (ins.get("corrente") or {}).get("registros", []),
                "investimento": (ins.get("investimento") or {}).get("registros", [])}

    # -------------------------------------------------------------- escrita
    def _salvar_resultado(self, id_: str, parametros: dict, insumos: dict) -> None:
        res = resultado_json(executar(parametros, insumos))
        self.repo.atualizar(id_, parametros=parametros, insumos=insumos, resultado=res,
                            nome_projeto=parametros.get("nome_projeto") or "",
                            cnpj_entidade=parametros.get("cnpj_entidade") or "",
                            n_erros=res["resumo"]["n_erros"], n_alertas=res["resumo"]["n_alertas"])

    @staticmethod
    def _lancamentos_json(lista: list[dict]) -> dict:
        df = pd.DataFrame(lista, columns=[*COLUNAS_EXTRATO, "classificacao"])
        return df_para_json(df)

    def criar(self, arquivos: Arquivos, parametros: dict[str, Any],
              lancamentos: dict[str, list[dict] | None] | None = None) -> str:
        """Cria uma análise a partir dos arquivos enviados e devolve o id.

        `lancamentos` (opcional) traz a classificação já revisada pelo usuário no frontend;
        quando presente, substitui a classificação automática da respectiva conta.
        """
        arquivos = {c: l for c, l in arquivos.items() if l}
        validar_arquivos(arquivos, self.max_upload_bytes)
        insumos = ler_documentos(arquivos)
        parametros = montar_parametros(parametros, insumos.get("projeto"))
        insumos = classificar_insumos(insumos, parametros.get("palavras_smf") or [])
        for conta, lista in (lancamentos or {}).items():
            if lista is not None:
                insumos[conta] = self._lancamentos_json(lista)
        res = resultado_json(executar(parametros, insumos))

        id_ = uuid.uuid4().hex
        self.repo.criar(id_, parametros, insumos, res, nome_projeto=parametros.get("nome_projeto") or "",
                        cnpj_entidade=parametros.get("cnpj_entidade") or "",
                        n_erros=res["resumo"]["n_erros"], n_alertas=res["resumo"]["n_alertas"])
        try:
            for campo, lista in arquivos.items():
                for i, (nome, conteudo) in enumerate(lista):
                    self.repo.salvar_arquivo(id_, campo, nome, conteudo, ordem=i)
        except Exception:
            self.repo.excluir(id_)  # não deixa análise "pela metade"
            raise
        return id_

    def atualizar_lancamentos(self, id_: str, corrente: list[dict] | None, investimento: list[dict] | None) -> None:
        """Substitui os lançamentos revisados e reprocessa (RF-03)."""
        a = self._obter(id_)
        ins = dict(a["insumos"])
        if corrente is not None:
            ins["corrente"] = self._lancamentos_json(corrente)
        if investimento is not None:
            ins["investimento"] = self._lancamentos_json(investimento)
        self._salvar_resultado(id_, a["parametros"], ins)

    def atualizar_parametros(self, id_: str, alteracoes: dict[str, Any]) -> None:
        """Altera parâmetros e reprocessa. Novas palavras da SMF reclassificam os lançamentos."""
        a = self._obter(id_)
        params = {**a["parametros"], **{k: valor_json(v) if isinstance(v, date) else v
                                        for k, v in alteracoes.items()}}
        ins = a["insumos"]
        if "palavras_smf" in alteracoes:
            ins = classificar_insumos(ins, params.get("palavras_smf") or [])
        self._salvar_resultado(id_, params, ins)

    def relatorio(self, id_: str, formato: str) -> tuple[bytes, str]:
        """Gera o relatório descritivo (Word ou Markdown) e devolve (conteúdo, nome base)."""
        a = self._obter(id_)
        r = executar(a["parametros"], a["insumos"])
        nome = (a["parametros"].get("nome_projeto") or "projeto").replace(" ", "_")
        if formato == "docx":
            return gerar_docx(r), nome
        return gerar_markdown(r).encode("utf-8"), nome

    def excluir(self, id_: str) -> None:
        if not self.repo.excluir(id_):
            raise AnaliseNaoEncontrada(f"Análise '{id_}' não encontrada.")
