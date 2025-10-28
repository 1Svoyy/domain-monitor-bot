import asyncio
import logging
import random
import ssl
from typing import Dict, Optional, Tuple

import aiohttp

from database import Database


logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    async def broadcast(self, message: str) -> None:
        chat_ids = await self.db.list_subscribers()
        for chat_id in chat_ids:
            try:
                await self.bot.send_message(chat_id, message)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.warning("Failed to send message to %s: %s", chat_id, exc)
                continue

    async def notify_downtime(self, domain: str, error: str) -> None:
        await self.broadcast(
            f"❌ <b>{domain}</b> недоступен\nПричина: <code>{error}</code>"
        )

    async def notify_recovery(self, domain: str) -> None:
        await self.broadcast(f"✅ <b>{domain}</b> снова доступен")


class DomainChecker:
    def __init__(self, db: Database, notifier: NotificationService) -> None:
        self.db = db
        self.notifier = notifier
        self._lock = asyncio.Lock()

    async def check_all_domains(self) -> None:
        async with self._lock:
            domains = await self.db.list_domains()
            for domain in domains:
                await self._check_domain_record(domain)

    async def check_domain_by_name(self, name: str) -> Tuple[bool, Optional[str]]:
        async with self._lock:
            record = await self.db.get_domain(name)
            if not record:
                raise ValueError("Домен не найден")
            return await self._check_domain_record(record, notify_on_change=False)

    async def _check_domain_record(
        self,
        domain: Dict,
        notify_on_change: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        is_up, error = await self._perform_check(domain["name"])
        status = "up" if is_up else "down"
        previous_status = domain.get("last_status") or "unknown"

        await self.db.update_domain_status(domain["id"], status, error)
        await self.db.log_check(domain["id"], status, error)

        if notify_on_change and previous_status != status:
            if status == "down":
                await self.notifier.notify_downtime(domain["name"], error or "Unknown error")
            elif previous_status == "down" and status == "up":
                await self.notifier.notify_recovery(domain["name"])

        return is_up, error

    async def _perform_check(self, domain: str) -> Tuple[bool, Optional[str]]:
        proxy = await self._get_proxy()
        headers = {"User-Agent": self._generate_user_agent()}
        timeout = aiohttp.ClientTimeout(total=20)
        url = domain if domain.startswith("http") else f"https://{domain}"

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                async with session.get(url, proxy=proxy) as response:
                    if response.status < 400:
                        return True, None
                    return False, f"HTTP {response.status}"
        except aiohttp.ClientConnectorCertificateError as exc:
            return False, "ERR_SSL_PROTOCOL_ERROR"
        except aiohttp.ClientSSLError:
            return False, "ERR_SSL_PROTOCOL_ERROR"
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return False, type(exc).__name__
        except ssl.SSLError:
            return False, "ERR_SSL_PROTOCOL_ERROR"

    async def _get_proxy(self) -> Optional[str]:
        proxy = await self.db.get_proxy_for_country("turkey")
        if not proxy:
            proxy = await self.db.get_active_proxy()
        if not proxy:
            return None
        auth = ""
        if proxy.get("username") and proxy.get("password"):
            auth = f"{proxy['username']}:{proxy['password']}@"
        return f"http://{auth}{proxy['host']}:{proxy['port']}"

    def _generate_user_agent(self) -> str:
        browser = random.choice(["Chrome", "Firefox", "Edge", "Safari"])
        version = ".".join(str(random.randint(60, 120)) for _ in range(3))
        os = random.choice(
            [
                "Windows NT 10.0; Win64; x64",
                "Macintosh; Intel Mac OS X 10_15_7",
                "X11; Linux x86_64",
                "iPhone; CPU iPhone OS 16_0 like Mac OS X",
            ]
        )
        return f"Mozilla/5.0 ({os}) AppleWebKit/537.36 (KHTML, like Gecko) {browser}/{version}"
