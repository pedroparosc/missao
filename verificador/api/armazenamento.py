"""Repositório de análises: SQLite (uso local/Docker) ou PostgreSQL (Vercel + Neon).

As duas implementações têm **a mesma interface** (`criar`, `obter`, `listar`, `atualizar`,
`excluir`, `salvar_arquivo`, `listar_arquivos`, `saudavel`); o serviço não sabe qual está em uso.
A escolha é feita por `criar_repositorio(config)`:

- `config.database_url` definido (ex.: `DATABASE_URL` criada pela integração Neon da Vercel)
  -> `RepositorioPostgres`; os arquivos originais são guardados no próprio banco (BYTEA),
  porque o disco de uma função serverless é temporário.
- caso contrário -> `Repositorio` (SQLite); os arquivos ficam em disco, em
  `<pasta_uploads>/<id da análise>/`.

Esquema (igual nos dois bancos, com tipos equivalentes)
-------------------------------------------------------
analises
    id            TEXT PK   identificador (uuid4 hex)
    criado_em     TEXT      ISO-8601 UTC (ordenável como texto)
    atualizado_em TEXT      ISO-8601 UTC
    nome_projeto  TEXT      redundante (para listar sem abrir o JSON)
    cnpj_entidade TEXT
    parametros    TEXT      JSON — parâmetros da verificação (Config do núcleo)
    insumos       TEXT      JSON — dados já lidos dos documentos (lançamentos classificados,
                            planilhas, notas, projeto). Permite reprocessar sem reler os arquivos.
    resultado     TEXT      JSON — último resultado da verificação
    n_erros, n_alertas INT  contadores para a listagem

arquivos
    id, analise_id (FK, ON DELETE CASCADE), campo, nome_original, caminho, tamanho, sha256,
    conteudo (BLOB/BYTEA, só no PostgreSQL)

O nome gravado em disco é saneado para impedir *path traversal* (ex.: `../../x.pdf`).
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
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:  # pragma: no cover
    from .config import Configuracao

_ESQUEMA_SQLITE = [
    """CREATE TABLE IF NOT EXISTS analises (
        id            TEXT PRIMARY KEY,
        criado_em     TEXT NOT NULL,
        atualizado_em TEXT NOT NULL,
        nome_projeto  TEXT NOT NULL DEFAULT '',
        cnpj_entidade TEXT NOT NULL DEFAULT '',
        parametros    TEXT NOT NULL,
        insumos       TEXT NOT NULL,
        resultado     TEXT NOT NULL,
        n_erros       INTEGER NOT NULL DEFAULT 0,
        n_alertas     INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS ix_analises_criado ON analises (criado_em DESC)",
    """CREATE TABLE IF NOT EXISTS arquivos (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        analise_id    TEXT NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
        campo         TEXT NOT NULL,
        nome_original TEXT NOT NULL,
        caminho       TEXT NOT NULL,
        tamanho       INTEGER NOT NULL,
        sha256        TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_arquivos_analise ON arquivos (analise_id)",
]

_ESQUEMA_POSTGRES = [
    """CREATE TABLE IF NOT EXISTS analises (
        seq           BIGSERIAL,
        id            TEXT PRIMARY KEY,
        criado_em     TEXT NOT NULL,
        atualizado_em TEXT NOT NULL,
        nome_projeto  TEXT NOT NULL DEFAULT '',
        cnpj_entidade TEXT NOT NULL DEFAULT '',
        parametros    TEXT NOT NULL,
        insumos       TEXT NOT NULL,
        resultado     TEXT NOT NULL,
        n_erros       INTEGER NOT NULL DEFAULT 0,
        n_alertas     INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS ix_analises_criado ON analises (criado_em DESC)",
    """CREATE TABLE IF NOT EXISTS arquivos (
        id            BIGSERIAL PRIMARY KEY,
        analise_id    TEXT NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
        campo         TEXT NOT NULL,
        nome_original TEXT NOT NULL,
        caminho       TEXT NOT NULL,
        tamanho       INTEGER NOT NULL,
        sha256        TEXT NOT NULL,
        conteudo      BYTEA)""",
    "CREATE INDEX IF NOT EXISTS ix_arquivos_analise ON arquivos (analise_id)",
]

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
    """Repositório SQLite + pasta de uploads. Seguro para várias threads
    (cada operação abre a sua própria conexão).

    As subclasses trocam só os "pontos de dialeto": `_conectar`, `_esquema`, `_sql`
    (marcador de parâmetro), `_ORDEM` e o destino dos arquivos.
    """

    tipo = "sqlite"
    persistente = True
    _ORDEM = "criado_em DESC, rowid DESC"

    def __init__(self, caminho_db: Path, pasta_uploads: Path, persistente: bool = True):
        self.caminho_db = Path(caminho_db)
        self.pasta_uploads = Path(pasta_uploads)
        self.persistente = persistente
        self._iniciado = False
        self._trava = threading.Lock()

    # ------------------------------------------------------------------ pontos de dialeto
    def _esquema(self) -> list[str]:
        return _ESQUEMA_SQLITE

    def _preparar(self) -> None:
        """Ações antes de criar o esquema (no SQLite: criar as pastas)."""
        self.caminho_db.parent.mkdir(parents=True, exist_ok=True)
        self.pasta_uploads.mkdir(parents=True, exist_ok=True)

    def _conectar(self):
        con = sqlite3.connect(self.caminho_db, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @staticmethod
    def _sql(sql: str) -> str:
        """Converte o SQL escrito com `?` para o marcador do driver (SQLite já usa `?`)."""
        return sql

    # ------------------------------------------------------------------ infraestrutura
    def _inicializar(self) -> None:
        """Cria pastas e tabelas na primeira utilização (não no import, para não criar
        nada só por importar o módulo)."""
        with self._trava:
            if self._iniciado:
                return
            self._preparar()
            con = self._conectar()
            try:
                for comando in self._esquema():
                    con.execute(comando)
                con.commit()
            finally:
                con.close()  # `with connect()` só faz commit; quem fecha é close()
            self._iniciado = True

    @contextmanager
    def _conexao(self) -> Iterator[Any]:
        """Abre uma conexão; faz commit ao final ou rollback em erro, e sempre fecha."""
        self._inicializar()
        con = self._conectar()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _exec(self, con, sql: str, params: tuple = ()):
        return con.execute(self._sql(sql), params)

    def saudavel(self) -> bool:
        """True se o banco responde a uma consulta simples."""
        try:
            with self._conexao() as con:
                self._exec(con, "SELECT 1").fetchone()
            return True
        except Exception:  # noqa: BLE001 — qualquer falha de conexão = não saudável
            return False

    @staticmethod
    def _decodificar(linha) -> dict[str, Any]:
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
            self._exec(
                con,
                "INSERT INTO analises (id, criado_em, atualizado_em, nome_projeto, cnpj_entidade, parametros,"
                " insumos, resultado, n_erros, n_alertas) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (id_, agora, agora, nome_projeto, cnpj_entidade, json.dumps(parametros, ensure_ascii=False),
                 json.dumps(insumos, ensure_ascii=False), json.dumps(resultado, ensure_ascii=False),
                 n_erros, n_alertas))

    def obter(self, id_: str) -> dict[str, Any] | None:
        """Análise completa (com JSONs decodificados) ou None."""
        with self._conexao() as con:
            linha = self._exec(
                con, "SELECT id, criado_em, atualizado_em, nome_projeto, cnpj_entidade, parametros, insumos,"
                     " resultado, n_erros, n_alertas FROM analises WHERE id = ?", (id_,)).fetchone()
        return self._decodificar(linha) if linha else None

    def listar(self, limite: int = 50, deslocamento: int = 0) -> tuple[int, list[dict[str, Any]]]:
        """(total, página) das análises, mais recentes primeiro. Não carrega os insumos (pesados)."""
        with self._conexao() as con:
            total = dict(self._exec(con, "SELECT COUNT(*) AS total FROM analises").fetchone())["total"]
            linhas = self._exec(
                con,
                "SELECT id, criado_em, atualizado_em, nome_projeto, cnpj_entidade, resultado, n_erros, n_alertas"
                f" FROM analises ORDER BY {self._ORDEM} LIMIT ? OFFSET ?",
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
            cur = self._exec(con, f"UPDATE analises SET {sets} WHERE id = ?", (*valores.values(), id_))
            return cur.rowcount > 0

    def excluir(self, id_: str) -> bool:
        """Remove a análise e seus registros de arquivos (cascade) e, no SQLite, a pasta de uploads."""
        with self._conexao() as con:
            existia = self._exec(con, "DELETE FROM analises WHERE id = ?", (id_,)).rowcount > 0
        self._remover_pasta(id_)
        return existia

    # ------------------------------------------------------------------ arquivos
    def _pasta_analise(self, id_: str) -> Path:
        # O id é gerado pelo servidor (uuid hex), mas saneamos por defesa em profundidade.
        return self.pasta_uploads / re.sub(r"[^0-9a-zA-Z]", "", id_)

    def _remover_pasta(self, id_: str) -> None:
        pasta = self._pasta_analise(id_)
        if pasta.exists():
            shutil.rmtree(pasta, ignore_errors=True)

    def _gravar_conteudo(self, analise_id: str, campo: str, nome: str, conteudo: bytes, ordem: int) -> str:
        """Grava o arquivo em disco, dentro da pasta da análise, e devolve o caminho."""
        pasta = self._pasta_analise(analise_id)
        pasta.mkdir(parents=True, exist_ok=True)
        destino = (pasta / f"{campo}_{ordem:02d}_{nome_seguro(nome)}").resolve()
        # Garantia final contra path traversal: o destino precisa estar dentro da pasta da análise.
        if not destino.is_relative_to(pasta.resolve()):
            raise ValueError("Nome de arquivo inválido.")
        destino.write_bytes(conteudo)
        return str(destino)

    def salvar_arquivo(self, analise_id: str, campo: str, nome: str, conteudo: bytes, ordem: int = 0) -> dict:
        """Guarda o arquivo original e registra metadados + SHA-256."""
        caminho = self._gravar_conteudo(analise_id, campo, nome, conteudo, ordem)
        meta = {"campo": campo, "nome_original": str(nome), "caminho": caminho,
                "tamanho": len(conteudo), "sha256": hashlib.sha256(conteudo).hexdigest()}
        self._inserir_arquivo(analise_id, meta, conteudo)
        return meta

    def _inserir_arquivo(self, analise_id: str, meta: dict, conteudo: bytes) -> None:
        with self._conexao() as con:
            self._exec(con, "INSERT INTO arquivos (analise_id, campo, nome_original, caminho, tamanho, sha256)"
                            " VALUES (?,?,?,?,?,?)", (analise_id, *meta.values()))

    def listar_arquivos(self, analise_id: str) -> list[dict[str, Any]]:
        with self._conexao() as con:
            linhas = self._exec(con, "SELECT campo, nome_original, caminho, tamanho, sha256 FROM arquivos"
                                     " WHERE analise_id = ? ORDER BY id", (analise_id,)).fetchall()
        return [dict(l) for l in linhas]


class RepositorioPostgres(Repositorio):
    """Repositório PostgreSQL (ex.: Neon pela Vercel). Os arquivos originais vão para a
    coluna `arquivos.conteudo` (BYTEA), pois o disco de funções serverless não é persistente.

    Requer o pacote `psycopg` (v3), importado só quando esta classe é usada.
    """

    tipo = "postgres"
    _ORDEM = "criado_em DESC, seq DESC"

    def __init__(self, url: str):
        super().__init__(Path("."), Path("."), persistente=True)
        self.url = url

    def _esquema(self) -> list[str]:
        return _ESQUEMA_POSTGRES

    def _preparar(self) -> None:
        pass  # nada em disco

    def _conectar(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover — depende do ambiente
            raise RuntimeError("DATABASE_URL configurada, mas o driver PostgreSQL não está instalado: "
                               "pip install \"psycopg[binary]\"") from exc
        # prepare_threshold=None: desliga prepared statements, necessário com o pooler (PgBouncer) do Neon.
        return psycopg.connect(self.url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def _remover_pasta(self, id_: str) -> None:
        pass  # arquivos ficam no banco e saem por ON DELETE CASCADE

    def _gravar_conteudo(self, analise_id, campo, nome, conteudo, ordem) -> str:
        return f"db://arquivos/{campo}_{ordem:02d}_{nome_seguro(nome)}"

    def _inserir_arquivo(self, analise_id: str, meta: dict, conteudo: bytes) -> None:
        with self._conexao() as con:
            self._exec(con, "INSERT INTO arquivos (analise_id, campo, nome_original, caminho, tamanho, sha256,"
                            " conteudo) VALUES (?,?,?,?,?,?,?)", (analise_id, *meta.values(), conteudo))


def criar_repositorio(config: "Configuracao") -> Repositorio:
    """Escolhe o repositório conforme a configuração (PostgreSQL se houver URL de banco)."""
    if config.database_url:
        return RepositorioPostgres(config.database_url)
    return Repositorio(config.caminho_db, config.pasta_uploads, persistente=config.disco_persistente)
