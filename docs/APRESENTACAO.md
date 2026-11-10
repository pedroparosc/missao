# Roteiro da apresentação (~10 minutos)

**Slides:** deck "Verificador de Prestação de Contas — Apresentação" (12 slides, com notas do apresentador
em cada slide). Exporta para PowerPoint e PDF pelo menu *Share › Export*. O link é privado: compartilhe pelo
menu *Share* com quem for apresentar junto.

**Antes de apresentar, preencha:** `[Disciplina]`, `[Nome 1..3]`, `[Nome do professor]` e `[__/__/2026]`
(slide 1). O endereço da aplicação já está nos slides 7 e 12: **<https://missao-phi-seven.vercel.app>**.

## Tempo por slide

| # | Slide | Tempo | Mensagem principal |
|---|---|---|---|
| 1 | Capa | 0:30 | Quem somos e o que o sistema faz, em uma frase. |
| 2 | O problema | 1:00 | A conferência manual é lenta, tem muitas regras e deixa passar erros. |
| 3 | A solução | 1:00 | 5 etapas: envio → leitura → classificação (revisável) → verificação → relatório. |
| 4 | O que é verificado | 0:45 | Cada passo da especificação virou uma regra automática; o captcha fica manual, de propósito. |
| 5 | Arquitetura | 1:00 | Três interfaces, uma API e **um único núcleo de regras**; SQLite ou PostgreSQL. |
| 6 | Tecnologias | 0:45 | Por que Python/pandas/FastAPI/PostgreSQL/Vercel. |
| 7 | Demonstração | 2:00 | Ao vivo na Vercel (roteiro abaixo). |
| 8 | Resultado do exemplo | 0:45 | 14 erros e 5 alertas, todos os erros propositais encontrados. |
| 9 | Qualidade | 0:45 | 105 testes, 94% de cobertura, 6 verificações no CI. |
| 10 | Publicação | 0:45 | GitHub → CI → Vercel → Neon; os 3 limites da nuvem e como foram resolvidos. |
| 11 | Limitações e próximos passos | 0:30 | OCR, login por usuário, preços integrados. |
| 12 | Perguntas | 0:15 | Agradecer e abrir para perguntas. |
| | **Total** | **10:00** | |

Com mais de uma pessoa, uma divisão possível: **A** slides 1–4, **B** slides 5–6 e 9–10, **C** a demonstração (7–8) e 11–12.

## Demonstração ao vivo (2 minutos)

Preparação, 5 minutos antes:
1. Abrir <https://missao-phi-seven.vercel.app/api/v1/saude> e conferir `"status":"ok"` e `"persistente":true`. Isso "acorda" a função.
2. Deixar a página inicial aberta numa aba e o Word pronto para abrir o relatório.
3. Opcional: apagar análises de teste no **Histórico** para a lista ficar limpa.

Roteiro:

| Passo | Ação | O que mostrar / dizer |
|---|---|---|
| 1 | **📂 Carregar documentos de exemplo** | Os 6 arquivos aparecem nos campos: projeto (.docx), extratos (.pdf e .xlsx), planilhas (.xlsx/.csv). "São dados fictícios com erros colocados de propósito." |
| 2 | **🔎 Verificar prestação de contas** | Em segundos: R$ 60.000 recebidos da SMF, **4 entradas**, **14 erros** e **5 alertas**. Role as ocorrências e aponte "Entradas da SMF acima do limite" e "Nota fiscal duplicada". |
| 3 | Aba **🔗 Conciliação** | Cada gasto da planilha casado com o extrato; mostre "Valor divergente" (R$ 6.580 x R$ 6.850). |
| 4 | Aba **🏦 Lançamentos** → entrada de **10/06/2026** → *Outra entrada* → **Salvar e recalcular** | "Se a classificação estiver errada, o usuário corrige e o sistema recalcula." Resultado: 13 erros e 6 alertas. |
| 5 | **⬇️ Relatório Word** | Abrir o .docx: resumo financeiro, parecer, erros, conciliação e checklist manual. |

**Plano B** (internet ou Vercel fora do ar):
- Notebook com o projeto: dois cliques em `verificador/executar_api.bat` e abrir `http://localhost:8000`, a mesma interface web.
- Ou `verificador/executar.bat` (Streamlit), enviando os arquivos de `verificador/exemplos/dados/`.
- Último recurso: prints da demonstração colados no fim dos slides.

## Perguntas prováveis da banca

| Pergunta | Resposta curta |
|---|---|
| Por que não automatizar a consulta na SEFAZ? | Os portais exigem captcha. Contornar captcha viola os termos de uso e é eticamente errado. O sistema gera um checklist com os links e os dados para a pessoa consultar. |
| E se o banco mudar o layout do extrato? | O leitor procura as colunas pelo nome (data, histórico, valor, saldo) e aceita PDF, Excel e CSV. Se algo for lido errado, o usuário corrige na aba Lançamentos e a verificação é refeita. |
| Como garantem que o resultado está certo? | 105 testes automatizados, incluindo um teste de regressão que compara a API com o motor original, linha por linha, nos dados de exemplo. O CI roda tudo a cada push. |
| Os dados ficam seguros? | Na nuvem os dados ficam num PostgreSQL com acesso só pela aplicação. A API aceita uma chave de acesso (`VERIFICADOR_API_KEY`), nomes de arquivo são saneados, os uploads têm limite de tamanho e o SQL é sempre parametrizado. Para dados reais, a recomendação é ativar a chave e restringir o acesso. |
| Por que Vercel? | Gratuita para projetos acadêmicos, publica sozinha a cada push no GitHub, gera previews por branch e tem PostgreSQL (Neon) integrado. O sistema também roda com Docker em qualquer servidor. |
| Por que dois frontends? | O Streamlit é ótimo para uso local (edição de tabelas), mas não roda em plataforma serverless. O frontend web roda na Vercel e consome a mesma API. As regras ficam num só lugar. |
| Quanto tempo economiza? | No exemplo, a verificação leva poucos segundos e encontra 14 erros. O tempo humano passa a ser gasto só nos itens apontados e no checklist manual. |
| O que faltou? | OCR para extratos escaneados, login por usuário e tabela de preços de referência integrada (slide 11). |

## Checklist final

- [ ] Placeholders dos slides preenchidos (nomes, disciplina, professor e data).
- [x] Link da Vercel nos slides 7 e 12.
- [ ] Deck compartilhado com os colegas de grupo (menu *Share*) e exportado em PDF como cópia de segurança.
- [x] `/api/v1/saude` da Vercel respondendo com `"persistente":true` (verificado em 10/11/2026).
- [ ] Demonstração ensaiada uma vez, de ponta a ponta.
- [ ] Plano B testado no notebook da apresentação.
- [ ] Ensaio cronometrado ≤ 10 minutos.
