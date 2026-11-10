"""Exporta o contrato OpenAPI da API para `docs/openapi.json` (na raiz do repositório).

Uso (na pasta `verificador/`):  python -m api.exportar_openapi [caminho_de_saida]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import RAIZ_PROJETO
from .main import criar_app


def main() -> None:
    saida = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ_PROJETO.parent / "docs" / "openapi.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    esquema = criar_app().openapi()
    saida.write_text(json.dumps(esquema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI {esquema['info']['version']} exportado para {saida}")


if __name__ == "__main__":
    main()
