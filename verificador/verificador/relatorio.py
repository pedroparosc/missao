"""Geração do relatório descritivo da prestação de contas (DOCX e Markdown)."""
from __future__ import annotations

import io
from datetime import datetime

from .utils import formatar_brl, formatar_cnpj, formatar_data
from .verificacoes import ALERTA, ERRO, INFO, Resultado


def resumo(r: Resultado) -> list[tuple[str, str]]:
    return [
        ("Total recebido da SMF", formatar_brl(r.total_smf)),
        ("Total gasto (saídas da conta corrente)", formatar_brl(r.total_gasto)),
        ("Total de rendimentos de aplicação", formatar_brl(r.total_rendimentos)),
        ("Diferença (recebido SMF − gasto)", formatar_brl(r.diferenca)),
        ("Total da planilha de gastos", formatar_brl(r.total_gasto_planilha)),
        ("Impostos/IOF sobre a aplicação", formatar_brl(r.total_impostos_invest)),
        ("Saldo final – conta corrente", f"{formatar_brl(r.saldo_corrente)}"
         + (f" ({r.saldo_corrente_origem})" if r.saldo_corrente_origem else "")),
        ("Saldo final – conta investimento", f"{formatar_brl(r.saldo_investimento)}"
         + (f" ({r.saldo_investimento_origem})" if r.saldo_investimento_origem else "")),
    ]


