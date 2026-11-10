/*
 * Frontend web do Verificador de Prestação de Contas.
 *
 * - Sem dependências nem build: um único script que consome a API REST (/api/v1).
 * - Rotas por hash: #/nova, #/historico, #/analise/<id>.
 * - Todo texto vindo do servidor é inserido com textContent (ou escapado), nunca como HTML,
 *   porque nomes de arquivos e históricos de extrato são dados de terceiros.
 * - A chave de API (opcional) fica só no localStorage deste navegador.
 */
"use strict";

const API = "/api/v1";

// Documentos fictícios servidos em /exemplos (mesmos de verificador/exemplos/dados).
const EXEMPLOS = {
  projeto: ["projeto - Festival Cultura Viva.docx"],
  extratos_corrente: ["extrato_conta_corrente.pdf"],
  extratos_investimento: ["extrato_investimento.xlsx"],
  planilha_gastos: ["planilha_gastos.xlsx"],
  planilha_previsto: ["previsto_executado.csv"],
  planilha_rendimentos: ["rendimentos.csv"],
};

const estado = {
  parametros: null,     // GET /parametros
  analise: null,        // AnaliseDetalhe aberta
  lancamentos: null,    // {corrente, investimento} em edição
  filtro: new Set(["Erro", "Alerta", "Informação"]),
};

