from __future__ import annotations

from abc import ABC, abstractmethod

from channels.message import Message


class Channel(ABC):
    """通知チャネルの抽象基底クラス。

    各チャネル実装（Discord、SES メール等）はこのクラスを継承し、
    ``id`` プロパティと ``send`` メソッドを実装する。
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """チャネルを一意に識別する文字列を返す。

        例: ``"discord"``, ``"email.scrumsign"``
        error-profiles.yml の channels リストと対応する。
        """
        ...

    @abstractmethod
    def send(self, message: Message) -> None:
        """指定した Message をこのチャネルへ送信する。

        送信失敗時は呼び出し元（_dispatch）が例外をキャッチするため、
        実装側は必要に応じて例外をそのまま raise して構わない。
        """
        ...
