"""
数据解析器：将 API 返回的余额数据转换为文本或绘图数据
"""

import json


class DataParser:
    """余额数据解析器"""

    def parse_balance_data(self, balance_data: dict) -> str:
        """解析余额数据为纯文本"""
        balance_data = self._ensure_dict(balance_data)
        if not isinstance(balance_data, dict):
            return "⚠️ 余额数据格式异常"

        is_available = balance_data.get("is_available", False)
        balance_infos = balance_data.get("balance_infos", [])
        if not isinstance(balance_infos, list):
            balance_infos = []
        balance_infos = [info for info in balance_infos if isinstance(info, dict)]

        currency = self._get_primary_currency(balance_infos)
        total = sum(
            self._safe_float(info.get("total_balance", 0.0))
            for info in balance_infos
            if str(info.get("currency", "")).upper() == currency
        )

        lines = [
            "=== DeepSeek 账户余额 ===",
            f"账户状态: {'✅ 可用' if is_available else '❌ 不可用'}",
            f"总余额: {self._format_currency(total, currency)}",
        ]

        if balance_infos:
            lines.append("明细:")
            for info in balance_infos:
                c = info.get("currency", "未知")
                t = self._safe_float(info.get("total_balance", 0.0))
                g = self._safe_float(info.get("granted_balance", 0.0))
                tp = self._safe_float(info.get("topped_up_balance", 0.0))
                lines.append(
                    f"  • {c}: {self._format_currency(t, c)} "
                    f"(赠送 {self._format_currency(g, c)}, "
                    f"充值 {self._format_currency(tp, c)})"
                )
        else:
            lines.append("无余额信息")

        return "\n".join(lines)

    def parse_balance_data_for_draw(self, balance_data: dict) -> dict:
        """解析余额数据为绘图结构"""
        balance_data = self._ensure_dict(balance_data)
        if not isinstance(balance_data, dict):
            return {"is_available": False, "total_balance": 0.0, "balance_infos": []}

        is_available = balance_data.get("is_available", False)
        balance_infos = []
        total_balance = 0.0

        raw_infos = [
            info for info in balance_data.get("balance_infos", [])
            if isinstance(info, dict)
        ]
        primary_currency = self._get_primary_currency(raw_infos)

        for info in raw_infos:
            currency = info.get("currency", "CNY")
            total = self._safe_float(info.get("total_balance", 0.0))
            granted = self._safe_float(info.get("granted_balance", 0.0))
            topped = self._safe_float(info.get("topped_up_balance", 0.0))
            balance_infos.append({
                "currency": currency, "total": total,
                "granted": granted, "topped": topped
            })
            if str(currency).upper() == primary_currency:
                total_balance += total

        # 主币种排在最前，保证图片卡片的总余额符号与数值一致
        balance_infos.sort(
            key=lambda i: 0 if str(i.get("currency", "")).upper() == primary_currency else 1
        )

        return {
            "is_available": is_available,
            "total_balance": total_balance,
            "balance_infos": balance_infos
        }

    def get_total_balance(self, balance_data: dict, currency=None) -> float:
        """
        从余额数据中提取总余额（数值）。
        多币种时只统计同一种货币（默认优先 CNY），避免不同币种直接相加。
        """
        balance_data = self._ensure_dict(balance_data)
        if not isinstance(balance_data, dict):
            return 0.0
        infos = [
            info for info in balance_data.get("balance_infos", [])
            if isinstance(info, dict)
        ]
        target_currency = (currency or self._get_primary_currency(infos)).upper()
        total = 0.0
        for info in infos:
            if str(info.get("currency", "")).upper() == target_currency:
                total += self._safe_float(info.get("total_balance", 0.0))
        return total

    # ==================== 工具方法 ====================

    @staticmethod
    def _get_primary_currency(balance_infos: list) -> str:
        """确定用于「总余额/报警阈值」比较的币种，优先 CNY"""
        currencies = [
            str(info.get("currency", "")).upper()
            for info in balance_infos
            if isinstance(info, dict) and info.get("currency")
        ]
        if "CNY" in currencies:
            return "CNY"
        return currencies[0] if currencies else "CNY"

    @staticmethod
    def _ensure_dict(data):
        if isinstance(data, str):
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return data
        return data

    @staticmethod
    def _safe_float(val, default=0.0):
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        return default

    @staticmethod
    def _format_currency(amount, currency: str) -> str:
        if isinstance(amount, str):
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                return amount
        elif not isinstance(amount, (int, float)):
            return str(amount)
        symbol_map = {"CNY": "¥", "USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£"}
        symbol = symbol_map.get(currency, currency)
        if amount.is_integer():
            return f"{symbol}{int(amount)}"
        return f"{symbol}{amount:.2f}"
