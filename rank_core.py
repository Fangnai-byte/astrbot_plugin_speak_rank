#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
群发言榜统计 - 核心逻辑（纯 Python，无 AstrBot 依赖，便于独立自测）

存储：sqlite3，按 (群号, QQ号, 日期) 聚合当日发言条数。
统计口径：
  - 今日榜：day == 今天
  - 本周榜：day >= 本周一（周一为一周起点）
  - 累计榜：全部历史
昵称：取该统计范围内该用户最近一次发言时记录的昵称（按 ts）。
"""
import os
import re
import sqlite3
import threading
import time
from datetime import date, timedelta

DB_REL_PATH = os.path.join("data", "speak_rank.db")
MAX_NAME_LEN = 32


class SpeakRankStore:
    """发言计数存储。所有方法线程安全（锁 + 每操作独立连接）。"""

    def __init__(self, plugin_dir: str):
        self.db_path = os.path.join(plugin_dir, DB_REL_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS msg_stats(
                        group_id TEXT NOT NULL,
                        user_id  TEXT NOT NULL,
                        user_name TEXT NOT NULL DEFAULT '',
                        day      TEXT NOT NULL,
                        cnt      INTEGER NOT NULL DEFAULT 0,
                        ts       INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (group_id, user_id, day)
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_stats_group_day "
                    "ON msg_stats(group_id, day)"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        return conn

    # ---------------- 写入 ----------------
    def record(self, group_id: str, user_id: str, user_name: str,
               day: str | None = None, ts: int | None = None) -> None:
        """某条发言 +1。day 格式 YYYY-MM-DD，缺省取本地当天；ts 为发言时间戳。"""
        day = day or date.today().isoformat()
        ts = ts if ts is not None else int(time.time())
        name = (user_name or user_id).strip()[:MAX_NAME_LEN]
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO msg_stats(group_id, user_id, user_name, day, cnt, ts)
                       VALUES(:g, :u, :n, :d, 1, :t)
                       ON CONFLICT(group_id, user_id, day)
                       DO UPDATE SET cnt = cnt + 1,
                                     user_name = excluded.user_name,
                                     ts = excluded.ts""",
                    {"g": str(group_id), "u": str(user_id), "n": name,
                     "d": day, "t": int(ts)},
                )

    # ---------------- 查询 ----------------
    def _rank(self, group_id: str, top_n: int, start_day: str | None,
              end_day: str | None) -> list[tuple[str, str, int]]:
        """返回 [(user_id, user_name, cnt), ...] 按 cnt 降序（同分按 user_id）。
        昵称取范围内最近一次发言所记录的昵称。"""
        gid = str(group_id)
        lim = int(top_n)
        # 昵称有效性：排除协议端纯数字占位/空串/框架占位串，避免上榜显示「未备注」。
        # 取名优先级：统计范围内最近一次有效昵称 -> 全历史最近一次有效昵称 -> QQ号。
        valid = (
            "TRIM(user_name) != ''"
            " AND TRIM(user_name) NOT GLOB '[0-9]*'"
            " AND LOWER(TRIM(user_name)) NOT IN"
            " ('n/a','未备注','未知','无名氏','bot','null','none')"
        )
        if start_day is None:
            sql = f"""
WITH agg AS (
  SELECT user_id, SUM(cnt) AS c
  FROM msg_stats WHERE group_id = :gid GROUP BY user_id
),
named AS (
  SELECT user_id, user_name,
         ROW_NUMBER() OVER (PARTITION BY user_id
                            ORDER BY ts DESC, day DESC) AS rn
  FROM msg_stats WHERE group_id = :gid AND {valid}
)
SELECT agg.user_id, COALESCE(named.user_name, agg.user_id), agg.c
FROM agg
LEFT JOIN named ON named.user_id = agg.user_id AND named.rn = 1
ORDER BY agg.c DESC, agg.user_id LIMIT :lim
"""
            params = {"gid": gid, "lim": lim}
        else:
            sql = f"""
WITH agg AS (
  SELECT user_id, SUM(cnt) AS c
  FROM msg_stats WHERE group_id = :gid
   AND day BETWEEN :s AND :e GROUP BY user_id
),
inrange AS (
  SELECT user_id, user_name,
         ROW_NUMBER() OVER (PARTITION BY user_id
                            ORDER BY ts DESC, day DESC) AS rn
  FROM msg_stats WHERE group_id = :gid
   AND day BETWEEN :s AND :e AND {valid}
),
history AS (
  SELECT user_id, user_name,
         ROW_NUMBER() OVER (PARTITION BY user_id
                            ORDER BY ts DESC, day DESC) AS rn
  FROM msg_stats WHERE group_id = :gid AND {valid}
)
SELECT agg.user_id,
       COALESCE(inrange.user_name, history.user_name, agg.user_id),
       agg.c
FROM agg
LEFT JOIN inrange ON inrange.user_id = agg.user_id AND inrange.rn = 1
LEFT JOIN history ON history.user_id = agg.user_id AND history.rn = 1
ORDER BY agg.c DESC, agg.user_id LIMIT :lim
"""
            params = {"gid": gid, "s": start_day, "e": end_day, "lim": lim}
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        return [(r[0], r[1] or r[0], int(r[2])) for r in rows]

    def today_rank(self, group_id: str, top_n: int,
                   today: date | None = None) -> list[tuple[str, str, int]]:
        today = today or date.today()
        return self._rank(group_id, top_n, today.isoformat(), today.isoformat())

    def week_rank(self, group_id: str, top_n: int,
                  today: date | None = None) -> list[tuple[str, str, int]]:
        today = today or date.today()
        monday = today - timedelta(days=today.weekday())
        return self._rank(group_id, top_n, monday.isoformat(), today.isoformat())

    def total_rank(self, group_id: str, top_n: int) -> list[tuple[str, str, int]]:
        return self._rank(group_id, top_n, None, None)

    def date_rank(self, group_id: str, top_n: int,
                  day: date) -> list[tuple[str, str, int]]:
        """指定某一自然日（本地时区，按 day 列聚合）的 TOP。"""
        return self._rank(group_id, top_n, day.isoformat(), day.isoformat())


