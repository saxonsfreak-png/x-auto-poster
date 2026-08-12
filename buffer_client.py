"""
Buffer API (GraphQL) クライアント。

Xへの実際の投稿・スケジューリングは、この Buffer の公式API経由で行う。
公式に許可された経路のため、Xの検知回避のような細工は一切不要。

参考ドキュメント:
- https://developers.buffer.com/guides/authentication.html
- https://developers.buffer.com/guides/posts-and-scheduling.html
- https://developers.buffer.com/guides/hosting-media.html
- https://developers.buffer.com/guides/post-metrics.html
- クエリを試したい場合は GraphQL Explorer が便利: https://developers.buffer.com/explorer.html
"""
from __future__ import annotations

from typing import Any

import requests

BUFFER_API_URL = "https://api.buffer.com"


class BufferAPIError(RuntimeError):
    pass


class BufferClient:
    def __init__(self, api_key: str, logger):
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        self._log = logger

    def _request(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = requests.post(
            BUFFER_API_URL,
            headers=self._headers,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "unknown")
            raise BufferAPIError(
                f"Buffer APIのレート制限に達しました。{retry_after}秒後に再試行してください。"
                f" レスポンス: {resp.text}"
            )

        resp.raise_for_status()
        data = resp.json()

        if "errors" in data and data["errors"]:
            raise BufferAPIError(f"Buffer GraphQLエラー: {data['errors']}")

        return data["data"]

    # ------------------------------------------------------------------
    # セットアップ補助(組織ID・チャンネルIDの特定に使用)
    # ------------------------------------------------------------------
    def get_organizations(self) -> list[dict[str, Any]]:
        query = """
        query GetOrganizations {
          account {
            organizations {
              id
              name
              ownerEmail
            }
          }
        }
        """
        data = self._request(query)
        return data["account"]["organizations"]

    def get_channels(self, organization_id: str) -> list[dict[str, Any]]:
        query = """
        query GetChannels($orgId: OrganizationId!) {
          channels(input: { organizationId: $orgId }) {
            id
            name
            displayName
            service
            isQueuePaused
          }
        }
        """
        data = self._request(query, {"orgId": organization_id})
        return data["channels"]

    # ------------------------------------------------------------------
    # 投稿作成
    # ------------------------------------------------------------------
    def create_scheduled_post(self, channel_id: str, text: str, image_url: str, due_at_iso: str) -> dict[str, Any]:
        """指定したUTC日時(ISO8601)に画像付きで投稿されるようスケジュールする。"""
        mutation = """
        mutation CreatePost($text: String!, $channelId: ChannelId!, $dueAt: DateTime!, $imageUrl: String!) {
          createPost(
            input: {
              text: $text
              channelId: $channelId
              schedulingType: automatic
              mode: customScheduled
              dueAt: $dueAt
              assets: [{ image: { url: $imageUrl } }]
            }
          ) {
            ... on PostActionSuccess {
              post {
                id
                text
                dueAt
                assets { id mimeType }
              }
            }
            ... on MutationError {
              message
            }
          }
        }
        """
        variables = {
            "text": text,
            "channelId": channel_id,
            "dueAt": due_at_iso,
            "imageUrl": image_url,
        }
        data = self._request(mutation, variables)
        result = data["createPost"]

        if "message" in result:
            # MutationError 型が返ってきた場合(Buffer 側でのバリデーションエラー等)
            raise BufferAPIError(f"投稿の作成に失敗しました: {result['message']}")

        return result["post"]

    # ------------------------------------------------------------------
    # 自己分析(過去の投稿実績の取得)
    # ------------------------------------------------------------------
    def get_recent_posts_with_metrics(self, organization_id: str, channel_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """直近の「送信済み」投稿とそのメトリクス(インプレッション等)を取得する。

        注意: Buffer側のメトリクス反映は最大24時間ほど遅れる場合がある。
        """
        query = """
        query GetRecentPosts($orgId: OrganizationId!, $channelId: ChannelId!, $first: Int!) {
          posts(
            first: $first
            input: {
              organizationId: $orgId
              filter: { status: [sent], channelIds: [$channelId] }
            }
          ) {
            edges {
              node {
                id
                text
                dueAt
                metrics { type name value unit }
              }
            }
          }
        }
        """
        variables = {"orgId": organization_id, "channelId": channel_id, "first": limit}
        data = self._request(query, variables)
        return [edge["node"] for edge in data["posts"]["edges"]]
