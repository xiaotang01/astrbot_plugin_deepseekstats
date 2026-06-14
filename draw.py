"""
生成可视化图片
余额卡片 / 白名单 / Key 列表
"""

from PIL import Image, ImageDraw, ImageFont
import io
import subprocess
import shutil
from pathlib import Path

# ==================== 字体 ====================

FONT_DIR = Path(__file__).parent / "fonts"
FONT_FILE = FONT_DIR / "NotoSansSC-Regular.ttf"

_font_cache = {}


def _run_cmd(cmd: list, timeout: int = 30) -> str:
    """安全执行系统命令"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _find_system_chinese_font() -> str:
    """通过 fc-list 查找系统中已安装的中文字体，返回字体文件路径"""
    # 优先查找 Noto Sans SC
    output = _run_cmd(["fc-list", ":lang=zh", "file"])
    if not output:
        return ""

    # 解析 fc-list 输出，每行格式类似: /path/to/font.ttf: Font Name:style
    candidates = []
    for line in output.splitlines():
        path = line.split(":")[0].strip()
        if path and Path(path).is_file():
            candidates.append(path)

    if not candidates:
        return ""

    # 优先选择 NotoSans 相关字体
    for p in candidates:
        lower = p.lower()
        if "notosanssc" in lower or "notosanscjk" in lower:
            return p
    # 其次选 simhei / wqy / source han
    for p in candidates:
        lower = p.lower()
        if any(kw in lower for kw in ("simhei", "wqy", "sourcehan", "noto-cjk", "notosans")):
            return p
    # 实在没有就用第一个
    return candidates[0]


def _try_install_font_package() -> bool:
    """尝试通过包管理器安装中文字体"""
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    # 尝试 apt-get (Debian/Ubuntu)
    if shutil.which("apt-get"):
        print("[DeepSeek] 尝试通过 apt 安装 fonts-noto-cjk...")
        _run_cmd(["apt-get", "update"], timeout=60)
        r = _run_cmd(["apt-get", "install", "-y", "fonts-noto-cjk-extra"], timeout=120)
        if not r:
            r = _run_cmd(["apt-get", "install", "-y", "fonts-noto-cjk"], timeout=120)
        if not r:
            r = _run_cmd(["apt-get", "install", "-y", "fonts-wqy-zenhei"], timeout=120)
        # 刷新字体缓存
        _run_cmd(["fc-cache", "-f"], timeout=30)
        return bool(_find_system_chinese_font())

    # 尝试 apk (Alpine)
    if shutil.which("apk"):
        print("[DeepSeek] 尝试通过 apk 安装 font-noto-cjk...")
        _run_cmd(["apk", "add", "--no-cache", "font-noto-cjk"], timeout=60)
        _run_cmd(["fc-cache", "-f"], timeout=30)
        return bool(_find_system_chinese_font())

    # 尝试 yum (CentOS/RHEL)
    if shutil.which("yum"):
        print("[DeepSeek] 尝试通过 yum 安装 google-noto-sans-cjk-ttc-fonts...")
        _run_cmd(["yum", "install", "-y", "google-noto-sans-cjk-ttc-fonts"], timeout=120)
        _run_cmd(["fc-cache", "-f"], timeout=30)
        return bool(_find_system_chinese_font())

    return False


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    if size in _font_cache:
        return _font_cache[size]

    # 0. 检查本地缓存
    if FONT_FILE.exists():
        try:
            f = ImageFont.truetype(str(FONT_FILE), size)
            f.getbbox("测试")
            _font_cache[size] = f
            return f
        except Exception:
            pass

    # 1. fc-list 查找系统中文字体
    font_path = _find_system_chinese_font()
    if font_path:
        try:
            f = ImageFont.truetype(font_path, size)
            f.getbbox("测试")
            _font_cache[size] = f
            print(f"[DeepSeek] 使用系统字体: {font_path}")
            return f
        except Exception:
            pass

    # 2. 尝试已知路径
    known_paths = [
        (Path("C:/Windows/Fonts/msyh.ttc"), 0),
        (Path("C:/Windows/Fonts/simhei.ttf"), 0),
        (Path("C:/Windows/Fonts/simsun.ttc"), 0),
    ]
    for path, index in known_paths:
        if path.exists():
            try:
                f = ImageFont.truetype(str(path), size, index=index)
                f.getbbox("测试")
                _font_cache[size] = f
                return f
            except Exception:
                continue

    # 3. 系统没有中文字体，尝试自动安装
    print("[DeepSeek] 系统未找到中文字体，尝试自动安装...")
    if _try_install_font_package():
        font_path = _find_system_chinese_font()
        if font_path:
            try:
                f = ImageFont.truetype(font_path, size)
                f.getbbox("测试")
                _font_cache[size] = f
                print(f"[DeepSeek] 安装后使用字体: {font_path}")
                return f
            except Exception:
                pass

    # 4. 安装失败，尝试从多个 CDN 下载
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    download_urls = [
        ("https://cdn.jsdelivr.net/gh/googlefonts/noto-cjk@main/Sans/OTF/SimplifiedChinese/NotoSansSC-Regular.otf",
         "NotoSansSC-Regular.otf"),
        ("https://mirrors.tuna.tsinghua.edu.cn/github-release/googlefonts/noto-cjk/LatestRelease/NotoSansSC-Regular.otf",
         "NotoSansSC-Regular.otf"),
        ("https://objects.githubusercontent.com/github-production-release-asset-2e65be/612060085/1a2e0f00-80cb-11eb-9aae-e8e8c0752468?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=releaseassetmanagement%2F20260608%2Fus-east-1%2Fs3%2Faws4_request",
         "NotoSansSC-Regular.otf"),
    ]
    import urllib.request
    for url, fname in download_urls:
        target = FONT_DIR / fname
        try:
            print(f"[DeepSeek] 正在下载字体: {url[:60]}...")
            urllib.request.urlretrieve(url, str(target), )
            if target.exists() and target.stat().st_size > 100000:
                try:
                    f = ImageFont.truetype(str(target), size)
                    f.getbbox("测试")
                    _font_cache[size] = f
                    print(f"[DeepSeek] 字体下载成功: {target}")
                    # 同时保存为通用名
                    if target != FONT_FILE:
                        shutil.copy2(str(target), str(FONT_FILE))
                    return f
                except Exception:
                    target.unlink(missing_ok=True)
        except Exception as e:
            print(f"[DeepSeek] 下载失败: {e}")
            target.unlink(missing_ok=True)

    # 5. 最终兜底
    print("[DeepSeek] 警告：无法获取中文字体，图片中文将显示为方块")
    f = ImageFont.load_default()
    _font_cache[size] = f
    return f


# ==================== 颜色常量 ====================

BG = (245, 245, 245)
CARD = (255, 255, 255)
DARK = (51, 51, 51)
MUTED = (102, 102, 102)
GRID = (224, 224, 224)
BLUE = (0, 120, 212)
GREEN = (40, 167, 69)
RED = (220, 53, 69)
SUCCESS = (0, 150, 0)
ERROR = (200, 0, 0)
ALARM_BG = (255, 243, 205)
ALARM_BORDER = (255, 193, 7)
ALARM_TEXT = (133, 100, 4)


# ==================== 工具函数 ====================

def _num(val, default=0.0):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    return default


def _text_w(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _currency_sym(c):
    return {"CNY": "¥", "USD": "$", "EUR": "€"}.get(c, c + " ")


# ==================== 1. 余额卡片 ====================

def draw_balance_image(balance_infos: list, total_balance: float, is_available: bool) -> bytes:
    balance_infos = [i for i in balance_infos if isinstance(i, dict)]
    total_balance = _num(total_balance)
    W = 600
    P = 20
    line_h, small_h = 30, 22
    H = 20 + 45 + 40 + 45 + 10 + line_h * (len(balance_infos) + 2) + small_h * len(balance_infos) + 60
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    tf = _get_font(24)
    hf = _get_font(20)
    nf = _get_font(16)
    sf = _get_font(14)
    d.rounded_rectangle([P, 20, W - P, H - 20], fill=CARD, radius=10, outline=GRID, width=1)
    y = 45
    d.text((P + 20, y), "DeepSeek 账户余额", font=tf, fill=DARK)
    y += 45
    st = "账户状态: 可用" if is_available else "账户状态: 不可用"
    d.text((P + 20, y), st, font=hf, fill=SUCCESS if is_available else ERROR)
    y += 40
    cur = balance_infos[0].get("currency", "CNY") if balance_infos else "CNY"
    d.text((P + 20, y), f"总余额: {_currency_sym(cur)}{total_balance:.2f}", font=hf, fill=BLUE)
    y += 45
    d.text((P + 20, y), "余额明细", font=hf, fill=DARK)
    y += 10
    d.line([(P + 20, y), (W - P - 20, y)], fill=GRID, width=1)
    y += 15
    for info in balance_infos:
        c = info.get("currency", "?")
        sym = _currency_sym(c)
        t = _num(info.get("total", 0))
        g = _num(info.get("granted", 0))
        tp = _num(info.get("topped", 0))
        d.text((P + 30, y), c, font=nf, fill=DARK)
        d.text((P + 130, y), f"{sym}{t:.2f}", font=nf, fill=DARK)
        y += small_h
        d.text((P + 45, y), f"赠送: {sym}{g:.2f}", font=sf, fill=MUTED)
        d.text((P + 200, y), f"充值: {sym}{tp:.2f}", font=sf, fill=MUTED)
        y += line_h
    d.text((P + 20, H - 40), "数据来自 DeepSeek API", font=sf, fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ==================== 2. 余额卡片 + 报警 ====================

def draw_balance_image_with_alarm(balance_infos: list, total_balance: float,
                                   is_available: bool, threshold: float) -> bytes:
    balance_infos = [i for i in balance_infos if isinstance(i, dict)]
    total_balance = _num(total_balance)
    W = 600
    P = 20
    line_h, small_h = 30, 22
    alarm_h = 70
    H = 20 + alarm_h + 45 + 40 + 45 + 10 + line_h * (len(balance_infos) + 2) + small_h * len(balance_infos) + 60
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    tf = _get_font(24)
    hf = _get_font(20)
    af = _get_font(16)
    nf = _get_font(16)
    sf = _get_font(14)

    d.rounded_rectangle([P, 15, W - P, 15 + alarm_h - 10], fill=ALARM_BG, radius=10, outline=ALARM_BORDER, width=2)
    d.text((P + 20, 25), "余额不足报警！", font=hf, fill=ALARM_TEXT)
    d.text((P + 20, 52), f"当前 ¥{total_balance:.2f}  低于阈值 ¥{threshold:.2f}，请尽快充值", font=af, fill=ALARM_TEXT)

    y = 15 + alarm_h + 10
    d.rounded_rectangle([P, y, W - P, H - 20], fill=CARD, radius=10, outline=GRID, width=1)
    y += 25
    d.text((P + 20, y), "DeepSeek 账户余额", font=tf, fill=DARK)
    y += 45
    st = "账户状态: 可用" if is_available else "账户状态: 不可用"
    d.text((P + 20, y), st, font=hf, fill=SUCCESS if is_available else ERROR)
    y += 40
    cur = balance_infos[0].get("currency", "CNY") if balance_infos else "CNY"
    d.text((P + 20, y), f"总余额: {_currency_sym(cur)}{total_balance:.2f}", font=hf, fill=BLUE)
    y += 45
    d.text((P + 20, y), "余额明细", font=hf, fill=DARK)
    y += 10
    d.line([(P + 20, y), (W - P - 20, y)], fill=GRID, width=1)
    y += 15
    for info in balance_infos:
        c = info.get("currency", "?")
        sym = _currency_sym(c)
        t = _num(info.get("total", 0))
        g = _num(info.get("granted", 0))
        tp = _num(info.get("topped", 0))
        d.text((P + 30, y), c, font=nf, fill=DARK)
        d.text((P + 130, y), f"{sym}{t:.2f}", font=nf, fill=DARK)
        y += small_h
        d.text((P + 45, y), f"赠送: {sym}{g:.2f}", font=sf, fill=MUTED)
        d.text((P + 200, y), f"充值: {sym}{tp:.2f}", font=sf, fill=MUTED)
        y += line_h
    d.text((P + 20, H - 40), "数据来自 DeepSeek API", font=sf, fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ==================== 3. 白名单卡片 ====================

def draw_whitelist_card(users: list, is_open: bool) -> bytes:
    W = 500
    H = max(200, 120 + len(users) * 30)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    tf = _get_font(22)
    nf = _get_font(16)
    d.rounded_rectangle([20, 20, W - 20, H - 20], fill=CARD, radius=10, outline=GRID, width=1)
    y = 45
    d.text((40, y), "白名单管理", font=tf, fill=DARK)
    y += 35
    status = "开放模式（白名单为空，允许所有用户）" if is_open else f"限制模式（{len(users)} 个用户）"
    d.text((40, y), status, font=nf, fill=SUCCESS if is_open else BLUE)
    y += 35
    if users:
        d.line([(40, y), (W - 40, y)], fill=GRID, width=1)
        y += 10
        for u in users:
            d.text((50, y), f"• {u}", font=nf, fill=DARK)
            y += 30
    else:
        d.text((50, y), "暂无用户", font=nf, fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ==================== 4. API Key 列表卡片 ====================

def draw_key_list_card(keys_display: list) -> bytes:
    W = 500
    H = max(180, 100 + len(keys_display) * 30)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    tf = _get_font(22)
    nf = _get_font(16)
    d.rounded_rectangle([20, 20, W - 20, H - 20], fill=CARD, radius=10, outline=GRID, width=1)
    y = 45
    d.text((40, y), "API Key 列表", font=tf, fill=DARK)
    y += 35
    d.line([(40, y), (W - 40, y)], fill=GRID, width=1)
    y += 10
    if keys_display:
        for ks in keys_display:
            d.text((50, y), ks, font=nf, fill=DARK)
            y += 30
    else:
        d.text((50, y), "暂未配置 API Key", font=nf, fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
