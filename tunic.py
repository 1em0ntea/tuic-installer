# -*- coding: utf-8 -*-
# Time       : 2023/6/26 11:05
# Author     : QIN2DIM
# Github     : https://github.com/QIN2DIM
# Description:
from __future__ import annotations

import argparse
import getpass
import inspect
import json
import logging
import os
import random
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, List, Any, NoReturn, Tuple
from urllib import request
from urllib.request import urlretrieve
from uuid import uuid4

logging.basicConfig(
    level=logging.INFO, stream=sys.stdout, format="%(asctime)s - %(levelname)s - %(message)s"
)

if not sys.platform.startswith("linux"):
    logging.error(" Opps~ 你只能在 Linux 操作系统上运行该脚本")
    sys.exit()
if getpass.getuser() != "root":
    logging.error(" Opps~ 你需要手动切换到 root 用户运行该脚本")
    sys.exit()

URL = "https://github.com/EAimTY/tuic/releases/download/tuic-server-1.0.0/tuic-server-1.0.0-x86_64-unknown-linux-gnu"

TEMPLATE_SERVICE = """
[Unit]
Description=tuic Service
Documentation=https://github.com/EAimTY/tuic
After=network.target nss-lookup.target

[Service]
Type=simple
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
ExecStart={exec_start}
Restart=on-failure
LimitNPROC=512
LimitNOFILE=infinity
WorkingDirectory={working_directory}

[Install]
WantedBy=multi-user.target
"""

# https://adguard-dns.io/kb/zh-CN/general/dns-providers
# https://github.com/MetaCubeX/Clash.Meta/blob/53f9e1ee7104473da2b4ff5da29965563084482d/config/config.go#L891
TEMPLATE_META_CONFIG = """
dns:
  enable: true
  prefer-h3: true
  enhanced-mode: fake-ip
  nameserver:
    - "https://dns.google/dns-query#PROXY"
    - "https://security.cloudflare-dns.com/dns-query#PROXY"
    - "quic://dns.adguard-dns.com"
  proxy-server-nameserver:
    - "https://223.5.5.5/dns-query"
  nameserver-policy:
    "geosite:cn":
      - "https://223.5.5.5/dns-query#h3=true"
rules:
  - GEOSITE,category-scholar-!cn,PROXY
  - GEOSITE,category-ads-all,REJECT
  - GEOSITE,youtube,PROXY
  - GEOSITE,google,PROXY
  - GEOSITE,cn,DIRECT
  - GEOSITE,private,DIRECT
  # - GEOSITE,tracker,DIRECT
  - GEOSITE,steam@cn,DIRECT
  - GEOSITE,category-games@cn,DIRECT
  - GEOSITE,geolocation-!cn,PROXY
  - GEOIP,private,DIRECT,no-resolve
  - GEOIP,telegram,PROXY
  - GEOIP,CN,DIRECT
  - DST-PORT,80/8080/443/8443,PROXY
  - MATCH,DIRECT
"""

TEMPLATE_META_PROXY_ADDONS = """
proxies:
  - {proxy}
proxy-groups:
  - {proxy_group}
"""


