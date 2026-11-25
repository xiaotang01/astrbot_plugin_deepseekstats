"""
DeepSeek 余额查询插件主类
命令: /余额  /白名单  /apikey
默认图片输出，图片失败降级文字，余额不足自动报警

修复内容:
  - 新增后台定时监控任务，主动检查余额并在低于阈值时发送报警
  - 新增报警冷却机制，避免重复报警骚扰
  - 支持配置 alarm_cooldown（报警冷却时间，分钟）
  - 优化报警目标格式，支持 platform:id 跨适配器
  - 增强错误日志
"""

import asyncio
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.core.message.components import Image, Plain

from .api import DeepSeekAPI, APIError
from .config import ConfigManager
from .parser import DataParser
from .draw import (
    draw_balance_image,
    draw_balance_image_with_alarm,
    draw_whitelist_card,
    draw_key_list_card,
)


@register(
    "astrbot_plugin_deepseekstats",
    "DeepSeek余额查询与报警",
    "查询DeepSeek API余额，支持多Key轮询、白名单管理、余额不足自动报警。",
    "v2.1.2",
)
class DeepSeekBalancePlugin(Star):
    _ALARM_TYPE_MAP = {
        "group": "GroupMessage",
        "groupmessage": "GroupMessage",
        "private": "FriendMessage",
        "friend": "FriendMessage",
        "friendmessage": "FriendMessage",
    }

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        logger.info(f"[DeepSeek] config类型: {type(config).__name__}")
        try:
            self._config_manager = ConfigManager(config)
        except Exception as e:
            logger.error(f"[DeepSeek] 配置初始化失败: {e}")
            self._config_manager = ConfigManager({})
        self._api = DeepSeekAPI()
        self._parser = DataParser()

        # ---- 报警后台任务相关 ----
        self._alarm_task = None
        self._last_alarm_times = {}  # {api_key: datetime} 冷却去重

    async def initialize(self):
        await self._api.initialize()
        # 启动后台余额监控任务
        self._start_alarm_monitor()

    # ==================== 后台余额监控 ====================

    def _start_alarm_monitor(self):
        """启动后台定时余额检查任务"""
        if not self._config_manager.get_alarm_enabled():
            logger.info("[DeepSeek] 余额报警未启用，跳过后台监控")
            return

        alarm_target = self._config_manager.get_alarm_target()
        _, err = self._parse_alarm_target(alarm_target)
        if err:
            logger.warning(
                f"[DeepSeek] 报警已启用但报警目标无效（{err}），"
                "支持格式: group:群号 / private:QQ号 / 群号，后台监控不会启动"
            )
            return

        logger.info(
            f"[DeepSeek] 启动后台余额监控: 间隔={self._config_manager.get_alarm_interval()}s, "
            f"冷却={self._config_manager.get_alarm_cooldown()}s, 目标={alarm_target}"
        )
        self._alarm_task = asyncio.ensure_future(self._alarm_monitor_loop())

    async def _alarm_monitor_loop(self):
        """后台循环：定时检查所有 Key 的余额，低于阈值时发送报警"""
        # 启动后先等一个间隔再检查，避免启动瞬间就报警
        await asyncio.sleep(self._config_manager.get_alarm_interval())

        while True:
            try:
                await self._check_all_keys_alarm()
            except asyncio.CancelledError:
                logger.info("[DeepSeek] 后台监控任务被取消")
                break
            except Exception as e:
                logger.error(f"[DeepSeek] 后台监控异常: {type(e).__name__}: {e}")

            # 每轮重新读取间隔，配置页修改后无需重启即可生效
            await asyncio.sleep(self._config_manager.get_alarm_interval())

    async def _check_all_keys_alarm(self):
        """遍历所有 API Key，检查余额并触发报警"""
        if not self._config_manager.get_alarm_enabled():
            return

        threshold = self._config_manager.get_alarm_threshold()
        if threshold <= 0:
            return

        api_keys = self._config_manager.get_all_keys()
        if not api_keys:
            return

        for api_key in api_keys:
            try:
                balance_data = await self._api.fetch_balance(api_key)
                total = self._parser.get_total_balance(balance_data)

                if total < threshold:
                    triggered, msg, _, _ = self._check_alarm(balance_data, api_key)
                    if triggered and await self._push_alarm(api_key, msg, total, threshold):
                        logger.warning(
                            f"[DeepSeek] 已发送余额报警: Key={self._mask_key(api_key)}, 余额=¥{total:.2f}"
                        )
                else:
                    logger.debug(f"[DeepSeek] Key {api_key[:8]}**** 余额 ¥{total:.2f} 正常")

            except APIError as e:
                logger.warning(f"[DeepSeek] 监控 Key {api_key[:8]}**** 查询失败: {e}")
            except Exception as e:
                logger.error(f"[DeepSeek] 监控 Key {api_key[:8]}**** 异常: {type(e).__name__}: {e}")

    async def _push_alarm(self, api_key: str, msg: str, total: float, threshold: float) -> bool:
        """按冷却策略推送报警，只有发送成功才记录冷却时间"""
        now = datetime.now()
        last_alarm = self._last_alarm_times.get(api_key)
        cooldown = self._config_manager.get_alarm_cooldown()
        if last_alarm and (now - last_alarm).total_seconds() < cooldown:
            logger.debug(
                f"[DeepSeek] Key {self._mask_key(api_key)} 余额 ¥{total:.2f} < ¥{threshold:.2f}，"
                f"但在冷却期内，跳过报警"
            )
            return False

        if await self._send_alarm_to_target(msg):
            self._last_alarm_times[api_key] = now
            return True
        return False

    # ==================== 工具方法 ====================

    def _check_whitelist(self, event: AstrMessageEvent) -> bool:
        return self._config_manager.get_whitelist().check_whitelist(str(event.session_id))

    def _use_text_mode(self, event: AstrMessageEvent) -> bool:
        return "文字" in event.message_str

    @staticmethod
    def _mask_key(api_key: str) -> str:
        """脱敏展示 API Key"""
        return api_key[:8] + "****" if len(api_key) > 8 else "****"

    def _check_alarm(self, balance_data: dict, api_key: str = "") -> tuple:
        """
        检查余额是否低于报警阈值（/余额 命令与后台监控共用）
        返回: (触发报警: bool, 报警消息: str, 当前余额: float, 阈值: float)
        """
        if not self._config_manager.get_alarm_enabled():
            return False, "", 0.0, 0.0

        threshold = self._config_manager.get_alarm_threshold()
        if threshold <= 0:
            return False, "", 0.0, 0.0

        total = self._parser.get_total_balance(balance_data)

        if total < threshold:
            lines = ["⚠️ DeepSeek 余额不足报警！"]
            if api_key:
                lines.append(f"API Key: {self._mask_key(api_key)}")
            lines.extend([
                f"当前余额: ¥{total:.2f}",
                f"报警阈值: ¥{threshold:.2f}",
                "请尽快充值！",
            ])
            return True, "\n".join(lines), total, threshold
        return False, "", total, threshold

    def _resolve_platform_id(self, platform_name: str = "aiocqhttp") -> str:
        """从已加载的平台实例中解析出平台 ID，取不到时回退为平台名称"""
        try:
            for inst in self.context.platform_manager.platform_insts:
                meta = inst.meta()
                if getattr(meta, "name", "") == platform_name:
                    return meta.id
        except Exception as e:
            logger.debug(f"[DeepSeek] 解析平台 ID 失败: {e}")
        return platform_name

    def _parse_alarm_target(self, target: str) -> tuple:
        """
        解析报警目标，返回 AstrBot 的 unified_msg_origin（platform:MessageType:session_id）
        支持格式:
          - group:群号                       -> aiocqhttp:GroupMessage:群号
          - private:QQ号                     -> aiocqhttp:FriendMessage:QQ号
          - 群号                              -> 按群聊处理
          - platform:group:群号              -> platform:GroupMessage:群号
          - platform:GroupMessage:session_id -> 原样使用
        返回: (unified_msg_origin, error_msg)
        """
        target = (target or "").strip()
        if not target:
            return "", "alarm_target 未配置"

        # 只填了群号，按群聊处理
        if target.isdigit():
            target = f"group:{target}"

        parts = [p.strip() for p in target.split(":")]
        if len(parts) == 2:
            platform = self._resolve_platform_id()
            type_token, target_id = parts
        elif len(parts) == 3:
            platform, type_token, target_id = parts
            platform = platform or self._resolve_platform_id()
        else:
            return "", f"alarm_target 格式错误: {target}（应为 group:群号 或 private:QQ号）"

        message_type = self._ALARM_TYPE_MAP.get(type_token.lower())
        if not message_type:
            return "", f"未知的报警目标类型: {type_token}，应为 group 或 private"
        if not target_id:
            return "", "alarm_target 中的目标 ID 为空"

        return f"{platform}:{message_type}:{target_id}", ""

    async def _send_alarm_to_target(self, msg: str) -> bool:
        """向配置的报警目标主动发送消息，成功返回 True"""
        target = self._config_manager.get_alarm_target()
        if not target:
            logger.warning("[DeepSeek] 报警目标为空，无法发送")
            return False

        session_id, err = self._parse_alarm_target(target)
        if err:
            logger.warning(f"[DeepSeek] 报警目标无效: {err}")
            return False

        try:
            chain = MessageChain([Plain(text=msg)])
            sent = await self.context.send_message(session_id, chain)
            if sent is False:
                logger.error(
                    f"[DeepSeek] 未找到与 {session_id} 匹配的平台实例，报警未发送"
                )
                return False
            logger.info(f"[DeepSeek] 报警消息已发送到 {session_id}")
            return True
        except ValueError as e:
            logger.error(f"[DeepSeek] 报警会话不合法 {session_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"[DeepSeek] 发送报警到 {session_id} 失败: {type(e).__name__}: {e}")
            return False

    # ==================== /余额（主命令） ====================

    @filter.command("余额")
    async def query_balance(self, event: AstrMessageEvent):
        """
        查询余额  /余额 [文字]
        默认图片输出，加"文字"强制文字模式
        余额低于阈值时自动报警
        """
        if not self._check_whitelist(event):
            yield event.plain_result("⚠️ 该功能仅对白名单用户开放")
            return

        api_key = self._config_manager.get_api_key()
        if not api_key:
            yield event.plain_result("⚠️ 请先在插件设置中配置 DeepSeek API Key")
            return

        text_mode = self._use_text_mode(event)

        # ---- 查询余额 ----
        try:
            balance_data = await self._api.fetch_balance(api_key)
            logger.info(f"[DeepSeek] 余额返回: {balance_data}")
        except APIError as e:
            yield event.plain_result(f"❌ {e}")
            return
        except Exception as e:
            logger.error(f"[DeepSeek] 余额查询异常: {type(e).__name__}: {e}")
            yield event.plain_result(f"❌ 查询失败：{e}")
            return

        # ---- 检查报警 ----
        alarm_triggered, alarm_msg, total, threshold = self._check_alarm(balance_data, api_key)

        # 向配置目标主动发送报警（与后台监控共用冷却策略）
        if alarm_triggered and alarm_msg:
            await self._push_alarm(api_key, alarm_msg, total, threshold)

        # ---- 输出结果 ----
        if text_mode:
            # 文字模式
            parts = []
            if alarm_triggered:
                parts.append(alarm_msg)
                parts.append("")
            parts.append(self._parser.parse_balance_data(balance_data))
            yield event.plain_result("\n".join(parts))
        else:
            # 图片模式（默认）
            try:
                dd = self._parser.parse_balance_data_for_draw(balance_data)
                if alarm_triggered:
                    img_bytes = draw_balance_image_with_alarm(
                        balance_infos=dd["balance_infos"],
                        total_balance=dd["total_balance"],
                        is_available=dd["is_available"],
                        threshold=threshold,
                    )
                else:
                    img_bytes = draw_balance_image(
                        balance_infos=dd["balance_infos"],
                        total_balance=dd["total_balance"],
                        is_available=dd["is_available"],
                    )
                yield event.chain_result([Image.fromBytes(img_bytes)])
            except Exception as e:
                logger.error(f"[DeepSeek] 图片渲染失败，降级文字: {type(e).__name__}: {e}")
                parts = []
                if alarm_triggered:
                    parts.append(alarm_msg)
                    parts.append("")
                parts.append(self._parser.parse_balance_data(balance_data))
                yield event.plain_result("\n".join(parts))

    # ==================== /白名单 ====================

    @filter.command("白名单")
    async def manage_whitelist(self, event: AstrMessageEvent):
        """白名单管理  /白名单 [列表|添加|移除] [用户ID]"""
        parts = event.message_str.strip().split()
        wm = self._config_manager.get_whitelist()

        if len(parts) < 2 or parts[1] == "列表":
            users = wm.list_users()
            is_open = wm.count() == 0
            try:
                yield event.chain_result([Image.fromBytes(draw_whitelist_card(users, is_open))])
            except Exception:
                if is_open:
                    yield event.plain_result("📋 白名单为空，当前为开放模式（允许所有用户）")
                else:
                    ul = "\n".join(f"  {i + 1}. {u}" for i, u in enumerate(users))
                    yield event.plain_result(f"📋 白名单用户 ({len(users)} 个):\n{ul}")
            return

        action = parts[1]

        if action == "添加" and len(parts) >= 3:
            uid = parts[2]
            if wm.add_user(uid):
                yield event.plain_result(f"✅ 已添加用户 {uid} 到白名单")
            else:
                yield event.plain_result(f"⚠️ 用户 {uid} 已在白名单中")
        elif action == "移除" and len(parts) >= 3:
            uid = parts[2]
            if wm.remove_user(uid):
                yield event.plain_result(f"✅ 已从白名单移除用户 {uid}")
            else:
                yield event.plain_result(f"⚠️ 用户 {uid} 不在白名单中")
        else:
            yield event.plain_result(
                "用法:\n"
                "  /白名单 列表\n"
                "  /白名单 添加 <用户ID>\n"
                "  /白名单 移除 <用户ID>"
            )

    # ==================== /apikey ====================

    @filter.command("apikey")
    async def manage_apikeys(self, event: AstrMessageEvent):
        """API Key 管理  /apikey [列表|添加|移除] [key|索引]"""
        parts = event.message_str.strip().split()
        km = self._config_manager.get_key_manager()

        if len(parts) < 2 or parts[1] == "列表":
            display = km.list_keys_display()
            try:
                yield event.chain_result([Image.fromBytes(draw_key_list_card(display))])
            except Exception:
                if display:
                    yield event.plain_result(f"🔑 API Key 列表 ({km.count()} 个):\n" + "\n".join(display))
                else:
                    yield event.plain_result("🔑 暂未配置 API Key")
            return

        action = parts[1]

        if action == "添加" and len(parts) >= 3:
            key = parts[2]
            if km.add_key(key):
                masked = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
                yield event.plain_result(f"✅ 已添加 API Key: {masked}\n当前共 {km.count()} 个 Key")
            else:
                yield event.plain_result("⚠️ 该 API Key 已存在")
        elif action == "移除" and len(parts) >= 3:
            try:
                idx = int(parts[2]) - 1
                removed = km.remove_key(idx)
                if removed:
                    masked = removed[:8] + "****" + removed[-4:] if len(removed) > 12 else "****"
                    yield event.plain_result(f"✅ 已移除 API Key: {masked}\n当前剩余 {km.count()} 个 Key")
                else:
                    yield event.plain_result(f"⚠️ 索引 {parts[2]} 无效")
            except ValueError:
                yield event.plain_result("⚠️ 索引必须是数字")
        else:
            yield event.plain_result(
                "用法:\n"
                "  /apikey 列表\n"
                "  /apikey 添加 <完整API_Key>\n"
                "  /apikey 移除 <索引号>"
            )

    # ==================== 销毁 ====================

    async def terminate(self):
        # 先停止后台监控任务
        if self._alarm_task and not self._alarm_task.done():
            self._alarm_task.cancel()
            try:
                await asyncio.wait_for(self._alarm_task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            logger.info("[DeepSeek] 后台监控任务已停止")
        await self._api.terminate()
