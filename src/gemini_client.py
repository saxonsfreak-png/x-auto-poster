"""
Gemini API クライアント(テキスト生成専用)。

画像生成は行わない: Geminiのネイティブ画像生成モデル(2.5/3.1 Flash Image, Imagen 4等)は
2026年8月確認時点で無料枠が無いため、画像生成は cloudflare_image_client.py 側に切り出している。

重要: Geminiのモデルラインナップ・無料枠の条件は数か月単位で変わる。
実行前に https://ai.google.dev/gemini-api/docs/pricing の該当モデルの
「Free Tier」列を確認し、必要なら config.yaml の gemini.text_model を更新すること。
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

# post_text(投稿文本文)と image_theme_en(画像生成用の英語テーマ)を
# 1回の呼び出しで両方取得する。image_theme_en を分けている理由は
# content_strategy.py のコメント参照(日本語の投稿文をそのまま画像プロンプトに
# 渡すと、画像モデルがそれを"描画すべき文字"と誤認して文字化けを起こすため)。
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "post_text": {"type": "string"},
        "image_theme_en": {"type": "string"},
    },
    "required": ["post_text", "image_theme_en"],
}


@dataclass
class GeneratedContent:
    post_text: str
    image_theme_en: str


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, logger):
        self._client = genai.Client(api_key=api_key)
        self._text_model = text_model
        self._log = logger

    def generate_post_content(
        self, prompt: str, temperature: float = 1.0, max_output_tokens: int = 1024
    ) -> GeneratedContent:
        try:
            response = self._client.models.generate_content(
                model=self._text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    # 「思考(thinking)」モデルだと、ここで確保したトークン予算を
                    # 目に見えない思考過程が消費してしまい、本文が尻切れになることがある
                    # (実際に発生した不具合)。短い投稿文を書くだけの処理なので無効化する。
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                ),
            )
        except Exception as e:
            raise GeminiError(f"テキスト生成でエラーが発生しました(model={self._text_model}): {e}") from e

        candidates = getattr(response, "candidates", None) or []
        finish_reason = candidates[0].finish_reason if candidates else None
        if finish_reason is not None and finish_reason.name == "MAX_TOKENS":
            raise GeminiError(
                f"max_output_tokens({max_output_tokens})に達し、本文が途中で切れました。"
                " config.yaml の gemini.text_generation_config.max_output_tokens を増やしてください。"
            )

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise GeminiError(
                "Geminiから空のレスポンスが返されました。safety設定でブロックされた可能性があります。"
                f" finish_reason={finish_reason} response={response}"
            )

        try:
            parsed = json.loads(raw_text)
            post_text = str(parsed["post_text"]).strip()
            image_theme_en = str(parsed["image_theme_en"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise GeminiError(f"Geminiの応答を期待した形式(JSON)として解析できませんでした: {e}. raw={raw_text!r}") from e

        if not post_text or not image_theme_en:
            raise GeminiError(f"post_text または image_theme_en が空でした。raw={raw_text!r}")

        return GeneratedContent(post_text=post_text, image_theme_en=image_theme_en)
