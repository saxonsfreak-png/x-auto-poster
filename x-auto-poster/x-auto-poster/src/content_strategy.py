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


def build_text_prompt(
    content_config: dict[str, Any],
    reference_posts: list[dict[str, Any]],
) -> str:
    genre = content_config["genre"]
    min_chars = content_config["min_chars"]
    max_chars = content_config["max_chars"]
    avoid_phrases = _format_avoid_phrases(content_config.get("avoid_phrases", []))
    reference_block = _format_reference_posts(reference_posts)

    return f"""\
あなたはX(旧Twitter)向けの投稿文を書く、経験豊富なソーシャルメディアライターです。
以下の条件で、日本語の投稿文を1つだけ書いてください。前置きや説明は不要で、投稿文の本文のみを出力してください。

# ジャンル
{genre}

# 文字数
{min_chars}〜{max_chars}文字(厳守)

# 文章の書き方の原則
{HOOK_PRINCIPLES}

# 避けるべき表現(スパムや誇大広告と誤認されやすいため)
{avoid_phrases}

# このアカウントで過去に反応が良かった投稿(参考にしてよいのはトーンや構成のみ。
# 文面や具体的な言い回しをそのまま流用しないこと)
{reference_block}

# 出力形式
投稿文本文のみ。前後に説明・タイトル・引用符などは付けないこと。
"""


def build_image_prompt(post_text: str, image_config: dict[str, Any]) -> str:
    style_prompt = image_config["style_prompt"]
    aspect_ratio = image_config.get("aspect_ratio", "1:1")
    return f"""\
次の投稿文のテーマを視覚的に想起させる、1枚のイラストを生成してください。

# 投稿文(テーマの参考。文章そのものを画像内に描画しないこと)
{post_text}

# スタイル指定
{style_prompt}

# その他条件
- 文字・ロゴ・透かし・UIのようなものは一切含めないこと
- アスペクト比: {aspect_ratio}
"""
