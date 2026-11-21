# -*- coding: utf-8 -*-
"""
汽水音乐 Android 自动领免费听时长
==================================
环境: Windows/macOS/Linux + adb(无线调试或 USB) + Python 3.10+
依赖: pip install rapidocr-onnxruntime opencv-python

开发实测机型: 小米 15 Pro (2410DPN6CC), Android 17, 1440x3200
坐标在文件下方常量区，按 1440x3200 标定，其它分辨率请自行标定修改。

流程:
  1. 启动 App -> 跳开屏广告(右上角「跳过」)
  2. 播放页 -> 弹窗「立即解锁 第N天畅听」(或点「免费听」兜底)
  3. 广告倒计时(19~29s) -> 顶部「领取成功」-> 点击
  4. 弹窗「领取奖励」-> 点击 -> 自动进入下一轮广告
  5. 遇到直播间广告: 自动收券关直播, 回到播放页后重新点解锁续跑
  6. 连续 MAX_IDLE 轮无奖励 -> 判定额度耗尽, 点「坚持退出」收尾
"""

import os
import subprocess
import sys
import time

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ADB = os.environ.get("ADB_PATH", "adb")  # 默认要求 adb 在 PATH，或用环境变量指定完整路径
PACKAGE = "com.luna.music"

SCREEN_W, SCREEN_H = 1440, 3200

# 识别区域 (x1, y1, x2, y2)，按整屏坐标
REG_TOPBAR = (0, 130, 1440, 340)      # 开屏跳过按钮 + 广告顶「领取成功」
REG_POPUP = (200, 1540, 1240, 1960)   # 「领取奖励 / 坚持退出」弹窗
REG_UNLOCK = (0, 1300, 1440, 2850)    # 播放页解锁弹窗（覆盖「今日畅听」「立即解锁」两块按钮）

# 点击坐标（按钮实测中心，1440x3200）
BTN_SKIP = (1224, 284)     # 开屏「跳过 5」
BTN_CLAIM_OK = (1150, 232) # 广告页顶「领取成功」（点文字，不点 ×）
BTN_REWARD = (720, 1720)   # 弹窗「领取奖励」
BTN_UNLOCK = (721, 2736)   # 播放页「立即解锁 今日畅听」
BTN_FREE = (1172, 2604)    # 播放页「免费听」（入口兜底）
BTN_EXIT = (720, 1880)     # 弹窗「坚持退出」
BTN_LIVE_CLOSE = (1328, 264)  # 直播间右上角 ×
REG_LIVE = (0, 130, 1440, 420)    # 直播间顶部特征区
REG_LIVE_POPUP = (0, 2700, 1440, 3050)  # 直播间领券弹窗按钮区

MAX_IDLE = 10              # 连续失败轮数上限
CLAIM_TIMEOUT = 60         # 等「领取成功」最长秒数
REWARD_TIMEOUT = 20        # 等「领取奖励」弹窗最长秒数
POPUP_SLEEP = 1.0          # 点击后等待秒数


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pick_device() -> str:
    def _list():
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        return [l.split()[0] for l in out.splitlines()[1:] if l.strip() and "device" in l]

    devs = _list()
    if not devs:
        log("未发现已连接设备，尝试通过 mDNS 自动发现无线调试服务...")
        reconnect()
        time.sleep(2)
        devs = _list()
    if not devs:
        sys.exit("没有可用设备：请在手机上开启「无线调试」后重试")
    if len(devs) > 1:
        log(f"检测到 {len(devs)} 台设备，使用第一台: {devs[0]}")
    return devs[0]


def refresh_device(old: str) -> str:
    """连接失效时重连并返回新设备串号"""
    reconnect()
    time.sleep(2)
    return pick_device()


def run(device: str, *args: str) -> str:
    try:
        p = subprocess.run([ADB, "-s", device, *args], capture_output=True,
                           text=True, timeout=15)
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return ""


def tap(device: str, x: int, y: int, desc: str):
    log(f"点击 [{desc}] -> ({x},{y})")
    run(device, "shell", "input", "tap", str(x), str(y))
    time.sleep(POPUP_SLEEP)


