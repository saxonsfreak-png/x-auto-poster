"""
ログ設定。
各フェーズ(生成・画像・アップロード・投稿)の成否が一目で分かるよう、
フェーズ名をログに含めることを前提にした setup。
GitHub Actions のログにもそのまま出力され、ジョブの実行結果画面で確認できる。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging(name: str = "x_auto_poster") -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(phase)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


class PhaseAdapter(logging.LoggerAdapter):
    """ログの [phase] 部分を差し込むための薄いラッパー。

    使用例:
        log = PhaseAdapter(logger, "画像生成")
        log.info("Gemini へリクエスト送信")
    """

    def __init__(self, logger: logging.Logger, phase: str):
        super().__init__(logger, {"phase": phase})

    def process(self, msg, kwargs):
        kwargs.setdefault("extra", {})["phase"] = self.extra["phase"]
        return msg, kwargs
