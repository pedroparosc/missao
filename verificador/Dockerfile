# Imagem única do Verificador de Prestação de Contas.
# - Comando padrão: API (FastAPI/Uvicorn) na porta 8000.
# - O frontend (Streamlit, porta 8501) usa a mesma imagem com outro comando (ver docker-compose.yml).
#
# Build:  docker build -t verificador-prestacao ./verificador
# Rodar:  docker run -p 8000:8000 -v verificador_dados:/app/data verificador-prestacao

# ---------------------------------------------------------------- estágio 1: dependências
FROM python:3.12-slim AS dependencias
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --prefix=/instalar -r /tmp/requirements.txt

# ---------------------------------------------------------------- estágio 2: execução
FROM python:3.12-slim
LABEL org.opencontainers.image.title="verificador-prestacao" \
      org.opencontainers.image.description="API e frontend do Verificador de Prestação de Contas" \
      org.opencontainers.image.source="https://github.com/pedroparosc/missao"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERIFICADOR_DB=/app/data/verificador.db \
    VERIFICADOR_UPLOADS=/app/data/uploads

COPY --from=dependencias /instalar /usr/local
WORKDIR /app
COPY . .

# Usuário sem privilégios; só /app/data (volume) é gravável.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data
USER app
VOLUME ["/app/data"]
EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/saude', timeout=4)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
