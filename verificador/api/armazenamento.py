"""Repositório de análises: banco SQLite + arquivos originais em disco.

Esquema
-------
analises
    id            TEXT PK   identificador (uuid4 hex)
    criado_em     TEXT      ISO-8601 UTC
    atualizado_em TEXT      ISO-8601 UTC
    nome_projeto  TEXT      redundante (para listar sem abrir o JSON)
    cnpj_entidade TEXT
    parametros    TEXT      JSON — parâmetros da verificação (Config do núcleo)
    insumos       TEXT      JSON — dados já lidos dos documentos (lançamentos classificados,
                            planilhas, notas, projeto). Permite reprocessar sem reler os arquivos.
    resultado     TEXT      JSON — último resultado da verificação
    n_erros, n_alertas INT  contadores para a listagem

arquivos
    id, analise_id (FK, ON DELETE CASCADE), campo, nome_original, caminho, tamanho, sha256

Os arquivos ficam em `<pasta_uploads>/<id da análise>/`. O nome gravado é saneado para
impedir *path traversal* (ex.: `../../x.pdf`) e caracteres inválidos no Windows.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS analises (
    id            TEXT PRIMARY KEY,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    nome_projeto  TEXT NOT NULL DEFAULT '',
    cnpj_entidade TEXT NOT NULL DEFAULT '',
    parametros    TEXT NOT NULL,
    insumos       TEXT NOT NULL,
    resultado     TEXT NOT NULL,
    n_erros       INTEGER NOT NULL DEFAULT 0,
    n_alertas     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_analises_criado ON analises (criado_em DESC);
CREATE TABLE IF NOT EXISTS arquivos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id    TEXT NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
    campo         TEXT NOT NULL,
    nome_original TEXT NOT NULL,
    caminho       TEXT NOT NULL,
    tamanho       INTEGER NOT NULL,
    sha256        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_arquivos_analise ON arquivos (analise_id);
"""

# Colunas JSON da tabela `analises` (são codificadas/decodificadas automaticamente).
_CAMPOS_JSON = ("parametros", "insumos", "resultado")


