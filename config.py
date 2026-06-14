"""
插件配置管理
从配置页面读取白名单、多 Key、报警设置，同步到文件存储
"""

import json
from astrbot.api import logger
from pathlib import Path
from .whitelist import WhitelistManager
from .key_manager import KeyManager


class ConfigManager:
    """配置管理器"""

    def __init__(self, config):
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}
        if not isinstance(config, dict):
            if hasattr(config, 'items'):
                config = dict(config)
            elif hasattr(config, '__dict__'):
                config = vars(config)
            else:
                logger.error(f"[DeepSeek] config 无法处理，类型: {type(config).__name__}")
                config = {}

        self._config = config
        self._whitelist_manager = None
        self._key_manager = None
        self._init_managers()

    def _init_managers(self):
        # ---- 白名单 ----
        whitelist_file = self._config.get("whitelist_file", "data/whitelist.txt")
        Path(whitelist_file).parent.mkdir(parents=True, exist_ok=True)
        self._whitelist_manager = WhitelistManager(whitelist_file)

        wl_raw = self._config.get("whitelist_users", [])
        self._sync_whitelist_from_config(wl_raw)

        # ---- Key ----
        keys_file = self._config.get("keys_file", "data/deepseek_keys.json")
        self._key_manager = KeyManager(keys_file)

        ek_raw = self._config.get("extra_api_keys", [])
        self._sync_keys_from_config(ek_raw)

        primary_key = self._config.get("deepseek_api_key", "")
        if primary_key and self._key_manager.count() == 0:
            self._key_manager.add_key(primary_key)

    def _sync_whitelist_from_config(self, raw):
        user_ids = self._extract_list(raw)
        if not user_ids:
            return
        wm = self._whitelist_manager
        file_ids = set(wm.list_users())
        added = 0
        for uid in user_ids:
            if uid not in file_ids:
                if wm.add_user(uid):
                    added += 1
        if added:
            logger.info(f"[DeepSeek] 从配置页同步白名单，新增 {added} 个用户")

    def _sync_keys_from_config(self, raw):
        keys = self._extract_list(raw)
        if not keys:
            return
        km = self._key_manager
        existing = set(km.get_keys())
        added = 0
        for key in keys:
            if key not in existing:
                if km.add_key(key):
                    added += 1
                    existing.add(key)
        if added:
            logger.info(f"[DeepSeek] 从配置页同步 API Key，新增 {added} 个")

    @staticmethod
    def _extract_list(raw) -> list:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        if isinstance(raw, str) and raw.strip():
            return [line.strip() for line in raw.strip().splitlines() if line.strip()]
        return []

    # ---- API Key ----

    def get_api_key(self) -> str:
        key = self._key_manager.get_next_key()
        if not key:
            primary = self._config.get("deepseek_api_key", "")
            if primary:
                return primary
            logger.warning("[DeepSeek] 未配置任何 API Key")
        return key

    def get_all_keys(self) -> list:
        return self._key_manager.get_keys()

    def get_key_manager(self) -> KeyManager:
        return self._key_manager

    # ---- 白名单 ----

    def get_whitelist(self) -> WhitelistManager:
        return self._whitelist_manager

    # ---- 报警 ----

    def get_alarm_enabled(self) -> bool:
        return bool(self._config.get("alarm_enabled", False))

    def get_alarm_threshold(self) -> float:
        val = self._config.get("alarm_threshold", 10.0)
        try:
            return float(val)
        except (ValueError, TypeError):
            return 10.0

    def get_alarm_target(self) -> str:
        """返回报警目标，格式: private:QQ号 或 group:群号，空字符串=仅查询时显示"""
        return str(self._config.get("alarm_target", "")).strip()
