"""
セットアップ補助スクリプト。

BUFFER_ORGANIZATION_ID と BUFFER_CHANNEL_ID を .env にまだ設定していない場合、
このスクリプトを実行すると一覧表示してくれる。

事前に .env に GEMINI_API_KEY... ではなく、最低限 BUFFER_API_KEY だけ設定しておけばよい。

実行方法:
    python scripts/find_buffer_ids.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.buffer_client import BufferAPIError, BufferClient  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


class _StubLogger:
    def info(self, msg):
        pass

    def warning(self, msg):
        print(f"[警告] {msg}")

    def error(self, msg):
        print(f"[エラー] {msg}")


def main() -> int:
    api_key = os.environ.get("BUFFER_API_KEY")
    if not api_key:
        print("BUFFER_API_KEY が .env に設定されていません。先に設定してください。")
        print("取得先: https://publish.buffer.com/settings/api")
        return 1

    client = BufferClient(api_key=api_key, logger=_StubLogger())

    try:
        orgs = client.get_organizations()
    except BufferAPIError as e:
        print(f"組織一覧の取得に失敗しました: {e}")
        return 1

    if not orgs:
        print("組織が見つかりませんでした。Bufferに正しくログインできているか確認してください。")
        return 1

    for org in orgs:
        print(f"\n組織: {org['name']}  (id: {org['id']})")
        try:
            channels = client.get_channels(org["id"])
        except BufferAPIError as e:
            print(f"  チャンネル一覧の取得に失敗しました: {e}")
            continue

        if not channels:
            print("  (この組織に接続済みのチャンネルはありません)")
            continue

        for ch in channels:
            marker = "  ← X(Twitter)のチャンネルです" if ch["service"] in ("twitter", "x") else ""
            print(f"  - {ch['displayName']} [{ch['service']}]  (id: {ch['id']}){marker}")

    print("\n上記の中から、投稿したいXチャンネルの id を")
    print("  BUFFER_ORGANIZATION_ID=<組織のid>")
    print("  BUFFER_CHANNEL_ID=<Xチャンネルのid>")
    print("として .env(および GitHub Secrets)に設定してください。")
    print("\n※ もし対象のXチャンネルが表示されない場合は、")
    print("  https://publish.buffer.com で先にXアカウントをBufferに接続してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
