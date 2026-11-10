"""Rotas de análises — espelham o fluxo do frontend Streamlit.

| Rota                                      | Equivalente no app.py                          |
|-------------------------------------------|------------------------------------------------|
| POST   /analises                          | uploads + barra lateral                        |
| GET    /analises                          | (novo) histórico                               |
| GET    /analises/{id}                     | abas Resultado, Conciliação, Previsto x exec., |
|                                           | Verificação manual e Dados lidos               |
| GET    /analises/{id}/lancamentos         | aba "Lançamentos (revisar)"                    |
| PUT    /analises/{id}/lancamentos         | edição da tabela de lançamentos -> recálculo   |
| PATCH  /analises/{id}/parametros          | alteração na barra lateral -> recálculo        |
| GET    /analises/{id}/relatorio.docx|.md  | botões de download                             |
| DELETE /analises/{id}                     | (novo) excluir                                 |
"""
from __future__ import annotations

import json
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import ValidationError

from verificador.utils import parse_data

from ..esquemas import (AnaliseDetalhe, Erro, Lancamentos, ListaAnalises, ParametrosAnalise,
                        ParametrosAtualizacao)
from ..seguranca import exigir_chave
from ..servico import ArquivoGrandeDemais, ServicoAnalises

router = APIRouter(prefix="/analises", tags=["análises"], dependencies=[Depends(exigir_chave)],
                   responses={401: {"model": Erro}, 404: {"model": Erro}})

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _servico(request: Request) -> ServicoAnalises:
    return request.app.state.servico


def _ler_uploads(request: Request, uploads: list[UploadFile] | None) -> list[tuple[str, bytes]]:
    """Lê os UploadFile de um campo respeitando o limite de tamanho (lê no máximo limite+1 bytes)."""
    lista = uploads or []
    limite = request.app.state.config.max_upload_bytes
    saida = []
    for u in lista:
        if not u.filename:  # campo enviado vazio pelo navegador
            continue
        conteudo = u.file.read(limite + 1)
        if len(conteudo) > limite:
            raise ArquivoGrandeDemais(f"{u.filename}: excede o limite de "
                                      f"{request.app.state.config.max_upload_mb} MB por arquivo.")
        saida.append((u.filename, conteudo))
    return saida


def _data_form(v: str | None, campo: str):
    """Aceita datas `AAAA-MM-DD` ou `DD/MM/AAAA` vindas de formulário; vazio = None."""
    if v is None or not v.strip():
        return None
    d = parse_data(v)
    if d is None:
        raise HTTPException(422, f"Data inválida em '{campo}': {v!r}.")
    return d


@router.post("", response_model=AnaliseDetalhe, status_code=status.HTTP_201_CREATED,
             summary="Criar análise (enviar documentos)",
             responses={413: {"model": Erro}, 415: {"model": Erro}, 422: {"model": Erro}})
def criar_analise(
    request: Request,
    # Todos os campos são declarados como lista para que o serviço consiga rejeitar (422) o envio
    # de vários arquivos em um campo de arquivo único. Com `UploadFile`, o FastAPI ficaria só com o
    # último e descartaria os demais sem avisar.
    projeto: Annotated[list[UploadFile] | None, File(description="Arquivo “projeto - [nome]” (um)")] = None,
    extratos_corrente: Annotated[list[UploadFile] | None, File(description="Extratos da conta corrente (vários)")] = None,
    extratos_investimento: Annotated[list[UploadFile] | None,
                                     File(description="Extratos da conta investimento (vários)")] = None,
    planilha_gastos: Annotated[list[UploadFile] | None, File(description="Planilha de gastos (um)")] = None,
    planilha_previsto: Annotated[list[UploadFile] | None, File(description="Previsto x executado (um)")] = None,
    planilha_rendimentos: Annotated[list[UploadFile] | None, File(description="Rendimentos (um)")] = None,
    notas_fiscais: Annotated[list[UploadFile] | None, File(description="Notas fiscais (vários)")] = None,
    nome_projeto: Annotated[str, Form()] = "",
    cnpj_entidade: Annotated[str, Form()] = "",
    inicio: Annotated[str | None, Form(description="AAAA-MM-DD ou DD/MM/AAAA")] = None,
    fim: Annotated[str | None, Form(description="AAAA-MM-DD ou DD/MM/AAAA")] = None,
    tolerancia_dias: Annotated[int, Form(ge=0, le=60)] = 5,
    max_entradas_smf: Annotated[int, Form(ge=1, le=20)] = 3,
    palavras_smf: Annotated[str | None, Form(description="Uma palavra-chave por linha (vazio = padrão)")] = None,
    lancamentos: Annotated[str | None, Form(description="JSON opcional {corrente:[...], investimento:[...]} "
                                                         "com a classificação já revisada")] = None,
) -> dict:
    """Recebe os documentos (multipart/form-data), executa a verificação e salva a análise.

    Nome, CNPJ e vigência não informados são extraídos do arquivo do projeto.
    É obrigatório enviar ao menos um extrato ou a planilha de gastos.
    """
    arquivos = {campo: _ler_uploads(request, valor) for campo, valor in (
        ("projeto", projeto), ("extratos_corrente", extratos_corrente),
        ("extratos_investimento", extratos_investimento), ("planilha_gastos", planilha_gastos),
        ("planilha_previsto", planilha_previsto), ("planilha_rendimentos", planilha_rendimentos),
        ("notas_fiscais", notas_fiscais))}

    palavras = [p.strip() for p in (palavras_smf or "").splitlines() if p.strip()]
    try:
        params = ParametrosAnalise(nome_projeto=nome_projeto.strip(), cnpj_entidade=cnpj_entidade.strip(),
                                   inicio=_data_form(inicio, "inicio"), fim=_data_form(fim, "fim"),
                                   tolerancia_dias=tolerancia_dias, max_entradas_smf=max_entradas_smf,
                                   **({"palavras_smf": palavras} if palavras else {}))
        lanc = Lancamentos.model_validate(json.loads(lancamentos)) if lancamentos else None
    except (ValidationError, json.JSONDecodeError) as exc:
        detalhe = exc.errors(include_url=False, include_context=False) if isinstance(exc, ValidationError) else f"JSON inválido: {exc}"
        raise HTTPException(422, detalhe) from exc

    lanc_dict = None
    if lanc is not None:
        lanc_dict = {c: ([l.model_dump() for l in v] if v is not None else None)
                     for c, v in (("corrente", lanc.corrente), ("investimento", lanc.investimento))}
    svc = _servico(request)
    id_ = svc.criar(arquivos, params.model_dump(), lanc_dict)
    return svc.detalhe(id_)