def _cabecalho(r: Resultado) -> list[tuple[str, str]]:
    c = r.config
    return [
        ("Projeto", c.nome_projeto or "-"),
        ("CNPJ da entidade", formatar_cnpj(c.cnpj_entidade) or "-"),
        ("Vigência", f"{formatar_data(c.inicio)} a {formatar_data(c.fim)}"),
        ("Conta(s) corrente", "; ".join(r.contas_corrente) or "-"),
        ("Conta(s) investimento", "; ".join(r.contas_investimento) or "-"),
        ("Data da verificação", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ]


def _parecer(r: Resultado) -> str:
    n_erros = sum(o.gravidade == ERRO for o in r.ocorrencias)
    n_alertas = sum(o.gravidade == ALERTA for o in r.ocorrencias)
    if n_erros == 0 and n_alertas == 0:
        return "Não foram encontradas irregularidades nas verificações automáticas."
    return (f"Foram encontrados {n_erros} erro(s) e {n_alertas} alerta(s) que devem ser "
            "notificados/esclarecidos pela entidade, conforme detalhado abaixo.")


def gerar_markdown(r: Resultado) -> str:
    out = [f"# Relatório Descritivo da Prestação de Contas", ""]
    out += [f"**{k}:** {v}  " for k, v in _cabecalho(r)] + [""]
    out += ["## 1. Resumo financeiro", "", "| Item | Valor |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in resumo(r)] + [""]
    if not r.entradas_smf.empty:
        out += ["## 2. Entradas da SMF", "", "| # | Data | Histórico | Valor |", "|---|---|---|---|"]
        for i, l in enumerate(r.entradas_smf.itertuples(), 1):
            out.append(f"| {i} | {formatar_data(l.data)} | {l.descricao} | {formatar_brl(l.valor)} |")
        out.append("")
    out += ["## 3. Parecer", "", _parecer(r), ""]
    for grav, titulo in ((ERRO, "4. Erros"), (ALERTA, "5. Alertas"), (INFO, "6. Informações")):
        oc = [o for o in r.ocorrencias if o.gravidade == grav]
        if not oc:
            continue
        out += [f"## {titulo}", ""]
        for o in oc:
            out.append(f"- **{o.categoria}:** {o.descricao}" + (f" _(ref.: {o.referencia})_" if o.referencia else ""))
        out.append("")
    if not r.previsto_executado.empty:
        out += ["## 7. Previsto x executado", "", "| Rubrica | Previsto | Executado | Diferença | Situação |",
                "|---|---|---|---|---|"]
        for l in r.previsto_executado.itertuples():
            out.append(f"| {l.rubrica} | {formatar_brl(l.previsto)} | {formatar_brl(l.executado_final)} | "
                       f"{formatar_brl(l.diferenca)} | {l.situacao} |")
        out.append("")
    if not r.checklist_manual.empty:
        out += ["## 8. Verificações manuais pendentes", ""]
        for l in r.checklist_manual.itertuples():
            out.append(f"- [ ] **{l.tipo}** – {l.item} – {l.dados_para_consulta} – {l.link}")
        out.append("")
    return "\n".join(out)


def gerar_docx(r: Resultado) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10.5)

    t = doc.add_heading("Relatório Descritivo da Prestação de Contas", 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def tabela(linhas, cabecalho=None):
        cols = len(linhas[0]) if linhas else len(cabecalho)
        tb = doc.add_table(rows=0, cols=cols)
        tb.style = "Light Grid Accent 1"
        if cabecalho:
            cel = tb.add_row().cells
            for i, h in enumerate(cabecalho):
                cel[i].text = h
                cel[i].paragraphs[0].runs[0].bold = True
        for l in linhas:
            cel = tb.add_row().cells
            for i, v in enumerate(l):
                cel[i].text = str(v)
        doc.add_paragraph()

    tabela(_cabecalho(r))
    doc.add_heading("1. Resumo financeiro", 1)
    tabela(resumo(r), ["Item", "Valor"])

    if not r.entradas_smf.empty:
        doc.add_heading("2. Entradas da SMF", 1)
        tabela([(i, formatar_data(l.data), l.descricao, formatar_brl(l.valor))
                for i, l in enumerate(r.entradas_smf.itertuples(), 1)], ["#", "Data", "Histórico", "Valor"])

    doc.add_heading("3. Parecer", 1)
    doc.add_paragraph(_parecer(r))

    cores = {ERRO: RGBColor(0xB0, 0x1E, 0x1E), ALERTA: RGBColor(0xA6, 0x6A, 0x00), INFO: RGBColor(0x1F, 0x4E, 0x79)}
    for grav, titulo in ((ERRO, "4. Erros"), (ALERTA, "5. Alertas"), (INFO, "6. Informações")):
        oc = [o for o in r.ocorrencias if o.gravidade == grav]
        if not oc:
            continue
        doc.add_heading(titulo, 1)
        for o in oc:
            p = doc.add_paragraph(style="List Bullet")
            run = p.add_run(f"{o.categoria}: ")
            run.bold = True
            run.font.color.rgb = cores[grav]
            p.add_run(o.descricao)
            if o.referencia:
                p.add_run(f" (ref.: {o.referencia})").italic = True

    if not r.previsto_executado.empty:
        doc.add_heading("7. Previsto x executado", 1)
        tabela([(l.rubrica, formatar_brl(l.previsto), formatar_brl(l.executado_final), formatar_brl(l.diferenca), l.situacao)
                for l in r.previsto_executado.itertuples()],
               ["Rubrica", "Previsto", "Executado", "Diferença", "Situação"])

    if not r.conciliacao.empty:
        doc.add_heading("8. Conciliação bancária", 1)
        tabela([("" if l.item is None or l.item != l.item else int(l.item), l.descricao_planilha or "-",
                 formatar_brl(l.valor_planilha), formatar_data(l.data_extrato), l.historico_extrato or "-",
                 formatar_brl(l.valor_extrato), l.status) for l in r.conciliacao.itertuples()],
               ["Item", "Planilha", "Valor planilha", "Data extrato", "Histórico extrato", "Valor extrato", "Status"])

    if not r.checklist_manual.empty:
        doc.add_heading("9. Verificações manuais pendentes", 1)
        doc.add_paragraph("Itens que exigem conferência humana (autenticidade nos portais da SEFAZ/Prefeitura "
                          "e compatibilidade de preços com o mercado/SATED SP).")
        tabela([(l.tipo, l.item, l.dados_para_consulta, l.link) for l in r.checklist_manual.itertuples()],
               ["Tipo", "Item", "Dados", "Link"])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
