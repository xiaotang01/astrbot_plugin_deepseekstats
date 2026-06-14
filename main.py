"""
DeepSeek 余额查询插件主类
命令: /余额(查询)  /白名单  /apikey
默认图片输出，图片失败降级文字，余额不足自动报警
"""

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
    "v2.0.0",
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

    async def initialize(self):
        await self._api.initialize()

    # ==================== 工具方法 ====================

    def _check_whitelist(self, event: AstrMessageEvent) -> bool:
        return self._config_manager.get_whitelist().check_whitelist(str(event.session_id))

    def _use_text_mode(self, event: AstrMessageEvent) -> bool:
        return "文字" in event.message_str

    def _check_alarm(self, balance_data: dict) -> tuple:
        """
        检查余额是否低于报警阈值
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

    async def _send_alarm_to_target(self, msg: str):
        """向配置的报警目标主动发送消息"""
        target = self._config_manager.get_alarm_target()
        if not target or ":" not in target:
            return

        parts = target.split(":", 1)
        target_type = parts[0].strip().lower()
        target_id = parts[1].strip()

        if not target_id:
            return

        if target_type == "private":
            session_id = f"aiocqhttp:private_{target_id}"
        elif target_type == "group":
            session_id = f"aiocqhttp:group_{target_id}"
        else:
            logger.warning(f"[DeepSeek] 未知的报警目标类型: {target_type}，应为 private 或 group")
            return

        try:
            chain = [Plain(text=msg)]
            await self.context.send_message(session_id, chain)
            logger.info(f"[DeepSeek] 报警消息已发送到 {session_id}")
        except AttributeError:
            logger.warning(f"[DeepSeek] 当前 AstrBot 版本不支持主动发送，请检查 context API")
        except Exception as e:
            logger.error(f"[DeepSeek] 发送报警到 {session_id} 失败: {e}")

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

        # 向配置目标主动发送报警
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
        await self._api.terminate()
