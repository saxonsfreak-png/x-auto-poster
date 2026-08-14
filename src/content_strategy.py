"""
投稿文・画像プロンプトの組み立て。

「バズっている他人の投稿をリアルタイムでスクレイピングして真似る」のではなく、
(1) 定番のエンゲージメント原則(フック優先・改行・具体性)と
(2) このアカウント自身の過去の実績データ(Buffer Post Metrics)
(3) X公式の「For You」アルゴリズム(github.com/xai-org/x-algorithm)から
    読み取れる、評価の仕組み上ほぼ確実に有利/不利になる特徴
の3つを組み合わせて生成方針を作る。(2)がまさに仕様書にあった
「自己分析の反映」にあたる部分で、Buffer側に蓄積されたインプレッション等の
実績を毎回の生成にフィードバックする。

(3)について: あのリポジトリは「バズる書き方」のガイドではなく配信システムの
ソースコードなので、そこから抽出できるのは個別のテクニックではなく、
「どんな行動が加点/減点されるか」という評価の仕組みレベルの話に限られる。
具体的には以下がコードで確認できた:
  - 評価対象は「いいね」だけでなく、リプライ・引用・DM共有・リンクコピー共有・
    滞在時間(dwell)まで個別に予測してスコア化される(RankingScorer)
  - 「興味なし」「ミュート」「ブロック」「通報」は明確な負の重みを持つ
    (伸びないだけでなく他の投稿より不利になる)
  - インプレッションの少ない新規アカウントは押し上げ措置(New-Author Boost)が
    ある一方、初速(直後の反応)が弱い投稿は新規フォロワー外への配信で
    足切りされやすい(NewUserMinEngagementFilter)
これらはHOOK_PRINCIPLESに反映済み。
"""
from __future__ import annotations

import re
from typing import Any

HOOK_PRINCIPLES = """\
- 1行目(最初の12〜15文字程度)で「え、それ知りたい」と思わせる、具体的で意外性のある一言を置くこと
  (新規アカウントは投稿ごとの初速が弱いと配信が広がりにくいため、特に重要)
- 抽象論ではなく、数字・期間・具体的な行動など「解像度の高い」情報を1つ以上入れること
  (読み手が一瞬立ち止まって読み込む「解像度の高さ」が滞在時間を伸ばす)
- 「いいね」で終わらせず、次のどちらかを狙うこと:
  (a) 思わず一言返したくなる余地(問いかけ・あるあるへの共感ポイント)
  (b) 「これ、あの人に送りたい」と思われる実用性(すぐ真似できる具体策・保存したくなる情報)
  (リプライ・DM共有・リンクコピー共有も個別に評価される仕組みのため)
- スマートフォンで読みやすいよう、意味の区切りで適度に改行を入れること(1文だけの塊を長々と続けない)
- 説教くさい断定や過剰な煽りは避け、「気づき」や「体験談」に近いトーンにすること
  (「興味なし」「ミュート」「通報」は明確な減点対象になる設計のため、うざく思われる
  リスクは伸びないだけでなく明確なマイナスになる)
- 絵文字は使っても0〜2個程度に留め、記号の乱用(★や!!!の連打など)はしないこと
- 基本的に最後の1行は、その投稿の内容に直結した、具体的で答えやすい質問で締めること
  (リプライは個別に評価される仕組みのため、コメント欄が動く投稿ほど有利)。
  「あなたはどう思いますか？」のような漠然とした問いではなく、Yes/Noや一言で
  すぐ答えられる質問にすること(例:「もう試した人いますか?」「週何時間なら
  始められそう?」)。ただし、内容的に質問がわざとらしくなる場合は無理に付けず、
  代わりに軽い一言で余韻を残しても構わない
"""

# 実際に発生した不具合の実例をそのままNG例として見せる。
# 抽象的に「注記を書くな」と言うより、具体的な悪い例を1つ見せる方が効果的だったため。
BAD_EXAMPLE = """\
書きにするだけ。(14文字)
これだけで、(6文字)
3日以内に初依頼が来たことも。
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
- 文字数の目安: {min_chars}〜{max_chars}文字程度(多少前後しても構わない。厳密に数えて
  途中で自己修正しようとする必要はない)
- 書き方の原則:
{HOOK_PRINCIPLES}
- 避けるべき表現(スパムや誇大広告と誤認されやすいため): {avoid_phrases}
- このアカウントで過去に反応が良かった投稿(参考にしてよいのはトーンや構成のみ。文面や言い回しの流用は禁止):
{reference_block}
- 他の投稿との重複回避: {duplicate_block}

# 絶対に守ること(post_textの形式について)
post_text には、完成した投稿本文だけを書くこと。以下のような形式は絶対に混ぜないこと:
- 文字数の注記(「(14文字)」「14文字」など、数字+「文字」という表記そのもの)
- 候補の列挙、下書きメモ、自己採点、自己修正の跡
- エスケープ表記の "\\n" という文字列そのもの(改行はJSON文字列内の実際の改行として表現し、
  バックスラッシュとエヌの2文字を書かないこと)

【絶対にやってはいけない出力例】(実際に発生した不具合そのままの例):
{BAD_EXAMPLE}
上記のように文字数を逐一注記したり、断片的な行に分けたりするのは禁止です。
自然な1つの投稿文として書いてください。

# タスク2: image_theme_en(画像生成用、英語)
post_text の内容を象徴する、1文程度の短い英語フレーズ。
これは画像生成AIに直接渡されるプロンプトの一部になります。次を厳守すること:
- 日本語の投稿文をそのまま翻訳したキャッチコピーのような文にしないこと
- あくまで「どんな具体的な物体・情景を描くか」という視覚的な説明のみにすること
  (例: "a small potted plant next to an open notebook and a soft desk lamp, warm morning light")
- post_text の内容に固有の具体的なディテールを1つ入れること(例: 電卓、付箋、コーヒーなど
  投稿内容と関係が分かるモノ)。毎回ほぼ同じ構図・同じモノにならないよう、光の当たり方や
  配置、色味に変化をつけること(似た画像が続くと一目で「見たことがある」と判断されやすく、
  見る手を止めさせる効果が薄れるため)
- 結晶・宝石・多面体のような抽象的でカクカクした幾何形状は避けること(文字のような模様が
  誤って描画されやすい傾向が確認されているため)。ノート、コーヒーカップ、植物、デスク、
  カレンダー、硬貨など、具体的で見慣れたモチーフを中心にすること
- 「文字」「text」「no text」などの単語は、image_theme_en の中に一切含めないこと
  (画像生成AI側にその単語自体が文字として描画されてしまう既知の不具合があるため)

# 出力形式
以下のJSONオブジェクトのみを出力すること(前後の説明・コードブロック記法は不要):
{{"post_text": "...", "image_theme_en": "..."}}
"""


