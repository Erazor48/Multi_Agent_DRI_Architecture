"""
YouTube connector — upload videos and manage playlists.

Handles action_type = "youtube_upload" and "youtube_create_playlist".

Setup:
  1. Google Cloud Console → Enable YouTube Data API v3
  2. Create OAuth2 credentials (Desktop App type)
  3. Run one-time auth flow to obtain a refresh token
  4. Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN in .env

Scopes required:
  https://www.googleapis.com/auth/youtube.upload
  https://www.googleapis.com/auth/youtube
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry
from dri.config.settings import settings


class YouTubeConnector(BaseConnector):

    def can_handle(self, action_type: str, action: dict) -> bool:
        return action_type in ("youtube_upload", "youtube_create_playlist")

    @property
    def is_configured(self) -> bool:
        return settings.has_youtube

    @property
    def setup_hint(self) -> str:
        return (
            "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN in .env. "
            "See Google Cloud Console → Enable YouTube Data API v3 → OAuth2 credentials."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(success=False, message=f"YouTube not configured. {self.setup_hint}")

        action_type = action.get("action_type")
        if action_type == "youtube_upload":
            return await self._upload_video(action)
        elif action_type == "youtube_create_playlist":
            return await self._create_playlist(action)
        return ConnectorResult(success=False, message=f"Unsupported action_type: {action_type}")

    def _get_credentials(self) -> Any:
        from google.oauth2.credentials import Credentials
        return Credentials(
            token=None,
            refresh_token=settings.youtube_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
            ],
        )

    async def _upload_video(self, action: dict) -> ConnectorResult:
        workspace_root = action.get("_workspace_root", "")
        file_path = action.get("file_path", "")
        if not file_path:
            return ConnectorResult(success=False, message="file_path is required for youtube_upload.")

        full_path = Path(workspace_root) / file_path if workspace_root else Path(file_path)
        if not full_path.exists():
            return ConnectorResult(success=False, message=f"Video file not found: {full_path}")

        title = action.get("subject", "Untitled Video")
        description = action.get("content", "")

        def _do_upload() -> tuple[str, str]:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.auth.transport.requests import Request

            creds = self._get_credentials()
            creds.refresh(Request())

            youtube = build("youtube", "v3", credentials=creds)
            media = MediaFileUpload(str(full_path), chunksize=-1, resumable=True)
            privacy = action.get("privacy_status", "private")
            request = youtube.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "categoryId": "22",  # People & Blogs default
                    },
                    "status": {"privacyStatus": privacy},
                },
                media_body=media,
            )
            response = request.execute()
            video_id = response.get("id", "")
            return f"https://www.youtube.com/watch?v={video_id}", video_id

        try:
            url, video_id = await asyncio.to_thread(_do_upload)
            return ConnectorResult(
                success=True,
                message=f"Video uploaded successfully: {url}",
                external_id=video_id,
                details={"url": url, "video_id": video_id, "title": title},
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"YouTube upload failed: {e}")

    async def _create_playlist(self, action: dict) -> ConnectorResult:
        title = action.get("subject", "New Playlist")
        description = action.get("content", "")

        def _do_create() -> tuple[str, str]:
            from googleapiclient.discovery import build
            from google.auth.transport.requests import Request

            creds = self._get_credentials()
            creds.refresh(Request())
            youtube = build("youtube", "v3", credentials=creds)
            response = youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title, "description": description},
                    "status": {"privacyStatus": "private"},
                },
            ).execute()
            playlist_id = response.get("id", "")
            return f"https://www.youtube.com/playlist?list={playlist_id}", playlist_id

        try:
            url, playlist_id = await asyncio.to_thread(_do_create)
            return ConnectorResult(
                success=True,
                message=f"Playlist created: {url}",
                external_id=playlist_id,
                details={"url": url, "playlist_id": playlist_id, "title": title},
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"YouTube playlist creation failed: {e}")


ConnectorRegistry.register(YouTubeConnector())
