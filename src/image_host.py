"""
Cloudinary への画像アップロード。

Buffer の API は画像ファイルの直接アップロードを受け付けず、
「認証不要で誰でも開ける公開URL」を要求する(署名付き/期限切れURLは不可)。
そのため Gemini が生成した画像バイト列を、いったんここで
Cloudinary(無料枠: 25クレジット/月 = 今回の用途では十分すぎる余裕)にアップロードし、
その安定した公開URLを Buffer に渡す。

参考: https://developers.buffer.com/guides/hosting-media.html
"""
from __future__ import annotations

import io
import uuid

import cloudinary
import cloudinary.uploader


class ImageHostError(RuntimeError):
    pass


class ImageHost:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str, folder: str, logger):
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        self._folder = folder
        self._log = logger

    def upload(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        public_id = f"{self._folder}/{uuid.uuid4().hex}"
        try:
            result = cloudinary.uploader.upload(
                io.BytesIO(image_bytes),
                public_id=public_id,
                folder=self._folder,
                resource_type="image",
                overwrite=False,
            )
        except Exception as e:  # cloudinary SDK raises its own exception types
            raise ImageHostError(f"Cloudinaryへの画像アップロードに失敗しました: {e}") from e

        secure_url = result.get("secure_url")
        if not secure_url:
            raise ImageHostError(f"Cloudinaryのレスポンスに secure_url が含まれていません: {result}")

        return secure_url
