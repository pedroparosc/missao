"""Testes unitários das funções auxiliares do núcleo (`verificador.utils`)."""
from datetime import date

import pytest

from verificador.utils import (cnpj_valido, contem, cpf_valido, formatar_brl, formatar_cnpj, formatar_data,
                               normalizar, parse_data, parse_valor, so_digitos)


@pytest.mark.parametrize("entrada, esperado", [
    ("1.234,56", 1234.56),
    ("-1.234,56", -1234.56),
    ("1.234,56 D", -1234.56),
    ("1.234,56 C", 1234.56),
    ("(1.234,56)", -1234.56),
    ("R$ 10,00", 10.0),
    ("1.000", 1000.0),
    ("1,234.56", 1234.56),
    (12.5, 12.5),
    ("", None),
    ("abc", None),
    (None, None),
])
def test_parse_valor(entrada, esperado):
    assert parse_valor(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    ("02/03/2026", date(2026, 3, 2)),
    ("2026-03-02", date(2026, 3, 2)),
    ("02/03/26", date(2026, 3, 2)),
    ("02.03.2026", date(2026, 3, 2)),
    ("31/02/2026", None),
    ("sem data", None),
    (None, None),
])
def test_parse_data(entrada, esperado):
    assert parse_data(entrada) == esperado


def test_parse_data_ano_padrao():
    assert parse_data("05/04", ano_padrao=2026) == date(2026, 4, 5)
    assert parse_data("05/04") is None


def test_formatacao():
    assert formatar_brl(1234.5) == "R$ 1.234,50"
    assert formatar_brl(-1234.5) == "-R$ 1.234,50"
    assert formatar_brl(None) == "-"
    assert formatar_data(date(2026, 3, 2)) == "02/03/2026"
    assert formatar_data(None) == "-"
    assert formatar_cnpj("12345678000195") == "12.345.678/0001-95"
    assert formatar_cnpj("52998224725") == "529.982.247-25"


def test_cnpj_cpf():
    assert cnpj_valido("12.345.678/0001-95")
    assert not cnpj_valido("12.345.678/0001-00")
    assert not cnpj_valido("11.111.111/1111-11")
    assert cpf_valido("529.982.247-25")
    assert cpf_valido("123.456.789-09")
    assert not cpf_valido("123.456.789-00")
    assert not cpf_valido("000.000.000-00")


def test_texto():
    assert normalizar("  Secretária   Municipal ") == "SECRETARIA MUNICIPAL"
    assert so_digitos("12.345-6") == "123456"
    assert contem("TED Receb. Secretaria Municipal da Fazenda", ["SECRETARIA MUNICIPAL DA FAZENDA"])
    assert not contem("PIX RECEBIDO", ["SMF"])
