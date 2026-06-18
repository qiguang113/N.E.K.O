from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

import websockets


class QQGroupOneBotClient:
    def __init__(self, onebot_url: str, token: str = "", logger: Any = None):
        self.onebot_url = str(onebot_url or "").strip()
        self.token = str(token or "")
        self.logger = logger
        self.ws: Any = None
        self._receive_task: asyncio.Task | None = None
        self._closing = False
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._pending_actions: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return bool(self.ws)

    async def connect(self) -> None:
        if self._receive_task and not self._receive_task.done():
            return
        self._closing = False
        await self._open_websocket()
        self._receive_task = asyncio.create_task(self._receive_loop())
        if self.logger:
            self.logger.info(f"QQ group status connected to OneBot at {self.onebot_url}")

    async def disconnect(self) -> None:
        self._closing = True
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        for future in list(self._pending_actions.values()):
            if not future.done():
                future.cancel()
        self._pending_actions.clear()
        if self.ws:
            try:
                await self.ws.close()
            finally:
                self.ws = None
        if self.logger:
            self.logger.info("QQ group status disconnected from OneBot")

    async def _open_websocket(self) -> None:
        url = self.onebot_url
        headers: dict[str, str] = {}
        if self.token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}access_token={self.token}"
            headers["Authorization"] = f"Bearer {self.token}"
        self.ws = await websockets.connect(url, additional_headers=headers if headers else None)

    async def _receive_loop(self) -> None:
        retry_delay = 1.0
        while not self._closing:
            if not self.ws:
                try:
                    await self._open_websocket()
                    retry_delay = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"QQ group status reconnect failed: {exc}; retrying in {retry_delay:.0f}s")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30.0)
                    continue
            try:
                raw_message = await self.ws.recv()
                payload = json.loads(raw_message)
                echo = payload.get("echo")
                if echo and str(echo) in self._pending_actions:
                    future = self._pending_actions.pop(str(echo), None)
                    if future and not future.done():
                        future.set_result(payload)
                    continue
                if payload.get("post_type") == "message" and payload.get("message_type") == "group":
                    try:
                        self._message_queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        _ = self._message_queue.get_nowait()
                        self._message_queue.put_nowait(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.logger and not self._closing:
                    self.logger.warning(f"QQ group status websocket disconnected: {exc}")
                if self.ws:
                    try:
                        await self.ws.close()
                    except Exception:
                        pass
                self.ws = None
                for echo, future in list(self._pending_actions.items()):
                    if not future.done():
                        future.set_exception(RuntimeError("WebSocket disconnected before action response"))
                    self._pending_actions.pop(echo, None)
                if not self._closing:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30.0)

    async def receive_message(self, timeout: float = 1.0) -> dict[str, Any] | None:
        try:
            raw = await asyncio.wait_for(self._message_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
        return {
            "message_type": "group",
            "group_id": str(raw.get("group_id") or ""),
            "user_id": str(raw.get("user_id") or ""),
            "user_nickname": sender.get("card") or sender.get("nickname") or "",
            "content": raw.get("raw_message") or "",
            "message_id": str(raw.get("message_id") or ""),
            "timestamp": int(raw.get("time") or 0),
            "self_id": str(raw.get("self_id") or ""),
            "raw": raw,
        }

    async def call_action(self, action: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        if not self.ws:
            raise RuntimeError("Not connected to OneBot")
        echo = secrets.token_hex(8)
        future = asyncio.get_running_loop().create_future()
        self._pending_actions[echo] = future
        try:
            await self.ws.send(json.dumps({"action": action, "params": params or {}, "echo": echo}))
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_actions.pop(echo, None)
        code = response.get("retcode")
        if code is None:
            code = response.get("result")
        if isinstance(code, (int, float)):
            failed_code = code != 0
        elif isinstance(code, str):
            failed_code = code.strip().lower() not in {"", "0", "none"}
        else:
            failed_code = False
        if response.get("status") == "failed" or failed_code:
            wording = response.get("wording") or response.get("message") or f"OneBot action failed: {action}"
            raise RuntimeError(f"{wording}; action={action}; code={code}")
        return response.get("data")

    async def get_login_info(self) -> dict[str, Any]:
        data = await self.call_action("get_login_info", timeout=5.0)
        return data if isinstance(data, dict) else {}

    async def send_group_message_segments(self, group_id: str, segments: list[dict[str, Any]]) -> None:
        if not self.ws:
            raise RuntimeError("Not connected to OneBot")
        await self.call_action("send_group_msg", params={
            "group_id": int(str(group_id)),
            "message": segments,
        }, timeout=10.0)

    async def send_private_message_segments(self, user_id: str, segments: list[dict[str, Any]]) -> None:
        if not self.ws:
            raise RuntimeError("Not connected to OneBot")
        await self.call_action("send_private_msg", params={
            "user_id": int(str(user_id)),
            "message": segments,
        }, timeout=10.0)

    async def send_group_forward_message_nodes(self, group_id: str, nodes: list[dict[str, Any]]) -> None:
        params = {
            "group_id": int(str(group_id)),
            "messages": nodes,
        }
        try:
            await self.call_action("send_group_forward_msg", params=params, timeout=10.0)
            return
        except Exception as first_exc:
            try:
                await self.call_action("send_forward_msg", params={**params, "message_type": "group"}, timeout=10.0)
                return
            except Exception as second_exc:
                raise RuntimeError(
                    f"send_group_forward_msg failed: {first_exc}; send_forward_msg failed: {second_exc}"
                ) from second_exc

    async def send_private_forward_message_nodes(self, user_id: str, nodes: list[dict[str, Any]]) -> None:
        params = {
            "user_id": int(str(user_id)),
            "messages": nodes,
        }
        try:
            await self.call_action("send_private_forward_msg", params=params, timeout=10.0)
            return
        except Exception as first_exc:
            try:
                await self.call_action("send_forward_msg", params={**params, "message_type": "private"}, timeout=10.0)
                return
            except Exception as second_exc:
                raise RuntimeError(
                    f"send_private_forward_msg failed: {first_exc}; send_forward_msg failed: {second_exc}"
                ) from second_exc
