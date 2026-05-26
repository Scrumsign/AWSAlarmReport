from __future__ import annotations

from abc import ABC, abstractmethod

from channels.message import Message


class Channel(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def send(self, message: Message) -> None: ...
