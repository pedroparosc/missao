"""Fábrica da aplicação FastAPI.

Executar (na pasta `verificador/`):

    uvicorn api.main:app --reload            # desenvolvimento
    uvicorn api.main:app --host 0.0.0.0      # servidor/contêiner

Na Vercel, o ponto de entrada é `index.py` (raiz do repositório), que importa este `app`.

Endereços:
    /            frontend web (pasta `verificador/web/`)
    /exemplos/   documentos fictícios de `exemplos/dados/` (botão "Carregar exemplo" do frontend)
    /api/v1/...  API REST
    /docs        documentação interativa (Swagger) · /redoc
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .armazenamento import criar_repositorio
from .config import RAIZ_PROJETO, Configuracao
from .rotas import analises, sistema
from .servico import ErroServico, ServicoAnalises

PREFIXO = "/api/v1"
PASTA_WEB = RAIZ_PROJETO / "web"
PASTA_EXEMPLOS = RAIZ_PROJETO / "exemplos" / "dados"

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
    app.state.servico = ServicoAnalises(criar_repositorio(config), config.max_upload_bytes)

    if config.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["*"],
                           allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.exception_handler(ErroServico)
    def _erro_servico(_: Request, exc: ErroServico) -> JSONResponse:
        # Converte erros de domínio (404, 413, 415, 422) em respostas HTTP padronizadas.
        return JSONResponse({"detail": exc.mensagem}, status_code=exc.status)

    app.include_router(sistema.router, prefix=PREFIXO)
    app.include_router(analises.router, prefix=PREFIXO)

    # Arquivos estáticos montados DEPOIS das rotas, para que /api, /docs e /openapi.json tenham
    # prioridade (na Vercel, montagens viram arquivos servidos pela CDN).
    if PASTA_EXEMPLOS.is_dir():
        app.mount("/exemplos", StaticFiles(directory=PASTA_EXEMPLOS), name="exemplos")
    if PASTA_WEB.is_dir():
        app.mount("/", StaticFiles(directory=PASTA_WEB, html=True), name="web")
    else:  # instalação sem o frontend web: a raiz leva à documentação da API
        @app.get("/", include_in_schema=False)
        def _raiz() -> RedirectResponse:
            return RedirectResponse("/docs")
    return app


# Instância usada por `uvicorn api.main:app` e pela Vercel (via index.py). Não cria arquivos
# no import: o banco é inicializado na primeira requisição.
app = criar_app()
