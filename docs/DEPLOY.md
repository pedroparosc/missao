# Deploy

## 1. Local no Windows (sem Docker)

| O quê | Como |
|---|---|
| Só o frontend (modo original) | Dois cliques em `verificador/executar.bat` → http://localhost:8501 |
| API | Dois cliques em `verificador/executar_api.bat` → http://localhost:8000/docs |
| Frontend integrado à API | Abra um terminal na pasta `verificador`, rode `set VERIFICADOR_API_URL=http://localhost:8000` e depois `executar.bat` |

Os dados da API ficam em `verificador/data/` (ignorado pelo git).

## 2. Docker Compose (recomendado para servidor)

```bash
docker compose up -d --build
```

- API: http://localhost:8000/docs
- Frontend: http://localhost:8501 (já integrado à API)
- Dados persistentes no volume `dados` (`/app/data`: `verificador.db` e `uploads/`)

Para exigir chave de API, crie um `.env` ao lado do `docker-compose.yml`:

```env
VERIFICADOR_API_KEY=troque-por-um-valor-longo-e-aleatorio
VERIFICADOR_CORS_ORIGINS=https://verificador.seudominio.com.br
```

## 3. Nuvem

A imagem é a mesma em qualquer provedor que rode contêineres.

| Provedor | Passos |
|---|---|
| **VM com Docker** (AWS EC2, Azure VM, GCP, VPS) | Instale o Docker, clone o repositório, crie o `.env` e rode `docker compose up -d --build`. Coloque um proxy HTTPS (Caddy/Nginx) na frente das portas 8000 e 8501. |
| **Render / Railway / Fly.io** | Crie um serviço "Docker" apontando para `verificador/Dockerfile`, porta 8000 e um disco persistente montado em `/app/data`. Para o frontend, crie um segundo serviço com o comando `streamlit run app.py --server.port 8501 --server.address 0.0.0.0` e a variável `VERIFICADOR_API_URL` com a URL pública da API. |
| **Azure Container Apps / Google Cloud Run** | Publique a imagem em um registro (ACR/GCR/GHCR). Cloud Run não tem disco local persistente: para usá-lo, troque o SQLite por um banco gerenciado (ver "Evoluções"). |

### Variáveis de ambiente

| Variável | Padrão | Produção |
|---|---|---|
| `VERIFICADOR_DB` | `/app/data/verificador.db` (contêiner) | manter em volume persistente |
| `VERIFICADOR_UPLOADS` | `/app/data/uploads` (contêiner) | manter em volume persistente |
| `VERIFICADOR_MAX_UPLOAD_MB` | 25 | ajustar ao tamanho dos extratos |
| `VERIFICADOR_API_KEY` | vazio (sem autenticação) | **obrigatório** |
| `VERIFICADOR_CORS_ORIGINS` | `http://localhost:8501` | domínio do frontend |
| `VERIFICADOR_API_URL` (frontend) | vazio (modo local) | URL da API |

## 4. CI/CD

O workflow `.github/workflows/ci.yml` roda a cada push na `main` e a cada pull request:

1. **Testes** em Python 3.11, 3.12 e 3.13, com cobertura mínima de 80%.
2. **Docker**: valida o `docker-compose.yml`, faz o build da imagem e um smoke test (sobe a API, chama `/saude` e cria uma análise com os arquivos de exemplo).

**Evolução sugerida (deploy contínuo):** adicionar um job que publica a imagem no GitHub Container
Registry (`ghcr.io/pedroparosc/missao`) a cada tag `v*` e chama o *deploy hook* do provedor escolhido.
Isso fica para depois da escolha do provedor, porque depende das credenciais dele.

## 5. Backup e restauração

```bash
# backup (com o compose rodando)
docker compose exec api python -c "import sqlite3; s=sqlite3.connect('/app/data/verificador.db'); d=sqlite3.connect('/app/data/backup.db'); s.backup(d)"
docker compose cp api:/app/data ./backup-$(date +%F)
```

Para restaurar, copie `verificador.db` e `uploads/` de volta para o volume e reinicie o serviço.

## 6. Rollback

Construa e marque as imagens por versão (`docker build -t verificador-prestacao:1.0.0 ./verificador`).
Para voltar, suba a tag anterior. O esquema do banco é criado com `CREATE TABLE IF NOT EXISTS`, então
versões anteriores continuam lendo o mesmo arquivo.

## 7. Evoluções

- Trocar o SQLite por PostgreSQL (alterar só `api/armazenamento.py`).
- Guardar os uploads em armazenamento de objetos (S3/Blob) em vez do disco local.
- Autenticação por usuário (OAuth2/JWT) se houver vários escritórios usando o mesmo servidor.
