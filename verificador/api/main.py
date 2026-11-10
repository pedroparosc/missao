"""Fábrica da aplicação FastAPI.

Executar (na pasta `verificador/`):

    uvicorn api.main:app --reload            # desenvolvimento
    uvicorn api.main:app --host 0.0.0.0      # servidor/contêiner

Documentação interativa: http://localhost:8000/docs (Swagger) e /redoc.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from . import __version__
from .armazenamento import Repositorio
from .config import Configuracao
from .rotas import analises, sistema
from .servico import ErroServico, ServicoAnalises

PREFIXO = "/api/v1"

DESCRICAO = """
API do **Verificador de Prestação de Contas**: recebe extratos, planilhas, notas e o arquivo
“projeto - [nome]”, executa os Passos 1 a 4 da verificação contábil e gera o relatório descritivo.

* Autenticação: cabeçalho `X-API-Key` quando `VERIFICADOR_API_KEY` estiver configurada.
* Erros seguem o formato `{"detail": ...}`.
* A consulta de autenticidade das notas (SEFAZ/Prefeitura) exige captcha e **não** é automatizada:
  a API devolve um checklist com os links para conferência manual.
"""


def criar_app(config: Configuracao | None = None) -> FastAPI:
    """Cria a aplicação. Testes passam uma `Configuracao` própria (banco temporário etc.)."""
    config = config or Configuracao.do_ambiente()
    app = FastAPI(title="Verificador de Prestação de Contas — API", version=__version__, description=DESCRICAO,
                  openapi_tags=[{"name": "análises", "description": "Criação, revisão e relatórios das análises."},
                                {"name": "sistema", "description": "Saúde e parâmetros padrão."}])
    app.state.config = config
    app.state.servico = ServicoAnalises(Repositorio(config.caminho_db, config.pasta_uploads),
                                        config.max_upload_bytes)

    if config.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["*"],
                           allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.exception_handler(ErroServico)
    def _erro_servico(_: Request, exc: ErroServico) -> JSONResponse:
        # Converte erros de domínio (404, 413, 415, 422) em respostas HTTP padronizadas.
        return JSONResponse({"detail": exc.mensagem}, status_code=exc.status)

    @app.get("/", include_in_schema=False)
    def _raiz() -> RedirectResponse:
        return RedirectResponse("/docs")

    app.include_router(sistema.router, prefix=PREFIXO)
    app.include_router(analises.router, prefix=PREFIXO)
    return app


# Instância usada por `uvicorn api.main:app`. Não cria arquivos no import: o banco é
# inicializado na primeira requisição.
app = criar_app()
