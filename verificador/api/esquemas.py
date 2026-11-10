"""Contratos de entrada e saída da API (modelos Pydantic).

Estes modelos são publicados automaticamente no OpenAPI (`/docs`, `/openapi.json`) e
documentados em `docs/API.md`. Os nomes dos campos seguem os do núcleo e do frontend
(ex.: `classificacao`, `total_smf`, `checklist_manual`) para facilitar a integração.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from verificador.verificacoes import CLASSIFICACOES, PAL_SMF_PADRAO

Gravidade = Literal["Erro", "Alerta", "Informação"]


# =========================================================================== sistema
class Saude(BaseModel):
    """Estado do serviço (usado por healthchecks de Docker/PaaS)."""
    status: Literal["ok", "degradado"]
    versao: str
    banco: bool = Field(description="True se o banco respondeu.")
    banco_tipo: Literal["sqlite", "postgres"]
    persistente: bool = Field(description="False quando os dados ficam em disco temporário (ex.: Vercel sem banco).")


class CampoArquivo(BaseModel):
    extensoes: list[str]
    multiplo: bool = Field(description="Aceita vários arquivos no mesmo campo.")
    descricao: str


class ParametrosPadrao(BaseModel):
    """Valores padrão exibidos na barra lateral do frontend."""
    classificacoes: list[str]
    palavras_smf: list[str]
    tolerancia_dias: int
    max_entradas_smf: int
    max_upload_mb: int
    max_requisicao_mb: float | None = Field(None, description="Limite total da requisição imposto pela "
                                                              "plataforma (4,5 MB na Vercel); null = sem limite extra.")
    campos_arquivo: dict[str, CampoArquivo]


# =========================================================================== parâmetros
class ParametrosAnalise(BaseModel):
    """Parâmetros da verificação — equivalem à classe `Config` do núcleo / barra lateral do app."""
    nome_projeto: str = ""
    cnpj_entidade: str = ""
    inicio: date | None = Field(None, description="Início da vigência (AAAA-MM-DD).")
    fim: date | None = Field(None, description="Fim da vigência (AAAA-MM-DD).")
    palavras_smf: list[str] = Field(default_factory=lambda: list(PAL_SMF_PADRAO),
                                    description="Trechos do histórico que identificam repasses da SMF.")
    tolerancia_dias: int = Field(5, ge=0, le=60, description="Tolerância de datas na conciliação.")
    max_entradas_smf: int = Field(3, ge=1, le=20, description="Máximo de entradas da SMF permitido.")


class ParametrosAtualizacao(BaseModel):
    """Atualização parcial dos parâmetros (PATCH). Campos omitidos não mudam.

    Se `palavras_smf` for enviado, os lançamentos são **reclassificados** automaticamente,
    descartando correções manuais de classificação feitas antes.
    """
    model_config = ConfigDict(extra="forbid")
    nome_projeto: str | None = None
    cnpj_entidade: str | None = None
    inicio: date | None = None
    fim: date | None = None
    palavras_smf: list[str] | None = None
    tolerancia_dias: int | None = Field(None, ge=0, le=60)
    max_entradas_smf: int | None = Field(None, ge=1, le=20)


# =========================================================================== lançamentos
class Lancamento(BaseModel):
    """Um lançamento de extrato bancário (crédito positivo, débito negativo)."""
    data: date
    descricao: str = ""
    documento: str = ""
    valor: float = Field(description="+crédito / −débito")
    saldo: float | None = None
    conta: str = ""
    arquivo: str = ""
    classificacao: str = Field("Gasto", description="Uma das classificações de /parametros.")

    @field_validator("classificacao")
    @classmethod
    def _classificacao_valida(cls, v: str) -> str:
        if v not in CLASSIFICACOES:
            raise ValueError(f"classificação inválida; use uma de: {', '.join(CLASSIFICACOES)}")
        return v


class Lancamentos(BaseModel):
    """Lançamentos das duas contas. Na atualização (PUT), uma conta omitida (null) não muda."""
    corrente: list[Lancamento] | None = None
    investimento: list[Lancamento] | None = None


# =========================================================================== resultado
class Ocorrencia(BaseModel):
    gravidade: Gravidade
    categoria: str
    descricao: str
    referencia: str = ""


class Resumo(BaseModel):
    """Números do relatório descritivo (Passo 4 + seção 4 do documento de referência)."""
    total_smf: float
    n_entradas_smf: int
    total_gasto: float
    total_rendimentos: float
    diferenca: float = Field(description="Total recebido da SMF − total gasto.")
    total_gasto_planilha: float
    total_impostos_invest: float
    total_tarifas: float
    saldo_corrente: float | None
    saldo_corrente_origem: str
    saldo_investimento: float | None
    saldo_investimento_origem: str
    n_erros: int
    n_alertas: int
    n_informacoes: int


class Arquivo(BaseModel):
    campo: str
    nome_original: str
    tamanho: int
    sha256: str


class ProjetoLido(BaseModel):
    """O que foi extraído do arquivo "projeto - [nome]"."""
    arquivo: str
    nome: str
    cnpjs: list[str]
    inicio: date | None
    fim: date | None
    valor_total: float | None
    menciona_contrapartida: bool
    rubricas: list[dict[str, Any]]


class DadosLidos(BaseModel):
    """Tabelas lidas das planilhas e notas (aba "Dados lidos" do frontend)."""
    gastos: list[dict[str, Any]]
    previsto: list[dict[str, Any]]
    rendimentos: list[dict[str, Any]]
    notas: list[dict[str, Any]]


class AnaliseResumo(BaseModel):
    """Item da listagem de análises (histórico)."""
    id: str
    criado_em: str
    atualizado_em: str
    nome_projeto: str
    cnpj_entidade: str
    total_smf: float
    total_gasto: float
    total_rendimentos: float
    diferenca: float
    n_erros: int
    n_alertas: int


class ListaAnalises(BaseModel):
    total: int
    itens: list[AnaliseResumo]


class AnaliseDetalhe(BaseModel):
    """Resultado completo de uma análise — tudo que as abas do frontend exibem."""
    id: str
    criado_em: str
    atualizado_em: str
    parametros: ParametrosAnalise
    resumo: Resumo
    contas_corrente: list[str]
    contas_investimento: list[str]
    ocorrencias: list[Ocorrencia]
    entradas_smf: list[dict[str, Any]]
    conciliacao: list[dict[str, Any]]
    previsto_executado: list[dict[str, Any]]
    checklist_manual: list[dict[str, Any]]
    avisos_leitura: list[str]
    arquivos: list[Arquivo]
    projeto: ProjetoLido | None
    dados_lidos: DadosLidos


class Erro(BaseModel):
    """Formato padrão de erro."""
    detail: Any