// ====================================================================== utilitários
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brl = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : moeda.format(v));
const dataBR = (iso) => (iso ? String(iso).slice(0, 10).split("-").reverse().join("/") : "—");
const dataHora = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR") : "—");
const tamanho = (b) => (b < 1024 * 1024 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(2)} MB`);

function chaveApi() {
  try { return localStorage.getItem("verificador.chave") || ""; } catch { return ""; }
}

/** Chamada à API. Lança Error com a mensagem `detail` da resposta em caso de falha. */
async function api(caminho, opcoes = {}) {
  const cab = new Headers(opcoes.headers || {});
  const chave = chaveApi();
  if (chave) cab.set("X-API-Key", chave);
  if (opcoes.json !== undefined) {
    cab.set("Content-Type", "application/json");
    opcoes.body = JSON.stringify(opcoes.json);
  }
  const resp = await fetch(API + caminho, { ...opcoes, headers: cab });
  if (!resp.ok) {
    let msg = `Erro ${resp.status}`;
    try {
      const corpo = await resp.json();
      const d = corpo.detail ?? corpo.error ?? corpo;
      msg = typeof d === "string" ? d
        : Array.isArray(d) ? d.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("; ")
        : JSON.stringify(d);
    } catch { /* corpo não-JSON (ex.: 413 da plataforma) */ }
    if (resp.status === 413) msg = `Arquivos grandes demais para o servidor (${msg}).`;
    if (resp.status === 401) msg = "Chave de API ausente ou inválida — informe-a no rodapé da página.";
    throw new Error(msg);
  }
  return resp;
}
const apiJson = async (c, o) => (await api(c, o)).json();

/** Cria um elemento com atributos e filhos (strings viram nós de texto, nunca HTML). */
function el(tag, attrs = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined) e.append(f instanceof Node ? f : String(f));
  return e;
}

function avisar(texto, tipo = "info") {
  const a = el("div", { class: `aviso ${tipo}`, role: tipo === "erro" ? "alert" : "status" }, texto);
  $("#avisos").append(a);
  setTimeout(() => a.remove(), tipo === "erro" ? 9000 : 5000);
}

async function ocupado(texto, tarefa) {
  $("#carregando-texto").textContent = texto;
  $("#carregando").hidden = false;
  try { return await tarefa(); }
  catch (e) { avisar(e.message, "erro"); return null; }
  finally { $("#carregando").hidden = true; }
}

/** Monta uma tabela: colunas = [{titulo, valor: (linha) => texto|Node, num?}] */
function tabela(alvo, colunas, linhas, { vazio = "Nada a mostrar.", aoClicar } = {}) {
  alvo.replaceChildren();
  alvo.append(el("thead", {}, el("tr", {}, colunas.map((c) => el("th", { class: c.num ? "num" : null }, c.titulo)))));
  const corpo = el("tbody");
  if (!linhas.length) corpo.append(el("tr", {}, el("td", { class: "vazio", colspan: colunas.length }, vazio)));
  for (const l of linhas) {
    const tr = el("tr", { class: aoClicar ? "clicavel" : null, onclick: aoClicar ? () => aoClicar(l) : null },
      colunas.map((c) => el("td", { class: c.num ? "num" : null }, c.valor(l) ?? "—")));
    corpo.append(tr);
  }
  alvo.append(corpo);
}

// ====================================================================== status da API
async function carregarStatus() {
  const s = $("#status");
  try {
    const r = await (await fetch(`${API}/saude`)).json();
    const banco = r.banco_tipo === "postgres" ? "PostgreSQL" : "SQLite";
    s.textContent = `API ${r.versao} · ${banco}${r.persistente ? "" : " (temporário)"}`;
    s.className = `status ${r.status === "ok" ? (r.persistente ? "st-ok" : "st-aviso") : "st-falha"}`;
    s.title = r.persistente ? "Histórico salvo de forma permanente."
      : "Banco temporário: o histórico pode ser apagado. Configure um PostgreSQL (DATABASE_URL).";
  } catch {
    s.textContent = "API indisponível";
    s.className = "status st-falha";
  }
}

// ====================================================================== nova análise
async function prepararFormulario() {
  try {
    estado.parametros = await apiJson("/parametros");
  } catch (e) {
    avisar(e.message, "erro");
    return;
  }
  const p = estado.parametros;
  const grade = $("#campos-arquivo");
  grade.replaceChildren();
  for (const [campo, regra] of Object.entries(p.campos_arquivo)) {
    const id = `arq-${campo}`;
    const input = el("input", {
      id, type: "file", name: campo, multiple: regra.multiplo || null,
      accept: regra.extensoes.map((x) => `.${x}`).join(","),
      onchange: atualizarMedidor,
    });
    grade.append(el("div", { class: "campo-arquivo", "data-campo": campo },
      el("label", { for: id }, regra.descricao),
      el("small", {}, `${regra.extensoes.join(", ").toUpperCase()}${regra.multiplo ? " · vários arquivos" : ""}`),
      input, el("div", { class: "lista" })));
  }
  const f = $("#form-nova");
  f.tolerancia_dias.value = p.tolerancia_dias;
  f.max_entradas_smf.value = p.max_entradas_smf;
  f.palavras_smf.placeholder = p.palavras_smf.join("\n");
  atualizarMedidor();
}

/** Soma o tamanho dos arquivos escolhidos e compara com o limite da plataforma (4,5 MB na Vercel). */
function atualizarMedidor() {
  let total = 0;
  for (const caixa of $$(".campo-arquivo")) {
    const arqs = [...$("input", caixa).files];
    total += arqs.reduce((s, a) => s + a.size, 0);
    caixa.classList.toggle("preenchido", arqs.length > 0);
    $(".lista", caixa).textContent = arqs.map((a) => `${a.name} (${tamanho(a.size)})`).join(" · ");
  }
  const m = $("#medidor");
  const p = estado.parametros || {};
  const limite = p.max_requisicao_mb ? p.max_requisicao_mb * 1024 * 1024 : null;
  m.textContent = `Total selecionado: ${tamanho(total)}`
    + (limite ? ` de ${String(p.max_requisicao_mb).replace(".", ",")} MB permitidos por envio neste servidor.`
      : ` · limite de ${p.max_upload_mb ?? "?"} MB por arquivo.`);
  const excedido = limite !== null && total > limite;
  m.classList.toggle("excedido", excedido);
  $("#btn-verificar").disabled = excedido;
  return { total, excedido };
}

async function carregarExemplo() {
  await ocupado("Carregando documentos de exemplo…", async () => {
    for (const [campo, nomes] of Object.entries(EXEMPLOS)) {
      const dt = new DataTransfer();
      for (const nome of nomes) {
        const r = await fetch(`/exemplos/${encodeURIComponent(nome)}`);
        if (!r.ok) throw new Error(`Exemplo indisponível: ${nome}`);
        dt.items.add(new File([await r.blob()], nome));
      }
      $(`#arq-${campo}`).files = dt.files;
    }
    atualizarMedidor();
    avisar("Documentos fictícios carregados (com erros propositais). Clique em “Verificar”.", "ok");
  });
}

