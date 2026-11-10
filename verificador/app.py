"""Interface web (Streamlit) do Verificador de Prestação de Contas.

Executar:  streamlit run app.py

Integração opcional com o backend (API REST em `api/`): defina a variável de ambiente
`VERIFICADOR_API_URL` (ex.: http://localhost:8000) e, se a API exigir, `VERIFICADOR_API_KEY`.
Com ela, o app ganha o botão "Salvar análise no servidor" e o painel "Histórico (servidor)".
Sem ela, o app funciona exatamente como antes (tudo local, nenhuma chamada de rede).
"""
from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd
import streamlit as st

from cliente_api import ClienteAPI, ErroAPI, df_para_lancamentos
from verificador import (carregar_extratos, carregar_notas, ler_planilha_gastos, ler_planilha_previsto,
                         ler_planilha_rendimentos, ler_projeto)
from verificador.relatorio import gerar_docx, gerar_markdown, resumo
from verificador.utils import cnpj_valido, formatar_brl, formatar_cnpj
from verificador.verificacoes import (ALERTA, CLASSIFICACOES, ERRO, INFO, PAL_SMF_PADRAO, Config,
                                      classificar, verificar)

st.set_page_config(page_title="Verificador de Prestação de Contas", page_icon="🧾", layout="wide")


# --------------------------------------------------------------------------- leitura em cache
@st.cache_data(show_spinner=False)
def _extratos(arqs):
    return carregar_extratos(list(arqs))


@st.cache_data(show_spinner=False)
def _projeto(nome, conteudo):
    return ler_projeto(nome, conteudo)


@st.cache_data(show_spinner=False)
def _gastos(nome, conteudo):
    return ler_planilha_gastos(nome, conteudo)


@st.cache_data(show_spinner=False)
def _previsto(nome, conteudo):
    return ler_planilha_previsto(nome, conteudo)


@st.cache_data(show_spinner=False)
def _rendimentos(nome, conteudo):
    return ler_planilha_rendimentos(nome, conteudo)


@st.cache_data(show_spinner=False)
def _notas(arqs):
    return carregar_notas(list(arqs))


def _arqs(uploads):
    return tuple((u.name, u.getvalue()) for u in (uploads or []))


def _hash(arqs) -> str:
    h = hashlib.md5()
    for nome, conteudo in arqs:
        h.update(nome.encode())
        h.update(hashlib.md5(conteudo).digest())
    return h.hexdigest()[:10]


# --------------------------------------------------------------------------- backend (opcional)
# None quando VERIFICADOR_API_URL não está definida: nesse caso nada abaixo faz chamadas de rede.
cliente = ClienteAPI.do_ambiente()


