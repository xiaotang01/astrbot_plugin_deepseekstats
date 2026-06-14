"""
DeepSeek API 调用封装（仅余额查询）
"""

import aiohttp
from astrbot.api import logger


class APIError(Exception):
    """API 请求异常"""
    pass


class DeepSeekAPI:
    """DeepSeek API 客户端"""

    def __init__(self):
        self._session = None

    async def initialize(self):
        self._session = aiohttp.ClientSession()

    async def fetch_balance(self, api_key: str) -> dict:
        """查询 DeepSeek 账户余额"""
        url = "https://api.deepseek.com/user/balance"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"[DeepSeek] 余额响应: {data}")
                    if "is_available" not in data or "balance_infos" not in data:
                        raise APIError("返回数据格式错误，缺少必要字段")
                    return data
                elif resp.status == 401:
                    raise APIError("API Key 无效，请检查配置")
                elif resp.status == 403:
                    raise APIError("访问被拒绝，请检查 API Key 权限")
                elif resp.status == 429:
                    raise APIError("请求频率过高，请稍后重试")
                else:
                    text = await resp.text()
                    logger.error(f"[DeepSeek] 请求失败: {resp.status} - {text}")
                    raise APIError(f"请求失败，状态码: {resp.status}")
        except aiohttp.ClientError as e:
            raise APIError(f"网络请求异常: {str(e)}")
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"未知错误: {str(e)}")

    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()
