"""Camada de persistência SQLite do J.A.R.V.I.S. (memórias, tarefas, notas e histórico)."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator
from zoneinfo import ZoneInfo

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("JARVIS_DB_PATH", str(BASE_DIR / "jarvis.db")))


def now_brt() -> datetime:
    """Retorna datetime atual no fuso horário de Brasília (America/Sao_Paulo)."""
    return datetime.now(SAO_PAULO_TZ)


def now_iso() -> str:
    """Retorna timestamp ISO 8601 no fuso horário de Brasília."""
    return now_brt().isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Abre conexão SQLite com WAL habilitado e row_factory por nome de coluna."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Inicializa todas as tabelas e índices do banco de dados SQLite."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave TEXT NOT NULL UNIQUE,
                valor TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'geral',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_categoria ON memories(categoria);

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                prazo TEXT,
                prioridade TEXT NOT NULL DEFAULT 'média',
                status TEXT NOT NULL DEFAULT 'pendente',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                tag TEXT NOT NULL DEFAULT 'geral',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notes_tag ON notes(tag);

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachment_name TEXT,
                attachment_mime TEXT,
                voice_mode INTEGER NOT NULL DEFAULT 0,
                tool_calls_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS google_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL DEFAULT 'https://oauth2.googleapis.com/token',
                client_id TEXT,
                client_secret TEXT,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                expiry TEXT,
                email TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


# ---------------------------------------------------------------------------
# Memórias persistentes
# ---------------------------------------------------------------------------


def save_memory(chave: str, valor: str, categoria: str = "geral") -> dict[str, Any]:
    """Insere ou atualiza uma memória persistente usando a chave como identificador."""
    chave_limpa = chave.strip()
    valor_limpo = valor.strip()
    cat_limpa = (categoria or "geral").strip().lower()
    ts = now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM memories WHERE lower(chave) = lower(?)",
            (chave_limpa,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE memories
                SET chave = ?, valor = ?, categoria = ?, updated_at = ?
                WHERE id = ?
                """,
                (chave_limpa, valor_limpo, cat_limpa, ts, existing["id"]),
            )
            memory_id = existing["id"]
            action = "atualizada"
        else:
            cursor = conn.execute(
                """
                INSERT INTO memories (chave, valor, categoria, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chave_limpa, valor_limpo, cat_limpa, ts, ts),
            )
            memory_id = cursor.lastrowid
            action = "salva"

        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return {"acao": action, "memoria": dict(row)}


def search_memories(termo: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Pesquisa memórias por termo em chave, valor ou categoria."""
    termo_limpo = (termo or "").strip()
    with get_connection() as conn:
        if not termo_limpo:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            like = f"%{termo_limpo}%"
            rows = conn.execute(
                """
                SELECT * FROM memories
                WHERE chave LIKE ? OR valor LIKE ? OR categoria LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def delete_memory(memory_id: int) -> bool:
    """Remove uma memória pelo ID."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Tarefas
# ---------------------------------------------------------------------------


def _normalize_priority(prioridade: str | None) -> str:
    val = (prioridade or "média").strip().lower()
    mapping = {
        "alta": "alta",
        "high": "alta",
        "urgente": "alta",
        "media": "média",
        "média": "média",
        "medium": "média",
        "normal": "média",
        "baixa": "baixa",
        "low": "baixa",
    }
    return mapping.get(val, "média")


def _normalize_task_status(status: str | None) -> str:
    val = (status or "pendente").strip().lower()
    if val in ("concluida", "concluída", "feita", "done", "completed"):
        return "concluida"
    if val in ("todas", "all", "todos"):
        return "todas"
    return "pendente"


def add_task(
    titulo: str,
    prazo: str | None = None,
    prioridade: str = "média",
) -> dict[str, Any]:
    """Adiciona uma nova tarefa."""
    titulo_limpo = titulo.strip()
    prazo_limpo = prazo.strip() if prazo and prazo.strip() else None
    prio = _normalize_priority(prioridade)
    ts = now_iso()

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (titulo, prazo, prioridade, status, created_at)
            VALUES (?, ?, ?, 'pendente', ?)
            """,
            (titulo_limpo, prazo_limpo, prio, ts),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_tasks(status: str = "pendente") -> list[dict[str, Any]]:
    """Lista tarefas filtrando por status ('pendente', 'concluida' ou 'todas')."""
    st = _normalize_task_status(status)
    priority_order = "CASE prioridade WHEN 'alta' THEN 1 WHEN 'média' THEN 2 ELSE 3 END"
    with get_connection() as conn:
        if st == "todas":
            rows = conn.execute(
                f"""
                SELECT * FROM tasks
                ORDER BY
                    CASE status WHEN 'pendente' THEN 0 ELSE 1 END,
                    {priority_order},
                    id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY {priority_order}, id DESC
                """,
                (st,),
            ).fetchall()
        return [dict(r) for r in rows]


def complete_task(id_ou_titulo: str | int) -> dict[str, Any] | None:
    """Marca uma tarefa como concluída pelo ID ou correspondência de título."""
    ref = str(id_ou_titulo).strip()
    ts = now_iso()

    with get_connection() as conn:
        row = None
        if ref.isdigit():
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(ref),)).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pendente' AND lower(titulo) = lower(?)
                ORDER BY id DESC LIMIT 1
                """,
                (ref,),
            ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'pendente' AND lower(titulo) LIKE lower(?)
                ORDER BY id DESC LIMIT 1
                """,
                (f"%{ref}%",),
            ).fetchone()
        if row is None:
            return None

        conn.execute(
            "UPDATE tasks SET status = 'concluida', completed_at = ? WHERE id = ?",
            (ts, row["id"]),
        )
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()
        return dict(updated)


def toggle_task(task_id: int) -> dict[str, Any] | None:
    """Alterna o status de uma tarefa entre pendente e concluída."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        if row["status"] == "pendente":
            conn.execute(
                "UPDATE tasks SET status = 'concluida', completed_at = ? WHERE id = ?",
                (now_iso(), task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = 'pendente', completed_at = NULL WHERE id = ?",
                (task_id,),
            )
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(updated)


def delete_task(task_id: int) -> bool:
    """Remove uma tarefa pelo ID."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Notas
# ---------------------------------------------------------------------------


def save_note(titulo: str, conteudo: str, tag: str = "geral") -> dict[str, Any]:
    """Salva uma nova nota rápida, resumo de estudo ou ideia."""
    ts = now_iso()
    tag_limpa = (tag or "geral").strip().lower()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO notes (titulo, conteudo, tag, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titulo.strip(), conteudo.strip(), tag_limpa, ts, ts),
        )
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_notes(tag: str | None = None, termo: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Lista notas com filtro opcional por tag e termo."""
    clauses: list[str] = []
    params: list[Any] = []

    if tag and tag.strip():
        clauses.append("lower(tag) = lower(?)")
        params.append(tag.strip())
    if termo and termo.strip():
        like = f"%{termo.strip()}%"
        clauses.append("(titulo LIKE ? OR conteudo LIKE ? OR tag LIKE ?)")
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM notes {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def delete_note(note_id: int) -> bool:
    """Remove uma nota pelo ID."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Histórico de conversas
# ---------------------------------------------------------------------------


def add_message(
    role: str,
    content: str,
    session_id: str = "default",
    attachment_name: str | None = None,
    attachment_mime: str | None = None,
    voice_mode: bool = False,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persiste uma mensagem no histórico da conversa."""
    ts = now_iso()
    tools_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (
                session_id, role, content, attachment_name, attachment_mime,
                voice_mode, tool_calls_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                attachment_name,
                attachment_mime,
                1 if voice_mode else 0,
                tools_json,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _deserialize_message(row)


def _deserialize_message(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw_tools = data.pop("tool_calls_json", None)
    data["tool_calls"] = json.loads(raw_tools) if raw_tools else []
    data["voice_mode"] = bool(data.get("voice_mode"))
    return data


def get_recent_messages(session_id: str = "default", limit: int = 30) -> list[dict[str, Any]]:
    """Recupera as últimas mensagens da sessão em ordem cronológica."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) sub
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
        return [_deserialize_message(r) for r in rows]


def clear_messages(session_id: str = "default") -> int:
    """Limpa o histórico de mensagens de uma sessão."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        return cur.rowcount


def get_stats() -> dict[str, int]:
    """Retorna contagens rápidas para o painel de status do HUD."""
    with get_connection() as conn:
        pending_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pendente'"
        ).fetchone()[0]
        total_memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        total_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return {
            "tarefas_pendentes": pending_tasks,
            "memorias": total_memories,
            "notas": total_notes,
            "mensagens": total_messages,
        }


# ---------------------------------------------------------------------------
# Tokens OAuth 2.0 do Google
# ---------------------------------------------------------------------------


def save_google_tokens(
    token: str,
    refresh_token: str | None = None,
    token_uri: str = "https://oauth2.googleapis.com/token",
    client_id: str | None = None,
    client_secret: str | None = None,
    scopes: list[str] | tuple[str, ...] | None = None,
    expiry: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Salva ou atualiza os tokens OAuth 2.0 do Google na tabela google_tokens."""
    ts = now_iso()
    scopes_json = json.dumps(list(scopes or []), ensure_ascii=False)

    with get_connection() as conn:
        existing = conn.execute("SELECT refresh_token, email FROM google_tokens WHERE id = 1").fetchone()
        effective_refresh = refresh_token or (existing["refresh_token"] if existing else None)
        effective_email = email or (existing["email"] if existing else None)

        conn.execute(
            """
            INSERT INTO google_tokens (
                id, token, refresh_token, token_uri, client_id, client_secret,
                scopes_json, expiry, email, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                token = excluded.token,
                refresh_token = excluded.refresh_token,
                token_uri = excluded.token_uri,
                client_id = excluded.client_id,
                client_secret = excluded.client_secret,
                scopes_json = excluded.scopes_json,
                expiry = excluded.expiry,
                email = excluded.email,
                updated_at = excluded.updated_at
            """,
            (
                token,
                effective_refresh,
                token_uri or "https://oauth2.googleapis.com/token",
                client_id,
                client_secret,
                scopes_json,
                expiry,
                effective_email,
                ts,
            ),
        )
        row = conn.execute("SELECT * FROM google_tokens WHERE id = 1").fetchone()
        return _deserialize_google_tokens(row)


def _deserialize_google_tokens(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw_scopes = data.pop("scopes_json", "[]")
    try:
        data["scopes"] = json.loads(raw_scopes) if raw_scopes else []
    except Exception:
        data["scopes"] = []
    return data


def get_google_tokens() -> dict[str, Any] | None:
    """Recupera os tokens OAuth 2.0 do Google salvos no SQLite."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM google_tokens WHERE id = 1").fetchone()
        if not row:
            return None
        return _deserialize_google_tokens(row)


def delete_google_tokens() -> bool:
    """Remove os tokens OAuth 2.0 do Google armazenados."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM google_tokens WHERE id = 1")
        return cur.rowcount > 0
