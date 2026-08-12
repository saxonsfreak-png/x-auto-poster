"""
Cloudflare Workers AI(REST API)クライアント。画像生成専用。

Geminiのネイティブ画像生成モデルは無料枠が無い(2026年8月確認)ため、
画像生成だけこちらに切り出している。テキスト生成は引き続き gemini_client.py(Gemini)を使用する。

無料枠: 10,000 neurons/日(画像1枚あたり目安50〜100 neurons。1日3枚なら全く問題にならない)
公式ドキュメント: https://developers.cloudflare.com/workers-ai/get-started/rest-api/
モデル一覧: https://developers.cloudflare.com/workers-ai/models/
"""
from __future__ import annotations

import base64

import requests

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4/accounts"


class CloudflareImageError(RuntimeError):
    pass


class CloudflareImageClient:
    def __init__(self, account_id: str, api_token: str, model: str, logger):
        self._url = f"{CLOUDFLARE_API_BASE}/{account_id}/ai/run/{model}"
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._model = model
        self._log = logger

    def generate_image(self, prompt: str, steps: int = 4) -> bytes:
        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json={"prompt": prompt, "steps": steps},
                timeout=60,
            )
        except requests.RequestException as e:
            raise CloudflareImageError(f"Cloudflare Workers AIへのリクエストに失敗しました: {e}") from e

        if resp.status_code != 200:
            raise CloudflareImageError(
                f"Cloudflare Workers AIがエラーを返しました(status={resp.status_code}, model={self._model}): {resp.text}"
            )

        data = resp.json()
        if not data.get("success", False):
            raise CloudflareImageError(f"Cloudflare Workers AIが失敗を返しました: {data.get('errors')}")

        # レスポンス形状は result.image に base64文字列が入る想定
        # (公式ドキュメントのWorkerバインディング例: `response.image` を atob() でデコード)。
        # モデルやAPIバージョンにより形状が変わる可能性があるため、想定外の形の場合は
        # エラーメッセージにレスポンス全体を含めてデバッグしやすくしている。
        result = data.get("result")
        image_b64 = None
        if isinstance(result, dict):
            image_b64 = result.get("image")

        if not image_b64:
            raise CloudflareImageError(
                "Cloudflare Workers AIのレスポンスに result.image が見つかりませんでした。"
                f" レスポンス全体: {data}"
            )

        try:
            return base64.b64decode(image_b64)
        except Exception as e:
            raise CloudflareImageError(f"画像データ(base64)のデコードに失敗しました: {e}") from e
