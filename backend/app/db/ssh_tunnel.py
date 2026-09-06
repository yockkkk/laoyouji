"""SSH 本地端口转发（给 MariaDB 直连用）。

为什么不用 sshtunnel 库：它 0.4.0 里还在引用 paramiko.DSSKey，而 paramiko 5
已经把 DSA 删了，一 import 就 AttributeError。转发本身就几十行，paramiko 又已经
是依赖，自己写反而少一个会烂掉的中间层。

干的事：在本机 127.0.0.1 上挑一个空闲端口监听，每来一条连接就在 SSH 会话里开一
条 direct-tcpip channel 通到服务器上的 (remote_host, remote_port)，然后两边对着
倒字节。aiomysql 只当自己连了本地端口，什么都不用知道。
"""
from __future__ import annotations

import logging
import select
import socket
import socketserver
import threading

import paramiko

logger = logging.getLogger(__name__)

_IDLE_TICK = 1.0
_CHUNK = 32768


class _Handler(socketserver.BaseRequestHandler):
    # 由 SSHPortForwarder 在子类上挂进去
    transport: paramiko.Transport
    dest: tuple[str, int]

    def handle(self) -> None:  # noqa: D102
        try:
            # timeout 必须给：paramiko 默认无限等。transport 半死（keepalive 还没
            # 判超时）时请求会整批堆死在这里，aiomysql 那边 connect_timeout 到点
            # 抛 TimeoutError，前端看到的就是 500/CORS。10 秒内开不了就明确失败，
            # 让 sql_repo._ensure_pool 走重建，而不是吊着不放。
            chan = self.transport.open_channel(
                "direct-tcpip", self.dest, self.request.getpeername(), timeout=10
            )
        except Exception as exc:
            logger.warning("SSH 隧道开 channel 失败 %s: %s", self.dest, exc)
            return
        if chan is None:
            logger.warning("SSH 隧道被服务器拒绝：%s", self.dest)
            return
        try:
            self._pump(chan)
        finally:
            try:
                chan.close()
            except Exception:
                pass

    def _pump(self, chan: paramiko.Channel) -> None:
        sock = self.request
        while True:
            try:
                ready, _, _ = select.select([sock, chan], [], [], _IDLE_TICK)
            except (OSError, ValueError):
                return
            if sock in ready:
                try:
                    data = sock.recv(_CHUNK)
                except OSError:
                    return
                if not data:
                    return
                chan.sendall(data)
            if chan in ready:
                try:
                    data = chan.recv(_CHUNK)
                except OSError:
                    return
                if not data:
                    return
                try:
                    sock.sendall(data)
                except OSError:
                    return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class SSHPortForwarder:
    """把 127.0.0.1:<自动分配> 转发到 ssh 服务器上的 (remote_host, remote_port)。

    全同步实现，调用方请用 asyncio.to_thread 包一层，别在事件循环里直接 start()。
    """

    def __init__(
        self,
        ssh_host: str,
        ssh_port: int,
        username: str,
        password: str,
        remote_host: str,
        remote_port: int,
    ) -> None:
        self._ssh_host = ssh_host
        self._ssh_port = int(ssh_port)
        self._username = username
        self._password = password
        self._dest = (remote_host, int(remote_port))

        self._client: paramiko.SSHClient | None = None
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self.local_port: int = 0

    def start(self) -> int:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self._ssh_host,
            port=self._ssh_port,
            username=self._username,
            password=self._password,
            timeout=15,
            banner_timeout=20,
            auth_timeout=20,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = client.get_transport()
        if transport is None:  # pragma: no cover - 理论上 connect 成功就有
            client.close()
            raise RuntimeError("SSH 连上了但拿不到 transport")
        # 演示时会有长时间没人说话的间隙，别让中间设备把连接掐了。
        # 15s 而不是 30s：半死状态（对端已凉、TCP 还没判死）能更快被
        # is_alive() 发现，隧道重建发生得更早，而不是让请求堆在半死通道上。
        transport.set_keepalive(15)

        handler = type("_BoundHandler", (_Handler,), {"transport": transport, "dest": self._dest})
        try:
            server = _Server(("127.0.0.1", 0), handler)
        except OSError:
            client.close()
            raise

        self._client = client
        self._server = server
        self.local_port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="ssh-tunnel",
            daemon=True,
        )
        self._thread.start()
        return self.local_port

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self.local_port = 0

    def is_alive(self) -> bool:
        client = self._client
        if client is None:
            return False
        transport = client.get_transport()
        return bool(transport and transport.is_active())


def probe(host: str, port: int, timeout: float = 3.0) -> bool:
    """本地端口能不能连上（给启动自检用）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