# ---------------- 消息解析 ----------------
_WS_RE = re.compile(r"\s+")

SCOPE_LABEL = {"day": "今日", "week": "本周", "total": "累计"}
DATE_SCOPE_PREFIX = "date:"
# 相对日期词 → 距今天数
_DAY_OFFSET_WORDS = {
    "前天": 2,
    "前日": 2,
    "昨日": 1,
    "昨天": 1,
}


def normalize_text(text: str) -> str:
    """去空白，方便关键词匹配。"""
    return _WS_RE.sub("", text or "")


def _target_date(text_norm: str, today: date | None = None) -> date | None:
    """从去空白文本解析目标日期：昨日/昨天、前天/前日、
    X月X日、XXXX年X月X日、YYYY-MM-DD 等；解析不到返回 None。
    """
    today = today or date.today()
    for word, offset in _DAY_OFFSET_WORDS.items():
        if word in text_norm:
            return today - timedelta(days=offset)
    # 完整年-月-日：2026-09-07 / 2026/9/7 / 2026.9.7 / 2026年9月7日
    m = re.search(
        r"(?P<y>\d{4})\s*[年\-/.]\s*(?P<mo>\d{1,2})\s*[月\-/.]\s*(?P<d>\d{1,2})日?",
        text_norm)
    if m:
        try:
            return date(int(m.group("y")), int(m.group("mo")),
                        int(m.group("d")))
        except ValueError:
            return None
    # 仅月-日：9月7日（默认今年）
    m = re.search(r"(?P<mo>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日", text_norm)
    if m:
        try:
            return date(today.year, int(m.group("mo")), int(m.group("d")))
        except ValueError:
            return None
    return None


def scope_label(scope: str) -> str:
    """把 scope 转成榜单标题用的中文标签（如「9月7日」）。"""
    if scope.startswith(DATE_SCOPE_PREFIX):
        try:
            d = date.fromisoformat(scope[len(DATE_SCOPE_PREFIX):])
        except ValueError:
            return "指定日"
        label = f"{d.month}月{d.day}日"
        return f"{d.year}年{label}" if d.year != date.today().year else label
    return SCOPE_LABEL.get(scope, "今日")


def match_scope(text_norm: str, today: date | None = None) -> str:
    """识别统计口径：day / week / total / date:YYYY-MM-DD，缺省 day。"""
    if "累计" in text_norm or "总" in text_norm:
        return "total"
    if "周" in text_norm:
        return "week"
    d = _target_date(text_norm, today)
    if d is not None:
        return f"{DATE_SCOPE_PREFIX}{d.isoformat()}"
    return "day"


def is_trigger(text_norm: str, triggers: list[str]) -> bool:
    """是否命中任一触发关键词。triggers 为空时按内置词表兜底。"""
    words = [str(t).strip() for t in (triggers or []) if str(t).strip()]
    words = words or ["发言榜", "水群榜"]
    return any(w in text_norm for w in words)


# ---------------- 榜单排版 ----------------
def build_rank_text(scope: str, rows: list[tuple[str, str, int]],
                    top_n: int) -> str:
    """拼出可发送的榜单文本。标题刻意不含触发词（如「发言榜」），
    避免榜单消息被引用/复读时再次触发查询造成循环。"""
    label = scope_label(scope)
    shown = min(len(rows), max(int(top_n), 1))
    lines = [f"【{label}发言 TOP{shown}】"]
    if not rows:
        lines.append(f"{label}还没有人发言喵～")
        return "\n".join(lines)
    for i, (uid, name, cnt) in enumerate(rows, 1):
        show = name if name != uid else f"{uid}（未备注）"
        lines.append(f"{i}. {show}：{cnt} 条")
    return "\n".join(lines)