async function enviarAnalise(ev) {
  ev.preventDefault();
  const f = ev.target;
  const dados = new FormData();
  let algum = false;
  for (const input of $$('input[type="file"]', f)) {
    for (const arq of input.files) { dados.append(input.name, arq, arq.name); algum = true; }
  }
  if (!algum) { avisar("Selecione os documentos ou use “Carregar documentos de exemplo”.", "erro"); return; }
  if (atualizarMedidor().excedido) { avisar("O total de arquivos excede o limite deste servidor.", "erro"); return; }
  for (const nome of ["nome_projeto", "cnpj_entidade", "inicio", "fim", "tolerancia_dias", "max_entradas_smf", "palavras_smf"]) {
    const v = f[nome].value.trim();
    if (v) dados.append(nome, v);
  }
  const det = await ocupado("Lendo documentos e verificando…", () => apiJson("/analises", { method: "POST", body: dados }));
  if (det) {
    avisar(`Análise concluída: ${det.resumo.n_erros} erro(s), ${det.resumo.n_alertas} alerta(s).`, "ok");
    location.hash = `#/analise/${det.id}`;
  }
}

// ====================================================================== histórico
async function mostrarHistorico() {
  const alvo = $("#tabela-historico");
  let lista;
  try { lista = await apiJson("/analises?limite=200"); } catch (e) { avisar(e.message, "erro"); return; }
  tabela(alvo, [
    { titulo: "Criada em", valor: (l) => dataHora(l.criado_em) },
    { titulo: "Projeto", valor: (l) => l.nome_projeto || "(sem nome)" },
    { titulo: "CNPJ", valor: (l) => l.cnpj_entidade || "—" },
    { titulo: "Recebido SMF", num: true, valor: (l) => brl(l.total_smf) },
    { titulo: "Total gasto", num: true, valor: (l) => brl(l.total_gasto) },
    { titulo: "Diferença", num: true, valor: (l) => brl(l.diferenca) },
    { titulo: "Erros", num: true, valor: (l) => el("span", { class: "selo Erro" }, l.n_erros) },
    { titulo: "Alertas", num: true, valor: (l) => el("span", { class: "selo Alerta" }, l.n_alertas) },
  ], lista.itens, { vazio: "Nenhuma análise salva ainda.", aoClicar: (l) => { location.hash = `#/analise/${l.id}`; } });
}

// ====================================================================== análise
async function abrirAnalise(id) {
  const det = await ocupado("Abrindo análise…", () => apiJson(`/analises/${encodeURIComponent(id)}`));
  if (!det) { location.hash = "#/historico"; return; }
  estado.analise = det;
  estado.lancamentos = null;
  renderizarAnalise();
}