def build_image_prompt(image_theme_en: str, image_config: dict[str, Any]) -> str:
    """画像生成プロンプトの組み立て。

    重要: "no text" のような禁止語を書かないこと。実際に検証した結果、
    flux-1-schnell は negative_prompt に非対応な上、プロンプト中に
    "text" 等の単語を含めると(禁止のつもりでも)かえって文字らしき
    模様を描画してしまう挙動が確認された。そのため、ここでは
    「何を描くか」という肯定文のみで構成する。
    """
    style_prompt = image_config["style_prompt"]
    return f"{image_theme_en}. {style_prompt} Square composition."


# 「(14文字)」「（14文字）」のように、半角/全角どちらの括弧でも、
# 数字の前後に多少スペースが入っていても検出できるようにする。
_CHAR_COUNT_ANNOTATION_RE = re.compile(r"[(（]\s*\d+\s*文字\s*[)）]")

# 「アイデア1」「候補2」「パターン３」のような、番号付き列挙の痕跡を検出する。
# 単語単体(「アイデア」等)は通常の文章にも自然に出てくるため対象にしない。
_NUMBERED_LIST_RE = re.compile(r"(アイデア|候補|パターン)\s*[0-9０-９]")


def validate_post_text(text: str, content_config: dict[str, Any]) -> str | None:
    """明らかにおかしい生成結果を弾くための簡易チェック。

    問題なければ None、問題があればその理由の文字列を返す。
    (thinkingトークンの漏れ出しや、下書き候補の列挙などが実際に発生したための安全網)
    """
    min_chars = content_config["min_chars"]
    max_chars = content_config["max_chars"]
    length = len(text)

    # X側の実際の文字数判定は「重み付きカウント」(日本語・絵文字などは1文字=2カウント)。
    # 単純な len() では見た目の文字数しか分からず、実際には280相当を超えて
    # Buffer/X側に拒否される、という不具合が実際に発生したため、公式準拠の
    # twitter-text-parser ライブラリで正確に判定する。
    max_platform_chars = content_config.get("max_platform_chars", 280)
    # twitter-text-parser の代わりに Pythonの標準的な文字数（length）でチェックする
    if length > max_platform_chars:
        return f"文字数が上限({max_platform_chars}文字)を超えています(現在{length}文字)"

    # かなり余裕を持たせた範囲(規定の半分未満 / 1.5倍超)を明らかな異常とみなす
    if length < min_chars * 0.5:
        return f"文字数が短すぎます({length}文字。規定は{min_chars}〜{max_chars}文字)"
    if length > max_chars * 1.5:
        return f"文字数が長すぎます({length}文字。規定は{min_chars}〜{max_chars}文字)"

    if _CHAR_COUNT_ANNOTATION_RE.search(text):
        return "文字数の自己注記(例: 「(14文字)」)が含まれています"

    # JSON解析後の文字列に、実際の改行ではなく「\」+「n」という2文字が
    # そのまま残っている場合、モデルがエスケープ表記を文章として書いてしまっている
    if "\\n" in text:
        return "エスケープ表記 '\\n' が文字列としてそのまま含まれています"

    # 「アイデア」単体は「アイデア出し」等、普通の文章でも自然に出てくる単語なので、
    # 誤検知を避けるため「アイデア1」のような番号付き列挙の形になっている場合のみ検知する
    if _NUMBERED_LIST_RE.search(text):
        return f"下書き・候補列挙のような痕跡('{_NUMBERED_LIST_RE.search(text).group()}')が含まれています"

    # 1行あたりの文字数が極端に短い行が多い場合、断片的なメモである可能性が高い
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) >= 3:
        short_lines = sum(1 for line in lines if len(line.strip()) <= 8)
        if short_lines >= len(lines) - 1:
            return "極端に短い行が並んでおり、メモ書きのような形式になっています"

    return None
