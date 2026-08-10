"""
Gemini API クライアント(テキスト生成専用)。

画像生成は行わない: Geminiのネイティブ画像生成モデル(2.5/3.1 Flash Image, Imagen 4等)は
2026年8月確認時点で無料枠が無いため、画像生成は cloudflare_image_client.py 側に切り出している。

重要: Geminiのモデルラインナップ・無料枠の条件は数か月単位で変わる。
実行前に https://ai.google.dev/gemini-api/docs/pricing の該当モデルの
「Free Tier」列を確認し、必要なら config.yaml の gemini.text_model を更新すること。
"""
from __future__ import annotations

from google import genai
from google.genai import types


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, logger):
        self._client = genai.Client(api_key=api_key)
        self._text_model = text_model
        self._log = logger

    def generate_post_text(self, prompt: str, temperature: float = 1.0, max_output_tokens: int = 400) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
        except Exception as e:
            raise GeminiError(f"テキスト生成でエラーが発生しました(model={self._text_model}): {e}") from e

        text = (response.text or "").strip()
        if not text:
            raise GeminiError(
                f"Geminiから空のテキストが返されました。safety設定でブロックされた可能性があります。"
                f" response={response}"
            )
        return text
