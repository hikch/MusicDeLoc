"""MusicDeLoc MusicBrainz API クライアント"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import json
import time
import urllib.parse
import urllib.request
import urllib.error

from exceptions import MusicBrainzError, NetworkError, RateLimitError, ArtistNotFoundError


@dataclass
class ArtistMatch:
    """MusicBrainz のアーティスト検索結果"""

    mbid: str
    name: str  # 正式名（通常は英語または原語）
    sort_name: str
    score: int  # マッチスコア (0-100)
    country: Optional[str] = None
    disambiguation: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "ArtistMatch":
        return cls(
            mbid=data["id"],
            name=data["name"],
            sort_name=data.get("sort-name", data["name"]),
            score=data.get("score", 0),
            country=data.get("country"),
            disambiguation=data.get("disambiguation"),
        )


class MusicBrainzClient:
    """MusicBrainz API クライアント"""

    API_BASE = "https://musicbrainz.org/ws/2"
    USER_AGENT = "MusicDeLoc/1.0.0 (https://github.com/user/musicdeloc)"
    DEFAULT_RATE_LIMIT = 1.5  # 1.5秒に1リクエスト（余裕を持たせる）
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2.0  # 指数バックオフの基数

    def __init__(self, rate_limit: float = DEFAULT_RATE_LIMIT):
        self._rate_limit_seconds = rate_limit
        self._last_request_time: float = 0.0
        self._alias_cache: dict[str, list[str]] = {}  # mbid -> aliases

    def _rate_limit(self) -> None:
        """レートリミットを遵守"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_seconds:
            time.sleep(self._rate_limit_seconds - elapsed)

    def _make_request(self, endpoint: str, params: dict) -> dict:
        """API リクエストを実行（リトライ付き）"""
        params["fmt"] = "json"
        url = f"{self.API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

        request = urllib.request.Request(
            url, headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"}
        )

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            self._rate_limit()

            try:
                self._last_request_time = time.time()
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))

            except urllib.error.HTTPError as e:
                if e.code == 503:
                    # レートリミット: 指数バックオフで待機
                    wait_time = self.RETRY_BACKOFF_BASE ** attempt
                    time.sleep(wait_time)
                    last_error = RateLimitError(f"レートリミット超過 (リトライ {attempt + 1}/{self.MAX_RETRIES})")
                    continue
                raise MusicBrainzError(f"MusicBrainz API エラー: {e.code} {e.reason}")

            except urllib.error.URLError as e:
                # 接続エラー: リトライ
                wait_time = self.RETRY_BACKOFF_BASE ** attempt
                time.sleep(wait_time)
                last_error = NetworkError(f"ネットワークエラー: {e.reason} (リトライ {attempt + 1}/{self.MAX_RETRIES})")
                continue

            except json.JSONDecodeError as e:
                raise MusicBrainzError(f"レスポンスの解析に失敗: {e}")

        # 全リトライ失敗
        if last_error:
            raise last_error
        raise NetworkError("リクエストに失敗しました")

    def search_artist(self, query: str, limit: int = 5) -> list[ArtistMatch]:
        """アーティスト名で検索

        Args:
            query: 検索クエリ（日本語アーティスト名）
            limit: 最大結果数

        Returns:
            マッチしたアーティストのリスト（スコア順）
        """
        params = {"query": query, "limit": limit}
        data = self._make_request("artist", params)

        artists = data.get("artists", [])
        return [ArtistMatch.from_api_response(a) for a in artists]

    def search_artist_by_alias(self, alias: str, limit: int = 5) -> list[ArtistMatch]:
        """エイリアス（別名）で検索

        Args:
            alias: エイリアス（日本語アーティスト名）
            limit: 最大結果数

        Returns:
            マッチしたアーティストのリスト（スコア順）
        """
        # alias フィールドを指定して検索
        params = {"query": f'alias:"{alias}"', "limit": limit}
        data = self._make_request("artist", params)

        artists = data.get("artists", [])
        return [ArtistMatch.from_api_response(a) for a in artists]

    def get_artist_aliases(self, mbid: str) -> list[str]:
        """アーティストのエイリアス（別名）一覧を取得

        Args:
            mbid: MusicBrainz アーティスト ID

        Returns:
            エイリアス名のリスト
        """
        # キャッシュ確認
        if mbid in self._alias_cache:
            return self._alias_cache[mbid]

        # API からアーティスト詳細を取得（エイリアス含む）
        try:
            data = self._make_request(f"artist/{mbid}", {"inc": "aliases"})
        except MusicBrainzError:
            return []

        aliases = []
        # 正式名も含める
        if "name" in data:
            aliases.append(data["name"])

        # エイリアス一覧を取得
        for alias in data.get("aliases", []):
            if "name" in alias:
                aliases.append(alias["name"])

        # キャッシュに保存
        self._alias_cache[mbid] = aliases
        return aliases

    def verify_alias(self, mbid: str, query_name: str) -> bool:
        """アーティストが指定された名前をエイリアスとして持っているか検証

        Args:
            mbid: MusicBrainz アーティスト ID
            query_name: 検索に使用した名前

        Returns:
            エイリアスに含まれている場合 True
        """
        aliases = self.get_artist_aliases(mbid)
        query_normalized = query_name.strip().lower()

        for alias in aliases:
            if alias.strip().lower() == query_normalized:
                return True
        return False

    def get_official_name(
        self, library_name: str
    ) -> Optional[tuple[str, str, Optional[str]]]:
        """ライブラリ上のアーティスト名から MusicBrainz 正式名を取得

        検索結果のアーティストが、検索名をエイリアスとして持っているか検証する。
        これにより「ジェネシス」で検索して「ジェネシス×ネメシス」がヒットしても、
        エイリアス検証で除外される。

        Args:
            library_name: ライブラリ上のアーティスト名

        Returns:
            (正式名, ソート名, MBID) または None（見つからない場合）
        """
        # 正規化
        query = library_name.strip()

        # 完全一致する場合はスキップ扱い（変換不要）
        # これは後で should_convert() で判定されるので、ここでは検索を続行

        # エイリアス検索を優先（日本語名はエイリアスとして登録されていることが多い）
        alias_matches = self.search_artist_by_alias(query, limit=5)
        for match in alias_matches:
            if match.score >= 80:
                # エイリアス検証
                if self.verify_alias(match.mbid, query):
                    return (match.name, match.sort_name, match.mbid)

        # 通常検索を試行
        matches = self.search_artist(query, limit=5)
        for match in matches:
            if match.score >= 80:
                # 正式名が検索名と完全一致する場合は検証不要
                if match.name.strip().lower() == query.lower():
                    return (match.name, match.sort_name, match.mbid)
                # エイリアス検証
                if self.verify_alias(match.mbid, query):
                    return (match.name, match.sort_name, match.mbid)

        # 見つからない場合は None
        return None

    def should_convert(self, library_name: str, musicbrainz_name: str) -> bool:
        """変換が必要か判定（ライブラリ名と正式名が異なる場合）"""
        return library_name.strip() != musicbrainz_name.strip()
