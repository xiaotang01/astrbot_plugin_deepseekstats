"""
DeepSeek 余额查询插件主类
命令: /余额(查询)  /白名单  /apikey
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
from astrbot.api.event import filter, AstrMessageEvent
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
    "v2.1.0",
)
class DeepSeekBalancePlugin(Star):

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
        self._alarm_interval = self._config_manager.get_alarm_interval()  # 检查间隔（秒）
        self._alarm_cooldown = self._config_manager.get_alarm_cooldown()  # 冷却时间（秒）

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
        if not alarm_target or ":" not in alarm_target:
            logger.warning(
                "[DeepSeek] 报警已启用但 alarm_target 未配置或格式错误（应为 private:QQ号 或 group:群号），"
                "后台监控不会启动"
            )
            return

        logger.info(
            f"[DeepSeek] 启动后台余额监控: 间隔={self._alarm_interval}s, "
            f"冷却={self._alarm_cooldown}s, 目标={alarm_target}"
        )
        self._alarm_task = asyncio.ensure_future(self._alarm_monitor_loop())

    async def _alarm_monitor_loop(self):
        """后台循环：定时检查所有 Key 的余额，低于阈值时发送报警"""
        # 启动后先等一个间隔再检查，避免启动瞬间就报警
        await asyncio.sleep(self._alarm_interval)

        while True:
            try:
                await self._check_all_keys_alarm()
            except asyncio.CancelledError:
                logger.info("[DeepSeek] 后台监控任务被取消")
                break
            except Exception as e:
                logger.error(f"[DeepSeek] 后台监控异常: {type(e).__name__}: {e}")

            await asyncio.sleep(self._alarm_interval)

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
                    # 检查冷却
                    now = datetime.now()
                    last_alarm = self._last_alarm_times.get(api_key)
                    if last_alarm and (now - last_alarm).total_seconds() < self._alarm_cooldown:
                        logger.debug(
                            f"[DeepSeek] Key {api_key[:8]}**** 余额 ¥{total:.2f} < ¥{threshold:.2f}，"
                            f"但在冷却期内，跳过报警"
                        )
                        continue

                    # 触发报警
                    masked = api_key[:8] + "****" if len(api_key) > 8 else "****"
                    msg = (
                        f"⚠️ DeepSeek 余额不足报警！\n"
                        f"API Key: {masked}\n"
                        f"当前余额: ¥{total:.2f}\n"
                        f"报警阈值: ¥{threshold:.2f}\n"
                        f"请尽快充值！"
                    )
                    logger.warning(f"[DeepSeek] 触发余额报警: Key={masked}, 余额=¥{total:.2f}")
                    await self._send_alarm_to_target(msg)
                    self._last_alarm_times[api_key] = now
                else:
                    logger.debug(f"[DeepSeek] Key {api_key[:8]}**** 余额 ¥{total:.2f} 正常")

            except APIError as e:
                logger.warning(f"[DeepSeek] 监控 Key {api_key[:8]}**** 查询失败: {e}")
            except Exception as e:
                logger.error(f"[DeepSeek] 监控 Key {api_key[:8]}**** 异常: {type(e).__name__}: {e}")

    # ==================== 工具方法 ====================

    def _check_whitelist(self, event: AstrMessageEvent) -> bool:
        return self._config_manager.get_whitelist().check_whitelist(str(event.session_id))

    def _use_text_mode(self, event: AstrMessageEvent) -> bool:
        return "文字" in event.message_str

    def _check_alarm(self, balance_data: dict) -> tuple:
        """
        检查余额是否低于报警阈值（供 /余额 命令主动触发时使用）
        返回: (触发报警: bool, 报警消息: str, 当前余额: float, 阈值: float)
        """
        if not self._config_manager.get_alarm_enabled():
            return False, "", 0.0, 0.0

        threshold = self._config_manager.get_alarm_threshold()
        if threshold <= 0:
            return False, "", 0.0, 0.0

        total = self._parser.get_total_balance(balance_data)

        if total < threshold:
            msg = (
                f"⚠️ DeepSeek 余额不足报警！\n"
                f"当前余额: ¥{total:.2f}\n"
                f"报警阈值: ¥{threshold:.2f}\n"
                f"请尽快充值！"
            )
            return True, msg, total, threshold
        return False, "", total, threshold

    def _parse_alarm_target(self, target: str) -> tuple:
        """
        解析报警目标字符串
        支持格式:
          - private:QQ号       -> session_id = aiocqhttp:private_QQ号
          - group:群号          -> session_id = aiocqhttp:group_群号
          - platform:type:id   -> session_id = platform:type_id  （扩展格式）
        返回: (session_id, error_msg)
        """
        if not target or ":" not in target:
            return "", "alarm_target 格式错误，应为 private:QQ号 或 group:群号"

        parts = target.split(":")
        if len(parts) == 3:
            # 扩展格式: platform:type:id
            platform, target_type, target_id = parts
        elif len(parts) == 2:
            # 标准格式: type:id（默认平台 aiocqhttp）
            platform = "aiocqhttp"
            target_type, target_id = parts
        else:
            return "", f"alarm_target 格式错误: {target}"

        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        platform = platform.strip()

        if not target_id:
            return "", "alarm_target 中的目标 ID 为空"

        if target_type == "private":
            session_id = f"{platform}:private_{target_id}"
        elif target_type == "group":
            session_id = f"{platform}:group_{target_id}"
        else:
            return "", f"未知的报警目标类型: {target_type}，应为 private 或 group"

        return session_id, ""

    async def _send_alarm_to_target(self, msg: str):
        """向配置的报警目标主动发送消息"""
        target = self._config_manager.get_alarm_target()
        if not target:
            logger.warning("[DeepSeek] 报警目标为空，无法发送")
            return

        session_id, err = self._parse_alarm_target(target)
        if err:
            logger.warning(f"[DeepSeek] {err}")
            return

        try:
            chain = [Plain(text=msg)]
            await self.context.send_message(session_id, chain)
            logger.info(f"[DeepSeek] 报警消息已发送到 {session_id}")
        except AttributeError:
            logger.warning(
                f"[DeepSeek] 当前 AstrBot 版本不支持主动发送（context.send_message 不存在），"
                f"请升级 AstrBot 或检查 API"
            )
        except Exception as e:
            logger.error(f"[DeepSeek] 发送报警到 {session_id} 失败: {type(e).__name__}: {e}")

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
        alarm_triggered, alarm_msg, total, threshold = self._check_alarm(balance_data)

        # 向配置目标主动发送报警（命令触发时也会发送一次）
        if alarm_triggered and alarm_msg:
            await self._send_alarm_to_target(alarm_msg)

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

    # ==================== /查询（兼容别名） ====================

    @filter.command("查询")
    async def query_alias(self, event: AstrMessageEvent):
        """兼容旧命令，转发到 /余额"""
        async for result in self.query_balance(event):
            yield result

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
