"""Cliente HTTP da API do Verificador (usado pelo frontend Streamlit e por scripts).

Só usa a biblioteca padrão (`urllib`), sem dependências extras.

Exemplo::

    from cliente_api import ClienteAPI
    api = ClienteAPI("http://localhost:8000", api_key=None)
    det = api.criar({"extratos_corrente": [("extrato.pdf", open("extrato.pdf", "rb").read())]},
                    {"cnpj_entidade": "12.345.678/0001-95"})
    open("relatorio.docx", "wb").write(api.relatorio(det["id"], "docx"))

O frontend ativa a integração quando a variável de ambiente `VERIFICADOR_API_URL` está definida
(e, se a API exigir, `VERIFICADOR_API_KEY`). Ver `ClienteAPI.do_ambiente()`.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime
from typing import Any, Callable

# Assinatura do transporte: (método, url, corpo, cabeçalhos) -> (status, cabeçalhos, corpo).
# Pode ser trocado nos testes para chamar a API em memória (TestClient).
Transporte = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, dict[str, str], bytes]]


class ErroAPI(Exception):
    """Resposta de erro da API (status HTTP + `detail`) ou falha de conexão (status 0)."""

    def __init__(self, status: int, detalhe: Any):
        super().__init__(f"HTTP {status}: {detalhe}")
        self.status = status
        self.detalhe = detalhe


def _transporte_urllib(timeout: float) -> Transporte:
    def enviar(metodo, url, corpo, cabecalhos):
        req = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL configurada pelo usuário
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()
        except (urllib.error.URLError, OSError) as e:
            raise ErroAPI(0, f"API indisponível em {url}: {getattr(e, 'reason', e)}") from e
    return enviar


def _multipart(campos: list[tuple[str, str]], arquivos: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    """Codifica `multipart/form-data`. Devolve (corpo, content-type)."""
    limite = uuid.uuid4().hex
    partes: list[bytes] = []
    for nome, valor in campos:
        partes += [f"--{limite}\r\n".encode(),
                   f'Content-Disposition: form-data; name="{nome}"\r\n\r\n'.encode(),
                   str(valor).encode("utf-8"), b"\r\n"]
    for nome, arquivo, conteudo in arquivos:
        arq = arquivo.replace('"', "'").replace("\r", "").replace("\n", "")
        partes += [f"--{limite}\r\n".encode(),
                   f'Content-Disposition: form-data; name="{nome}"; filename="{arq}"\r\n'.encode("utf-8"),
                   b"Content-Type: application/octet-stream\r\n\r\n", conteudo, b"\r\n"]
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def _json_valor(v: Any) -> Any:
    """date/datetime -> ISO; NaN/NaT -> None (para enviar lançamentos de um DataFrame)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if str(v) in ("NaT", "<NA>"):
        return None
    return v


def df_para_lancamentos(df) -> list[dict]:
    """Converte o DataFrame de lançamentos do frontend em lista JSON aceita pela API."""
    if df is None or len(df) == 0:
        return []
    campos = ("data", "descricao", "documento", "valor", "saldo", "conta", "arquivo", "classificacao")
    return [{c: _json_valor(l.get(c)) for c in campos} for l in df.to_dict("records")]


