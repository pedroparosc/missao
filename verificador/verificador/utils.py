"""Funções auxiliares: normalização de texto, valores monetários, datas e CNPJ/CPF."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

import pandas as pd


def normalizar(txt) -> str:
    """Maiúsculas, sem acentos e com espaços simples."""
    if txt is None or (isinstance(txt, float) and pd.isna(txt)):
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def so_digitos(txt) -> str:
    if txt is None or (isinstance(txt, float) and pd.isna(txt)):
        return ""
    return re.sub(r"\D", "", str(txt))


def vazio(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip() in ("", "nan", "NaT", "None")


# --------------------------------------------------------------------------- valores
_RE_VALOR = re.compile(r"-?\(?\s*(?:R\$)?\s*-?\d[\d.,]*\)?\s*[-+]?\s*[DC]?$", re.I)


def parse_valor(v) -> float | None:
    """Converte '1.234,56', '-1.234,56', '1.234,56 D', '(1.234,56)', 1234.56 em float com sinal."""
    if vazio(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().upper().replace("R$", "").replace(" ", " ").strip()
    if not s:
        return None
    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo, s = True, s[1:-1].strip()
    if s.endswith("D"):
        negativo, s = True, s[:-1].strip()
    elif s.endswith("C"):
        s = s[:-1].strip()
    if s.endswith("-"):
        negativo, s = True, s[:-1].strip()
    elif s.endswith("+"):
        s = s[:-1].strip()
    if s.startswith("-"):
        negativo, s = True, s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()
    s = s.replace(" ", "")
    if not re.fullmatch(r"[\d.,]+", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negativo else n


def formatar_brl(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if v < 0 else f"R$ {s}"


# --------------------------------------------------------------------------- datas
def parse_data(v, ano_padrao: int | None = None) -> date | None:
    if vazio(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        a, mes, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", s)
        if not m:
            return None
        d, mes = int(m.group(1)), int(m.group(2))
        if m.group(3):
            a = int(m.group(3))
            if a < 100:
                a += 2000
        elif ano_padrao:
            a = ano_padrao
        else:
            return None
    try:
        return date(a, mes, d)
    except ValueError:
        return None


def formatar_data(d) -> str:
    return d.strftime("%d/%m/%Y") if isinstance(d, date) else "-"


# --------------------------------------------------------------------------- documentos
def cnpj_valido(cnpj) -> bool:
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False

    def dv(base: str, pesos: list[int]) -> str:
        r = sum(int(n) * p for n, p in zip(base, pesos)) % 11
        return "0" if r < 2 else str(11 - r)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(c[:12], p1)
    d2 = dv(c[:12] + d1, [6] + p1)
    return c[12:] == d1 + d2


def cpf_valido(cpf) -> bool:
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    for i in (9, 10):
        r = sum(int(c[j]) * (i + 1 - j) for j in range(i)) * 10 % 11
        if r % 10 != int(c[i]):
            return False
    return True


def formatar_cnpj(c) -> str:
    d = so_digitos(c)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return str(c or "")


def contem(texto: str, palavras) -> bool:
    t = normalizar(texto)
    return any(normalizar(p) in t for p in palavras if p)
