"""
SQLite persistence layer for JRVS YouTube data.

Stores channel metadata, video statistics, embeddings metadata,
cluster assignments, predictions, and thumbnail analysis results.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from jrvs.config import Config
from jrvs.utils.logger import setup_logger, log_db_operation, log_error

# Initialize logger
logger = setup_logger('jrvs.database')


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id   TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    subscribers  INTEGER DEFAULT 0,
    total_views  INTEGER DEFAULT 0,
    video_count  INTEGER DEFAULT 0,
    description  TEXT DEFAULT '',
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id        TEXT PRIMARY KEY,
    channel_id      TEXT NOT NULL,
    title           TEXT NOT NULL,
    published_at    TEXT NOT NULL,
    views           INTEGER DEFAULT 0,
    likes           INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    duration        TEXT DEFAULT '',
    tags            TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    thumbnail_url   TEXT DEFAULT '',
    fetched_at      TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE IF NOT EXISTS video_features (
    video_id            TEXT PRIMARY KEY,
    view_velocity       REAL DEFAULT 0,
    engagement_rate     REAL DEFAULT 0,
    likes_per_view      REAL DEFAULT 0,
    comments_per_view   REAL DEFAULT 0,
    title_length        INTEGER DEFAULT 0,
    title_word_count    INTEGER DEFAULT 0,
    tag_count           INTEGER DEFAULT 0,
    has_numbers_in_title INTEGER DEFAULT 0,
    has_question_in_title INTEGER DEFAULT 0,
    days_since_upload   REAL DEFAULT 0,
    hour_of_publish     INTEGER DEFAULT 0,
    day_of_week         INTEGER DEFAULT 0,
    duration_seconds    INTEGER DEFAULT 0,
    title_sentiment     REAL DEFAULT 0,
    title_positive      REAL DEFAULT 0,
    title_negative      REAL DEFAULT 0,
    desc_length         INTEGER DEFAULT 0,
    desc_word_count     INTEGER DEFAULT 0,
    link_count          INTEGER DEFAULT 0,
    hashtag_count       INTEGER DEFAULT 0,
    has_cta             INTEGER DEFAULT 0,
    has_timestamps      INTEGER DEFAULT 0,
    title_in_tags       INTEGER DEFAULT 0,
    computed_at         TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS video_clusters (
    video_id    TEXT PRIMARY KEY,
    cluster_id  INTEGER DEFAULT -1,
    topic_label TEXT DEFAULT '',
    umap_x      REAL DEFAULT 0,
    umap_y      REAL DEFAULT 0,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS video_predictions (
    video_id        TEXT PRIMARY KEY,
    predicted_views REAL DEFAULT 0,
    actual_views    INTEGER DEFAULT 0,
    residual        REAL DEFAULT 0,
    outlier_score   REAL DEFAULT 0,
    computed_at     TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE TABLE IF NOT EXISTS thumbnail_analysis (
    video_id            TEXT PRIMARY KEY,
    dominant_colors     TEXT DEFAULT '[]',
    has_face            INTEGER DEFAULT 0,
    has_text_overlay    INTEGER DEFAULT 0,
    brightness          REAL DEFAULT 0,
    contrast            REAL DEFAULT 0,
    clip_features_json  TEXT DEFAULT '',
    computed_at         TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE INDEX IF NOT EXISTS idx_videos_channel   ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_views     ON videos(views DESC);
CREATE INDEX IF NOT EXISTS idx_features_video   ON video_features(video_id);
CREATE INDEX IF NOT EXISTS idx_clusters_cluster ON video_clusters(cluster_id);
CREATE INDEX IF NOT EXISTS idx_predictions_outlier ON video_predictions(outlier_score DESC);

CREATE TABLE IF NOT EXISTS web_search_results (
    result_id   TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    snippet     TEXT DEFAULT '',
    source      TEXT DEFAULT 'brave',
    fetched_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_web_query ON web_search_results(query);
CREATE INDEX IF NOT EXISTS idx_web_fetched ON web_search_results(fetched_at DESC);

CREATE TABLE IF NOT EXISTS youtube_search_results (
    result_id     TEXT PRIMARY KEY,
    query         TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    title         TEXT NOT NULL,
    channel_title TEXT DEFAULT '',
    channel_id    TEXT DEFAULT '',
    views         INTEGER DEFAULT 0,
    url           TEXT DEFAULT '',
    description   TEXT DEFAULT '',
    source        TEXT DEFAULT 'youtube',
    fetched_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_yt_search_query   ON youtube_search_results(query);
CREATE INDEX IF NOT EXISTS idx_yt_search_fetched ON youtube_search_results(fetched_at DESC);

-- ── Autonomous Agent ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      TEXT PRIMARY KEY,
    goal_id     TEXT NOT NULL,
    goal_text   TEXT NOT NULL,
    schedule    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/running/done/failed/paused
    plan_json   TEXT DEFAULT '[]',
    started_at  TEXT,
    finished_at TEXT,
    summary     TEXT DEFAULT '',
    error       TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_goal    ON agent_runs(goal_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status  ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started ON agent_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS agent_actions (
    action_id   TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    goal_id     TEXT NOT NULL,
    step        INTEGER NOT NULL DEFAULT 0,
    tier        TEXT NOT NULL DEFAULT 'notify',  -- auto/notify/confirm/blocked
    tool        TEXT NOT NULL,
    args_json   TEXT DEFAULT '{}',
    result_json TEXT DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending', -- pending/approved/denied/done/failed
    created_at  TEXT NOT NULL,
    executed_at TEXT DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_actions_run    ON agent_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_status ON agent_actions(status);
CREATE INDEX IF NOT EXISTS idx_agent_actions_tier   ON agent_actions(tier);

CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id  TEXT PRIMARY KEY,
    goal_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_memory_key ON agent_memory(goal_id, key);
"""


