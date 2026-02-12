"""MusicDeLoc AppleScript 連携モジュール"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import subprocess
import re

from exceptions import (
    AppleMusicError,
    AppleMusicNotRunningError,
    AppleMusicPermissionError,
)


@dataclass
class Track:
    """Music アプリのトラック情報"""

    persistent_id: str
    name: str
    artist: str
    album: str
    album_artist: Optional[str]
    sort_artist: Optional[str]
    sort_album_artist: Optional[str]


class AppleMusicClient:
    """Music アプリとの AppleScript 連携クライアント"""

    def _run_applescript(self, script: str) -> str:
        """AppleScript を実行して結果を返す"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=600,  # 10分タイムアウト
            )
        except subprocess.TimeoutExpired:
            raise AppleMusicError("AppleScript の実行がタイムアウトしました")

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not running" in stderr.lower():
                raise AppleMusicNotRunningError("Music アプリが起動していません")
            if "not allowed" in stderr.lower() or "permission" in stderr.lower():
                raise AppleMusicPermissionError(
                    "オートメーション権限がありません。"
                    "システム設定 > プライバシーとセキュリティ > オートメーション で許可してください"
                )
            raise AppleMusicError(f"AppleScript エラー: {stderr}")

        return result.stdout.strip()

    def _escape_for_applescript(self, text: str) -> str:
        """AppleScript 用にテキストをエスケープ"""
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def is_running(self) -> bool:
        """Music アプリが起動しているか確認"""
        script = """
        tell application "System Events"
            return (name of processes) contains "Music"
        end tell
        """
        result = self._run_applescript(script)
        return result.lower() == "true"

    def get_unique_artists(self) -> set[str]:
        """ユニークなアーティスト名のセットを取得（高速一括取得）

        重複排除は Python 側で行う（AppleScript の repeat ループは遅いため）
        """
        script = """
        tell application "Music"
            set artistList to artist of every track of library playlist 1
            set albumArtistList to album artist of every track of library playlist 1
        end tell
        set AppleScript's text item delimiters to "|||"
        return (artistList as text) & "\\n" & (albumArtistList as text)
        """
        result = self._run_applescript(script)
        if not result:
            return set()

        # 重複排除は Python の set で高速処理
        all_artists: set[str] = set()
        for line in result.split("\n"):
            for artist in line.split("|||"):
                if artist and artist != "missing value":
                    all_artists.add(artist)
        return all_artists

    def get_artist_track_count(self) -> dict[str, int]:
        """アーティストごとのトラック数を取得"""
        script = """
        tell application "Music"
            set artistList to artist of every track of library playlist 1
        end tell

        set AppleScript's text item delimiters to "|||"
        return artistList as text
        """
        result = self._run_applescript(script)
        if not result:
            return {}

        artists = result.split("|||")
        counts: dict[str, int] = {}
        for artist in artists:
            if artist:
                counts[artist] = counts.get(artist, 0) + 1
        return counts

    def get_tracks_by_artist(self, artist_name: str) -> list[Track]:
        """指定アーティストのトラックを取得"""
        escaped = self._escape_for_applescript(artist_name)
        script = f"""
        tell application "Music"
            set matchingTracks to every track of library playlist 1 whose artist is "{escaped}"
            set trackData to {{}}
            repeat with t in matchingTracks
                set trackInfo to {{persistent ID of t, name of t, artist of t, album of t, album artist of t, sort artist of t, sort album artist of t}}
                set end of trackData to trackInfo
            end repeat
        end tell

        set output to ""
        repeat with td in trackData
            set AppleScript's text item delimiters to "\\t"
            set output to output & (td as text) & "\\n"
        end repeat
        return output
        """
        result = self._run_applescript(script)
        if not result:
            return []

        tracks = []
        for line in result.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                tracks.append(
                    Track(
                        persistent_id=parts[0],
                        name=parts[1],
                        artist=parts[2],
                        album=parts[3],
                        album_artist=parts[4] if parts[4] != "missing value" else None,
                        sort_artist=parts[5] if parts[5] != "missing value" else None,
                        sort_album_artist=parts[6]
                        if parts[6] != "missing value"
                        else None,
                    )
                )
        return tracks

    def batch_update_by_artist(
        self,
        old_artist: str,
        new_artist: str,
        update_album_artist: bool = True,
        update_sort_fields: bool = True,
    ) -> int:
        """同じアーティスト名を持つ全トラックを一括更新

        Returns:
            更新されたトラック数
        """
        old_escaped = self._escape_for_applescript(old_artist)
        new_escaped = self._escape_for_applescript(new_artist)

        # artist フィールドの更新
        script_parts = [
            f"""
        tell application "Music"
            set matchingTracks to every track of library playlist 1 whose artist is "{old_escaped}"
            set trackCount to count of matchingTracks
            repeat with t in matchingTracks
                set artist of t to "{new_escaped}"
        """
        ]

        if update_sort_fields:
            script_parts.append(f'        set sort artist of t to "{new_escaped}"')

        script_parts.append(
            """
            end repeat
            return trackCount
        end tell
        """
        )

        script = "\n".join(script_parts)
        result = self._run_applescript(script)
        artist_count = int(result) if result.isdigit() else 0

        # album artist フィールドの更新（別途実行）
        if update_album_artist:
            script = f"""
            tell application "Music"
                set matchingTracks to every track of library playlist 1 whose album artist is "{old_escaped}"
                repeat with t in matchingTracks
                    set album artist of t to "{new_escaped}"
            """
            if update_sort_fields:
                script += f'            set sort album artist of t to "{new_escaped}"\n'
            script += """
                end repeat
                return count of matchingTracks
            end tell
            """
            self._run_applescript(script)

        return artist_count

    def get_track_info_for_backup(self, artist_name: str) -> list[dict]:
        """バックアップ用にトラック情報を取得"""
        escaped = self._escape_for_applescript(artist_name)
        script = f"""
        tell application "Music"
            set matchingTracks to every track of library playlist 1 whose artist is "{escaped}" or album artist is "{escaped}"
            set trackData to {{}}
            repeat with t in matchingTracks
                set trackInfo to {{persistent ID of t, name of t, artist of t, album of t, album artist of t, sort artist of t, sort album artist of t}}
                set end of trackData to trackInfo
            end repeat
        end tell

        set output to ""
        repeat with td in trackData
            set AppleScript's text item delimiters to "\\t"
            set output to output & (td as text) & "\\n"
        end repeat
        return output
        """
        result = self._run_applescript(script)
        if not result:
            return []

        tracks = []
        for line in result.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                tracks.append(
                    {
                        "persistent_id": parts[0],
                        "name": parts[1],
                        "artist": parts[2],
                        "album": parts[3],
                        "album_artist": parts[4] if parts[4] != "missing value" else None,
                        "sort_artist": parts[5] if parts[5] != "missing value" else None,
                        "sort_album_artist": parts[6]
                        if parts[6] != "missing value"
                        else None,
                    }
                )
        return tracks

    def restore_track(
        self,
        persistent_id: str,
        artist: Optional[str] = None,
        album_artist: Optional[str] = None,
        sort_artist: Optional[str] = None,
        sort_album_artist: Optional[str] = None,
    ) -> bool:
        """トラックのアーティスト情報を復元"""
        escaped_id = self._escape_for_applescript(persistent_id)

        updates = []
        if artist is not None:
            updates.append(f'set artist of t to "{self._escape_for_applescript(artist)}"')
        if album_artist is not None:
            updates.append(
                f'set album artist of t to "{self._escape_for_applescript(album_artist)}"'
            )
        if sort_artist is not None:
            updates.append(
                f'set sort artist of t to "{self._escape_for_applescript(sort_artist)}"'
            )
        if sort_album_artist is not None:
            updates.append(
                f'set sort album artist of t to "{self._escape_for_applescript(sort_album_artist)}"'
            )

        if not updates:
            return True

        script = f"""
        tell application "Music"
            set t to first track of library playlist 1 whose persistent ID is "{escaped_id}"
            {chr(10).join(updates)}
            return true
        end tell
        """
        try:
            self._run_applescript(script)
            return True
        except AppleMusicError:
            return False
