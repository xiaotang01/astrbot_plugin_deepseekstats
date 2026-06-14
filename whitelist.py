"""
白名单管理器
基于文件的用户白名单，白名单为空时默认放行
"""

from pathlib import Path
from astrbot.api import logger


class WhitelistManager:
    """基于文件的白名单管理"""

    def __init__(self, whitelist_file: str):
        self.whitelist_file = Path(whitelist_file)
        self._whitelist = set()
        self._load_whitelist()

    def _load_whitelist(self):
        self._whitelist.clear()
        if not self.whitelist_file.exists():
            logger.info(f"[DeepSeek] 白名单文件不存在，将创建: {self.whitelist_file}")
            self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)
            self.whitelist_file.touch()
            return
        try:
            with open(self.whitelist_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._whitelist.add(line)
            logger.info(f"[DeepSeek] 加载白名单 {len(self._whitelist)} 个用户")
        except Exception as e:
            logger.error(f"[DeepSeek] 加载白名单失败: {e}")

    def _save_whitelist(self):
        try:
            with open(self.whitelist_file, "w", encoding="utf-8") as f:
                for user in sorted(self._whitelist):
                    f.write(f"{user}\n")
        except Exception as e:
            logger.error(f"[DeepSeek] 保存白名单失败: {e}")

    def check_whitelist(self, user_id: str) -> bool:
        if len(self._whitelist) == 0:
            logger.debug("[DeepSeek] 白名单为空，默认允许所有用户")
            return True
        return user_id in self._whitelist

    def add_user(self, user_id: str) -> bool:
        if user_id in self._whitelist:
            return False
        self._whitelist.add(user_id)
        self._save_whitelist()
        return True

    def remove_user(self, user_id: str) -> bool:
        if user_id not in self._whitelist:
            return False
        self._whitelist.remove(user_id)
        self._save_whitelist()
        return True

    def list_users(self) -> list:
        return sorted(self._whitelist)

    def count(self) -> int:
        return len(self._whitelist)
