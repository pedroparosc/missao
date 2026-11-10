# API REST — Verificador de Prestação de Contas

- **Base:** `http://localhost:8000/api/v1`
- **Documentação interativa:** `/docs` (Swagger) e `/redoc`
- **Contrato:** [`openapi.json`](openapi.json), gerado com `python -m api.exportar_openapi`
- **Versão:** 1.1.0
- **Frontend web:** `/` (pasta `verificador/web/`). Documentos de exemplo em `/exemplos/<arquivo>`.

## Convenções

| Tema | Regra |
|---|---|
| Autenticação | Se `VERIFICADOR_API_KEY` estiver definida, envie `X-API-Key: <chave>`. Sem a chave, a resposta é **401**. `/saude` é sempre pública. |
| Formato | JSON em UTF-8. Datas no formato `AAAA-MM-DD`. No formulário de criação também se aceita `DD/MM/AAAA`. |
| Valores | `float` em reais. Nos lançamentos, crédito é positivo e débito é negativo. |
| Erros | `{"detail": "mensagem"}` ou `{"detail": [erros de validação]}` |
| Gravidades | `"Erro"`, `"Alerta"`, `"Informação"` |

| Código | Quando |
|---|---|
| 200 / 201 / 204 | Sucesso (201 na criação, 204 na exclusão) |
| 401 | Chave de API ausente ou inválida |
| 404 | Análise não encontrada |
| 413 | Arquivo acima de `VERIFICADOR_MAX_UPLOAD_MB` (padrão 25 MB por arquivo) |
| 415 | Extensão de arquivo não aceita no campo |
| 422 | Dados inválidos: data, JSON, classificação, limites, campo único com vários arquivos, nenhum extrato nem planilha |

---

## Sistema

### `GET /saude`
Saúde do serviço, usada por healthchecks.
```json
{"status": "ok", "versao": "1.1.0", "banco": true, "banco_tipo": "postgres", "persistente": true}
```
`banco_tipo` é `sqlite` ou `postgres`. `persistente` é `false` quando os dados ficam em disco
temporário (Vercel sem `DATABASE_URL`).

### `GET /parametros`
Valores padrão da barra lateral do frontend e os campos de upload aceitos.
```json
{
  "classificacoes": ["Entrada SMF (Fazenda)", "Outra entrada", "Aplicação (p/ investimento)", "Resgate (do investimento)",
                     "Rendimento", "Imposto/IOF/IR", "Tarifa bancária", "Saque/espécie", "Estorno/devolução", "Gasto"],
  "palavras_smf": ["SECRETARIA MUNICIPAL DA FAZENDA", "..."],
  "tolerancia_dias": 5, "max_entradas_smf": 3, "max_upload_mb": 25,
  "max_requisicao_mb": null,
  "campos_arquivo": {"extratos_corrente": {"extensoes": ["csv", "pdf", "xls", "xlsx"], "multiplo": true, "descricao": "..."}}
}
```

---

`max_requisicao_mb` é o limite **total** de um envio imposto pela plataforma (4,5 na Vercel). `null` significa sem limite extra.

---

## Análises

### `POST /analises`
Cria uma análise. O corpo é `multipart/form-data`. Executa os Passos 1 a 3 da verificação e salva tudo.

**Arquivos**

| Campo | Extensões | Vários? |
|---|---|---|
| `projeto` | pdf, docx, xlsx, xls, csv, txt | não |
| `extratos_corrente` | pdf, csv, xlsx, xls | sim |
| `extratos_investimento` | pdf, csv, xlsx, xls | sim |
| `planilha_gastos` | xlsx, xls, csv, pdf | não |
| `planilha_previsto` | xlsx, xls, csv, pdf | não |
| `planilha_rendimentos` | xlsx, xls, csv, pdf | não |
| `notas_fiscais` | xml, pdf, png, jpg, jpeg | sim |

É obrigatório enviar ao menos um extrato ou a planilha de gastos.

**Parâmetros (campos de formulário, todos opcionais)**

| Campo | Padrão | Observação |
|---|---|---|
| `nome_projeto` | lido do arquivo do projeto | |
| `cnpj_entidade` | 1º CNPJ válido do projeto | |
| `inicio`, `fim` | vigência lida do projeto | `AAAA-MM-DD` ou `DD/MM/AAAA` |
| `tolerancia_dias` | 5 | 0–60 |
| `max_entradas_smf` | 3 | 1–20 |
| `palavras_smf` | lista padrão | uma por linha |
| `lancamentos` | — | JSON `{"corrente": [...], "investimento": [...]}` com a classificação já revisada. Substitui a classificação automática. |

```bash
curl -X POST http://localhost:8000/api/v1/analises \
  -F "projeto=@projeto - Festival Cultura Viva.docx" \
  -F "extratos_corrente=@extrato_conta_corrente.pdf" \
  -F "extratos_investimento=@extrato_investimento.xlsx" \
  -F "planilha_gastos=@planilha_gastos.xlsx" \
  -F "max_entradas_smf=3"
```

