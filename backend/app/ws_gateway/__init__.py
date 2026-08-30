"""ws_gateway:连接/发号/抢占/消息分发(职责表见 backend-plan §2)。"""

from .gateway import Connection, handle_connection

__all__ = ["Connection", "handle_connection"]
