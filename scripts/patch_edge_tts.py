#!/usr/bin/env python3
"""临时补丁：修复 edge-tts 合成端点 403（对应上游 PR #491）

背景（2026-10-13）：
  微软已将 Edge TTS 的**合成** WebSocket 端点从
    wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=...
  迁移到
    wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key=...
  edge-tts 7.2.8（PyPI 当前最新，2026-03-22 发布）仍指向旧端点 → 握手 403、合成完全失败。
  上游修复 PR：https://github.com/rany2/edge-tts/pull/491 （尚未合并发布）
  参考 issue：https://github.com/rany2/edge-tts/issues/490

本脚本直接改写 site-packages 内 edge_tts/constants.py 的 WSS_URL。
⚠️ 必须改文件、不能 monkeypatch 变量：communicate.py 用的是
   `from .constants import WSS_URL`，在 import 时即完成绑定，改常量对象不会生效。

自愈设计：官方发布含该修复的新版后，"旧行"不再存在 → 自动跳过，无需人工撤除本步骤。
退出码恒为 0（补丁失败不应阻断日报流程），异常一律以 ::warning:: 形式提示。
"""
import pathlib
import sys

OLD = 'WSS_URL = f"wss://{BASE_URL}/edge/v1?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"'
NEW = (
    'WSS_URL = (\n'
    '    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"\n'
    '    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"\n'
    ')'
)


def main():
    dry = "--dry" in sys.argv
    try:
        import edge_tts
    except ImportError:
        print("::warning::edge_tts 未安装，跳过 403 补丁")
        return 0

    p = pathlib.Path(edge_tts.__file__).parent / "constants.py"
    if not p.exists():
        print(f"::warning::未找到 {p}，跳过 403 补丁")
        return 0

    s = p.read_text(encoding="utf-8")

    if OLD in s:
        if dry:
            print(f"[dry-run] 将把 WSS_URL 切换为新端点：{p}")
            return 0
        p.write_text(s.replace(OLD, NEW), encoding="utf-8")
        print("✅ edge-tts 403 补丁已应用：合成端点 → api.msedgeservices.com")
    elif "api.msedgeservices.com" in s:
        print("· edge-tts 已在用新端点（上游已修复），补丁自动跳过")
    else:
        print("::warning::constants.py 中未匹配到预期 WSS_URL，edge-tts 结构可能已变，请人工检查")
    return 0


if __name__ == "__main__":
    sys.exit(main())