class ClienteAPI:
    """Cliente da API REST `/api/v1`. Todos os métodos levantam `ErroAPI` em caso de erro."""

    def __init__(self, url_base: str, api_key: str | None = None, timeout: float = 180,
                 transporte: Transporte | None = None):
        self.url_base = url_base.rstrip("/")
        self.api_key = api_key
        self._enviar = transporte or _transporte_urllib(timeout)

    @classmethod
    def do_ambiente(cls) -> "ClienteAPI | None":
        """Cria o cliente a partir de VERIFICADOR_API_URL/VERIFICADOR_API_KEY, ou None se não configurado."""
        url = os.getenv("VERIFICADOR_API_URL", "").strip()
        return cls(url, os.getenv("VERIFICADOR_API_KEY") or None) if url else None

    # ------------------------------------------------------------------ infraestrutura
    def _req(self, metodo: str, caminho: str, *, json_: Any = None, corpo: bytes | None = None,
             tipo: str | None = None, query: dict | None = None) -> tuple[dict[str, str], bytes]:
        url = f"{self.url_base}/api/v1{caminho}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        cab = {"Accept": "application/json"}
        if self.api_key:
            cab["X-API-Key"] = self.api_key
        if json_ is not None:
            corpo, tipo = json.dumps(json_, ensure_ascii=False).encode("utf-8"), "application/json"
        if tipo:
            cab["Content-Type"] = tipo
        status, cabecalhos, dados = self._enviar(metodo, url, corpo, cab)
        if status >= 400:
            try:
                detalhe = json.loads(dados).get("detail", dados.decode("utf-8", "replace"))
            except (ValueError, AttributeError):
                detalhe = dados.decode("utf-8", "replace")
            raise ErroAPI(status, detalhe)
        return cabecalhos, dados

    def _json(self, metodo: str, caminho: str, **kw) -> Any:
        _, dados = self._req(metodo, caminho, **kw)
        return json.loads(dados) if dados else None

    # ------------------------------------------------------------------ endpoints
    def saude(self) -> dict:
        return self._json("GET", "/saude")

    def parametros(self) -> dict:
        return self._json("GET", "/parametros")

    def listar(self, limite: int = 50, deslocamento: int = 0) -> dict:
        return self._json("GET", "/analises", query={"limite": limite, "deslocamento": deslocamento})

    def obter(self, analise_id: str) -> dict:
        return self._json("GET", f"/analises/{urllib.parse.quote(analise_id)}")

    def criar(self, arquivos: dict[str, list[tuple[str, bytes]]], parametros: dict[str, Any] | None = None,
              lancamentos: dict[str, list[dict]] | None = None) -> dict:
        """Envia os documentos e cria a análise.

        arquivos:    {"extratos_corrente": [(nome, bytes), ...], "projeto": [(nome, bytes)], ...}
        parametros:  nome_projeto, cnpj_entidade, inicio, fim (date ou texto), tolerancia_dias,
                     max_entradas_smf, palavras_smf (lista)
        lancamentos: {"corrente": [...], "investimento": [...]} já revisados (opcional)
        """
        campos = []
        for k, v in (parametros or {}).items():
            if v is None or v == "":
                continue
            if k == "palavras_smf":
                v = "\n".join(v) if isinstance(v, (list, tuple)) else v
            campos.append((k, _json_valor(v)))
        if lancamentos is not None:
            campos.append(("lancamentos", json.dumps(lancamentos, ensure_ascii=False)))
        anexos = [(campo, nome, conteudo) for campo, lista in arquivos.items() for nome, conteudo in lista]
        corpo, tipo = _multipart(campos, anexos)
        return self._json("POST", "/analises", corpo=corpo, tipo=tipo)

    def lancamentos(self, analise_id: str) -> dict:
        return self._json("GET", f"/analises/{urllib.parse.quote(analise_id)}/lancamentos")

    def salvar_lancamentos(self, analise_id: str, corrente: list[dict] | None = None,
                           investimento: list[dict] | None = None) -> dict:
        return self._json("PUT", f"/analises/{urllib.parse.quote(analise_id)}/lancamentos",
                          json_={"corrente": corrente, "investimento": investimento})

    def atualizar_parametros(self, analise_id: str, **alteracoes: Any) -> dict:
        return self._json("PATCH", f"/analises/{urllib.parse.quote(analise_id)}/parametros",
                          json_={k: _json_valor(v) for k, v in alteracoes.items()})

    def relatorio(self, analise_id: str, formato: str = "docx") -> bytes:
        """Conteúdo do relatório: formato "docx" ou "md"."""
        if formato not in ("docx", "md"):
            raise ValueError("formato deve ser 'docx' ou 'md'")
        _, dados = self._req("GET", f"/analises/{urllib.parse.quote(analise_id)}/relatorio.{formato}")
        return dados

    def excluir(self, analise_id: str) -> None:
        self._req("DELETE", f"/analises/{urllib.parse.quote(analise_id)}")
