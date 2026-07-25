#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
毎日、Gemini で「絵文字で表せる未出題の英単語30語」を生成する。
- used.json に既出単語を蓄積し、Gemini に除外させて重複を防ぐ
- words/<YYYY-M-D>.json (ゼロ埋めなし＝アプリのdateKeyと一致) に30語を保存
使い方:
  GEMINI_API_KEY=xxx python scripts/gen_words.py --date 2026-07-25 --days 1
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORDS_DIR = os.path.join(ROOT, "words")
USED_PATH = os.path.join(ROOT, "used.json")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
DAILY = 30

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U00002190-\U000021FF\U0001F1E6-\U0001F1FF\U0000FE00-\U0000FE0F\U0000200D]"
)


def has_emoji(s):
    return bool(s) and bool(EMOJI_RE.search(s))


def load_used():
    if os.path.exists(USED_PATH):
        try:
            return set(w.lower() for w in json.load(open(USED_PATH, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_used(used):
    json.dump(sorted(used), open(USED_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)


def gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.1, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    return d["candidates"][0]["content"]["parts"][0]["text"]


def gen_batch(n, used, got_en):
    exclude = sorted(used | got_en)
    ex = exclude[-900:] if len(exclude) > 900 else exclude   # 送りすぎ防止
    prompt = f"""あなたは4〜6歳の子ども向け英語クイズの単語を作る専門家です。
条件:
- 具体的で身近な、子どもが日常で出会う英単語（名詞中心。動物・食べ物・果物・野菜・乗り物・
  体・自然・天気・遊び道具・楽器・スポーツ・衣類・家・場所・人・仕事など）
- 各単語は「1つのUnicode絵文字」で分かりやすく表せるものだけ（絵文字が無い抽象語はダメ）
- 次のリストの単語は絶対に含めない（すでに出題済み）: {', '.join(ex) if ex else '(なし)'}
- 単語どうしの重複なし
ちょうど {n} 語を、次の形式のJSON配列だけで出力してください（説明文は不要）:
[{{"en":"lion","read":"ライオン","ja":"ライオン","emoji":"🦁"}}]
en=英単語(小文字), read=カタカナ読み, ja=やさしい日本語(ひらがな中心), emoji=最も合う絵文字1つ。"""
    txt = gemini(prompt)
    try:
        arr = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.S)
        arr = json.loads(m.group(0)) if m else []
    out = []
    for it in arr if isinstance(arr, list) else []:
        en = (it.get("en") or "").strip()
        emoji = (it.get("emoji") or "").strip()
        if not en or en.lower() in used or en.lower() in got_en:
            continue
        if not has_emoji(emoji):
            continue
        out.append({"en": en, "read": (it.get("read") or "").strip(),
                    "ja": (it.get("ja") or "").strip(), "emoji": emoji})
    return out


def generate_day(date_key, used):
    got, seen_emoji, got_en, tries = [], set(), set(), 0
    while len(got) < DAILY and tries < 6:
        try:
            batch = gen_batch(DAILY - len(got), used, got_en)
        except Exception as e:
            print(f"  Gemini呼び出し失敗(retry): {e}")
            time.sleep(3); tries += 1; continue
        for w in batch:
            if w["en"].lower() in used or w["en"].lower() in got_en:
                continue
            if w["emoji"] in seen_emoji:      # 同じ日の中で絵文字が被らないように
                continue
            got.append(w); got_en.add(w["en"].lower()); seen_emoji.add(w["emoji"])
            if len(got) >= DAILY:
                break
        tries += 1
    for w in got:
        used.add(w["en"].lower())
    os.makedirs(WORDS_DIR, exist_ok=True)
    json.dump({"date": date_key, "words": got},
              open(os.path.join(WORDS_DIR, date_key + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (省略時は今日/JST)")
    ap.add_argument("--days", type=int, default=1, help="連続で何日分生成するか")
    args = ap.parse_args()
    if not KEY:
        print("GEMINI_API_KEY が未設定です"); sys.exit(1)

    used = load_used()
    JST = datetime.timezone(datetime.timedelta(hours=9))
    start = (datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
             if args.date else datetime.datetime.now(JST).date())
    for i in range(args.days):
        ds = start + datetime.timedelta(days=i)
        key = f"{ds.year}-{ds.month}-{ds.day}"   # ゼロ埋めなし＝アプリのdateKeyと一致
        path = os.path.join(WORDS_DIR, key + ".json")
        if os.path.exists(path):
            print(f"{key}: 既存のためスキップ"); continue
        n = generate_day(key, used)
        print(f"{key}: {n}語 生成")
    save_used(used)
    print(f"used.json: 累計 {len(used)} 語")


if __name__ == "__main__":
    main()