function renderizarAnalise() {
  const a = estado.analise;
  const r = a.resumo;
  $("#analise-titulo").textContent = a.parametros.nome_projeto || "Análise sem nome";
  $("#analise-meta").textContent = `CNPJ ${a.parametros.cnpj_entidade || "—"} · vigência ${dataBR(a.parametros.inicio)} a `
    + `${dataBR(a.parametros.fim)} · atualizada em ${dataHora(a.atualizado_em)}`;

  // métricas
  const m = (rotulo, valor, detalhe, classe) => el("div", { class: `metrica ${classe || ""}` },
    el("div", { class: "rotulo" }, rotulo), el("div", { class: "valor" }, valor), detalhe ? el("div", { class: "detalhe" }, detalhe) : null);
  $("#metricas").replaceChildren(
    m("Recebido da SMF", brl(r.total_smf), `${r.n_entradas_smf} entrada(s)`),
    m("Total gasto", brl(r.total_gasto), `planilha: ${brl(r.total_gasto_planilha)}`),
    m("Rendimentos", brl(r.total_rendimentos)),
    m("Diferença (SMF − gasto)", brl(r.diferenca)),
    m("Saldo conta corrente", brl(r.saldo_corrente), r.saldo_corrente_origem),
    m("Saldo conta investimento", brl(r.saldo_investimento), r.saldo_investimento_origem),
    m("Erros", r.n_erros, null, r.n_erros ? "erro" : ""),
    m("Alertas", r.n_alertas, null, r.n_alertas ? "alerta" : ""),
  );
  $("#parecer").textContent = r.n_erros || r.n_alertas
    ? `Parecer: foram encontrados ${r.n_erros} erro(s) e ${r.n_alertas} alerta(s) que devem ser notificados/esclarecidos pela entidade.`
    : "Parecer: não foram encontradas irregularidades nas verificações automáticas.";

  renderizarFiltros();
  renderizarOcorrencias();
  renderizarLancamentos();

  // conciliação
  const conc = a.conciliacao;
  const cont = conc.reduce((acc, l) => ({ ...acc, [l.status]: (acc[l.status] || 0) + 1 }), {});
  $("#resumo-conciliacao").textContent = Object.entries(cont).map(([k, v]) => `${k}: ${v}`).join(" · ")
    || "Envie o extrato da conta corrente e a planilha de gastos para conciliar.";
  tabela($("#tabela-conciliacao"), [
    { titulo: "Item", valor: (l) => l.item ?? "—" },
    { titulo: "Data planilha", valor: (l) => dataBR(l.data_planilha) },
    { titulo: "Descrição (planilha)", valor: (l) => l.descricao_planilha || "—" },
    { titulo: "Valor planilha", num: true, valor: (l) => brl(l.valor_planilha) },
    { titulo: "Data extrato", valor: (l) => dataBR(l.data_extrato) },
    { titulo: "Histórico (extrato)", valor: (l) => l.historico_extrato || "—" },
    { titulo: "Valor extrato", num: true, valor: (l) => brl(l.valor_extrato) },
    { titulo: "Situação", valor: (l) => el("span", { class: `selo ${l.status.startsWith("Conciliado") ? "ok" : "Erro"}` }, l.status) },
  ], conc);

  // previsto x executado
  tabela($("#tabela-orcamento"), [
    { titulo: "Rubrica", valor: (l) => l.rubrica },
    { titulo: "Previsto", num: true, valor: (l) => brl(l.previsto) },
    { titulo: "Executado", num: true, valor: (l) => brl(l.executado_final) },
    { titulo: "Diferença", num: true, valor: (l) => brl(l.diferenca) },
    { titulo: "Situação", valor: (l) => el("span", { class: `selo ${l.situacao === "Excedente" ? "Alerta" : "ok"}` }, l.situacao) },
  ], a.previsto_executado, { vazio: "Envie a planilha previsto x executado ou um projeto com tabela de rubricas." });

  // verificação manual
  tabela($("#tabela-manual"), [
    { titulo: "Tipo", valor: (l) => l.tipo },
    { titulo: "Item", valor: (l) => l.item },
    { titulo: "Dados para consulta", valor: (l) => l.dados_para_consulta },
    { titulo: "Link", valor: (l) => /^https?:\/\//.test(l.link) ? el("a", { href: l.link, target: "_blank", rel: "noopener noreferrer" }, "abrir ↗") : "—" },
  ], a.checklist_manual, { vazio: "Nada pendente." });

  // dados lidos
  const p = a.projeto;
  $("#dados-projeto").replaceChildren(el("h2", {}, "Arquivo do projeto"), p
    ? el("p", {}, `${p.arquivo} · vigência lida: ${dataBR(p.inicio)} a ${dataBR(p.fim)} · valor total: ${brl(p.valor_total)}`
      + ` · CNPJs encontrados: ${p.cnpjs.join(", ") || "—"}${p.menciona_contrapartida ? " · menciona contrapartida" : ""}`)
    : el("p", { class: "sutil" }, "Arquivo do projeto não enviado."));
  $("#dados-avisos").replaceChildren(el("h2", {}, `Avisos de leitura (${a.avisos_leitura.length})`),
    a.avisos_leitura.length ? el("ul", {}, a.avisos_leitura.map((t) => el("li", {}, t))) : el("p", { class: "sutil" }, "Nenhum aviso."));
  tabela($("#tabela-arquivos"), [
    { titulo: "Campo", valor: (l) => l.campo },
    { titulo: "Arquivo", valor: (l) => l.nome_original },
    { titulo: "Tamanho", num: true, valor: (l) => tamanho(l.tamanho) },
    { titulo: "SHA-256", valor: (l) => el("code", { title: l.sha256 }, l.sha256.slice(0, 16) + "…") },
  ], a.arquivos);

  // parâmetros
  const f = $("#form-parametros");
  for (const k of ["nome_projeto", "cnpj_entidade", "inicio", "fim", "tolerancia_dias", "max_entradas_smf"]) {
    f[k].value = a.parametros[k] ?? "";
  }
}

function renderizarFiltros() {
  const caixa = $("#filtros");
  caixa.replaceChildren();
  const r = estado.analise.resumo;
  const contagem = { Erro: r.n_erros, Alerta: r.n_alertas, "Informação": r.n_informacoes };
  for (const g of ["Erro", "Alerta", "Informação"]) {
    caixa.append(el("button", {
      type: "button", "aria-pressed": String(estado.filtro.has(g)),
      onclick: () => { estado.filtro.has(g) ? estado.filtro.delete(g) : estado.filtro.add(g); renderizarFiltros(); renderizarOcorrencias(); },
    }, `${g} (${contagem[g]})`));
  }
}

function renderizarOcorrencias() {
  const linhas = estado.analise.ocorrencias.filter((o) => estado.filtro.has(o.gravidade));
  tabela($("#tabela-ocorrencias"), [
    { titulo: "Gravidade", valor: (o) => el("span", { class: `selo ${o.gravidade}` }, o.gravidade) },
    { titulo: "Categoria", valor: (o) => o.categoria },
    { titulo: "Descrição", valor: (o) => o.descricao },
    { titulo: "Referência", valor: (o) => o.referencia || "—" },
  ], linhas, { vazio: "Nenhuma ocorrência com os filtros atuais." });
}

async function renderizarLancamentos() {
  if (!estado.lancamentos) {
    try {
      const l = await apiJson(`/analises/${encodeURIComponent(estado.analise.id)}/lancamentos`);
      // guarda a classificação original para destacar o que o usuário alterou
      for (const conta of ["corrente", "investimento"]) l[conta].forEach((x) => { x._original = x.classificacao; });
      estado.lancamentos = l;
    } catch (e) { avisar(e.message, "erro"); return; }
  }
  const opcoes = estado.parametros?.classificacoes || [];
  for (const conta of ["corrente", "investimento"]) {
    tabela($(`#lanc-${conta}`), [
      { titulo: "Data", valor: (l) => dataBR(l.data) },
      { titulo: "Histórico", valor: (l) => l.descricao },
      { titulo: "Documento", valor: (l) => l.documento || "—" },
      { titulo: "Valor", num: true, valor: (l) => brl(l.valor) },
      { titulo: "Saldo", num: true, valor: (l) => brl(l.saldo) },
      {
        titulo: "Classificação", valor: (l) => {
          const s = el("select", { "aria-label": `Classificação de ${l.descricao}` }, opcoes.map((o) => el("option", { value: o, selected: o === l.classificacao }, o)));
          s.addEventListener("change", () => {
            l.classificacao = s.value;
            s.closest("tr").classList.toggle("alterado", l.classificacao !== l._original);
          });
          return s;
        },
      },
    ], estado.lancamentos[conta], { vazio: "Nenhum lançamento." });
  }
}

async function salvarLancamentos() {
  const limpar = (lista) => lista.map(({ _original, ...resto }) => resto);
  const det = await ocupado("Recalculando…", () => apiJson(`/analises/${encodeURIComponent(estado.analise.id)}/lancamentos`, {
    method: "PUT", json: { corrente: limpar(estado.lancamentos.corrente), investimento: limpar(estado.lancamentos.investimento) },
  }));
  if (det) {
    estado.analise = det;
    estado.lancamentos = null;
    renderizarAnalise();
    avisar(`Recalculado: ${det.resumo.n_erros} erro(s), ${det.resumo.n_alertas} alerta(s).`, "ok");
  }
}

async function salvarParametros(ev) {
  ev.preventDefault();
  const f = ev.target;
  const corpo = {
    nome_projeto: f.nome_projeto.value.trim(),
    cnpj_entidade: f.cnpj_entidade.value.trim(),
    inicio: f.inicio.value || null,
    fim: f.fim.value || null,
    tolerancia_dias: Number(f.tolerancia_dias.value),
    max_entradas_smf: Number(f.max_entradas_smf.value),
  };
  const det = await ocupado("Recalculando…", () => apiJson(`/analises/${encodeURIComponent(estado.analise.id)}/parametros`, { method: "PATCH", json: corpo }));
  if (det) { estado.analise = det; renderizarAnalise(); avisar("Parâmetros aplicados.", "ok"); }
}

async function baixarRelatorio(formato) {
  await ocupado("Gerando relatório…", async () => {
    const resp = await api(`/analises/${encodeURIComponent(estado.analise.id)}/relatorio.${formato}`);
    const disp = resp.headers.get("Content-Disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/i.exec(disp) || /filename="([^"]+)"/i.exec(disp);
    const nome = m ? decodeURIComponent(m[1]) : `relatorio.${formato}`;
    const url = URL.createObjectURL(await resp.blob());
    el("a", { href: url, download: nome }).click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });
}

async function excluirAnalise() {
  if (!confirm("Excluir esta análise e os arquivos guardados no servidor? Esta ação não pode ser desfeita.")) return;
  const ok = await ocupado("Excluindo…", () => api(`/analises/${encodeURIComponent(estado.analise.id)}`, { method: "DELETE" }));
  if (ok) { avisar("Análise excluída.", "ok"); location.hash = "#/historico"; }
}

function trocarAba(nome) {
  for (const b of $$(".abas button")) b.setAttribute("aria-selected", String(b.dataset.aba === nome));
  for (const p of $$(".painel")) p.hidden = p.dataset.painel !== nome;
}

// ====================================================================== roteamento
async function rotear() {
  const [, rota, id] = (location.hash || "#/nova").split("/");
  for (const t of $$(".tela")) t.hidden = true;
  for (const a of $$(".menu a[data-rota]")) a.classList.toggle("ativo", a.dataset.rota === rota);
  if (rota === "historico") { $("#tela-historico").hidden = false; await mostrarHistorico(); }
  else if (rota === "analise" && id) { $("#tela-analise").hidden = false; trocarAba("resultado"); await abrirAnalise(decodeURIComponent(id)); }
  else { $("#tela-nova").hidden = false; }
  window.scrollTo(0, 0);
}

// ====================================================================== inicialização
document.addEventListener("DOMContentLoaded", async () => {
  $("#form-nova").addEventListener("submit", enviarAnalise);
  $("#btn-exemplo").addEventListener("click", carregarExemplo);
  $("#btn-atualizar-hist").addEventListener("click", mostrarHistorico);
  $("#btn-salvar-lanc").addEventListener("click", salvarLancamentos);
  $("#form-parametros").addEventListener("submit", salvarParametros);
  $("#btn-excluir").addEventListener("click", excluirAnalise);
  for (const b of $$("[data-relatorio]")) b.addEventListener("click", () => baixarRelatorio(b.dataset.relatorio));
  for (const b of $$(".abas button")) b.addEventListener("click", () => trocarAba(b.dataset.aba));

  const chave = $("#chave-api");
  chave.value = chaveApi();
  chave.addEventListener("change", () => {
    try { localStorage.setItem("verificador.chave", chave.value.trim()); } catch { /* armazenamento bloqueado */ }
    prepararFormulario();
  });

  window.addEventListener("hashchange", rotear);
  carregarStatus();
  await prepararFormulario();
  await rotear();
});
