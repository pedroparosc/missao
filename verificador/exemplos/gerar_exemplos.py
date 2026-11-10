"""Gera um conjunto fictício de documentos de prestação de contas, com erros propositais,
para testar o verificador.  Uso:  python exemplos/gerar_exemplos.py
"""
from pathlib import Path

import pandas as pd
from docx import Document
from fpdf import FPDF

PASTA = Path(__file__).parent / "dados"
PASTA.mkdir(exist_ok=True)


def gerar_cnpj(base12: str) -> str:
    def dv(b, pesos):
        r = sum(int(n) * p for n, p in zip(b, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(base12, p1)
    d = base12 + d1 + dv(base12 + d1, [6] + p1)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


ENTIDADE = gerar_cnpj("123456780001")
F_SOM = gerar_cnpj("223344550001")
F_GRAFICA = gerar_cnpj("334455660001")
F_TRANSP = gerar_cnpj("445566770001")
F_PAPEL = gerar_cnpj("556677880001")

# ------------------------------------------------------------------ projeto (DOCX)
doc = Document()
doc.add_heading("Projeto - Festival Cultura Viva", 0)
doc.add_paragraph(f"Proponente: Associação Cultural Exemplo – CNPJ {ENTIDADE}")
doc.add_paragraph("Vigência: 01/03/2026 a 31/08/2026")
doc.add_paragraph("Valor total: R$ 60.000,00, repassado pela Secretaria Municipal da Fazenda (SMF).")
doc.add_paragraph("Objeto: realização de 4 apresentações musicais gratuitas e 2 oficinas de percussão.")
t = doc.add_table(rows=1, cols=2)
t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Rubrica", "Valor previsto"
for rub, val in [("Cachês artísticos", "30.000,00"), ("Sonorização e iluminação", "15.000,00"),
                 ("Divulgação", "8.000,00"), ("Transporte", "7.000,00")]:
    c = t.add_row().cells
    c[0].text, c[1].text = rub, val
doc.save(PASTA / "projeto - Festival Cultura Viva.docx")

# ------------------------------------------------------------------ extrato conta corrente (PDF)
lanc_cc = [
    ("02/03/2026", "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "20.000,00 C", "20.000,00 C"),
    ("03/03/2026", "APLICACAO POUPANCA", "18.000,00 D", "2.000,00 C"),
    ("10/03/2026", "PIX ENVIADO JOAO DA SILVA 445512", "3.000,00 D", "1.000,00 D"),  # saldo negativo proposital? não
    ("02/04/2026", "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "20.000,00 C", "19.000,00 C"),
    ("05/04/2026", "PAGTO BOLETO GRAFICA RAPIDA 001122", "4.200,00 D", "14.800,00 C"),
    ("12/04/2026", "PIX ENVIADO SOM TOTAL LTDA 778899", "9.800,00 D", "5.000,00 C"),
    ("15/04/2026", "TARIFA PACOTE SERVICOS", "45,00 D", "4.955,00 C"),
    ("20/04/2026", "SAQUE CAIXA ELETRONICO", "500,00 D", "4.455,00 C"),
    ("02/05/2026", "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "10.000,00 C", "14.455,00 C"),
    ("05/05/2026", "RESGATE POUPANCA", "10.000,00 C", "24.455,00 C"),
    ("08/05/2026", "PIX ENVIADO MARIA SOUZA 556677", "7.500,00 D", "16.955,00 C"),
    ("15/05/2026", "PIX ENVIADO TRANSPORTES SP 991100", "6.850,00 D", "10.105,00 C"),
    ("20/05/2026", "PIX ENVIADO PAPELARIA CENTRAL 123123", "780,00 D", "9.325,00 C"),
    ("10/06/2026", "TED RECEB SECRETARIA MUNICIPAL DA FAZENDA", "10.000,00 C", "19.325,00 C"),
    ("15/06/2026", "PIX ENVIADO CARLOS PERCUSSAO 334455", "12.000,00 D", "7.325,00 C"),
    ("20/06/2026", "PIX RECEBIDO FULANO DE TAL", "1.000,00 C", "8.325,00 C"),
    ("10/07/2026", "PAGTO BOLETO GRAFICA RAPIDA 002233", "3.500,00 D", "4.825,00 C"),
]
# corrige o 3º lançamento para saldo coerente
lanc_cc[2] = ("10/03/2026", "PIX ENVIADO JOAO DA SILVA 445512", "1.500,00 D", "500,00 C")
# recalcula saldos
saldo = 0.0
for i, (d, h, v, _) in enumerate(lanc_cc):
    val = float(v[:-2].replace(".", "").replace(",", "."))
    saldo += val if v.endswith("C") else -val
    s = f"{abs(saldo):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    lanc_cc[i] = (d, h, v, s + (" C" if saldo >= 0 else " D"))

pdf = FPDF()
pdf.add_page()
pdf.set_font("Helvetica", size=10)
for linha in ["BANCO EXEMPLO S.A. - EXTRATO DE CONTA CORRENTE",
              "Cliente: ASSOCIACAO CULTURAL EXEMPLO",
              "Agencia: 1234-5   Conta Corrente: 56789-0",
              "Periodo: 01/03/2026 a 31/07/2026", "",
              "Data        Historico                                          Valor            Saldo",
              "01/03/2026  SALDO ANTERIOR                                                     0,00 C"]:
    pdf.cell(0, 6, linha, new_x="LMARGIN", new_y="NEXT")
for d, h, v, s in lanc_cc:
    pdf.cell(0, 6, f"{d}  {h:<48} {v:>14}   {s:>14}", new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 6, f"31/07/2026  SALDO FINAL {lanc_cc[-1][3]:>60}", new_x="LMARGIN", new_y="NEXT")
pdf.output(str(PASTA / "extrato_conta_corrente.pdf"))

# ------------------------------------------------------------------ extrato investimento (XLSX com preâmbulo)
linhas = [["BANCO EXEMPLO S.A. - EXTRATO POUPANÇA", None, None, None],
          ["Agência: 1234-5  Conta Poupança: 56789-0", None, None, None],
          ["Período: 01/03/2026 a 31/07/2026", None, None, None],
          [None, None, None, None],
          ["Data", "Histórico", "Valor", "Saldo"],
          ["03/03/2026", "APLICACAO", 18000.00, 18000.00],
          ["03/04/2026", "RENDIMENTO", 112.40, 18112.40],
          ["03/05/2026", "RENDIMENTO", 115.10, 18227.50],
          ["05/05/2026", "RESGATE", -10000.00, 8227.50],
          ["03/06/2026", "RENDIMENTO", 52.30, 8279.80],
          ["03/07/2026", "RENDIMENTO", 53.05, 8332.85]]
pd.DataFrame(linhas).to_excel(PASTA / "extrato_investimento.xlsx", header=False, index=False)

# ------------------------------------------------------------------ planilha de gastos (XLSX)
gastos = [
    # data pgto, emissão, fornecedor, cnpj, descrição, rubrica, doc, tipo, valor
    ("10/03/2026", "25/02/2026", "João da Silva", "529.982.247-25", "Cachê músico ensaio", "Cachês artísticos", "445512", "RPA", 1500.00),
    ("05/04/2026", "04/04/2026", "Gráfica Rápida", F_GRAFICA, "Impressão de cartazes", "Divulgação", "1122", "NF-e", 4200.00),
    ("12/04/2026", "11/04/2026", "Som Total Ltda", F_SOM, "Locação de som e luz", "Sonorização e iluminação", "778899", "NFS-e", 9800.00),
    ("08/05/2026", "08/05/2026", "Maria Souza", "123.456.789-00", "Cachê cantora", "Cachês artísticos", "556677", "Recibo", 7500.00),
    ("15/05/2026", "14/05/2026", "Transportes SP", F_TRANSP, "Transporte de equipamentos", "Transporte", "991100", "NFS-e", 6580.00),
    ("20/05/2026", "19/05/2026", "Papelaria Central", F_PAPEL, "Material de escritório", "Material de consumo", "123123", "NFC-e", 780.00),
    ("15/06/2026", "15/06/2026", "Carlos Percussão", "12.345.678/0001-00", "Oficina de percussão", "Cachês artísticos", "334455", "NFS-e", 12000.00),
    ("10/07/2026", "09/07/2026", "Gráfica Rápida", F_GRAFICA, "Impressão de folders", "Divulgação", "1122", "NF-e", 3500.00),
    ("25/07/2026", "24/07/2026", "Som Total Ltda", F_SOM, "Técnico de som extra", "Sonorização e iluminação", "778950", "NFS-e", 1200.00),
]
pd.DataFrame(gastos, columns=["Data pagamento", "Data emissão", "Fornecedor", "CNPJ/CPF", "Descrição",
                              "Rubrica", "Nº Nota Fiscal", "Tipo documento", "Valor (R$)"]) \
    .to_excel(PASTA / "planilha_gastos.xlsx", index=False)

# ------------------------------------------------------------------ previsto x executado (CSV)
pd.DataFrame([("Cachês artísticos", "30.000,00", "21.000,00"),
              ("Sonorização e iluminação", "15.000,00", "11.000,00"),
              ("Divulgação", "8.000,00", "7.700,00"),
              ("Transporte", "7.000,00", "6.580,00"),
              ("TOTAL", "60.000,00", "46.280,00")],
             columns=["Rubrica", "Previsto", "Executado"]).to_csv(PASTA / "previsto_executado.csv", sep=";", index=False)

# ------------------------------------------------------------------ rendimentos (CSV)
pd.DataFrame([("04/2026", "112,40"), ("05/2026", "115,10"), ("06/2026", "52,30"), ("07/2026", "50,00")],
             columns=["Mês", "Rendimento"]).to_csv(PASTA / "rendimentos.csv", sep=";", index=False)

print("Arquivos gerados em", PASTA)
print("CNPJ da entidade:", ENTIDADE)