@router.get("", response_model=ListaAnalises, summary="Listar análises (histórico)")
def listar_analises(request: Request, limite: Annotated[int, Query(ge=1, le=200)] = 50,
                    deslocamento: Annotated[int, Query(ge=0)] = 0) -> dict:
    """Análises mais recentes primeiro, com os totais do resumo e a contagem de erros/alertas."""
    return _servico(request).listar(limite, deslocamento)


@router.get("/{analise_id}", response_model=AnaliseDetalhe, summary="Detalhar análise")
def obter_analise(request: Request, analise_id: str) -> dict:
    """Resultado completo: resumo, ocorrências, entradas SMF, conciliação, previsto x executado,
    checklist manual, avisos de leitura, arquivos e dados lidos."""
    return _servico(request).detalhe(analise_id)


@router.get("/{analise_id}/lancamentos", response_model=Lancamentos, summary="Lançamentos classificados")
def obter_lancamentos(request: Request, analise_id: str) -> dict:
    """Lançamentos dos extratos com a classificação atual (aba “Lançamentos (revisar)”)."""
    return _servico(request).lancamentos(analise_id)


@router.put("/{analise_id}/lancamentos", response_model=AnaliseDetalhe, summary="Corrigir lançamentos e recalcular")
def atualizar_lancamentos(request: Request, analise_id: str, corpo: Lancamentos) -> dict:
    """Substitui os lançamentos de uma ou das duas contas (classificação, valores lidos errado do PDF,
    linhas incluídas/removidas) e refaz a verificação. Conta omitida (`null`) não é alterada."""
    svc = _servico(request)
    svc.atualizar_lancamentos(
        analise_id,
        [l.model_dump() for l in corpo.corrente] if corpo.corrente is not None else None,
        [l.model_dump() for l in corpo.investimento] if corpo.investimento is not None else None)
    return svc.detalhe(analise_id)


@router.patch("/{analise_id}/parametros", response_model=AnaliseDetalhe, summary="Alterar parâmetros e recalcular")
def atualizar_parametros(request: Request, analise_id: str, corpo: ParametrosAtualizacao) -> dict:
    """Atualização parcial dos parâmetros. Enviar `palavras_smf` reclassifica os lançamentos."""
    svc = _servico(request)
    svc.atualizar_parametros(analise_id, corpo.model_dump(exclude_unset=True))
    return svc.detalhe(analise_id)


def _download(conteudo: bytes, nome_base: str, ext: str, mime: str) -> Response:
    # Nome ASCII seguro + variante UTF-8 (RFC 5987) para preservar acentos.
    ascii_ = re.sub(r"[^A-Za-z0-9_.-]", "_", nome_base) or "projeto"
    arquivo = f"relatorio_prestacao_contas_{nome_base}.{ext}"
    disp = (f'attachment; filename="relatorio_prestacao_contas_{ascii_}.{ext}"; '
            f"filename*=UTF-8''{quote(arquivo)}")
    return Response(conteudo, media_type=mime, headers={"Content-Disposition": disp})


@router.get("/{analise_id}/relatorio.docx", summary="Baixar relatório (Word)",
            response_class=Response, responses={200: {"content": {MIME_DOCX: {}}}})
def relatorio_docx(request: Request, analise_id: str) -> Response:
    """Relatório descritivo da prestação de contas em Word (.docx)."""
    conteudo, nome = _servico(request).relatorio(analise_id, "docx")
    return _download(conteudo, nome, "docx", MIME_DOCX)


@router.get("/{analise_id}/relatorio.md", summary="Baixar relatório (Markdown)",
            response_class=Response, responses={200: {"content": {"text/markdown": {}}}})
def relatorio_md(request: Request, analise_id: str) -> Response:
    """Relatório descritivo da prestação de contas em Markdown."""
    conteudo, nome = _servico(request).relatorio(analise_id, "md")
    return _download(conteudo, nome, "md", "text/markdown; charset=utf-8")


@router.delete("/{analise_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Excluir análise")
def excluir_analise(request: Request, analise_id: str) -> Response:
    """Remove a análise, seus registros e os arquivos originais guardados."""
    _servico(request).excluir(analise_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
