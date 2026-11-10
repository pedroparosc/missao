"""Exportação do contrato OpenAPI (docs/openapi.json) e coerência com a documentação."""
import json
import sys
from pathlib import Path

from api import exportar_openapi

RAIZ_REPO = Path(__file__).resolve().parents[2]


def test_exportar_openapi(tmp_path, monkeypatch):
    saida = tmp_path / "openapi.json"
    monkeypatch.setattr(sys, "argv", ["exportar_openapi", str(saida)])
    exportar_openapi.main()
    esquema = json.loads(saida.read_text(encoding="utf-8"))
    assert esquema["info"]["title"].startswith("Verificador de Prestação de Contas")
    assert {"/api/v1/saude", "/api/v1/parametros", "/api/v1/analises", "/api/v1/analises/{analise_id}",
            "/api/v1/analises/{analise_id}/lancamentos", "/api/v1/analises/{analise_id}/parametros",
            "/api/v1/analises/{analise_id}/relatorio.docx", "/api/v1/analises/{analise_id}/relatorio.md"
            } <= set(esquema["paths"])


def test_docs_api_cobre_todas_as_rotas():
    """Toda rota do OpenAPI precisa aparecer em docs/API.md (documentação mantida em dia)."""
    from api.main import criar_app
    doc = (RAIZ_REPO / "docs" / "API.md").read_text(encoding="utf-8")
    for caminho, metodos in criar_app().openapi()["paths"].items():
        for metodo in metodos:
            assert f"{metodo.upper()} {caminho.removeprefix('/api/v1')}" in doc, f"{metodo.upper()} {caminho}"
