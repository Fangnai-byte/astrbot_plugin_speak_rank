# Changelog

## [1.0.0] - 2026-09-07

### Added
- 群消息发言计数（按群、按人、按天），sqlite 落盘
- 关键词查询：今日 / 本周 / 累计 三种发言榜
- 机器人自身发言默认计入（include_bot），且不会自我触发
- 配置：top_n / trigger_words / include_bot / exclude_user_ids
- 2026-09-07: 展示层把机器人自身发言的昵称 bot 映射为可配置的 bot_display_name（默认「绫地宁宁」）