def agora_iso() -> str:
    """Data/hora atual em UTC, ISO-8601 com segundos (ordenável como texto)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nome_seguro(nome: str, limite: int = 120) -> str:
    """Saneia um nome de arquivo vindo do cliente.

    Remove qualquer diretório (com `/` ou `\\`), caracteres fora de letras/dígitos/`._- `,
    pontos iniciais (arquivos ocultos, `..`) e limita o tamanho preservando a extensão.
    """
    base = str(nome or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^\w.\- ]", "_", base).strip().lstrip(".")
    if not base:
        return "arquivo"
    if len(base) > limite:
        raiz, _, ext = base.rpartition(".")
        base = (raiz[: limite - len(ext) - 1] + "." + ext) if raiz and len(ext) <= 10 else base[:limite]
    return base


class Repositorio:
    """Acesso ao SQLite e à pasta de uploads. Seguro para uso por várias threads
    (cada operação abre a sua própria conexão)."""

    def __init__(self, caminho_db: Path, pasta_uploads: Path):
        self.caminho_db = Path(caminho_db)
        self.pasta_uploads = Path(pasta_uploads)
        self._iniciado = False
        self._trava = threading.Lock()

    # ------------------------------------------------------------------ infraestrutura
    def _inicializar(self) -> None:
        """Cria pastas e tabelas na primeira utilização (não no import, para não criar
        `data/` só por importar o módulo)."""
        with self._trava:
            if self._iniciado:
                return
            self.caminho_db.parent.mkdir(parents=True, exist_ok=True)
            self.pasta_uploads.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.caminho_db)
            try:
                con.executescript(_ESQUEMA)
            finally:
                con.close()  # `with sqlite3.connect()` só faz commit; quem fecha é close()
            self._iniciado = True

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão com chaves estrangeiras ativas; faz commit ao final ou rollback em erro."""
        self._inicializar()
        con = sqlite3.connect(self.caminho_db, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def saudavel(self) -> bool:
        """True se o banco responde a uma consulta simples."""
        try:
            with self._conexao() as con:
                con.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    @staticmethod
    def _decodificar(linha: sqlite3.Row) -> dict[str, Any]:
        d = dict(linha)
        for c in _CAMPOS_JSON:
            if c in d and d[c] is not None:
                d[c] = json.loads(d[c])
        return d

    # ------------------------------------------------------------------ análises
    def criar(self, id_: str, parametros: dict, insumos: dict, resultado: dict,
              nome_projeto: str = "", cnpj_entidade: str = "", n_erros: int = 0, n_alertas: int = 0) -> None:
        agora = agora_iso()
        with self._conexao() as con:
            con.execute(
                "INSERT INTO analises (id, criado_em, atualizado_em, nome_projeto, cnpj_entidade, parametros,"
                " insumos, resultado, n_erros, n_alertas) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (id_, agora, agora, nome_projeto, cnpj_entidade, json.dumps(parametros, ensure_ascii=False),
                 json.dumps(insumos, ensure_ascii=False), json.dumps(resultado, ensure_ascii=False),
                 n_erros, n_alertas))

    def obter(self, id_: str) -> dict[str, Any] | None:
        """Análise completa (com JSONs decodificados) ou None."""
        with self._conexao() as con:
            linha = con.execute("SELECT * FROM analises WHERE id = ?", (id_,)).fetchone()
        return self._decodificar(linha) if linha else None

    def listar(self, limite: int = 50, deslocamento: int = 0) -> tuple[int, list[dict[str, Any]]]:
        """(total, página) das análises, mais recentes primeiro. Não carrega os insumos (pesados)."""
        with self._conexao() as con:
            total = con.execute("SELECT COUNT(*) FROM analises").fetchone()[0]
            linhas = con.execute(
                "SELECT id, criado_em, atualizado_em, nome_projeto, cnpj_entidade, resultado, n_erros, n_alertas"
                " FROM analises ORDER BY criado_em DESC, rowid DESC LIMIT ? OFFSET ?",
                (limite, deslocamento)).fetchall()
        return total, [self._decodificar(l) for l in linhas]

    def atualizar(self, id_: str, **campos: Any) -> bool:
        """Atualiza colunas informadas (JSONs são codificados). Retorna False se o id não existe."""
        permitidos = {"nome_projeto", "cnpj_entidade", "n_erros", "n_alertas", *_CAMPOS_JSON}
        invalidos = set(campos) - permitidos
        if invalidos:
            raise ValueError(f"Campos não atualizáveis: {sorted(invalidos)}")
        valores = {k: (json.dumps(v, ensure_ascii=False) if k in _CAMPOS_JSON else v) for k, v in campos.items()}
        valores["atualizado_em"] = agora_iso()
        sets = ", ".join(f"{k} = ?" for k in valores)  # nomes vêm da lista branca acima
        with self._conexao() as con:
            cur = con.execute(f"UPDATE analises SET {sets} WHERE id = ?", (*valores.values(), id_))
        return cur.rowcount > 0

    def excluir(self, id_: str) -> bool:
        """Remove a análise, seus registros de arquivos (cascade) e a pasta de uploads."""
        with self._conexao() as con:
            cur = con.execute("DELETE FROM analises WHERE id = ?", (id_,))
        pasta = self._pasta_analise(id_)
        if pasta.exists():
            shutil.rmtree(pasta, ignore_errors=True)
        return cur.rowcount > 0

    # ------------------------------------------------------------------ arquivos
    def _pasta_analise(self, id_: str) -> Path:
        # O id é gerado pelo servidor (uuid hex), mas saneamos por defesa em profundidade.
        return self.pasta_uploads / re.sub(r"[^0-9a-zA-Z]", "", id_)

    def salvar_arquivo(self, analise_id: str, campo: str, nome: str, conteudo: bytes, ordem: int = 0) -> dict:
        """Grava o arquivo original dentro da pasta da análise e registra metadados + SHA-256."""
        pasta = self._pasta_analise(analise_id)
        pasta.mkdir(parents=True, exist_ok=True)
        destino = (pasta / f"{campo}_{ordem:02d}_{nome_seguro(nome)}").resolve()
        # Garantia final contra path traversal: o destino precisa estar dentro da pasta da análise.
        if not destino.is_relative_to(pasta.resolve()):
            raise ValueError("Nome de arquivo inválido.")
        destino.write_bytes(conteudo)
        meta = {"campo": campo, "nome_original": str(nome), "caminho": str(destino),
                "tamanho": len(conteudo), "sha256": hashlib.sha256(conteudo).hexdigest()}
        with self._conexao() as con:
            con.execute("INSERT INTO arquivos (analise_id, campo, nome_original, caminho, tamanho, sha256)"
                        " VALUES (?,?,?,?,?,?)", (analise_id, *meta.values()))
        return meta

    def listar_arquivos(self, analise_id: str) -> list[dict[str, Any]]:
        with self._conexao() as con:
            linhas = con.execute("SELECT campo, nome_original, caminho, tamanho, sha256 FROM arquivos"
                                 " WHERE analise_id = ? ORDER BY id", (analise_id,)).fetchall()
        return [dict(l) for l in linhas]