**Resposta 201 (`AnaliseDetalhe`, resumida)**
```json
{
  "id": "c5336708c72b40898731ab8db76f0181",
  "criado_em": "2026-11-10T13:35:18+00:00",
  "parametros": {"nome_projeto": "Festival Cultura Viva", "cnpj_entidade": "12.345.678/0001-95",
                 "inicio": "2026-03-01", "fim": "2026-08-31", "tolerancia_dias": 5, "max_entradas_smf": 3, "palavras_smf": ["..."]},
  "resumo": {"total_smf": 60000.0, "n_entradas_smf": 4, "total_gasto": 46675.0, "total_rendimentos": 332.85,
             "diferenca": 13325.0, "saldo_corrente": 6325.0, "saldo_investimento": 8332.85,
             "n_erros": 14, "n_alertas": 5, "n_informacoes": 1, "...": "..."},
  "ocorrencias": [{"gravidade": "Erro", "categoria": "Entradas da SMF acima do limite",
                   "descricao": "Foram identificadas 4 entradas da SMF (máximo 3). 1 entrada(s) a mais...", "referencia": ""}],
  "entradas_smf": [{"data": "2026-03-02", "descricao": "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "valor": 20000.0, "conta": "..."}],
  "conciliacao": [{"item": 1, "status": "Conciliado", "valor_planilha": 1500.0, "valor_extrato": 1500.0, "...": "..."}],
  "previsto_executado": [{"rubrica": "Cachês artísticos", "previsto": 30000.0, "executado_final": 21000.0, "situacao": "Economia"}],
  "checklist_manual": [{"tipo": "Economicidade – remuneração (SATED SP)", "item": "...", "link": "https://www.satedsp.org.br/"}],
  "avisos_leitura": [],
  "arquivos": [{"campo": "extratos_corrente", "nome_original": "extrato_conta_corrente.pdf", "tamanho": 1690, "sha256": "..."}],
  "projeto": {"nome": "Festival Cultura Viva", "cnpjs": ["..."], "rubricas": [{"rubrica": "...", "previsto": 30000.0}]},
  "dados_lidos": {"gastos": [], "previsto": [], "rendimentos": [], "notas": []}
}
```

### `GET /analises`
Histórico, das mais recentes para as mais antigas. Query: `limite` (1–200, padrão 50) e `deslocamento` (≥ 0).
```json
{"total": 1, "itens": [{"id": "...", "criado_em": "...", "atualizado_em": "...", "nome_projeto": "Festival Cultura Viva",
  "cnpj_entidade": "12.345.678/0001-95", "total_smf": 60000.0, "total_gasto": 46675.0, "total_rendimentos": 332.85,
  "diferenca": 13325.0, "n_erros": 14, "n_alertas": 5}]}
```

### `GET /analises/{analise_id}`
Resultado completo (`AnaliseDetalhe`), no mesmo formato do `POST`.

### `GET /analises/{analise_id}/lancamentos`
Lançamentos dos extratos com a classificação atual.
```json
{"corrente": [{"data": "2026-03-02", "descricao": "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "documento": "",
               "valor": 20000.0, "saldo": 20000.0, "conta": "Ag 1234-5 / Conta 56789-0",
               "arquivo": "extrato_conta_corrente.pdf", "classificacao": "Entrada SMF (Fazenda)"}],
 "investimento": []}
```

### `PUT /analises/{analise_id}/lancamentos`
Substitui os lançamentos (classificação corrigida, valores lidos errado do PDF, linhas novas ou removidas) e
**recalcula** a verificação. Uma conta enviada como `null` ou omitida não muda. Responde com o `AnaliseDetalhe` atualizado.
```bash
curl -X PUT http://localhost:8000/api/v1/analises/<id>/lancamentos \
  -H "Content-Type: application/json" \
  -d '{"corrente": [{"data": "2026-06-10", "descricao": "TED ...", "valor": 10000, "classificacao": "Outra entrada"}]}'
```

### `PATCH /analises/{analise_id}/parametros`
Atualização parcial dos parâmetros, com recálculo. Campos desconhecidos dão 422.
Enviar `palavras_smf` **reclassifica** os lançamentos e descarta as correções manuais feitas antes.
```json
{"max_entradas_smf": 4, "fim": "2026-08-31"}
```

### `GET /analises/{analise_id}/relatorio.docx`
### `GET /analises/{analise_id}/relatorio.md`
Relatório descritivo (Passo 4) em Word ou Markdown, com `Content-Disposition: attachment`.
```bash
curl -OJ http://localhost:8000/api/v1/analises/<id>/relatorio.docx
```

### `DELETE /analises/{analise_id}`
Exclui a análise e os arquivos originais guardados. Responde **204**.

---

## Cliente Python

O arquivo `verificador/cliente_api.py` (só biblioteca padrão) envolve todos os endpoints:

```python
from cliente_api import ClienteAPI
api = ClienteAPI("http://localhost:8000", api_key=None)
det = api.criar({"extratos_corrente": [("extrato.pdf", open("extrato.pdf", "rb").read())]},
                {"cnpj_entidade": "12.345.678/0001-95", "inicio": "2026-03-01", "fim": "2026-08-31"})
cc = api.lancamentos(det["id"])["corrente"]
api.salvar_lancamentos(det["id"], corrente=cc)
open("relatorio.docx", "wb").write(api.relatorio(det["id"], "docx"))
```
