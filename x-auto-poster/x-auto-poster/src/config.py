"""
設定の読み込み。
- 非機密設定: config.yaml
- 機密情報: 環境変数(ローカルでは .env 経由 / GitHub Actions では Secrets 経由)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# ローカル実行時のみ .env を読み込む(GitHub Actions では既に環境変数が注入済み)
load_dotenv(REPO_ROOT / ".env")

REQUIRED_ENV_VARS = [
    "GEMINI_API_KEY",
    "BUFFER_API_KEY",
    "BUFFER_ORGANIZATION_ID",
    "BUFFER_CHANNEL_ID",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
]


class ConfigError(RuntimeError):
    pass


@dataclass
class Secrets:
    gemini_api_key: str
    buffer_api_key: str
    buffer_organization_id: str
    buffer_channel_id: str
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str


@dataclass
class AppConfig:
    posting_times_jst: list[str]
    content: dict[str, Any]
    self_analysis: dict[str, Any]
    gemini: dict[str, Any]
    image: dict[str, Any]
    cloudinary: dict[str, Any]
    secrets: Secrets = field(repr=False)


def load_secrets() -> Secrets:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            "以下の環境変数が設定されていません: "
            + ", ".join(missing)
            + "\n.env ファイル(ローカル)または GitHub Secrets(Actions)を確認してください。"
            "詳しくは README.md の「セットアップ」を参照してください。"
        )
    return Secrets(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        buffer_api_key=os.environ["BUFFER_API_KEY"],
        buffer_organization_id=os.environ["BUFFER_ORGANIZATION_ID"],
        buffer_channel_id=os.environ["BUFFER_CHANNEL_ID"],
        cloudinary_cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        cloudinary_api_key=os.environ["CLOUDINARY_API_KEY"],
        cloudinary_api_secret=os.environ["CLOUDINARY_API_SECRET"],
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else REPO_ROOT / "config.yaml"
    if not config_path.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    try:
        return AppConfig(
            posting_times_jst=raw["posting_times_jst"],
            content=raw["content"],
            self_analysis=raw["self_analysis"],
            gemini=raw["gemini"],
            image=raw["image"],
            cloudinary=raw.get("cloudinary", {}),
            secrets=load_secrets(),
        )
    except KeyError as e:
        raise ConfigError(f"config.yaml に必須項目が不足しています: {e}") from e
