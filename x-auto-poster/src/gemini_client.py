"""
Gemini API クライアント(テキスト生成 + 画像生成)。

重要: Geminiのモデルラインナップ・無料枠の条件は数か月単位で変わる。
実行前に https://ai.google.dev/gemini-api/docs/models を確認し、
必要なら config.yaml の gemini.text_model / gemini.image_model を更新すること。
また無料枠のレート制限に達した場合、Google側のレスポンスにその旨が明示されるので、
GEMINI_QUOTA_EXCEEDED 例外のメッセージを確認して対応してください。
"""
from __future__ import annotations

from google import genai
from google.genai import types


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, image_model: str, logger):
        self._client = genai.Client(api_key=api_key)
        self._text_model = text_model
        self._image_model = image_model
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

    def generate_post_image(self, prompt: str) -> bytes:
        try:
            response = self._client.models.generate_content(
                model=self._image_model,
                contents=prompt,
            )
        except Exception as e:
            raise GeminiError(f"画像生成でエラーが発生しました(model={self._image_model}): {e}") from e

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            parts = getattr(candidate.content, "parts", None) or []
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is not None and inline_data.data:
                    return inline_data.data

        raise GeminiError(
            "Geminiのレスポンスに画像データが含まれていませんでした。"
            f" model={self._image_model} のレスポンス内容を確認してください: {response}"
        )
