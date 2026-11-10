"""Rotas de sistema: saúde do serviço e parâmetros padrão."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from verificador.verificacoes import CLASSIFICACOES, PAL_SMF_PADRAO, Config

from .. import __version__
from ..esquemas import ParametrosPadrao, Saude
from ..seguranca import exigir_chave
from ..servico import CAMPOS_ARQUIVO

router = APIRouter(tags=["sistema"])


@router.get("/saude", response_model=Saude, summary="Saúde do serviço")
def saude(request: Request) -> Saude:
    """Usado por healthchecks (Docker/PaaS). Público: não exige chave de API."""
    banco = request.app.state.servico.repo.saudavel()
    return Saude(status="ok" if banco else "degradado", versao=__version__, banco=banco)


@router.get("/parametros", response_model=ParametrosPadrao, dependencies=[Depends(exigir_chave)],
            summary="Parâmetros padrão e campos de upload")
def parametros(request: Request) -> ParametrosPadrao:
    """Valores padrão da barra lateral do frontend e as extensões aceitas em cada campo de upload."""
    padrao = Config()
    return ParametrosPadrao(
        classificacoes=list(CLASSIFICACOES), palavras_smf=list(PAL_SMF_PADRAO),
        tolerancia_dias=padrao.tolerancia_dias, max_entradas_smf=padrao.max_entradas_smf,
        max_upload_mb=request.app.state.config.max_upload_mb,
        campos_arquivo={c: {"extensoes": sorted(r.extensoes), "multiplo": r.multiplo, "descricao": r.descricao}
                        for c, r in CAMPOS_ARQUIVO.items()})
