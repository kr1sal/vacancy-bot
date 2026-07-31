import json
import sqlite3
from config import DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        pass  # already exists


def init_db() -> None:
    with _conn() as conn:
        # WAL mode + разумный busy_timeout: writer из бота и FastAPI больше не конфликтуют
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_vacancies (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                company TEXT,
                url TEXT,
                salary TEXT,
                description TEXT,
                viewed INTEGER DEFAULT 0,
                starred INTEGER DEFAULT 0,
                applied INTEGER DEFAULT 0,
                applied_at TIMESTAMP,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS generated_letters (
                vacancy_id TEXT PRIMARY KEY,
                letter TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vacancy_summaries (
                vacancy_id TEXT PRIMARY KEY,
                summary_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        _add_column_if_missing(conn, "seen_vacancies", "salary", "TEXT")
        _add_column_if_missing(conn, "seen_vacancies", "description", "TEXT")
        _add_column_if_missing(conn, "seen_vacancies", "viewed", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "seen_vacancies", "starred", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "seen_vacancies", "applied", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "seen_vacancies", "applied_at", "TIMESTAMP")
        _add_column_if_missing(conn, "seen_vacancies", "match_decision", "TEXT")


def is_seen(vacancy_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM seen_vacancies WHERE id = ?", (vacancy_id,)).fetchone()
        return row is not None


def mark_seen(vacancy_id: str, source: str, title: str, company: str,
              url: str, salary: str = "", description: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO seen_vacancies
               (id, source, title, company, url, salary, description)
               VALUES (?,?,?,?,?,?,?)""",
            (vacancy_id, source, title, company, url, salary, description),
        )


def list_vacancies(filter_type: str = "all") -> list[dict]:
    where = ""
    if filter_type == "new":
        where = "WHERE viewed = 0"
    elif filter_type == "viewed":
        where = "WHERE viewed = 1"
    elif filter_type == "starred":
        where = "WHERE starred = 1"
    elif filter_type == "applied":
        where = "WHERE applied = 1"
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT sv.*, s.summary_json,
                       CASE WHEN l.vacancy_id IS NULL THEN 0 ELSE 1 END AS has_letter
                FROM seen_vacancies sv
                LEFT JOIN vacancy_summaries s ON s.vacancy_id = sv.id
                LEFT JOIN generated_letters l ON l.vacancy_id = sv.id
                {where}
                ORDER BY sv.seen_at DESC"""
        ).fetchall()
        return [_serialize(r) for r in rows]


def get_vacancy(vacancy_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            """SELECT sv.*, s.summary_json, l.letter,
                      CASE WHEN l.vacancy_id IS NULL THEN 0 ELSE 1 END AS has_letter
               FROM seen_vacancies sv
               LEFT JOIN vacancy_summaries s ON s.vacancy_id = sv.id
               LEFT JOIN generated_letters l ON l.vacancy_id = sv.id
               WHERE sv.id = ?""",
            (vacancy_id,),
        ).fetchone()
        if not row:
            return None
        data = _serialize(row)
        data["letter"] = row["letter"] if "letter" in row.keys() else None
        return data


def _serialize(row: sqlite3.Row) -> dict:
    keys = row.keys()
    summary = None
    if "summary_json" in keys and row["summary_json"]:
        try:
            summary = json.loads(row["summary_json"])
        except Exception:
            summary = None
    return {
        "id": row["id"],
        "source": row["source"],
        "title": row["title"],
        "company": row["company"],
        "url": row["url"],
        "salary": row["salary"] if "salary" in keys else "",
        "description": row["description"] if "description" in keys else "",
        "viewed": bool(row["viewed"]) if "viewed" in keys else False,
        "starred": bool(row["starred"]) if "starred" in keys else False,
        "applied": bool(row["applied"]) if "applied" in keys else False,
        "applied_at": row["applied_at"] if "applied_at" in keys else None,
        "match_decision": row["match_decision"] if "match_decision" in keys else None,
        "seen_at": row["seen_at"],
        "summary": summary,
        "has_letter": bool(row["has_letter"]) if "has_letter" in keys else False,
    }


def mark_viewed(vacancy_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE seen_vacancies SET viewed = 1 WHERE id = ?", (vacancy_id,))


def toggle_applied(vacancy_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT applied FROM seen_vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()
        if not row:
            return False
        new_val = 0 if row["applied"] else 1
        conn.execute(
            "UPDATE seen_vacancies SET applied = ?, applied_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id = ?",
            (new_val, new_val, vacancy_id),
        )
        return bool(new_val)


def toggle_star(vacancy_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT starred FROM seen_vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()
        if not row:
            return False
        new_val = 0 if row["starred"] else 1
        conn.execute("UPDATE seen_vacancies SET starred = ? WHERE id = ?", (new_val, vacancy_id))
        return bool(new_val)


def counts() -> dict:
    with _conn() as conn:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN viewed = 0 THEN 1 ELSE 0 END) AS new_count,
                 SUM(CASE WHEN viewed = 1 THEN 1 ELSE 0 END) AS viewed_count,
                 SUM(CASE WHEN starred = 1 THEN 1 ELSE 0 END) AS starred_count,
                 SUM(CASE WHEN applied = 1 THEN 1 ELSE 0 END) AS applied_count,
                 SUM(CASE WHEN match_decision IS NULL THEN 1 ELSE 0 END) AS match_pending_count,
                 COUNT(*) AS total
               FROM seen_vacancies"""
        ).fetchone()
        return {
            "new": row["new_count"] or 0,
            "viewed": row["viewed_count"] or 0,
            "starred": row["starred_count"] or 0,
            "applied": row["applied_count"] or 0,
            "match_pending": row["match_pending_count"] or 0,
            "all": row["total"] or 0,
        }


def match_queue(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT sv.*, s.summary_json,
                      CASE WHEN l.vacancy_id IS NULL THEN 0 ELSE 1 END AS has_letter
               FROM seen_vacancies sv
               LEFT JOIN vacancy_summaries s ON s.vacancy_id = sv.id
               LEFT JOIN generated_letters l ON l.vacancy_id = sv.id
               WHERE sv.match_decision IS NULL
               ORDER BY sv.seen_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_serialize(r) for r in rows]


def set_match_decision(vacancy_id: str, decision: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT id FROM seen_vacancies WHERE id = ?", (vacancy_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE seen_vacancies SET match_decision = ?, viewed = 1 WHERE id = ?",
            (decision, vacancy_id),
        )
        return True


def save_letter(vacancy_id: str, letter: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO generated_letters (vacancy_id, letter) VALUES (?,?)",
            (vacancy_id, letter),
        )


def get_letter(vacancy_id: str) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT letter FROM generated_letters WHERE vacancy_id = ?", (vacancy_id,)
        ).fetchone()
        return row["letter"] if row else None


def save_summary(vacancy_id: str, summary: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vacancy_summaries (vacancy_id, summary_json) VALUES (?,?)",
            (vacancy_id, json.dumps(summary, ensure_ascii=False)),
        )


def get_summary(vacancy_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT summary_json FROM vacancy_summaries WHERE vacancy_id = ?", (vacancy_id,)
        ).fetchone()
        return json.loads(row["summary_json"]) if row else None
