# DeepSeek 余额查询与报警插件 for AstrBot

查询 DeepSeek API 账户余额，支持图片卡片展示、多 Key 轮询、白名单管理和余额不足自动报警。

## 功能

- `/余额` — 以图片卡片形式展示余额信息（默认）
- `/余额 文字` — 以纯文本形式展示余额信息
- `/白名单 列表` — 查看白名单用户
- `/白名单 添加 <用户ID>` — 将用户加入白名单
- `/白名单 移除 <用户ID>` — 将用户移出白名单
- `/apikey 列表` — 查看所有 API Key（脱敏显示）
- `/apikey 添加 <Key>` — 添加新的 API Key
- `/apikey 移除 <索引>` — 按索引移除 API Key
- **后台定时监控余额**，低于阈值时自动向指定目标推送报警消息
- 报警冷却机制，避免重复通知骚扰
- 图片渲染失败时自动降级为文字输出

## 配置

1. 在 AstrBot 插件配置中填写 `deepseek_api_key`（主 API Key）
2. 在「额外 API Key」列表中可添加多个 Key，实现轮询统计
3. 在「白名单用户」列表中可管理允许使用插件的用户 ID（为空则允许所有用户）
4. （可选）开启「启用余额不足报警」，设置报警阈值（元）
5. （可选）设置「报警目标」，格式为 `private:QQ号`（私聊）或 `group:群号`（群聊），也可以直接填群号；留空则仅在查询时显示报警
6. （可选）调整「后台检查间隔」（默认 300 秒）和「报警冷却时间」（默认 3600 秒）
7. 重启 AstrBot 或热加载插件

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `deepseek_api_key` | string | `""` | 主 DeepSeek API Key |
| `extra_api_keys` | list | `[]` | 额外 API Key，用于多 Key 轮询 |
| `whitelist_users` | list | `[]` | 白名单用户 ID，为空则允许所有用户 |
| `alarm_enabled` | bool | `false` | 是否启用余额不足报警 |
| `alarm_threshold` | float | `10.0` | 报警阈值（元），余额低于此值时触发 |
| `alarm_target` | string | `""` | 报警目标，格式 `private:QQ号`、`group:群号` 或直接填群号 |
| `alarm_interval` | int | `300` | 后台检查间隔（秒），最少 60 |
| `alarm_cooldown` | int | `3600` | 报警冷却时间（秒），最少 300 |

## 报警机制

### 工作原理

1. 插件启动后，若 `alarm_enabled=true` 且 `alarm_target` 已配置，自动启动后台监控任务
2. 每隔 `alarm_interval` 秒（默认 5 分钟）检查所有已配置 API Key 的余额
3. 当某个 Key 的余额低于 `alarm_threshold` 时，向 `alarm_target` 发送报警消息
4. 同一 Key 在 `alarm_cooldown`（默认 1 小时）内不会重复报警
5. 用户手动执行 `/余额` 命令时也会触发检查和报警

### 报警目标格式

- `private:QQ号` — 推送到指定 QQ 私聊
- `group:群号` — 推送到指定 QQ 群
- `群号` — 只填群号时按群聊处理
- `平台ID:group:群号` / `平台ID:private:QQ号` — 指定特定平台实例（平台 ID 可在 WebUI 平台配置中查看）
- `平台ID:GroupMessage:session_id` / `平台ID:FriendMessage:session_id` — AstrBot 原生会话格式

## 依赖

- aiohttp >= 3.8.0
- Pillow >= 9.0.0

## 注意

- 图片模式需要中文字体支持。插件会依次尝试：本地缓存字体 → 系统已安装中文字体（fc-list 自动检测）→ 自动通过包管理器安装 → CDN 下载 → 默认字体兜底。
- 如果服务器网络受限，可手动将 `NotoSansSC-Regular.otf` 放入插件目录下的 `fonts/` 文件夹。
- 多 Key 模式下查询会自动轮询，每次查询使用下一个 Key。
- DeepSeek 用量统计 API（`/user/usage`）当前不可用（返回 404），相关功能已移除。若该接口后续开放，可重新添加。

## 更新日志

### v2.1.0 (2026-07-09)
- **修复**：余额报警功能不生效 — 新增后台定时监控任务，主动检查余额并推送报警
- **新增**：报警冷却机制，避免重复报警
- **新增**：`alarm_interval` 和 `alarm_cooldown` 配置项
- **改进**：报警目标解析支持扩展格式 `platform:type:id`

### v2.0.0 (2026-06-08)
- 合并 `/余额` 和 `/用量` 命令，默认图片输出
- 新增余额不足报警、白名单管理、多 API Key 管理
- 新增中文字体自动安装机制

> **此插件 100% 由 AI 生成。**
