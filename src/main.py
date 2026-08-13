"""
メイン実行スクリプト。

1日1回(投稿時間帯より前)に実行することを想定。
その日の posting_times_jst の各時刻について:
  1. 自己分析: Bufferから過去の投稿実績を取得
  2. テキスト生成: Gemini(投稿文 + 画像生成用の英語テーマを同時に取得)
  3. 画像生成: Cloudflare Workers AI
  4. 画像ホスティング: Cloudinaryへアップロードして公開URLを取得
  5. 投稿予約: Bufferにその時刻(dueAt)で予約投稿を作成
を実行する。実際の投稿(Xへの公開)はBufferが指定時刻に行う。

1つの時間枠で失敗しても、他の時間枠の処理は続行する
(1回のエラーで1日分の投稿が全滅しないようにするため)。

使い方:
    python -m src.main              # 通常実行(実際にBufferへ予約投稿を作成する)
    python -m src.main --dry-run    # Gemini/Cloudflare/Cloudinaryまでは実行するが、Bufferへの投稿作成はスキップ
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from src.buffer_client import BufferAPIError, BufferClient
from src.cloudflare_image_client import CloudflareImageClient, CloudflareImageError
from src.config import ConfigError, load_config
from src.content_strategy import build_image_prompt, build_text_prompt, validate_post_text
from src.gemini_client import GeminiClient, GeminiError
from src.image_host import ImageHost, ImageHostError
from src.logging_setup import PhaseAdapter, setup_logging
from src.scheduling import JST, compute_due_at_utc

ERROR_DIR = Path(__file__).resolve().parent.parent / "errors"


def save_error_detail(slot_label: str, phase: str, error: Exception) -> Path:
    """エラー発生時の詳細を保存する(ブラウザ操作を前提とした 'スクリーンショット' の代わりに、
    API呼び出し中心の構成に合わせて「その時点までの状況」をJSONで残す)。
    GitHub Actions 上では、このディレクトリをジョブの artifact としてアップロードする設定にしてある
    (.github/workflows/post.yml 参照)。
    """
    ERROR_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(JST).strftime("%Y%m%dT%H%M%S")
    path = ERROR_DIR / f"error_{slot_label}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "slot": slot_label,
                "phase": phase,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "timestamp_jst": datetime.now(JST).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def fetch_reference_posts(buffer_client: BufferClient, config, base_logger) -> list[dict]:
    log = PhaseAdapter(base_logger, "自己分析")
    try:
        posts = buffer_client.get_recent_posts_with_metrics(
            organization_id=config.secrets.buffer_organization_id,
            channel_id=config.secrets.buffer_channel_id,
            limit=30,
        )
    except BufferAPIError as e:
        log.warning(f"過去投稿の取得に失敗したため、参考データなしで続行します: {e}")
        return []

    def impressions_of(post: dict) -> float:
        return next(
            (m["value"] for m in post.get("metrics", []) if m.get("type") == "impressions"),
            0.0,
        )

    ranked = sorted(posts, key=impressions_of, reverse=True)
    top_n = config.self_analysis.get("top_n_reference_posts", 5)
    top_posts = ranked[:top_n]
    log.info(f"過去投稿{len(posts)}件のうち、上位{len(top_posts)}件を参考データとして使用します")
    return top_posts


def process_slot(
    slot_label: str,
    time_str: str,
    config,
    gemini_client: GeminiClient,
    cloudflare_client: CloudflareImageClient,
    image_host: ImageHost,
    buffer_client: BufferClient,
    reference_posts: list[dict],
    already_used_texts: list[str],
    base_logger,
    dry_run: bool,
) -> bool:
    """1つの時間枠(例: "07:25")の処理。成功したら True を返す。

    already_used_texts: 同一実行内で既に生成した投稿文のリスト(呼び出し側と共有するmutableなlist)。
    生成に成功するたびにこのリストへ追記し、次の時間枠の生成時に「これと似すぎないように」
    という指示として使う(1回の実行で3件が似た内容になるのを防ぐため)。
    """

    # --- テキスト生成(検証NGなら最大2回まで再試行) ---
    log = PhaseAdapter(base_logger, f"{slot_label}/テキスト生成")
    post_text = None
    content = None
    last_error = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            log.info(f"Geminiへ投稿文の生成をリクエスト(試行{attempt}/{max_attempts})")
            text_prompt = build_text_prompt(config.content, reference_posts, already_used_texts)
            gen_cfg = config.gemini.get("text_generation_config", {})
            content = gemini_client.generate_post_content(
                text_prompt,
                temperature=gen_cfg.get("temperature", 1.0),
                max_output_tokens=gen_cfg.get("max_output_tokens", 1024),
            )
            validation_error = validate_post_text(content.post_text, config.content)
            if validation_error:
                raise GeminiError(f"生成結果が条件を満たしていません: {validation_error}. text={content.post_text!r}")
            post_text = content.post_text
            break
        except GeminiError as e:
            last_error = e
            log.warning(f"試行{attempt}/{max_attempts} 失敗: {e}")

    if post_text is None:
        log.error(f"{max_attempts}回試行しましたが失敗しました: {last_error}")
        save_error_detail(slot_label, "text_generation", last_error)
        return False

    log.info(f"生成成功({len(post_text)}文字): {post_text[:40]}...")
    already_used_texts.append(post_text)

    # --- 画像生成(Cloudflare Workers AI) ---
    log = PhaseAdapter(base_logger, f"{slot_label}/画像生成")
    try:
        log.info("Cloudflare Workers AIへ画像の生成をリクエスト")
        image_prompt = build_image_prompt(content.image_theme_en, config.image)
        image_bytes = cloudflare_client.generate_image(image_prompt)
        log.info(f"生成成功({len(image_bytes)} bytes)")
    except CloudflareImageError as e:
        log.error(f"失敗: {e}")
        save_error_detail(slot_label, "image_generation", e)
        return False

    # --- 画像アップロード ---
    log = PhaseAdapter(base_logger, f"{slot_label}/画像アップロード")
    try:
        image_url = image_host.upload(image_bytes)
        log.info(f"成功: {image_url}")
    except ImageHostError as e:
        log.error(f"失敗: {e}")
        save_error_detail(slot_label, "image_upload", e)
        return False

    # --- 投稿予約 ---
    log = PhaseAdapter(base_logger, f"{slot_label}/投稿予約")
    due_at = compute_due_at_utc(time_str)
    if dry_run:
        log.info(f"[dry-run] 実際の予約はスキップします。 due_at(UTC)={due_at}")
        log.info(f"[dry-run] 投稿文: {post_text}")
        log.info(f"[dry-run] 画像テーマ(英語): {content.image_theme_en}")
        log.info(f"[dry-run] 画像URL: {image_url}")
        return True

    try:
        buffer_client.create_scheduled_post(
            channel_id=config.secrets.buffer_channel_id,
            text=post_text,
            image_url=image_url,
            due_at_iso=due_at,
        )
        log.info(f"成功: due_at(UTC)={due_at}")
        return True
    except BufferAPIError as e:
        log.error(f"失敗: {e}")
        save_error_detail(slot_label, "buffer_scheduling", e)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="X自動投稿パイプライン")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gemini生成・Cloudinaryアップロードまで実行し、Bufferへの投稿予約は行わない",
    )
    args = parser.parse_args()

    logger = setup_logging()
    log = PhaseAdapter(logger, "起動")

    try:
        config = load_config()
    except ConfigError as e:
        log.error(f"設定エラー: {e}")
        return 1

    log.info(f"設定読み込み完了。投稿予定時刻(JST): {config.posting_times_jst}")
    if args.dry_run:
        log.info("dry-run モードで実行します(Bufferへの投稿予約は行いません)")

    gemini_client = GeminiClient(
        api_key=config.secrets.gemini_api_key,
        text_model=config.gemini["text_model"],
        logger=logger,
    )
    cloudflare_client = CloudflareImageClient(
        account_id=config.secrets.cloudflare_account_id,
        api_token=config.secrets.cloudflare_api_token,
        model=config.cloudflare.get("image_model", "@cf/black-forest-labs/flux-1-schnell"),
        logger=logger,
    )
    image_host = ImageHost(
        cloud_name=config.secrets.cloudinary_cloud_name,
        api_key=config.secrets.cloudinary_api_key,
        api_secret=config.secrets.cloudinary_api_secret,
        folder=config.cloudinary.get("folder", "x-auto-poster"),
        logger=logger,
    )
    buffer_client = BufferClient(api_key=config.secrets.buffer_api_key, logger=logger)

    reference_posts = fetch_reference_posts(buffer_client, config, logger)
    already_used_texts: list[str] = []

    results = {}
    for time_str in config.posting_times_jst:
        slot_label = time_str.replace(":", "")
        results[time_str] = process_slot(
            slot_label=slot_label,
            time_str=time_str,
            config=config,
            gemini_client=gemini_client,
            cloudflare_client=cloudflare_client,
            image_host=image_host,
            buffer_client=buffer_client,
            reference_posts=reference_posts,
            already_used_texts=already_used_texts,
            base_logger=logger,
            dry_run=args.dry_run,
        )

    summary = PhaseAdapter(logger, "サマリー")
    succeeded = [t for t, ok in results.items() if ok]
    failed = [t for t, ok in results.items() if not ok]
    summary.info(f"成功: {succeeded}")
    if failed:
        summary.error(f"失敗: {failed}(詳細は errors/ ディレクトリを確認してください)")

    # 1つでも失敗があれば、GitHub Actions 側でジョブを failed として検知できるよう非ゼロを返す
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