def reconnect():
    """无线调试断线自愈：重新发现服务并连接"""
    log("尝试自愈重连...")
    subprocess.run([ADB, "disconnect"], capture_output=True)
    out = subprocess.run([ADB, "mdns", "services"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "_adb-tls-connect" in line:
            parts = line.split()
            host = parts[-1]  # 形如 192.168.31.57:37323
            r = subprocess.run([ADB, "connect", host], capture_output=True, text=True)
            log(f"  connect {host}: {r.stdout.strip()}")
            return True
    return False


def shot(device: str, retries: int = 3):
    for i in range(retries):
        try:
            p = subprocess.run([ADB, "-s", device, "exec-out", "screencap", "-p"],
                               capture_output=True, timeout=15)
            img = cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                return img
        except subprocess.TimeoutExpired:
            pass
        log(f"  截屏失败，重试 {i + 1}/{retries}")
        if i == retries - 1 and reconnect():
            time.sleep(2)
    raise RuntimeError("截屏连续失败，设备可能离线")


class Ocr:
    def __init__(self):
        log("加载 OCR 模型（首次约 3-5 秒）...")
        self.engine = RapidOCR()

    def find(self, img, region, keywords, conf=0.55):
        """在 region 内 OCR，返回第一个命中关键词的 {text,score,cx,cy}（全屏坐标）或 None"""
        x1, y1, x2, y2 = region
        crop = img[y1:y2, x1:x2]
        res, _ = self.engine(crop)
        if not res:
            return None
        for box, text, score in res:
            if score < conf:
                continue
            for kw in keywords:
                if kw in text:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    cx = x1 + int(sum(xs) / len(xs))
                    cy = y1 + int(sum(ys) / len(ys))
                    return {"text": text, "score": round(score, 2), "cx": cx, "cy": cy}
        return None


def skip_splash(device: str, ocr: Ocr) -> bool:
    """启动 App 后 8 秒内跳开屏广告"""
    log("阶段一：检测开屏跳过")
    deadline = time.time() + 8
    while time.time() < deadline:
        hit = ocr.find(shot(device), REG_TOPBAR, ["跳过"])
        if hit:
            log(f"  命中开屏广告: '{hit['text']}' -> 点击")
            tap(device, *BTN_SKIP, "跳过开屏广告")
            return True
        time.sleep(0.3)
    log("  未检测到开屏跳过")
    return False


def detect_state(device: str, ocr: Ocr) -> str:
    """
    判断当前所在界面:
      'ad'           广告页（可领取）
      'unlock_popup' 播放页解锁弹窗（含「立即解锁 第N天畅听」）
      'player'       播放页，无弹窗
    """
    img = shot(device)
    if ocr.find(img, REG_TOPBAR, ["领取成功", "反馈", "秒后可"]):
        return "ad"
    if ocr.find(img, REG_UNLOCK, ["立即解锁", "畅听", "再看"]):
        return "unlock_popup"
    return "player"


def enter_ad(device: str, ocr: Ocr) -> bool:
    """进入广告：优先弹窗「立即解锁」，其次点「免费听」"""
    log("阶段二：进入广告入口")
    deadline = time.time() + 40
    tapped_free = False
    while time.time() < deadline:
        img = shot(device)
        hit = ocr.find(img, REG_UNLOCK, ["立即解锁", "畅听", "再看"])
        if hit:
            log(f"  命中解锁弹窗: '{hit['text']}' -> 点击")
            tap(device, *BTN_UNLOCK, "立即解锁 今日畅听")
            return True
        if not tapped_free:
            log("  未检测到解锁弹窗，点「免费听」尝试唤起")
            tap(device, *BTN_FREE, "免费听")
            tapped_free = True
        time.sleep(1.5)
    log("  进入广告入口超时")
    return False


def wait_and_claim(device: str, ocr: Ocr) -> int:
    """
    一轮广告：等「领取成功」-> 点击 -> 等「领取奖励」-> 点击。
    返回 1=成功进入下一轮, 0=本轮失败。
    """
    # 1) 等「领取成功」
    deadline = time.time() + CLAIM_TIMEOUT
    got = None
    checks = 0
    while time.time() < deadline:
        img = shot(device)
        got = ocr.find(img, REG_TOPBAR, ["领取成功"])
        if got:
            break
        checks += 1
        if checks == 3 and not ocr.find(img, REG_TOPBAR, ["广告", "反馈", "秒"]):
            log("  连续 3 次截屏无广告页特征，本轮快速失败")
            return 0
        time.sleep(1.0)
    if not got:
        log("  等待「领取成功」超时")
        return 0

    log(f"  倒计时结束: '{got['text']}'")
    tap(device, *BTN_CLAIM_OK, "领取成功")

    # 2) 等「领取奖励」弹窗
    deadline = time.time() + REWARD_TIMEOUT
    got = None
    while time.time() < deadline:
        got = ocr.find(shot(device), REG_POPUP, ["领取奖励"])
        if got:
            break
        time.sleep(0.5)
    if not got:
        log("  未等到「领取奖励」弹窗")
        return 0

    log(f"  弹窗命中: '{got['text']}' -> 点击进入下一轮")
    tap(device, *BTN_REWARD, "领取奖励")
    time.sleep(2.0)  # 等下一个广告加载
    return 1


def handle_live_room(device: str, ocr: Ocr) -> bool:
    """
    检测并清理直播间广告场景：
      1. 领券弹窗（「开心收下」）→ 点击收下
      2. 直播间右上角 × → 关闭
      3. 若关闭后回到播放页解锁弹窗（「再看1个提前领第N天」）→ 重新进广告
    返回 True=确认并清理过直播间。
    """
    img = shot(device)
    if not ocr.find(img, REG_LIVE, ["更多直播", "人气榜", "本场点赞", "开心收下"]):
        return False
    log("  检测到直播间广告，清理中...")
    # 1) 领券弹窗
    hit = ocr.find(img, REG_LIVE_POPUP, ["开心收下"])
    if hit:
        tap(device, hit["cx"], hit["cy"], "开心收下")
        time.sleep(1.5)
    # 2) 关闭直播间
    tap(device, *BTN_LIVE_CLOSE, "直播间关闭")
    time.sleep(4)
    # 3) 关闭后可能回到播放页弹窗，重新点解锁进广告
    img = shot(device)
    hit = ocr.find(img, REG_UNLOCK, ["立即解锁", "畅听", "再看"])
    if hit:
        log(f"  关闭后回到播放页弹窗: '{hit['text']}' -> 重新进入广告")
        tap(device, *BTN_UNLOCK, "立即解锁 畅听")
        time.sleep(3)
    return True


def run_ad_loop(device: str, ocr: Ocr) -> int:
    log("阶段三：广告领取循环（Ctrl+C 可随时中断）")
    success = 0
    idle = 0
    while idle < MAX_IDLE:
        log(f"---- 第 {success + idle + 1} 轮 (成功 {success} / 连续失败 {idle}) ----")
        try:
            r = wait_and_claim(device, ocr)
        except Exception as e:
            log(f"  本轮异常: {e}")
            try:
                device = refresh_device(device)
                log(f"  已重连: {device}")
            except SystemExit:
                log("重连失败，结束循环")
                break
            continue
        if r == 1:
            success += 1
            idle = 0
        else:
            if handle_live_room(device, ocr):
                continue  # 直播间已清理，等广告加载，不计失败
            idle += 1
            time.sleep(3)
    log(f"连续 {MAX_IDLE} 轮无奖励，判定额度耗尽")
    log("尝试点「坚持退出」收尾...")
    tap(device, *BTN_EXIT, "坚持退出")
    return success


def main():
    log("[启动] 汽水音乐 Android 自动领取")
    device = pick_device()
    log(f"设备: {device}")
    ocr = Ocr()

    log("启动汽水音乐...")
    run(device, "shell", "monkey", "-p", PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(1)

    skip_splash(device, ocr)
    time.sleep(2)

    state = detect_state(device, ocr)
    log(f"当前界面状态: {state}")
    if state == "ad":
        log("已在广告流程中，直接开始领取循环")
    elif state == "unlock_popup":
        log("检测到解锁弹窗，点击进入广告")
        tap(device, *BTN_UNLOCK, "立即解锁 畅听")
        time.sleep(3)
    else:
        if not enter_ad(device, ocr):
            log("[结束] 未能进入广告，本次结束")
            return

    total = run_ad_loop(device, ocr)
    log("=" * 50)
    log(f"[结束] 运行结束，共成功领取 {total} 次")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断")