def mostrar_historico(api: ClienteAPI) -> None:
    """Painel com as análises salvas no servidor: resumo, download do relatório e exclusão."""
    try:
        lista = api.listar(limite=200)
    except ErroAPI as exc:
        st.error(f"Não foi possível consultar o servidor: {exc.detalhe}")
        return
    if not lista["itens"]:
        st.info("Nenhuma análise salva no servidor ainda.")
        return
    tabela = pd.DataFrame(lista["itens"])
    st.dataframe(tabela[["criado_em", "nome_projeto", "cnpj_entidade", "total_smf", "total_gasto",
                         "total_rendimentos", "diferenca", "n_erros", "n_alertas"]],
                 width="stretch", hide_index=True, column_config={
                     "criado_em": "Criada em (UTC)", "nome_projeto": "Projeto", "cnpj_entidade": "CNPJ",
                     **{c: st.column_config.NumberColumn(c.replace("_", " ").capitalize(), format="%.2f")
                        for c in ("total_smf", "total_gasto", "total_rendimentos", "diferenca")},
                     "n_erros": "Erros", "n_alertas": "Alertas"})
    rotulos = {i["id"]: f"{i['criado_em'][:16].replace('T', ' ')} · {i['nome_projeto'] or '(sem nome)'}"
               for i in lista["itens"]}
    escolhido = st.selectbox("Abrir análise", list(rotulos), format_func=rotulos.get, key="hist_sel")
    if not escolhido:
        return
    try:
        det = api.obter(escolhido)
    except ErroAPI as exc:
        st.error(f"Erro ao abrir a análise: {exc.detalhe}")
        return
    r = det["resumo"]
    m = st.columns(4)
    m[0].metric("Recebido da SMF", formatar_brl(r["total_smf"]), f"{r['n_entradas_smf']} entrada(s)", delta_color="off")
    m[1].metric("Total gasto", formatar_brl(r["total_gasto"]))
    m[2].metric("Erros", r["n_erros"])
    m[3].metric("Alertas", r["n_alertas"])
    if det["ocorrencias"]:
        st.dataframe(pd.DataFrame(det["ocorrencias"]), width="stretch", hide_index=True)
    nome_arq = f"relatorio_prestacao_contas_{(det['parametros']['nome_projeto'] or 'projeto').replace(' ', '_')}"
    c1, c2, c3 = st.columns(3)
    try:
        c1.download_button("⬇️ Relatório (.docx)", api.relatorio(escolhido, "docx"), f"{nome_arq}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           width="stretch", key=f"hist_docx_{escolhido}")
        c2.download_button("⬇️ Relatório (.md)", api.relatorio(escolhido, "md"), f"{nome_arq}.md", "text/markdown",
                           width="stretch", key=f"hist_md_{escolhido}")
    except ErroAPI as exc:
        st.error(f"Erro ao gerar o relatório: {exc.detalhe}")
    confirmar = c3.checkbox("Confirmo a exclusão", key=f"hist_conf_{escolhido}")
    if c3.button("🗑️ Excluir do servidor", disabled=not confirmar, width="stretch", key=f"hist_del_{escolhido}"):
        try:
            api.excluir(escolhido)
            st.success("Análise excluída.")
            st.rerun()
        except ErroAPI as exc:
            st.error(f"Erro ao excluir: {exc.detalhe}")


# --------------------------------------------------------------------------- uploads
st.title("🧾 Verificador de Prestação de Contas")
st.caption("Envie os documentos da prestação de contas. Os extratos e o arquivo "
           "**“projeto - [nome do projeto]”** são os principais mandantes da verificação.")

c1, c2 = st.columns(2)
with c1:
    up_proj = st.file_uploader("📄 Arquivo do projeto (“projeto - [nome do projeto]”)",
                               type=["pdf", "docx", "xlsx", "xls", "csv", "txt"])
    up_cc = st.file_uploader("🏦 Extratos da conta corrente específica", type=["pdf", "csv", "xlsx", "xls"],
                             accept_multiple_files=True)
    up_inv = st.file_uploader("📈 Extratos da conta investimento", type=["pdf", "csv", "xlsx", "xls"],
                              accept_multiple_files=True)
with c2:
    up_gastos = st.file_uploader("🧮 Planilha de gastos (resumo de cada gasto)", type=["xlsx", "xls", "csv", "pdf"])
    up_prev = st.file_uploader("📊 Planilha previsto x executado (opcional)", type=["xlsx", "xls", "csv", "pdf"])
    up_rend = st.file_uploader("💰 Planilha de rendimentos da aplicação (opcional)", type=["xlsx", "xls", "csv", "pdf"])
    up_nf = st.file_uploader("🧾 Notas fiscais anexadas (opcional) — XML, PDF ou imagem",
                             type=["xml", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

avisos_leitura: list[str] = []
projeto = None
if up_proj:
    try:
        projeto = _projeto(up_proj.name, up_proj.getvalue())
    except Exception as exc:
        avisos_leitura.append(f"{up_proj.name}: erro ao ler o projeto ({exc}).")

# Pré-preenche a configuração com o que foi extraído do arquivo do projeto (uma vez por arquivo).
if projeto is not None and st.session_state.get("_proj_id") != up_proj.file_id:
    st.session_state["_proj_id"] = up_proj.file_id
    st.session_state["cfg_nome"] = projeto.nome
    validos = [c for c in projeto.cnpjs if cnpj_valido(c)]
    if validos:
        st.session_state["cfg_cnpj"] = formatar_cnpj(validos[0])
    if projeto.inicio:
        st.session_state["cfg_inicio"] = projeto.inicio
    if projeto.fim:
        st.session_state["cfg_fim"] = projeto.fim

# --------------------------------------------------------------------------- configuração
with st.sidebar:
    st.header("⚙️ Dados do projeto")
    nome = st.text_input("Nome do projeto", key="cfg_nome")
    cnpj = st.text_input("CNPJ da entidade prestadora de contas", key="cfg_cnpj")
    if cnpj and not cnpj_valido(cnpj):
        st.warning("CNPJ inválido.")
    if projeto is not None and len(projeto.cnpjs) > 1:
        st.caption("CNPJs encontrados no projeto: " + ", ".join(formatar_cnpj(c) for c in projeto.cnpjs))
    inicio = st.date_input("Início da vigência", value=None, key="cfg_inicio", format="DD/MM/YYYY")
    fim = st.date_input("Fim da vigência", value=None, key="cfg_fim", format="DD/MM/YYYY")
    if inicio is None or fim is None:
        st.info("Informe a vigência para checar despesas fora do prazo.")
    st.divider()
    st.subheader("Parâmetros")
    tolerancia = st.number_input("Tolerância de datas na conciliação (dias)", 0, 60, 5)
    max_smf = st.number_input("Máximo de entradas da SMF", 1, 20, 3)
    palavras = st.text_area("Palavras que identificam entradas da SMF no extrato (uma por linha)",
                            "\n".join(PAL_SMF_PADRAO), height=180)
    palavras_smf = [p.strip() for p in palavras.splitlines() if p.strip()]
    if cliente is not None:
        st.divider()
        st.subheader("🗄️ Servidor")
        try:
            st.caption(f"Conectado a {cliente.url_base} (API v{cliente.saude()['versao']}).")
        except ErroAPI as exc:
            st.warning(f"API indisponível: {exc.detalhe}")

cfg = Config(nome_projeto=nome, cnpj_entidade=cnpj, inicio=inicio, fim=fim, palavras_smf=palavras_smf,
             tolerancia_dias=int(tolerancia), max_entradas_smf=int(max_smf))

if not (up_cc or up_inv or up_gastos):
    st.info("⬆️ Envie ao menos os extratos e a planilha de gastos para iniciar a verificação.")
    if cliente is not None:
        with st.expander("🗄️ Histórico de análises (servidor)", expanded=True):
            mostrar_historico(cliente)
    st.stop()

# --------------------------------------------------------------------------- leitura
with st.spinner("Lendo documentos..."):
    arq_cc, arq_inv = _arqs(up_cc), _arqs(up_inv)
    cc, meta_cc, av = _extratos(arq_cc)
    avisos_leitura += av
    inv, meta_inv, av = _extratos(arq_inv)
    avisos_leitura += av
    gastos, av = _gastos(up_gastos.name, up_gastos.getvalue()) if up_gastos else (None, [])
    avisos_leitura += av
    previsto, av = _previsto(up_prev.name, up_prev.getvalue()) if up_prev else (None, [])
    avisos_leitura += av
    rend_plan, av = _rendimentos(up_rend.name, up_rend.getvalue()) if up_rend else (None, [])
    avisos_leitura += av
    notas, av = _notas(_arqs(up_nf)) if up_nf else (pd.DataFrame(), [])
    avisos_leitura += av

if avisos_leitura:
    with st.expander(f"⚠️ Avisos de leitura dos arquivos ({len(avisos_leitura)})", expanded=True):
        for a in avisos_leitura:
            st.write("• " + a)

nomes_abas = ["📋 Resultado", "🏦 Lançamentos (revisar)", "🔗 Conciliação", "📊 Previsto x executado",
              "✅ Verificação manual", "🗂️ Dados lidos"]
if cliente is not None:
    nomes_abas.append("🗄️ Histórico (servidor)")
abas = st.tabs(nomes_abas)
aba_res, aba_lanc, aba_conc, aba_orc, aba_manual, aba_dados = abas[:6]
aba_hist = abas[6] if cliente is not None else None


def _editor(df: pd.DataFrame, tipo: str, chave: str) -> pd.DataFrame:
    if df.empty:
        st.write("Nenhum lançamento.")
        return df
    base = classificar(df, tipo, cfg.palavras_smf)
    base["data"] = pd.to_datetime(base["data"])
    editado = st.data_editor(
        base, key=chave, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "classificacao": st.column_config.SelectboxColumn("Classificação", options=CLASSIFICACOES, required=True),
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "valor": st.column_config.NumberColumn("Valor (+crédito/−débito)", format="%.2f"),
            "saldo": st.column_config.NumberColumn("Saldo", format="%.2f"),
            "descricao": "Histórico", "documento": "Documento", "conta": "Conta", "arquivo": "Arquivo",
        })
    editado = editado.dropna(subset=["data", "valor"]).copy()
    editado["data"] = pd.to_datetime(editado["data"]).dt.date
    for c in ("descricao", "documento", "conta", "arquivo"):
        editado[c] = editado[c].fillna("").astype(str)
    editado["saldo"] = editado["saldo"].astype(float)
    editado["classificacao"] = editado["classificacao"].fillna("Gasto")
    return editado.reset_index(drop=True)


with aba_lanc:
    st.caption("Confira os lançamentos lidos dos extratos. Corrija a **classificação** (ou valores lidos "
               "incorretamente do PDF) — a verificação é recalculada automaticamente.")
    st.subheader("Conta corrente")
    cc_ok = _editor(cc, "corrente", f"ed_cc_{_hash(arq_cc)}")
    st.subheader("Conta investimento")
    inv_ok = _editor(inv, "investimento", f"ed_inv_{_hash(arq_inv)}")

res = verificar(cfg, cc_ok, inv_ok, meta_cc, meta_inv, gastos, previsto, rend_plan, notas,
                projeto.rubricas if projeto is not None else None,
                projeto.menciona_contrapartida if projeto is not None else False)

# --------------------------------------------------------------------------- resultado
with aba_res:
    m = st.columns(4)
    m[0].metric("Recebido da SMF", formatar_brl(res.total_smf), f"{len(res.entradas_smf)} entrada(s)", delta_color="off")
    m[1].metric("Total gasto", formatar_brl(res.total_gasto))
    m[2].metric("Rendimentos", formatar_brl(res.total_rendimentos))
    m[3].metric("Diferença (SMF − gasto)", formatar_brl(res.diferenca))
    m = st.columns(4)
    m[0].metric("Saldo conta corrente", formatar_brl(res.saldo_corrente), res.saldo_corrente_origem or None, delta_color="off")
    m[1].metric("Saldo conta investimento", formatar_brl(res.saldo_investimento), res.saldo_investimento_origem or None, delta_color="off")
    n_err = sum(o.gravidade == ERRO for o in res.ocorrencias)
    n_ale = sum(o.gravidade == ALERTA for o in res.ocorrencias)
    m[2].metric("Erros", n_err)
    m[3].metric("Alertas", n_ale)

    st.subheader("Ocorrências")
    oc = res.tabela_ocorrencias()
    filtro = st.multiselect("Mostrar", [ERRO, ALERTA, INFO], default=[ERRO, ALERTA, INFO])
    if oc.empty:
        st.success("Nenhuma ocorrência.")
    else:
        icones = {ERRO: "🔴 Erro", ALERTA: "🟡 Alerta", INFO: "🔵 Informação"}
        mostrar = oc[oc["gravidade"].isin(filtro)].assign(gravidade=lambda d: d["gravidade"].map(icones))
        st.dataframe(mostrar, width="stretch", hide_index=True,
                     column_config={"gravidade": "Gravidade", "categoria": "Categoria",
                                    "descricao": st.column_config.TextColumn("Descrição", width="large"),
                                    "referencia": "Referência"})

    st.subheader("Relatório descritivo")
    nome_arq = f"relatorio_prestacao_contas_{(cfg.nome_projeto or 'projeto').replace(' ', '_')}"
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Baixar relatório (Word .docx)", gerar_docx(res), f"{nome_arq}.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       width="stretch")
    md = gerar_markdown(res)
    d2.download_button("⬇️ Baixar relatório (Markdown)", md, f"{nome_arq}.md", "text/markdown",
                       width="stretch")
    with st.expander("Pré-visualizar relatório"):
        st.markdown(md)

    if cliente is not None:
        st.subheader("Salvar no servidor")
        st.caption("Envia os documentos, os parâmetros da barra lateral e os lançamentos **como revisados** "
                   "para o backend, que guarda a análise no histórico.")
        if st.button("☁️ Salvar análise no servidor", type="primary"):
            arquivos_envio = {
                "projeto": _arqs([up_proj] if up_proj else []), "extratos_corrente": arq_cc,
                "extratos_investimento": arq_inv, "planilha_gastos": _arqs([up_gastos] if up_gastos else []),
                "planilha_previsto": _arqs([up_prev] if up_prev else []),
                "planilha_rendimentos": _arqs([up_rend] if up_rend else []), "notas_fiscais": _arqs(up_nf)}
            parametros_envio = {"nome_projeto": cfg.nome_projeto, "cnpj_entidade": cfg.cnpj_entidade,
                                "inicio": cfg.inicio, "fim": cfg.fim, "palavras_smf": cfg.palavras_smf,
                                "tolerancia_dias": cfg.tolerancia_dias, "max_entradas_smf": cfg.max_entradas_smf}
            try:
                with st.spinner("Enviando para o servidor..."):
                    salvo = cliente.criar({k: list(v) for k, v in arquivos_envio.items() if v}, parametros_envio,
                                          {"corrente": df_para_lancamentos(cc_ok),
                                           "investimento": df_para_lancamentos(inv_ok)})
                st.success(f"Análise salva no servidor (id {salvo['id'][:8]}…): "
                           f"{salvo['resumo']['n_erros']} erro(s), {salvo['resumo']['n_alertas']} alerta(s).")
            except ErroAPI as exc:
                st.error(f"Não foi possível salvar: {exc.detalhe}")

if aba_hist is not None:
    with aba_hist:
        mostrar_historico(cliente)

with aba_conc:
    if res.conciliacao.empty:
        st.write("Envie o extrato da conta corrente e a planilha de gastos para conciliar.")
    else:
        cont = res.conciliacao["status"].value_counts()
        st.write(" · ".join(f"**{k}:** {v}" for k, v in cont.items()))
        st.dataframe(res.conciliacao, width="stretch", hide_index=True, column_config={
            "valor_planilha": st.column_config.NumberColumn("Valor planilha", format="%.2f"),
            "valor_extrato": st.column_config.NumberColumn("Valor extrato", format="%.2f"),
            "data_planilha": st.column_config.DateColumn("Data planilha", format="DD/MM/YYYY"),
            "data_extrato": st.column_config.DateColumn("Data extrato", format="DD/MM/YYYY"),
        })

with aba_orc:
    if res.previsto_executado.empty:
        st.write("Envie a planilha previsto x executado ou um arquivo de projeto com tabela de rubricas.")
    else:
        st.dataframe(res.previsto_executado, width="stretch", hide_index=True, column_config={
            c: st.column_config.NumberColumn(c.replace("_", " ").capitalize(), format="%.2f")
            for c in ("previsto", "executado", "executado_planilha_gastos", "executado_final", "diferenca")})

with aba_manual:
    st.caption("Estas verificações dependem de consulta humana. Os portais da SEFAZ e da Prefeitura exigem "
               "captcha, que deve ser respondido por você — o sistema não automatiza essa etapa.")
    if res.checklist_manual.empty:
        st.write("Nada pendente.")
    else:
        st.dataframe(res.checklist_manual, width="stretch", hide_index=True, column_config={
            "link": st.column_config.LinkColumn("Link", display_text="abrir"),
            "tipo": "Tipo", "item": "Item", "dados_para_consulta": "Dados para consulta"})

with aba_dados:
    if projeto is not None:
        st.subheader("Projeto")
        st.write(f"**Arquivo:** {projeto.arquivo} · **Vigência lida:** {projeto.inicio} a {projeto.fim} · "
                 f"**Valor total lido:** {formatar_brl(projeto.valor_total)}")
        if not projeto.rubricas.empty:
            st.dataframe(projeto.rubricas, hide_index=True)
    for titulo, df in (("Planilha de gastos", gastos), ("Previsto x executado", previsto),
                       ("Rendimentos (planilha)", rend_plan), ("Notas fiscais", notas)):
        if df is not None and not df.empty:
            st.subheader(titulo)
            st.dataframe(df, width="stretch", hide_index=True)
