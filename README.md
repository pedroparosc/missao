# missao — Verificador de Prestação de Contas

[![CI](https://github.com/pedroparosc/missao/actions/workflows/ci.yml/badge.svg)](https://github.com/pedroparosc/missao/actions/workflows/ci.yml)

**Aplicação no ar:** <https://missao-phi-seven.vercel.app> · documentação da API: <https://missao-phi-seven.vercel.app/docs>

Automatiza a conferência contábil de prestações de contas de projetos financiados pela
Secretaria Municipal da Fazenda (SMF). O sistema lê extratos bancários, planilhas, notas fiscais e o
arquivo “projeto - [nome]”, cruza tudo conforme o
[passo a passo de referência](passo_a_passo_prestacao_de_contas.md) e gera o **relatório descritivo**.

## Estrutura

```
missao/
├── passo_a_passo_prestacao_de_contas.md   # especificação funcional (regras de negócio)
├── development_plan.md                    # plano de desenvolvimento do backend (com progresso)
├── docs/
│   ├── API.md                             # referência da API REST
│   ├── ARQUITETURA.md                     # diagramas e decisões
│   ├── DEPLOY.md                          # deploy local, Docker e nuvem
│   ├── DEPLOY_VERCEL.md                   # deploy na Vercel + PostgreSQL Neon
│   ├── APRESENTACAO.md                    # roteiro da apresentação na faculdade
│   └── openapi.json                       # contrato OpenAPI exportado
├── index.py · pyproject.toml · vercel.json  # ponto de entrada e configuração da Vercel
├── docker-compose.yml                     # API + frontend
├── .github/workflows/ci.yml               # testes + build Docker
└── verificador/
    ├── app.py                             # frontend Streamlit (uso local)
    ├── web/                               # frontend web (HTML/JS) — usado na Vercel
    ├── verificar_pasta.py                 # CLI
    ├── cliente_api.py                     # cliente HTTP da API
    ├── verificador/                       # núcleo: leitores, regras, relatório
    ├── api/                               # backend (FastAPI)
    ├── tests/                             # testes automatizados (pytest)
    ├── exemplos/                          # dados fictícios com erros propositais
    ├── Dockerfile
    ├── executar.bat                       # abre o frontend (Windows)
    └── executar_api.bat                   # abre a API (Windows)
```

## Início rápido

**Windows, sem instalar nada além do Python:** dois cliques em `verificador/executar.bat` (frontend) e,
se quiser o backend, em `verificador/executar_api.bat`. Detalhes em [verificador/README.md](verificador/README.md).

**Vercel (nuvem, link público):** importe o repositório em <https://vercel.com/new> e conecte um
PostgreSQL Neon gratuito. O passo a passo está em [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md).

**Docker:**

```bash
docker compose up -d --build
```

Frontend web e API em http://localhost:8000 (documentação em `/docs`) e Streamlit em http://localhost:8501.

**Desenvolvimento:**

```bash
cd verificador
python -m pip install -r requirements-dev.txt
python -m pytest --cov=api
uvicorn api.main:app --reload
```

## Documentação

- [Especificação funcional (passo a passo)](passo_a_passo_prestacao_de_contas.md)
- [Plano de desenvolvimento](development_plan.md)
- [Manual do usuário](verificador/README.md)
- [API REST](docs/API.md) · [Arquitetura](docs/ARQUITETURA.md) · [Deploy](docs/DEPLOY.md) · [Deploy na Vercel](docs/DEPLOY_VERCEL.md)
- [Roteiro da apresentação](docs/APRESENTACAO.md)
