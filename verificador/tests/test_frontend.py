"""Testes do frontend Streamlit (`app.py`) com o AppTest oficial do Streamlit.

Garantem que a integração com o backend é opcional (tarefa 5.4 do plano):
sem `VERIFICADOR_API_URL` o app não mostra nada do servidor nem faz chamadas de rede.
"""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _textos(at) -> str:
    partes = [e.value for e in (*at.info, *at.warning, *at.caption, *at.subheader)]
    partes += [e.label for e in at.expander]
    return "\n".join(str(p) for p in partes)


def test_sem_api_configurada_nao_mostra_servidor(monkeypatch):
    monkeypatch.delenv("VERIFICADOR_API_URL", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    texto = _textos(at)
    assert "Envie ao menos os extratos" in texto
    assert "Servidor" not in texto and "Histórico" not in texto


def test_api_configurada_mas_indisponivel_avisa(monkeypatch):
    monkeypatch.setenv("VERIFICADOR_API_URL", "http://127.0.0.1:9")  # porta fechada
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    texto = _textos(at)
    assert "API indisponível" in texto
    assert "Histórico de análises (servidor)" in texto
