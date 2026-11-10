"""Backend (API REST) do Verificador de Prestação de Contas.

O backend expõe por HTTP o mesmo motor usado pelo frontend Streamlit (`app.py`):
ele **não** reimplementa regras de negócio, apenas orquestra o núcleo
(`verificador.leitores`, `verificador.verificacoes`, `verificador.relatorio`),
persiste as análises e serve os relatórios.

Módulos:
    config         Configuração por variáveis de ambiente (VERIFICADOR_*).
    seguranca      Autenticação opcional por chave de API (cabeçalho X-API-Key).
    esquemas       Contratos de entrada/saída (Pydantic), publicados no OpenAPI.
    serializacao   Conversão DataFrame/date/NaN <-> JSON sem perda.
    armazenamento  Repositório SQLite + gravação segura dos arquivos enviados.
    servico        Orquestração: ler documentos -> classificar -> verificar -> persistir.
    rotas          Endpoints HTTP (sistema e análises).
    main           Fábrica da aplicação FastAPI (`criar_app`) e instância `app`.
"""

__version__ = "1.0.0"
