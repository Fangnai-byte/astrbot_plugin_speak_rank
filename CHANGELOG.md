# Changelog

## [1.1.0] - 2026-09-09

### Added
- 支持按日期查询：昨日/昨天、前天/前日、9月7日、2026年9月7日、
  2026-09-07（亦兼容 `/`、`.` 分隔），底层复用 `_rank` 的任意日期区间能力
- 播报标题随查询日期动态显示（如「9月8日发言 TOP10」）

### Changed
- `match_scope` 返回值扩展：新增 `date:YYYY-MM-DD` 口径，原 `day/week/total` 语义不变

## [1.0.0] - 2026-09-07

### Added
- 群消息发言计数（按群、按人、按天），sqlite 落盘
- 关键词查询：今日 / 本周 / 累计 三种发言榜
- 机器人自身发言默认计入（include_bot），且不会自我触发
- 配置：top_n / trigger_words / include_bot / exclude_user_ids
- 2026-09-07: 展示层把机器人自身发言的昵称 bot 映射为可配置的 bot_display_name（默认「绫地宁宁」）
