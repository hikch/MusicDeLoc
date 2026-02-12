"""MusicDeLoc キャッシュ管理モジュール"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
import json

from exceptions import CacheError

ActionType = Literal["convert", "skip", "not_found", "manual"]


@dataclass
class CachedEntry:
    """キャッシュされたアーティスト情報"""

    action: ActionType
    musicbrainz_name: Optional[str]
    mbid: Optional[str]
    checked_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CachedEntry":
        return cls(
            action=data["action"],
            musicbrainz_name=data.get("musicbrainz_name"),
            mbid=data.get("mbid"),
            checked_at=data["checked_at"],
        )


class CacheManager:
    """アーティスト名マッピングのキャッシュ管理"""

    VERSION = "1.0"
    DEFAULT_DIR = Path.home() / ".musicdeloc"

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path or (self.DEFAULT_DIR / "cache.json")
        self._entries: dict[str, CachedEntry] = {}
        self._load()

    def _ensure_dir(self) -> None:
        """キャッシュディレクトリを作成"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """キャッシュファイルを読み込み"""
        if not self.cache_path.exists():
            return

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("version") != self.VERSION:
                # バージョン不一致の場合は空で開始
                return

            entries = data.get("entries", {})
            for artist_name, entry_data in entries.items():
                self._entries[artist_name] = CachedEntry.from_dict(entry_data)
        except (json.JSONDecodeError, KeyError) as e:
            raise CacheError(f"キャッシュファイルの読み込みに失敗: {e}")

    def _save(self) -> None:
        """キャッシュファイルを保存"""
        self._ensure_dir()

        data = {
            "version": self.VERSION,
            "entries": {name: entry.to_dict() for name, entry in self._entries.items()},
        }

        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            raise CacheError(f"キャッシュファイルの保存に失敗: {e}")

    def get(self, artist_name: str) -> Optional[CachedEntry]:
        """キャッシュからエントリを取得"""
        return self._entries.get(artist_name)

    def set(
        self,
        artist_name: str,
        action: ActionType,
        musicbrainz_name: Optional[str] = None,
        mbid: Optional[str] = None,
    ) -> None:
        """エントリをキャッシュに保存"""
        self._entries[artist_name] = CachedEntry(
            action=action,
            musicbrainz_name=musicbrainz_name,
            mbid=mbid,
            checked_at=datetime.now().isoformat(),
        )
        self._save()

    def set_convert(
        self, artist_name: str, musicbrainz_name: str, mbid: Optional[str] = None
    ) -> None:
        """変換エントリを保存"""
        self.set(artist_name, "convert", musicbrainz_name, mbid)

    def set_skip(
        self, artist_name: str, musicbrainz_name: str, mbid: Optional[str] = None
    ) -> None:
        """スキップエントリを保存（正式名と一致）"""
        self.set(artist_name, "skip", musicbrainz_name, mbid)

    def set_not_found(self, artist_name: str) -> None:
        """見つからなかったエントリを保存"""
        self.set(artist_name, "not_found", None, None)

    def set_manual(
        self, artist_name: str, musicbrainz_name: str, mbid: Optional[str] = None
    ) -> None:
        """手動入力エントリを保存"""
        self.set(artist_name, "manual", musicbrainz_name, mbid)

    def remove(self, artist_name: str) -> bool:
        """キャッシュからエントリを削除"""
        if artist_name in self._entries:
            del self._entries[artist_name]
            self._save()
            return True
        return False

    def clear(self) -> None:
        """キャッシュをクリア"""
        self._entries.clear()
        self._save()

    def get_all(self) -> dict[str, CachedEntry]:
        """全エントリを取得"""
        return self._entries.copy()

    def get_pending(self, all_artists: set[str]) -> set[str]:
        """キャッシュにない（未処理の）アーティスト名を取得"""
        return all_artists - set(self._entries.keys())

    def get_conversions(self) -> dict[str, str]:
        """変換対象のマッピングを取得（artist_name -> musicbrainz_name）"""
        return {
            name: entry.musicbrainz_name
            for name, entry in self._entries.items()
            if entry.action in ("convert", "manual") and entry.musicbrainz_name
        }

    def get_skipped(self) -> list[str]:
        """スキップされたアーティスト名を取得"""
        return [name for name, entry in self._entries.items() if entry.action == "skip"]

    def get_not_found(self) -> list[str]:
        """見つからなかったアーティスト名を取得"""
        return [
            name for name, entry in self._entries.items() if entry.action == "not_found"
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, artist_name: str) -> bool:
        return artist_name in self._entries
