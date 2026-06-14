"""
多 API Key 管理器
支持轮询、增删查，Key 脱敏展示
"""

import json
from pathlib import Path
from astrbot.api import logger


class KeyManager:
    """管理多个 DeepSeek API Key，支持轮询调度"""

    def __init__(self, keys_file: str = "data/deepseek_keys.json"):
        self.keys_file = Path(keys_file)
        self._keys = []
        self._rotate_index = 0
        self._load_keys()

    def _load_keys(self):
        self._keys.clear()
        if not self.keys_file.exists():
            self.keys_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_keys()
            return
        try:
            with open(self.keys_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._keys = [k for k in data if isinstance(k, str) and k]
            logger.info(f"[DeepSeek] 加载 {len(self._keys)} 个 API Key")
        except Exception as e:
            logger.error(f"[DeepSeek] 加载 Key 文件失败: {e}")

    def _save_keys(self):
        try:
            with open(self.keys_file, "w", encoding="utf-8") as f:
                json.dump(self._keys, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DeepSeek] 保存 Key 文件失败: {e}")

    def add_key(self, key: str) -> bool:
        """添加一个 Key，重复返回 False"""
        if key in self._keys:
            return False
        self._keys.append(key)
        self._save_keys()
        return True

    def remove_key(self, index: int) -> str:
        """按索引移除 Key（从 0 开始），返回被移除的 Key"""
        if 0 <= index < len(self._keys):
            removed = self._keys.pop(index)
            if self._rotate_index >= len(self._keys) and self._keys:
                self._rotate_index = 0
            self._save_keys()
            return removed
        return ""

    def get_keys(self) -> list:
        return list(self._keys)

    def get_next_key(self) -> str:
        """轮询获取下一个 Key"""
        if not self._keys:
            return ""
        key = self._keys[self._rotate_index % len(self._keys)]
        self._rotate_index = (self._rotate_index + 1) % len(self._keys)
        return key

    def list_keys_display(self) -> list:
        """返回脱敏的 Key 列表字符串"""
        result = []
        for i, k in enumerate(self._keys):
            if len(k) > 12:
                masked = k[:8] + "****" + k[-4:]
            else:
                masked = "****"
            result.append(f"  {i + 1}. {masked}")
        return result

    def count(self) -> int:
        return len(self._keys)
