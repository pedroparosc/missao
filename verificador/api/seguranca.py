"""Autenticação opcional por chave de API.

Se `VERIFICADOR_API_KEY` estiver definida, toda rota protegida exige o cabeçalho
`X-API-Key` com o mesmo valor; caso contrário responde 401. Sem a variável, o
backend fica aberto (uso local, como o `executar.bat`).
"""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status


def exigir_chave(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Dependência FastAPI: valida a chave de API quando ela está configurada."""
    esperada = request.app.state.config.api_key
    if not esperada:
        return
    # compare_digest evita ataques de temporização na comparação da chave.
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), esperada.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave de API ausente ou inválida (cabeçalho X-API-Key).",
                            headers={"WWW-Authenticate": "ApiKey"})