class Database:
    """Thin wrapper around SQLite for JRVS data."""

    def __init__(self) -> None:
        Config.ensure_dirs()
        self._db_path = str(Config.DB_PATH)
        logger.info("Database initialized", extra={'db_path': self._db_path})
        self._init_schema()

    # ── connection helpers ──────────────────────────────────────────────
    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        start_time = time.time()
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
            duration = time.time() - start_time
            log_db_operation('schema_init', 'all_tables', duration=duration)
            logger.info("Database schema initialized", extra={'duration': duration})
        except Exception as e:
            log_error(e, {'operation': 'schema_init', 'db_path': self._db_path})
            raise

    # ── Channel CRUD ────────────────────────────────────────────────────
    def upsert_channel(self, data: dict[str, Any]) -> None:
        start_time = time.time()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO channels (channel_id, title, subscribers, total_views,
                                          video_count, description, fetched_at)
                    VALUES (:channel_id, :title, :subscribers, :total_views,
                            :video_count, :description, :fetched_at)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        title       = excluded.title,
                        subscribers = excluded.subscribers,
                        total_views = excluded.total_views,
                        video_count = excluded.video_count,
                        description = excluded.description,
                        fetched_at  = excluded.fetched_at
                    """,
                {**data, "fetched_at": _now()},
                )
                affected_rows = cursor.rowcount
            duration = time.time() - start_time
            log_db_operation('upsert', 'channels', affected_rows=affected_rows, duration=duration)
            logger.info("Channel upserted", extra={
                'channel_id': data.get('channel_id'),
                'channel_title': data.get('title'),
                'affected_rows': affected_rows,
                'duration': duration
            })
        except Exception as e:
            duration = time.time() - start_time
            log_error(e, {
                'operation': 'upsert_channel', 
                'channel_id': data.get('channel_id'),
                'duration': duration
            })
            raise

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        start_time = time.time()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
                ).fetchone()
                result = dict(row) if row else None
                duration = time.time() - start_time
                log_db_operation('select', 'channels', affected_rows=1 if result else 0, duration=duration)
                logger.debug("Channel retrieved", extra={
                    'channel_id': channel_id,
                    'found': result is not None,
                    'duration': duration
                })
                return result
        except Exception as e:
            duration = time.time() - start_time
            log_error(e, {
                'operation': 'get_channel',
                'channel_id': channel_id,
                'duration': duration
            })
            raise

    # ── Video CRUD ──────────────────────────────────────────────────────
    def upsert_videos(self, videos: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO videos (video_id, channel_id, title, published_at,
                                    views, likes, comments, duration, tags,
                                    description, thumbnail_url, fetched_at)
                VALUES (:video_id, :channel_id, :title, :published_at,
                        :views, :likes, :comments, :duration, :tags,
                        :description, :thumbnail_url, :fetched_at)
                ON CONFLICT(video_id) DO UPDATE SET
                    views         = excluded.views,
                    likes         = excluded.likes,
                    comments      = excluded.comments,
                    thumbnail_url = excluded.thumbnail_url,
                    fetched_at    = excluded.fetched_at
                """,
                [{**v, "fetched_at": _now()} for v in videos],
            )

    def get_videos(self, channel_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE channel_id = ? ORDER BY published_at DESC LIMIT ?",
                (channel_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_videos_for_channel(self, channel_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE channel_id = ? ORDER BY published_at DESC",
                (channel_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Feature Engineering ─────────────────────────────────────────────
    def upsert_features(self, features: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO video_features
                    (video_id, view_velocity, engagement_rate, likes_per_view,
                     comments_per_view, title_length, title_word_count, tag_count,
                     has_numbers_in_title, has_question_in_title, days_since_upload,
                     hour_of_publish, day_of_week, duration_seconds,
                     title_sentiment, title_positive, title_negative,
                     desc_length, desc_word_count, link_count, hashtag_count,
                     has_cta, has_timestamps, title_in_tags, computed_at)
                VALUES
                    (:video_id, :view_velocity, :engagement_rate, :likes_per_view,
                     :comments_per_view, :title_length, :title_word_count, :tag_count,
                     :has_numbers_in_title, :has_question_in_title, :days_since_upload,
                     :hour_of_publish, :day_of_week, :duration_seconds,
                     :title_sentiment, :title_positive, :title_negative,
                     :desc_length, :desc_word_count, :link_count, :hashtag_count,
                     :has_cta, :has_timestamps, :title_in_tags, :computed_at)
                ON CONFLICT(video_id) DO UPDATE SET
                    view_velocity        = excluded.view_velocity,
                    engagement_rate      = excluded.engagement_rate,
                    likes_per_view       = excluded.likes_per_view,
                    comments_per_view    = excluded.comments_per_view,
                    title_length         = excluded.title_length,
                    title_word_count     = excluded.title_word_count,
                    tag_count            = excluded.tag_count,
                    has_numbers_in_title = excluded.has_numbers_in_title,
                    has_question_in_title= excluded.has_question_in_title,
                    days_since_upload    = excluded.days_since_upload,
                    hour_of_publish      = excluded.hour_of_publish,
                    day_of_week          = excluded.day_of_week,
                    duration_seconds     = excluded.duration_seconds,
                    title_sentiment      = excluded.title_sentiment,
                    title_positive       = excluded.title_positive,
                    title_negative       = excluded.title_negative,
                    desc_length          = excluded.desc_length,
                    desc_word_count      = excluded.desc_word_count,
                    link_count           = excluded.link_count,
                    hashtag_count        = excluded.hashtag_count,
                    has_cta              = excluded.has_cta,
                    has_timestamps       = excluded.has_timestamps,
                    title_in_tags        = excluded.title_in_tags,
                    computed_at          = excluded.computed_at
                """,
                [{**f, "computed_at": _now()} for f in features],
            )

    def get_features(self, channel_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT vf.* FROM video_features vf
                JOIN videos v ON vf.video_id = v.video_id
                WHERE v.channel_id = ?
                """,
                (channel_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Cluster assignments ─────────────────────────────────────────────
    def upsert_clusters(self, clusters: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO video_clusters
                    (video_id, cluster_id, topic_label, umap_x, umap_y, computed_at)
                VALUES
                    (:video_id, :cluster_id, :topic_label, :umap_x, :umap_y, :computed_at)
                ON CONFLICT(video_id) DO UPDATE SET
                    cluster_id  = excluded.cluster_id,
                    topic_label = excluded.topic_label,
                    umap_x      = excluded.umap_x,
                    umap_y      = excluded.umap_y,
                    computed_at = excluded.computed_at
                """,
                [{**c, "computed_at": _now()} for c in clusters],
            )

    def get_clusters(self, channel_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT vc.*, v.title, v.views FROM video_clusters vc
                JOIN videos v ON vc.video_id = v.video_id
                WHERE v.channel_id = ?
                ORDER BY vc.cluster_id, v.views DESC
                """,
                (channel_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Predictions ─────────────────────────────────────────────────────
    def upsert_predictions(self, preds: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO video_predictions
                    (video_id, predicted_views, actual_views, residual,
                     outlier_score, computed_at)
                VALUES
                    (:video_id, :predicted_views, :actual_views, :residual,
                     :outlier_score, :computed_at)
                ON CONFLICT(video_id) DO UPDATE SET
                    predicted_views = excluded.predicted_views,
                    actual_views    = excluded.actual_views,
                    residual        = excluded.residual,
                    outlier_score   = excluded.outlier_score,
                    computed_at     = excluded.computed_at
                """,
                [{**p, "computed_at": _now()} for p in preds],
            )

    def get_predictions(self, channel_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT vp.*, v.title FROM video_predictions vp
                JOIN videos v ON vp.video_id = v.video_id
                WHERE v.channel_id = ?
                ORDER BY vp.outlier_score DESC
                """,
                (channel_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Thumbnail Analysis ──────────────────────────────────────────────
    def upsert_thumbnail_analysis(self, rows_data: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO thumbnail_analysis
                    (video_id, dominant_colors, has_face, has_text_overlay,
                     brightness, contrast, clip_features_json, computed_at)
                VALUES
                    (:video_id, :dominant_colors, :has_face, :has_text_overlay,
                     :brightness, :contrast, :clip_features_json, :computed_at)
                ON CONFLICT(video_id) DO UPDATE SET
                    dominant_colors   = excluded.dominant_colors,
                    has_face          = excluded.has_face,
                    has_text_overlay  = excluded.has_text_overlay,
                    brightness        = excluded.brightness,
                    contrast          = excluded.contrast,
                    clip_features_json= excluded.clip_features_json,
                    computed_at       = excluded.computed_at
                """,
                [{**r, "computed_at": _now()} for r in rows_data],
            )

    def get_thumbnail_analysis(self, channel_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ta.*, v.title, v.views FROM thumbnail_analysis ta
                JOIN videos v ON ta.video_id = v.video_id
                WHERE v.channel_id = ?
                ORDER BY v.views DESC
                """,
                (channel_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("dominant_colors"):
                    try:
                        d["dominant_colors"] = json.loads(d["dominant_colors"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                result.append(d)
            return result


    # ── YouTube Search Results ───────────────────────────────────────
    def upsert_youtube_search_results(self, results: list[dict[str, Any]]) -> None:
        """Persist YouTube search results (idempotent on result_id)."""
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO youtube_search_results
                    (result_id, query, video_id, title, channel_title, channel_id,
                     views, url, description, source, fetched_at)
                VALUES
                    (:result_id, :query, :video_id, :title, :channel_title, :channel_id,
                     :views, :url, :description, :source, :fetched_at)
                ON CONFLICT(result_id) DO UPDATE SET
                    views      = excluded.views,
                    fetched_at = excluded.fetched_at
                """,
                [{**r, "fetched_at": _now()} for r in results],
            )

    def get_youtube_search_results(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return the most recent YouTube search results, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM youtube_search_results ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Web Search Results ────────────────────────────────────────────
    def upsert_web_results(self, results: list[dict[str, Any]]) -> None:
        """Persist web search results (idempotent on result_id)."""
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO web_search_results
                    (result_id, query, title, url, snippet, source, fetched_at)
                VALUES
                    (:result_id, :query, :title, :url, :snippet, :source, :fetched_at)
                ON CONFLICT(result_id) DO UPDATE SET
                    snippet    = excluded.snippet,
                    fetched_at = excluded.fetched_at
                """,
                [{**r, "fetched_at": _now()} for r in results],
            )

    def get_web_results(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return the most recent web search results, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM web_search_results ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_web_results_for_query(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Exact-query lookup — used to skip re-fetching recent results."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM web_search_results
                WHERE query = ?
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Autonomous Agent ──────────────────────────────────────────────

    def upsert_agent_run(self, run: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs
                    (run_id, goal_id, goal_text, schedule, status,
                     plan_json, started_at, finished_at, summary, error)
                VALUES
                    (:run_id, :goal_id, :goal_text, :schedule, :status,
                     :plan_json, :started_at, :finished_at, :summary, :error)
                ON CONFLICT(run_id) DO UPDATE SET
                    status      = excluded.status,
                    plan_json   = excluded.plan_json,
                    finished_at = excluded.finished_at,
                    summary     = excluded.summary,
                    error       = excluded.error
                """,
                run,
            )

    def get_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_agent_action(self, action: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_actions
                    (action_id, run_id, goal_id, step, tier, tool,
                     args_json, result_json, status, created_at, executed_at)
                VALUES
                    (:action_id, :run_id, :goal_id, :step, :tier, :tool,
                     :args_json, :result_json, :status, :created_at, :executed_at)
                ON CONFLICT(action_id) DO UPDATE SET
                    status      = excluded.status,
                    result_json = excluded.result_json,
                    executed_at = excluded.executed_at
                """,
                action,
            )

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_pending_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_actions "
                "WHERE status IN ('pending', 'awaiting_approval') "
                "ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_actions_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_actions WHERE run_id = ? ORDER BY step",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_action(self, action_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_actions SET status = 'approved' WHERE action_id = ?",
                (action_id,),
            )

    def deny_action(self, action_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_actions SET status = 'denied' WHERE action_id = ?",
                (action_id,),
            )

    def set_agent_memory(self, goal_id: str, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_memory (memory_id, goal_id, key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(goal_id, key) DO UPDATE SET value = excluded.value,
                                                         updated_at = excluded.updated_at
                """,
                (f"{goal_id}:{key}", goal_id, key, value, _now()),
            )

    def get_agent_memory(self, goal_id: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM agent_memory WHERE goal_id = ?", (goal_id,)
            ).fetchall()
            return {r["key"]: r["value"] for r in rows}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
