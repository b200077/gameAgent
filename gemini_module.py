# ── gemini_module.py ────────────────────────────────
# Gemini API 呼叫（文字 / 圖片），含重試與備用模型
# 金鑰讀取 .env 的 GEMINI_API_KEY

import os
import random
import sys
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
import httpx

# PyInstaller --onefile 時 __file__ 在暫存資料夾，要改讀 exe 旁邊的 .env
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_BASE_DIR, ".env"))

RETRYABLE = {429, 500, 502, 503, 504}
MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]  # 依序當主模型與備用
TIMEOUT_SEC = 20  # 單次請求逾時秒數，超過就換下一個模型，避免一直等不到回應

_client = None

def get_client():
    """第一次使用時才建立 client，避免沒有金鑰時 import 就失敗"""
    global _client
    if _client is None:
        _client = genai.Client(http_options=types.HttpOptions(timeout=TIMEOUT_SEC * 1000))
    return _client


USAGE_LOG = os.path.join(_BASE_DIR, "gemini_usage.log")  # 每次呼叫的 token 用量紀錄


def _log_usage(model, resp):
    """把這次呼叫的 token 用量寫進 gemini_usage.log，回傳一行摘要"""
    u = getattr(resp, "usage_metadata", None)
    inp = getattr(u, "prompt_token_count", None) or 0
    out = getattr(u, "candidates_token_count", None) or 0
    think = getattr(u, "thoughts_token_count", None) or 0
    total = getattr(u, "total_token_count", None) or (inp + out + think)
    line = f"模型 {model}｜輸入 {inp}｜輸出 {out}｜思考 {think}｜合計 {total} tokens"
    _write_log(line)
    print("[Gemini]", line)
    return line


def _write_log(line):
    """用量與錯誤都寫進 gemini_usage.log，exe 出問題時可以回頭查"""
    try:
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
    except OSError:
        pass


def generate_content_with_usage(contents, retries=3, config=None):
    """回傳 (文字, 用量摘要)。contents 可以是字串，或 [PIL.Image, 字串, ...] 的 list"""
    client = get_client()
    last_err = None
    for model in MODELS:
        for i in range(retries):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return resp.text, _log_usage(model, resp)
            except httpx.TimeoutException:
                last_err = f"{model} 超過 {TIMEOUT_SEC} 秒沒有回應"
                print(f"[Warning] {last_err}，換下一個模型")
                _write_log(f"[錯誤] {last_err}")
                break
            except errors.APIError as e:
                last_err = e
                if e.code == 404:
                    print(f"[Skip] {model} 不存在，換下一個")
                    break
                if e.code not in RETRYABLE:
                    _write_log(f"[錯誤] {model} {e.code} {e.status}: {e.message}")
                    raise
                wait = (2 ** i) + random.uniform(0, 1)
                print(f"[Warning] {model} {e.code} {e.status}，{wait:.1f}s 後重試 ({i+1}/{retries})")
                time.sleep(wait)
    _write_log(f"[錯誤] 所有模型皆失敗: {last_err}")
    raise RuntimeError(f"所有模型皆失敗: {last_err}")


def generate_content(contents, retries=3, config=None):
    return generate_content_with_usage(contents, retries=retries, config=config)[0]


def generate_text(prompt, retries=3, config=None):
    return generate_content(prompt, retries=retries, config=config)


IMAGE_EXPLAIN_PROMPT = """請分析這張圖片（通常是遊戲畫面截圖），用繁體中文回答，格式如下：

【圖片內容】
（簡短說明這是什麼畫面、在做什麼）

【原文】
（逐字抄出圖片中的文字，保留原本語言；沒有文字就寫「無」）

【原文解釋】
（這一段「用原文的語言」寫，不要用中文。先說圖片中的文字是什麼，日文要附上假名讀音，
  再用一兩句說明它的意思、語氣與使用場合。例如日文：
  画像に書かれている日本語のテキストは「畏まりました♡」（かしこまりました♡）です。
  「かしこまりました」は、目上の人に対して「承知いたしました」「了解いたしました」という意味を丁寧に表す言葉です。
  原文是中文或沒有文字則省略這一段）

【解釋】
（若原文是外語（日文、英文、韓文等）：說明重要單字的讀音與意思、文法重點、語氣或在遊戲中的用法；
  若是中文：說明專有名詞、遊戲術語或可能需要注意的地方）

【中文翻譯】
（原文若非中文，給出自然通順的繁體中文翻譯；原文已是中文則寫「（原文即中文）」）"""


# 思考等級調低：看圖翻譯不需要深度推理，回應更快、思考 token 也更少
IMAGE_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
)


def explain_image(pil_image, retries=1):
    # retries=1：主模型忙碌(503/504)就直接換備用模型，不在同一個模型上重試等太久
    """把圖片傳給 Gemini，回傳 (說明與翻譯, 用量摘要)"""
    return generate_content_with_usage(
        [pil_image, IMAGE_EXPLAIN_PROMPT], retries=retries, config=IMAGE_CONFIG
    )


if __name__ == "__main__":
    print("伺服器收到的回應：", generate_text("請用一句話介紹什麼是 API。"))
