"""MusicDeLoc 例外クラス"""


class MusicDeLocError(Exception):
    """MusicDeLoc の基底例外"""

    pass


class AppleMusicError(MusicDeLocError):
    """Apple Music / AppleScript 関連エラー"""

    pass


class AppleMusicNotRunningError(AppleMusicError):
    """Music アプリが起動していない"""

    pass


class AppleMusicPermissionError(AppleMusicError):
    """オートメーション権限がない"""

    pass


class TrackNotFoundError(AppleMusicError):
    """指定されたトラックが見つからない"""

    pass


class MusicBrainzError(MusicDeLocError):
    """MusicBrainz API 関連エラー"""

    pass


class RateLimitError(MusicBrainzError):
    """レートリミット超過"""

    pass


class NetworkError(MusicBrainzError):
    """ネットワーク接続エラー"""

    pass


class ArtistNotFoundError(MusicBrainzError):
    """アーティストが見つからない"""

    pass


class CacheError(MusicDeLocError):
    """キャッシュ関連エラー"""

    pass


class BackupError(MusicDeLocError):
    """バックアップ/復元関連エラー"""

    pass
