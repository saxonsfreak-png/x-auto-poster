"""
投稿文・画像プロンプトの組み立て。

「バズっている他人の投稿をリアルタイムでスクレイピングして真似る」のではなく、
(1) 定番のエンゲージメント原則(フック優先・改行・具体性)と
(2) このアカウント自身の過去の実績データ(Buffer Post Metrics)
の2つを組み合わせて生成方針を作る。(2)がまさに仕様書にあった
「自己分析の反映」にあたる部分で、Buffer側に蓄積されたインプレッション等の
実績を毎回の生成にフィードバックする。
"""
from __future__ import annotations

from typing import Any

HOOK_PRINCIPLES = """\
- 1行目(最初の12〜15文字程度)で「え、それ知りたい」と思わせる、具体的で意外性のある一言を置くこと
- 抽象論ではなく、数字・期間・具体的な行動など「解像度の高い」情報を1つ以上入れること
- スマートフォンで読みやすいよう、意味の区切りで適度に改行を入れること(1文だけの塊を長々と続けない)
- 説教くさい断定や過剰な煽りは避け、「気づき」や「体験談」に近いトーンにすること
- 絵文字は使っても0〜2個程度に留め、記号の乱用(★や!!!の連打など)はしないこと
- 最後に、押し付けがましくない一言(問いかけや軽い一言)で余韻を残すこと
"""


def _format_avoid_phrases(avoid_phrases: list[str]) -> str:
    if not avoid_phrases:
        return "(特になし)"
    return "、".join(avoid_phrases)


def _format_reference_posts(reference_posts: list[dict[str, Any]]) -> str:
    if not reference_posts:
        return "(まだ実績データがありません。定番のフック原則のみを参考にしてください。)"

    lines = []
    for i, post in enumerate(reference_posts, start=1):
        impressions = next(
            (m["value"] for m in post.get("metrics", []) if m.get("type") == "impressions"),
            None,
        )
        reactions = next(
            (m["value"] for m in post.get("metrics", []) if m.get("type") == "reactions"),
            None,
        )
        stats = []
        if impressions is not None:
            stats.append(f"インプレッション約{int(impressions)}")
        if reactions is not None:
            stats.append(f"リアクション約{int(reactions)}")
        stats_str = f"({', '.join(stats)})" if stats else ""
        lines.append(f"{i}. {stats_str}\n{post['text']}")
    return "\n\n".join(lines)


def _format_avoid_duplicates(already_used_texts: list[str]) -> str:
    if not already_used_texts:
        return "(今回はまだ他に生成した投稿はありません)"
    numbered = "\n".join(f"- {t}" for t in already_used_texts)
    return (
        "今回の実行で既に以下の投稿文を生成済みです。話題の切り口・書き出し・文構造が"
        f"似すぎないよう、明確に違う角度で書いてください。\n{numbered}"
    )


def build_text_prompt(
    content_config: dict[str, Any],
    reference_posts: list[dict[str, Any]],
    already_used_texts: list[str] | None = None,
) -> str:
    genre = content_config["genre"]
    min_chars = content_config["min_chars"]
    max_chars = content_config["max_chars"]
    avoid_phrases = _format_avoid_phrases(content_config.get("avoid_phrases", []))
    reference_block = _format_reference_posts(reference_posts)
    duplicate_block = _format_avoid_duplicates(already_used_texts or [])

    return f"""\
あなたはX(旧Twitter)向けの投稿文を書く、経験豊富なソーシャルメディアライターです。
以下の条件を満たす投稿を1件作成し、指定したJSON形式のみで出力してください。

# タスク1: post_text(投稿文本文、日本語)
- ジャンル: {genre}
- 文字数: {min_chars}〜{max_chars}文字(厳守。文字数の注記や候補の列挙などは一切書かず、完成した本文だけを書くこと)
- 書き方の原則:
{HOOK_PRINCIPLES}
- 避けるべき表現(スパムや誇大広告と誤認されやすいため): {avoid_phrases}
- このアカウントで過去に反応が良かった投稿(参考にしてよいのはトーンや構成のみ。文面や言い回しの流用は禁止):
{reference_block}
- 他の投稿との重複回避: {duplicate_block}

# タスク2: image_theme_en(画像生成用、英語)
post_text の内容を象徴する、1文程度の短い英語フレーズ。
これは画像生成AIに直接渡されるプロンプトの一部になります。次を厳守すること:
- 日本語の投稿文をそのまま翻訳したキャッチコピーのような文にしないこと(画像に文字として
  描画されようとして文字化けする原因になる)
- あくまで「どんな物体・情景・構図を描くか」という視覚的な説明のみにすること
  (例: "a small potted plant next to an open notebook and a soft desk lamp, warm morning light")
- 文字・数字・記号・看板・本のタイトルなど、画像内に文字として現れそうな要素は絶対に含めないこと

# 出力形式
以下のJSONオブジェクトのみを出力すること(前後の説明・コードブロック記法は不要):
{{"post_text": "...", "image_theme_en": "..."}}
"""


def build_image_prompt(image_theme_en: str, image_config: dict[str, Any]) -> str:
    style_prompt = image_config["style_prompt"]
    return (
        f"{image_theme_en}. {style_prompt} "
        "No text, no letters, no words, no numbers, no logos, no watermarks, no signage, "
        "no typography of any kind anywhere in the image. Square composition."
    )


def validate_post_text(text: str, content_config: dict[str, Any]) -> str | None:
    """明らかにおかしい生成結果を弾くための簡易チェック。

    問題なければ None、問題があればその理由の文字列を返す。
    (thinkingトークンの漏れ出しや、下書き候補の列挙などが実際に発生したための安全網)
    """
    min_chars = content_config["min_chars"]
    max_chars = content_config["max_chars"]
    length = len(text)

    # かなり余裕を持たせた範囲(規定の半分未満 / 1.5倍超)を明らかな異常とみなす
    if length < min_chars * 0.5:
        return f"文字数が短すぎます({length}文字。規定は{min_chars}〜{max_chars}文字)"
    if length > max_chars * 1.5:
        return f"文字数が長すぎます({length}文字。規定は{min_chars}〜{max_chars}文字)"

    suspicious_markers = ["文字)", "文字】", "アイデア", "候補1", "候補2", "パターン1", "パターン2"]
    for marker in suspicious_markers:
        if marker in text:
            return f"下書き・候補列挙のような痕跡('{marker}')が含まれています"

    return None