@dataclass
class Project:
    workstation = Path("/home/tuic-server")
    executable = workstation.joinpath("tuic")
    server_config = workstation.joinpath("server_config.json")

    client_nekoray_config = workstation.joinpath("nekoray_config.json")
    client_meta_config = workstation.joinpath("meta_config.yaml")
    client_singbox_config = workstation.joinpath("singbox_config.json")

    service = Path("/etc/systemd/system/tuic.service")

    # 设置别名
    root = Path(os.path.expanduser("~"))
    path_bash_aliases = root.joinpath(".bashrc")
    _remote_command = "python3 <(curl -fsSL https://ros.services/tunic.py)"
    _alias = "tunic"

    _server_ip = ""
    _server_port = -1

    def __post_init__(self):
        os.makedirs(self.workstation, exist_ok=True)

    @staticmethod
    def is_port_in_used(_port: int, proto: Literal["tcp", "udp"]) -> bool | None:
        """Check socket UDP/data_gram or TCP/data_stream"""
        proto2type = {"tcp": socket.SOCK_STREAM, "udp": socket.SOCK_DGRAM}
        socket_type = proto2type[proto]
        with suppress(socket.error), socket.socket(socket.AF_INET, socket_type) as s:
            s.bind(("0.0.0.0", _port))
            return False
        return True

    @property
    def server_ip(self):
        return self._server_ip

    @server_ip.setter
    def server_ip(self, ip: str):
        self._server_ip = ip

    @property
    def server_port(self):
        # 初始化监听端口
        if self._server_port < 0:
            rand_ports = list(range(49152, 59152))
            random.shuffle(rand_ports)
            for p in rand_ports:
                if not self.is_port_in_used(p, proto="udp"):
                    self._server_port = p
                    logging.info(f"正在初始化监听端口 - port={p}")
                    break

        # 返回已绑定的空闲端口
        return self._server_port

    @server_port.setter
    def server_port(self, port: int):
        self._server_port = port

    @property
    def alias(self):
        # redirect to https://raw.githubusercontent.com/QIN2DIM/tuic-installer/main/tunic.py
        return f"alias {self._alias}='{self._remote_command}'"

    def set_alias(self):
        # Avoid adding tunic alias repeatedly
        if self.path_bash_aliases.exists():
            pre_text = self.path_bash_aliases.read_text(encoding="utf8")
            for ck in [f"\n{self.alias}\n", f"\n{self.alias}", f"{self.alias}\n", self.alias]:
                if ck in pre_text:
                    return
        # New `tunic` alias record
        with open(self.path_bash_aliases, "a", encoding="utf8") as file:
            file.write(f"\n{self.alias}\n")
        logging.info(f"✅ 现在你可以通过别名唤起脚本 - alias={self._alias}")

    def remove_alias(self):
        histories = [self.root.joinpath(".bash_aliases"), self.path_bash_aliases]
        for hp in histories:
            if not hp.exists():
                continue
            text = hp.read_text(encoding="utf8")
            for ck in [f"\n{self.alias}\n", f"\n{self.alias}", f"{self.alias}\n", self.alias]:
                text = text.replace(ck, "")
            hp.write_text(text, encoding="utf8")

    @staticmethod
    def reset_shell() -> NoReturn:
        # Reload Linux SHELL and refresh alias values
        os.execl(os.environ["SHELL"], "bash", "-l")

    @property
    def systemd_template(self) -> str:
        return TEMPLATE_SERVICE.format(
            exec_start=f"{self.executable} -c {self.server_config}",
            working_directory=f"{self.workstation}",
        )


@dataclass
class Certificate:
    domain: str

    @property
    def fullchain(self):
        return f"/etc/letsencrypt/live/{self.domain}/fullchain.pem"

    @property
    def privkey(self):
        return f"/etc/letsencrypt/live/{self.domain}/privkey.pem"


