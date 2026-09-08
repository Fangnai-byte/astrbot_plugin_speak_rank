#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speak Rank (群发言榜) - AstrBot 插件
=====================================
统计每个群内的发言条数，群友发送关键词（如「今日发言榜」「本周发言榜」
「累计发言榜」，或直接「发言榜」默认今日）即可查看本群排行。

- 统计范围：当前群（按群独立统计）
- 统计口径：今日 / 昨日 / 前天 / 指定日期(如 9月7日) / 本周(周一起) /
  累计，sqlite 落盘，重启不丢
- 机器人自身发言：默认也计入（include_bot=true）；机器人自己的消息
  不会触发查询，避免自我循环
"""
import os
from datetime import date

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star

try:  # 兼容包/非包两种加载方式
    from .rank_core import (SpeakRankStore, build_rank_text, is_trigger,
                            match_scope, normalize_text)
except ImportError:  # pragma: no cover
    from rank_core import (SpeakRankStore, build_rank_text, is_trigger,
                           match_scope, normalize_text)


class SpeakRankPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.store = SpeakRankStore(self.plugin_dir)
        logger.info(f"[SpeakRank] 数据文件: {self.store.db_path}")

    # ---------------- 工具 ----------------
    def _top_n(self) -> int:
        try:
            return max(1, int(self.config.get("top_n", 10) or 10))
        except (TypeError, ValueError):
            return 10

    def _include_bot(self) -> bool:
        return bool(self.config.get("include_bot", True))

    def _excluded_ids(self) -> set[str]:
        raw = self.config.get("exclude_user_ids", []) or []
        if isinstance(raw, str):
            raw = raw.replace("，", ",").split(",")
        return {str(x).strip() for x in raw if str(x).strip()}

    def _triggers(self) -> list[str]:
        raw = self.config.get("trigger_words", []) or []
        return [str(x).strip() for x in raw if str(x).strip()]

    def _bot_display_name(self) -> str:
        """机器人自身发言在榜上的显示名（框架落库昵称为 bot）。"""
        name = self.config.get("bot_display_name", "") or ""
        return str(name).strip() or "绫地宁宁"

    # ---------------- 群消息监听 ----------------
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        try:
            group_id = str(event.get_group_id() or "")
            user_id = str(event.get_sender_id() or "")
            if not group_id or not user_id:
                return
            is_bot = str(event.get_self_id() or "") == user_id
            text = normalize_text(event.get_message_str() or "")
            triggers = self._triggers()

            # 1) 计数（默认含机器人自身）
            if (is_bot and not self._include_bot()) or user_id in self._excluded_ids():
                return  # 不计入
            # 机器人自身发言：显示名固定取 bot_display_name（默认绫地宁宁），
            # 避免框架落库昵称为空/占位导致榜单显示「未备注」
            if is_bot:
                name = self._bot_display_name()
            else:
                name = event.get_sender_name() or user_id
            self.store.record(group_id, user_id, name)

            # 2) 机器人自己的消息永不触发查询（防自我循环）
            if is_bot:
                return
            if not text or not is_trigger(text, triggers):
                return

            # 3) 查询并播报（date:YYYY-MM-DD = 指定日期）
            scope = match_scope(text)
            if scope == "week":
                rows = self.store.week_rank(group_id, self._top_n())
            elif scope == "total":
                rows = self.store.total_rank(group_id, self._top_n())
            elif scope.startswith("date:"):
                rows = self.store.date_rank(
                    group_id, self._top_n(),
                    date.fromisoformat(scope[len("date:"):]))
            else:
                rows = self.store.today_rank(group_id, self._top_n())
            bot_name = self._bot_display_name()
            rows = [(u, bot_name if n == "bot" else n, c)
                    for u, n, c in rows]
            yield event.plain_result(
                build_rank_text(scope, rows, self._top_n())
            )
        except Exception as e:
            logger.error(f"[SpeakRank] 处理群消息异常: {e}")
