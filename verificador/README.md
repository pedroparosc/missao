# Verificador de Prestação de Contas

Software que automatiza o passo a passo de `../passo_a_passo_prestacao_de_contas.md`:
lê os extratos, as planilhas e o arquivo do projeto, cruza tudo e gera o **relatório descritivo** (Word e Markdown).

## Como usar

1. Dê dois cliques em **`executar.bat`**. Na primeira vez ele instala as dependências, o que leva alguns minutos.
2. O navegador abre em `http://localhost:8501`. Envie os arquivos:
   | Campo | Formatos |
   |---|---|
   | Arquivo do projeto (“projeto - [nome]”) | PDF, DOCX, XLSX, CSV, TXT |
   | Extratos da conta corrente específica (vários) | PDF, XLSX, CSV |
   | Extratos da conta investimento (vários) | PDF, XLSX, CSV |
   | Planilha de gastos | XLSX, CSV, PDF |
   | Previsto x executado / Rendimentos (opcionais) | XLSX, CSV, PDF |
   | Notas fiscais (opcional) | XML, PDF, imagem |
3. Confira na barra lateral o nome, o CNPJ e a vigência, que são preenchidos a partir do arquivo do projeto.
4. Na aba **Lançamentos (revisar)**, confira a classificação de cada lançamento: Entrada SMF, Gasto, Aplicação, Resgate, Rendimento etc. Se algo foi lido errado de um PDF, corrija direto na tabela e a verificação é refeita.
5. Na aba **Resultado**, baixe o relatório em `.docx` ou `.md`.

Para testar sem dados reais, rode `python exemplos/gerar_exemplos.py` com o Python do ambiente. Ele cria documentos fictícios em `exemplos/dados/` com erros propositais.

Para usar sem interface: `python verificar_pasta.py <pasta> [--cnpj ...] [--inicio dd/mm/aaaa --fim dd/mm/aaaa]`.

## Backend (API REST) e histórico de análises

O mesmo motor também está disponível como **API REST** (FastAPI), que guarda as análises em um histórico.

1. Dê dois cliques em **`executar_api.bat`**. A API sobe em `http://localhost:8000` e a documentação interativa fica em `/docs`.
2. Para o frontend usar a API, abra um terminal nesta pasta e rode:
   ```bat
   set VERIFICADOR_API_URL=http://localhost:8000
   executar.bat
   ```
   Aparecem o botão **☁️ Salvar análise no servidor** na aba *Resultado* e o painel **🗄️ Histórico (servidor)**,
   onde você reabre análises, baixa relatórios e exclui registros.
3. Sem `VERIFICADOR_API_URL`, o app funciona como antes: tudo local, sem rede.

Referência completa: [`../docs/API.md`](../docs/API.md). Arquitetura: [`../docs/ARQUITETURA.md`](../docs/ARQUITETURA.md).
Deploy (Docker/nuvem): [`../docs/DEPLOY.md`](../docs/DEPLOY.md).

| Componente | Arquivo | Função |
|---|---|---|
| Aplicação FastAPI | `api/main.py` | Cria a app, CORS, tratamento de erros |
| Rotas | `api/rotas/` | Endpoints `/api/v1/...` |
| Serviço | `api/servico.py` | Lê documentos → classifica → verifica → persiste |
| Repositório | `api/armazenamento.py` | SQLite + arquivos originais (SHA-256) |
| Contratos | `api/esquemas.py` | Modelos de entrada e saída (OpenAPI) |
| Cliente | `cliente_api.py` | Cliente HTTP usado pelo frontend |

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest --cov=api --cov=cliente_api
```

Os testes cobrem as funções auxiliares, as regras de verificação, a serialização e o repositório,
todos os endpoints (inclusive erros 401/404/413/415/422), o cliente HTTP, o frontend (AppTest) e a
**regressão**: com os dados de `exemplos/dados`, a API produz o mesmo resultado que o motor original.

## O que é verificado

| Passo / regra do documento | Verificação automática |
|---|---|
| Passo 1 – datas | Pagamentos, emissão de notas e débitos do extrato fora da vigência |
| Passo 1 – duplicidade | Mesmo nº de nota do mesmo fornecedor mais de uma vez; gastos idênticos repetidos |
| Passo 1 – autenticidade (SEFAZ/Prefeitura) | **Manual**: lista com os links e os dados para consulta, só quando há notas anexadas |
| Passo 2 – nexo causal | Rubrica do gasto inexistente no plano de trabalho/orçamento |
| Passo 2 – economicidade | **Manual**: link de busca de preço (Google) ou SATED SP para cachês e remunerações |
| Passo 3 – conciliação | Cada gasto da planilha contra cada saída do extrato (valor, data ± tolerância, nº da transação). Também aponta gastos sem lançamento, lançamentos sem gasto e valores divergentes |
| Passo 3 – rendimentos | Rendimentos do extrato x planilha de rendimentos; aplicações/resgates entre as contas |
| Passo 4 – relatório | Total recebido da SMF, total gasto, rendimentos, diferença, saldos das duas contas e lista de erros |
| Erros comuns | NFC-e/cupom, CNPJ/CPF inválido, nota emitida para outro CNPJ, RPA/recibo (INSS/ISS), saques/espécie, créditos de outra origem (conta mista), contrapartida, extratos de mais de uma conta |
| Especificações | Mais de 3 entradas da SMF: quantidade a mais, total e data/valor de cada uma; saldo final da conta corrente e da conta investimento |

## Limitações

- **PDF**: a leitura funciona com PDFs de texto (gerados pelo banco). PDFs escaneados (imagem) não são lidos; nesse caso use o extrato em Excel/CSV. Layouts de banco variam, então sempre confira a aba de lançamentos.
- **Captcha**: os portais da SEFAZ e da Prefeitura exigem captcha. O sistema não o contorna; a consulta é feita por você com os links da aba *Verificação manual*.
- As entradas da SMF (Secretaria Municipal da Fazenda, nome com que os repasses aparecem no extrato) são identificadas por palavras-chave do histórico, editáveis na barra lateral.