class CertBot:
    def __init__(self, domain: str):
        self._domain = domain

        self._should_revive_port_80 = False
        self._is_success = True

    def _cert_pre_hook(self):
        # Fallback strategy: Ensure smooth flow of certificate requests
        p = Path("/etc/letsencrypt/live/")
        if p.exists():
            logging.info("移除證書殘影...")
            for k in os.listdir(p):
                k_full = p.joinpath(k)
                if (
                    not p.joinpath(self._domain).exists()
                    and k.startswith(f"{self._domain}-")
                    and k_full.is_dir()
                ):
                    shutil.rmtree(k_full, ignore_errors=True)

        logging.info("正在为解析到本机的域名申请免费证书")

        logging.info("正在更新包索引")
        os.system("apt update -y > /dev/null 2>&1 ")

        logging.info("安装 certbot")
        os.system("apt install certbot -y > /dev/null 2>&1")

        # Pre-hook strategy: stop process running in port 80
        logging.info("检查 80 端口占用")
        if Project.is_port_in_used(80, proto="tcp"):
            os.system("systemctl stop nginx > /dev/null 2>&1 && nginx -s stop > /dev/null 2>&1")
            os.system("kill $(lsof -t -i:80)  > /dev/null 2>&1")
            self._should_revive_port_80 = True

    def _cert_post_hook(self):
        # Post-hook strategy: restart process running in port 80
        if self._should_revive_port_80:
            os.system("systemctl restart nginx > /dev/null 2>&1")
            self._should_revive_port_80 = False

        # Exception: certs 5 per 7 days
        if not self._is_success:
            sys.exit()

        # This operation ensures that certbot.timer is started
        logging.info(f"运行证书续订服务 - service=certbot.timer")
        os.system(f"systemctl daemon-reload && systemctl enable --now certbot.timer")

    def _run(self):
        logging.info("开始申请证书")
        cmd = (
            "certbot certonly "
            "--standalone "
            "--register-unsafely-without-email "
            "--agree-tos "
            "--keep "
            "--non-interactive "
            "-d {domain}"
        )
        p = subprocess.Popen(
            cmd.format(domain=self._domain).split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            text=True,
        )
        output = p.stderr.read().strip()
        if output and "168 hours" in output:
            logging.warning(
                """
                一个域名每168小时只能申请5次免费证书，
                你可以为当前主机创建一条新的域名A纪录来解决这个问题。
                在解决这个问题之前你没有必要进入到后续的安装步骤。
                """
            )
            self._is_success = False

    def run(self):
        self._cert_pre_hook()
        self._run()
        self._cert_post_hook()

    def remove(self):
        """可能存在重复申请的 domain-0001"""
        logging.info("移除可能残留的证书文件")
        p = subprocess.Popen(
            f"certbot delete --cert-name {self._domain}".split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        p.stdin.write("y\n")
        p.stdin.flush()

        # 兜底
        shutil.rmtree(Path(Certificate(self._domain).fullchain).parent, ignore_errors=True)


@dataclass
class Service:
    path: Path
    name: str = "tuic"

    @classmethod
    def build_from_template(cls, path: Path, template: str | None = ""):
        if template:
            path.write_text(template, encoding="utf8")
            os.system("systemctl daemon-reload")
        return cls(path=path)

    def download_server(self, workstation: Path):
        ex_path = workstation.joinpath("tuic")
        try:
            urlretrieve(URL, f"{ex_path}")
            logging.info(f"下载完毕 - ex_path={ex_path}")
        except OSError:
            logging.info("服务正忙，尝试停止任务...")
            self.stop()
            time.sleep(0.5)
            return self.download_server(workstation)
        else:
            os.system(f"chmod +x {ex_path}")
            logging.info(f"授予执行权限 - ex_path={ex_path}")

    def start(self):
        """部署服务之前需要先初始化服务端配置并将其写到工作空间"""
        os.system(f"systemctl enable --now {self.name}")
        logging.info("系统服务已启动")
        logging.info("已设置服务开机自启")

    def stop(self):
        logging.info("停止系统服务")
        os.system(f"systemctl stop {self.name}")

    def restart(self):
        logging.info("重启系统服务")
        os.system(f"systemctl daemon-reload && systemctl restart {self.name}")

    def status(self) -> Tuple[bool, str]:
        result = subprocess.run(
            f"systemctl is-active {self.name}".split(), capture_output=True, text=True
        )
        text = result.stdout.strip()
        response = None
        if text == "inactive":
            text = "\033[91m" + text + "\033[0m"
        elif text == "active":
            text = "\033[32m" + text + "\033[0m"
            response = True
        return response, text

    def remove(self, workstation: Path):
        logging.info("注销系统服务")
        os.system(f"systemctl disable --now {self.name} > /dev/null 2>&1")

        logging.info("关停相关进程")
        os.system("pkill tuic")

        logging.info("移除系统服务配置文件")
        if self.path.exists():
            os.remove(self.path)

        logging.info("移除工作空间")
        shutil.rmtree(workstation)


# =================================== Runtime Settings ===================================


def from_dict_to_cls(cls, data):
    return cls(
        **{
            key: (data[key] if val.default == val.empty else data.get(key, val.default))
            for key, val in inspect.signature(cls).parameters.items()
        }
    )


@dataclass
class User:
    username: str
    password: str

    @classmethod
    def gen(cls):
        return cls(username=str(uuid4()), password=secrets.token_hex()[:16])


@dataclass
class ServerConfig:
    """
    Config template of tuic-server(v1.0.0)
    https://github.com/EAimTY/tuic/tree/dev/tuic-server
    """

    server: str
    """
    The socket address to listen on
    """

    users: Dict[str, str]
    """
    User map, contains user UUID and password
    """

    certificate: str
    private_key: str
    """
    The path to the private key file and cert file
    """

    congestion_control: Literal["cubic", "new_reno", "bbr"] = "bbr"
    """
    [Optional] Congestion control algorithm
    Default: "cubic"
    """

    alpn: List[str] | None = field(default_factory=list)
    """
    # [Optional] Application layer protocol negotiation
    # Default being empty (no ALPN)
    """

    udp_relay_ipv6: bool = True
    """
    # Optional. If the server should create separate UDP sockets for relaying IPv6 UDP packets
    # Default: true
    """

    zero_rtt_handshake: bool = True
    """
    # Optional. Enable 0-RTT QUIC connection handshake on the server side
    # This is not impacting much on the performance, as the protocol is fully multiplexed
    # WARNING: Disabling this is highly recommended, as it is vulnerable to replay attacks. See https://blog.cloudflare.com/even-faster-connection-establishment-with-quic-0-rtt-resumption/#attack-of-the-clones
    # Default: false
    """

    dual_stack: bool | None = None
    """
    [Optional] Set if the listening socket should be dual-stack
    If this option is not set, the socket behavior is platform dependent
    """

    auth_timeout: str = "3s"
    """
    [Optional] How long the server should wait for the client to send the authentication command
    Default: 3s
    """

    task_negotiation_timeout: str = "3s"
    """
    [Optional] Maximum duration server expects for task negotiation
    Default: 3s
    """

    max_idle_time: str = "10s"
    """
    [Optional] How long the server should wait before closing an idle connection
    Default: 10s
    """

    max_external_packet_size: int = 1500
    """
    [Optional] Maximum packet size the server can receive from outbound UDP sockets, in bytes
    Default: 1500
    """

    send_window: int = 16777216
    """
    [Optional] Maximum number of bytes to transmit to a peer without acknowledgment
    Should be set to at least the expected connection latency multiplied by the maximum desired throughput
    Default: 8MiB * 2
    """

    receive_window: int = 8388608
    """
    [Optional]. Maximum number of bytes the peer may transmit without acknowledgement on any one stream before becoming blocked
    Should be set to at least the expected connection latency multiplied by the maximum desired throughput
    Default: 8MiB
    """

    gc_interval: str = "3s"
    """
    [Optional] Interval between UDP packet fragment garbage collection
    Default: 3s
    """

    gc_lifetime: str = "15s"
    """
    [Optional] How long the server should keep a UDP packet fragment. Outdated fragments will be dropped
    Default: 15s
    """

    log_level: Literal["warn", "info", "debug", "error"] = "warn"
    """
    [Optional] Set the log level
    Default: "warn"
    """

    def __post_init__(self):
        self.server = self.server or "[::]:443"
        self.alpn = self.alpn or ["h3", "spdy/3.1"]

    @classmethod
    def from_automation(
        cls, users: List[User] | User, path_fullchain: str, path_privkey: str, server_port: int
    ):
        if not isinstance(users, list):
            users = [users]
        users = {user.username: user.password for user in users}
        server = f"[::]:{server_port}"
        return cls(server=server, users=users, certificate=path_fullchain, private_key=path_privkey)

    def to_json(self, sp: Path):
        sp.write_text(json.dumps(self.__dict__, indent=4, ensure_ascii=True))
        logging.info(f"保存服务端配置文件 - save_path={sp}")


@dataclass
class ClientRelay:
    """Settings for the outbound TUIC proxy"""

    server: str
    """
    // Format: "HOST:PORT"
    // The HOST must be a common name in the certificate
    // If the "ip" field in the "relay" section is not set, the HOST is also used for DNS resolving
    """

    uuid: str
    password: str
    """
    TUIC User Object
    """

    ip: str | None = None
    """
    // Optional. The IP address of the TUIC proxy server, for overriding DNS resolving
    // If not set, the HOST in the "server" field is used for DNS resolving
    """

    certificates: List[str] | None = field(default_factory=list)
    """
    Because this script implements the steps of automatic certificate application, this parameter will never be used.
    """

    udp_relay_mode: Literal["native", "quic"] = "quic"
    """
    // Optional. Set the UDP packet relay mode
    // Can be:
    // - "native": native UDP characteristics
    // - "quic": lossless UDP relay using QUIC streams, additional overhead is introduced
    // Default: "native"
    """

    congestion_control: Literal["cubic", "new_reno", "bbr"] = "bbr"
    """
    // Optional. Congestion control algorithm, available options:
    // "cubic", "new_reno", "bbr"
    // Default: "cubic"
    """

    alpn: List[str] | None = field(default_factory=list)
    """
    // Optional. Application layer protocol negotiation
    // Default being empty (no ALPN)
    """

    zero_rtt_handshake: bool = True
    """
    // Optional. Enable 0-RTT QUIC connection handshake on the client side
    // This is not impacting much on the performance, as the protocol is fully multiplexed
    // WARNING: Disabling this is highly recommended, as it is vulnerable to replay attacks. See https://blog.cloudflare.com/even-faster-connection-establishment-with-quic-0-rtt-resumption/#attack-of-the-clones
    // Default: false
    """

    send_window: int = 16777216
    """
    [Optional] Maximum number of bytes to transmit to a peer without acknowledgment
    Should be set to at least the expected connection latency multiplied by the maximum desired throughput
    Default: 8MiB * 2 
    """

    receive_window: int = 8388608
    """
    [Optional]. Maximum number of bytes the peer may transmit without acknowledgement on any one stream before becoming blocked
    Should be set to at least the expected connection latency multiplied by the maximum desired throughput
    Default: 8MiB 
    """

    gc_interval: str = "3s"
    """
    [Optional] Interval between UDP packet fragment garbage collection
    Default: 3s
    """

    gc_lifetime: str = "15s"
    """
    [Optional] How long the server should keep a UDP packet fragment. Outdated fragments will be dropped
    Default: 15s
    """

    def __post_init__(self):
        self.alpn = self.alpn or ["h3", "spdy/3.1"]
        self.certificates = None

    @classmethod
    def copy_from_server(cls, domain: str, user: User, sc: ServerConfig, server_port: int):
        server = f"{domain}:{server_port}"
        return cls(
            server=server,
            uuid=user.username,
            password=user.password,
            alpn=sc.alpn,
            congestion_control=sc.congestion_control,
            send_window=sc.send_window,
            receive_window=sc.receive_window,
            gc_interval=sc.gc_interval,
            gc_lifetime=sc.gc_lifetime,
        )


@dataclass
class ClientLocal:
    server: str
    username: str | None = None
    password: str | None = None
    dual_stack: bool | None = None
    max_packet_size: int | None = 1500


@dataclass
class NekoRayConfig:
    """
    https://github.com/EAimTY/tuic/tree/dev/tuic-client
    Config template of tuic-client(v1.0.0)
    Apply on the NekoRay(v3.8)
    """

    relay: Dict[str, Any] = field(default_factory=dict)
    local: Dict[str, Any] = field(default_factory=dict)
    log_level: Literal["warn", "info", "debug", "error"] = "warn"

    @classmethod
    def from_server(
        cls, relay: ClientRelay, server_addr: str, server_port: int, server_ip: str | None = None
    ):
        local = ClientLocal(server="127.0.0.1:%socks_port%")

        relay.server = f"{server_addr}:{server_port}"

        if server_ip is not None:
            relay.ip = server_ip

        relay, local = relay.__dict__, local.__dict__

        local = {k: local[k] for k in local if local[k] is not None}
        relay = {k: relay[k] for k in relay if relay[k] is not None}

        return cls(relay=relay, local=local)

    @classmethod
    def from_json(cls, sp: Path):
        data = json.loads(sp.read_text(encoding="utf8"))
        return from_dict_to_cls(cls, data)

    def to_json(self, sp: Path):
        sp.write_text(json.dumps(self.__dict__, indent=4, ensure_ascii=True))

    @property
    def showcase(self) -> str:
        return json.dumps(self.__dict__, indent=4, ensure_ascii=True)

    @property
    def serv_peer(self) -> Tuple[str, str]:
        serv_addr, serv_port = self.relay.get("server", "").split(":")
        return serv_addr, serv_port


@dataclass
class ClashMetaConfig:
    # 在 meta_config.yaml 中的配置内容
    contents: str

    @classmethod
    def from_server(
        cls, relay: ClientRelay, server_addr: str, server_port: int, server_ip: str | None = None
    ):
        def from_string_to_yaml(s: str):
            _suffix = ", "
            fs = _suffix.join([i.strip() for i in s.split("\n") if i])
            fs = fs[: len(fs) - len(_suffix)]
            return "{ " + fs + " }"

        def remove_empty_lines(s: str):
            lines = s.split("\n")
            non_empty_lines = [line for line in lines if line.strip()]
            return "\n".join(non_empty_lines)

        name = "tunic"

        # https://wiki.metacubex.one/config/proxies/tuic/
        proxy = f"""
        name: "{name}"
        type: tuic
        server: {server_addr}
        port: {server_port}
        uuid: {relay.uuid}
        password: "{relay.password}"
        ip: {server_ip or ''}
        udp-relay-mode: {relay.udp_relay_mode}
        congestion-controller: {relay.congestion_control}
        alpn: {relay.alpn}
        reduce-rtt: {relay.zero_rtt_handshake}
        max-udp-relay-packet-size: 1464
        """

        # https://wiki.metacubex.one/config/proxy-groups/select/
        proxy_group = f"""
        name: PROXY
        type: select
        proxies: ["{name}"]
        """

        proxy = from_string_to_yaml(proxy)
        proxy_group = from_string_to_yaml(proxy_group)

        addons = TEMPLATE_META_PROXY_ADDONS.format(proxy=proxy, proxy_group=proxy_group)
        contents = TEMPLATE_META_CONFIG + addons
        contents = remove_empty_lines(contents)

        return cls(contents=contents)

    def to_yaml(self, sp: Path):
        sp.write_text(self.contents + "\n")


@dataclass
class SingBoxConfig:
    type: str
    tag: str
    server: str
    server_port: int
    uuid: str
    password: str
    congestion_control: Literal["cubic", "new_reno", "bbr"] = "bbr"
    udp_relay_mode: Literal["udp", "quic"] = "quic"
    zero_rtt_handshake: bool = True

    tls: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_server(
        cls, relay: ClientRelay, server_addr: str, server_port: int, server_ip: str | None = None
    ):
        return cls(
            type="tuic",
            tag="tuic-out",
            server=server_ip or "",
            server_port=server_port,
            uuid=relay.uuid,
            password=relay.password,
            congestion_control=relay.congestion_control,
            udp_relay_mode=relay.udp_relay_mode,
            zero_rtt_handshake=relay.zero_rtt_handshake,
            tls={
                "enabled": True,
                "disable_sni": False,
                "server_name": server_addr,
                "insecure": False,
                "alpn": relay.alpn,
            },
        )

    @classmethod
    def from_json(cls, sp: Path):
        data = json.loads(sp.read_text(encoding="utf8"))
        return from_dict_to_cls(cls, data)

    def to_json(self, sp: Path):
        sp.write_text(json.dumps(self.__dict__, indent=4, ensure_ascii=True))

    @property
    def showcase(self) -> str:
        return json.dumps(self.__dict__, indent=4, ensure_ascii=True)


# =================================== DataModel ===================================


TEMPLATE_PRINT_NEKORAY = """
\033[36m--> NekoRay 自定义核心配置\033[0m
# 名称：(custom)
# 地址：{server_addr}
# 端口：{listen_port}
# 命令：-c %config%
# 核心：tuic

{nekoray_config}
"""

TEMPLATE_PRINT_META = """
\033[36m--> Clash.Meta 配置文件输出路径\033[0m
{meta_path}
"""

TEMPLATE_PRINT_SINGBOX = """
\033[36m--> sing-box tuic 客户端出站配置\033[0m
{singbox_config}
"""


class Template:
    def __init__(self, project: Project, mode: Literal["install", "check"] = "check"):
        self.project = project
        self.mode = mode

    def gen_clients(self, server_addr: str, user: User, server_config: ServerConfig):
        logging.info("正在生成客户端配置文件")
        project = self.project

        # 生成客户端通用实例
        server_ip, server_port = project.server_ip, project.server_port
        relay = ClientRelay.copy_from_server(server_addr, user, server_config, server_port)

        # 生成 NekoRay 客户端配置实例
        # https://matsuridayo.github.io/n-extra_core/
        nekoray = NekoRayConfig.from_server(relay, server_addr, server_port, server_ip)
        nekoray.to_json(project.client_nekoray_config)

        # 生成 Clash.Meta 客户端配置实例
        # https://wiki.metacubex.one/config/proxies/tuic/
        meta = ClashMetaConfig.from_server(relay, server_addr, server_port, server_ip)
        meta.to_yaml(project.client_meta_config)

        # 生成 sing-box 客户端出站配置
        # https://sing-box.sagernet.org/configuration/outbound/tuic/
        singbox = SingBoxConfig.from_server(relay, server_addr, server_port, server_ip)
        singbox.to_json(project.client_singbox_config)

    def print_nekoray(self):
        if not self.project.client_nekoray_config.exists():
            logging.error(f"❌ 客户端配置文件不存在 - path={self.project.client_nekoray_config}")
        else:
            nekoray = NekoRayConfig.from_json(self.project.client_nekoray_config)
            serv_addr, serv_port = nekoray.serv_peer
            print(
                TEMPLATE_PRINT_NEKORAY.format(
                    server_addr=serv_addr, listen_port=serv_port, nekoray_config=nekoray.showcase
                )
            )

    def print_clash_meta(self, mode: Literal["install", "check"] = None):
        self.mode = mode or self.mode
        if not self.project.client_meta_config.exists():
            logging.error(f"❌ 客户端配置文件不存在 - path={self.project.client_meta_config}")
        elif self.mode == "install":
            print(TEMPLATE_PRINT_META.format(meta_path=self.project.client_meta_config))
        elif self.mode == "check":
            print(TEMPLATE_PRINT_META.format(meta_path=self.project.client_meta_config))
            print("\033[36m--> Clash.Meta 配置信息\033[0m")
            print(self.project.client_meta_config.read_text())

    def print_singbox(self):
        if not self.project.client_nekoray_config.exists():
            logging.error(f"❌ 客户端配置文件不存在 - path={self.project.client_nekoray_config}")
        else:
            singbox = SingBoxConfig.from_json(self.project.client_singbox_config)
            print(TEMPLATE_PRINT_SINGBOX.format(singbox_config=singbox.showcase))

    def parse(self, params: argparse):
        show_all = not any([params.clash, params.nekoray, params.v2ray, params.singbox])
        if show_all:
            self.print_nekoray()
            self.print_clash_meta()
            self.print_singbox()
        elif params.nekoray:
            self.print_nekoray()
        elif params.clash:
            self.print_clash_meta(mode="check")
        elif params.singbox:
            self.print_singbox()
        elif params.v2ray:
            logging.warning("Unimplemented feature")


class Scaffold:
    @staticmethod
    def _validate_domain(domain: str | None) -> NoReturn | Tuple[str, str]:
        """

        :param domain:
        :return: Tuple[domain, server_ip]
        """
        if not domain:
            domain = input("> 解析到本机的域名：")

        try:
            server_ip = socket.getaddrinfo(domain, None)[-1][4][0]
        except socket.gaierror:
            logging.error(f"域名不可达或拼写错误的域名 - domain={domain}")
        else:
            my_ip = request.urlopen("http://ifconfig.me/ip").read().decode("utf8")
            if my_ip != server_ip:
                logging.error(
                    f"你的主机外网IP与域名解析到的IP不一致 - my_ip={my_ip} domain={domain} server_ip={server_ip}"
                )
            else:
                return domain, server_ip

        # 域名解析错误，应当阻止用户执行安装脚本
        sys.exit()

    @staticmethod
    def _validate_port(port: int | None) -> NoReturn | int | None:
        # No `-p` parameter specified
        if port is None:
            return

        # Avoid conflicts with known services as much as possible
        if port < 49152:
            logging.error(f"指定的端口应当大于 49151 - scope=[49152, 65535]")
            sys.exit()

        # UDP port already in use
        if Project.is_port_in_used(port, proto="udp"):
            logging.error(f"UDP 端口已被占用 - port={port}")
            sys.exit()

        # Available port
        logging.info(f"端口绑定成功 - port={port}")
        return port

    @staticmethod
    def _recv_stream(script: str, pipe: Literal["stdout", "stderr"] = "stdout") -> str:
        p = subprocess.Popen(
            script.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            text=True,
        )
        if pipe == "stdout":
            return p.stdout.read().strip()
        if pipe == "stderr":
            return p.stderr.read().strip()

    @staticmethod
    def install(params: argparse.Namespace):
        """
        1. 运行 certbot 申请证书
        3. 初始化 Project 环境对象
        4. 初始化 server config
        5. 初始化 client config
        6. 生成 client config 配置信息
        :param params:
        :return:
        """
        port = Scaffold._validate_port(params.port)

        (domain, server_ip) = Scaffold._validate_domain(params.domain)
        logging.info(f"域名解析成功 - domain={domain}")

        # 初始化证书对象
        cert = Certificate(domain)

        # 为绑定到本机的域名申请证书
        if not Path(cert.fullchain).exists():
            CertBot(domain).run()
        else:
            logging.info(f"证书文件已存在 - path={Path(cert.fullchain).parent}")

        # 初始化 workstation
        project = Project()
        user = User.gen()

        # 设置脚本别名
        project.set_alias()

        # 绑定传入的端口，或随机选用未被占用的 UDP 端口
        project.server_port = port or project.server_port
        server_port = project.server_port

        # 初始化系统服务配置
        project.server_ip = server_ip
        service = Service.build_from_template(
            path=project.service, template=project.systemd_template
        )

        logging.info(f"正在下载 tuic-server")
        service.download_server(project.workstation)

        logging.info("正在生成默认的服务端配置")
        server_config = ServerConfig.from_automation(
            user, cert.fullchain, cert.privkey, server_port
        )
        server_config.to_json(project.server_config)

        logging.info("正在部署系统服务")
        service.start()

        logging.info("正在检查服务状态")
        (response, text) = service.status()

        # 在控制台输出客户端配置
        if response is True:
            t = Template(project, mode="install")
            t.gen_clients(domain, user, server_config)
            t.parse(params)
            project.reset_shell()
        else:
            logging.info(f"服务启动失败 - status={text}")

    @staticmethod
    def remove(params: argparse.Namespace):
        (domain, _) = Scaffold._validate_domain(params.domain)
        logging.info(f"解绑服务 - bind={domain}")

        project = Project()

        # 移除脚本别名
        project.remove_alias()

        # 移除可能残留的证书文件
        CertBot(domain).remove()

        # 关停进程，注销系统服务，移除工作空间
        service = Service.build_from_template(project.service)
        service.remove(project.workstation)

        project.reset_shell()

    @staticmethod
    def check(params: argparse.Namespace, mode: Literal["install", "check"] = "check"):
        project = Project()
        Template(project, mode).parse(params)

    @staticmethod
    def service_relay(cmd: str):
        project = Project()
        service = Service.build_from_template(path=project.service)

        if cmd == "status":
            active = Scaffold._recv_stream(f"systemctl is-active {service.name}")
            logging.info(f"TUIC 服务状态：{active}")
            version = Scaffold._recv_stream(f"{project.executable} -v")
            logging.info(f"TUIC 服务版本：{version}")
            ct_active = Scaffold._recv_stream("systemctl is-active certbot.timer")
            logging.info(f"证书续订服务状态：{ct_active}")
            logging.info(f"服務端配置：{project.server_config}")
            logging.info(f"客戶端配置[NekoRay]：{project.client_nekoray_config}")
            logging.info(f"客戶端配置[Clash.Meta]：{project.client_meta_config}")
            logging.info(f"客戶端配置[sing-box]：{project.client_singbox_config}")
            logging.info(f"TUIC 系统服务配置：{project.service}")
        elif cmd == "log":
            # FIXME unknown syslog
            syslog = Scaffold._recv_stream(f"journalctl -u {service.name} -f -o cat")
            print(syslog)
        elif cmd == "start":
            service.start()
        elif cmd == "stop":
            service.stop()
        elif cmd == "restart":
            service.restart()


def run():
    parser = argparse.ArgumentParser(description="TUIC Scaffold (Python3.8+)")
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Automatically install and run")
    install_parser.add_argument("-d", "--domain", type=str, help="指定域名，否则需要在运行脚本后以交互的形式输入")
    install_parser.add_argument("-p", "--port", type=int, help="指定服务监听端口，否则随机选择未被使用的端口")

    remove_parser = subparsers.add_parser("remove", help="Uninstall services and associated caches")
    remove_parser.add_argument("-d", "--domain", type=str, help="传参指定域名，否则需要在运行脚本后以交互的形式输入")

    check_parser = subparsers.add_parser("check", help="Print client configuration")

    subparsers.add_parser("status", help="Check tuic-service status")
    subparsers.add_parser("log", help="Check tuic-service syslog")
    subparsers.add_parser("start", help="Start tuic-service")
    subparsers.add_parser("stop", help="Stop tuic-service")
    subparsers.add_parser("restart", help="restart tuic-service")

    for c in [check_parser, install_parser]:
        c.add_argument("--nekoray", action="store_true", help="show NekoRay config")
        c.add_argument("--clash", action="store_true", help="show Clash.Meta config")
        c.add_argument("--v2ray", action="store_true", help="show v2rayN config")
        c.add_argument("--singbox", action="store_true", help="show sing-box config")

    args = parser.parse_args()
    command = args.command

    with suppress(KeyboardInterrupt):
        if command == "install":
            Scaffold.install(params=args)
        elif command == "remove":
            Scaffold.remove(params=args)
        elif command == "check":
            Scaffold.check(params=args)
        elif command in ["status", "log", "start", "stop", "restart"]:
            Scaffold.service_relay(command)
        else:
            parser.print_help()


if __name__ == "__main__":
    run()
