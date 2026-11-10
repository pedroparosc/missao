# Arquitetura

## Visão geral

```mermaid
flowchart LR
    subgraph Clientes
        ST["Frontend Streamlit<br/>verificador/app.py (local)"]
        WEB["Frontend web<br/>verificador/web (local, Docker, Vercel)"]
        CLI["CLI<br/>verificar_pasta.py"]
        EXT["Outros clientes<br/>(curl, sistemas)"]
    end
    subgraph Backend["Backend FastAPI — verificador/api"]
        R["rotas/ (HTTP)"] --> S["servico.py"]
        S --> SER["serializacao.py"]
        S --> REP["armazenamento.py"]
        SEG["seguranca.py · config.py"] -.-> R
    end
    subgraph Nucleo["Núcleo de domínio — verificador/verificador"]
        L["leitores.py"]
        V["verificacoes.py"]
        RL["relatorio.py"]
    end
    ST -- "local (import)" --> Nucleo
    ST -- "HTTP via cliente_api.py (opcional)" --> R
    CLI --> Nucleo
    EXT --> R
    WEB -- "fetch /api/v1" --> R
    S --> L & V & RL
    REP --> DB[("SQLite (local) ou<br/>PostgreSQL (Vercel/Neon)")]
    REP --> FS[("uploads/")]
```

### Camadas

| Camada | Pasta | Regra |
|---|---|---|
| Apresentação | `app.py`, `web/`, `verificar_pasta.py` | Interfaces (Streamlit e web) e CLI. Não contêm regras de negócio. |
| API (adaptador HTTP) | `api/rotas`, `api/esquemas.py`, `api/seguranca.py` | Valida a entrada, converte em chamadas ao serviço e serializa a saída. |
| Aplicação | `api/servico.py` | Casos de uso (criar, revisar, reprocessar, relatório). Não conhece HTTP. |
| Infraestrutura | `api/armazenamento.py`, `api/serializacao.py`, `api/config.py` | SQLite, disco e variáveis de ambiente. |
| Domínio | `verificador/` | Leitura de documentos, regras dos Passos 1–4 e relatório. **Única fonte das regras.** |

## Fluxo de uma análise

```mermaid
sequenceDiagram
    participant C as Cliente
    participant API as rotas/analises.py
    participant S as servico.py
    participant N as Núcleo
    participant DB as armazenamento.py
    C->>API: POST /analises (multipart)
    API->>API: limite de tamanho, chave de API
    API->>S: criar(arquivos, parametros, lancamentos?)
    S->>S: validar_arquivos (campo, extensão, quantidade)
    S->>N: ler_projeto / carregar_extratos / ler_planilha_* / carregar_notas
    S->>S: montar_parametros (completa com dados do projeto)
    S->>N: classificar + verificar
    S->>DB: criar (parametros, insumos, resultado) + salvar_arquivo (SHA-256)
    API-->>C: 201 AnaliseDetalhe
    C->>API: PUT /analises/{id}/lancamentos
    API->>S: atualizar_lancamentos
    S->>DB: obter insumos
    S->>N: verificar (sem reler arquivos)
    S->>DB: atualizar
    API-->>C: 200 AnaliseDetalhe
```

## Modelo de dados

```mermaid
erDiagram
    ANALISES ||--o{ ARQUIVOS : possui
    ANALISES {
        text id PK
        text criado_em
        text atualizado_em
        text nome_projeto
        text cnpj_entidade
        json parametros "Config do núcleo"
        json insumos "dados lidos + lançamentos classificados"
        json resultado "último resultado"
        int n_erros
        int n_alertas
    }
    ARQUIVOS {
        int id PK
        text analise_id FK
        text campo
        text nome_original
        text caminho
        int tamanho
        text sha256
    }
```

**Por que guardar os "insumos" e não só os arquivos?** O frontend permite corrigir a classificação
e os valores dos lançamentos. Guardar os dados já lidos permite recalcular na hora, sem reler PDFs, e
mantém as correções do usuário. Os arquivos originais ficam guardados para auditoria, com hash SHA-256.

## Decisões (ADR resumido)

| # | Decisão | Alternativas consideradas | Motivo |
|---|---|---|---|
| 1 | FastAPI | Flask, Django REST | Validação/OpenAPI automáticos, upload multipart nativo, desempenho. |
| 2 | Backend no mesmo pacote do núcleo | Microsserviço separado | Zero duplicação de regras. Um único deploy. |
| 3 | SQLite (stdlib) no uso local, PostgreSQL na nuvem | ORM (SQLAlchemy) | Sem infraestrutura extra no uso local. Na Vercel o disco é temporário, então `RepositorioPostgres` (mesma interface, SQL quase idêntico) é ativado por `DATABASE_URL`. |
| 4 | Processamento síncrono | Fila (Celery/RQ) | Uma verificação leva segundos. Fila só se surgir lote grande. |
| 5 | Integração opcional no Streamlit | Reescrever o frontend como cliente puro da API | Não quebra o uso local atual (`executar.bat`). |
| 6 | Sem automação de captcha | Serviços de quebra de captcha | Requisito do documento de referência e questão ética/legal. A API gera checklist com links. |
| 7 | Frontend web em HTML/JS puro na Vercel | Next.js/React; Streamlit Community Cloud | A Vercel não roda Streamlit. HTML/JS sem build é servido pela própria API (um único deploy e um único link) e não exige Node.js. |

## Segurança

- Chave de API opcional (`X-API-Key`), comparada em tempo constante.
- Limite de tamanho por arquivo, com leitura limitada a `limite + 1` bytes para não carregar arquivos enormes na memória.
- Lista branca de extensões por campo.
- Nome de arquivo saneado e confinado à pasta da análise (sem *path traversal*).
- SQL sempre parametrizado. Nomes de coluna em `UPDATE` vêm de uma lista branca.
- Contêiner roda como usuário sem privilégios. Só `/app/data` é gravável.
- CORS restrito por padrão a `http://localhost:8501`.
