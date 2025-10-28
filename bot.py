import logging
from typing import Optional

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from checker import DomainChecker
from database import Database


logger = logging.getLogger(__name__)


class BotService:
    def __init__(self, bot: Bot, db: Database, checker: DomainChecker) -> None:
        self.db = db
        self.bot = bot
        self.notifier = checker.notifier
        self.checker = checker
        self.dispatcher = Dispatcher()
        self.router = Router()
        self._register_handlers()
        self.dispatcher.include_router(self.router)

    def _normalize_domain(self, value: str) -> str:
        text = value.strip().lower()
        if text.startswith("http://"):
            text = text[7:]
        elif text.startswith("https://"):
            text = text[8:]
        return text.strip("/")

    def _register_handlers(self) -> None:
        self.router.message.register(self.cmd_start, Command(commands=["start"]))
        self.router.message.register(self.add_domain, Command(commands=["add_domain"]))
        self.router.message.register(self.remove_domain, Command(commands=["remove_domain"]))
        self.router.message.register(self.list_domains, Command(commands=["list_domains"]))
        self.router.message.register(self.force_check, Command(commands=["check"]))
        self.router.message.register(self.add_proxy, Command(commands=["add_proxy"]))
        self.router.message.register(self.remove_proxy, Command(commands=["remove_proxy"]))
        self.router.message.register(self.list_proxies, Command(commands=["list_proxies"]))

    async def run(self) -> None:
        logger.info("Starting bot polling")
        await self.dispatcher.start_polling(self.bot)

    async def stop(self) -> None:
        await self.bot.session.close()

    async def cmd_start(self, message: Message) -> None:
        await self.db.add_subscriber(message.chat.id)
        await message.answer(
            "Привет! Я мониторю домены. Используй /add_domain, чтобы добавить домен для проверки."
        )

    async def add_domain(self, message: Message, command: CommandObject) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        if not command.args:
            await message.answer("Укажи домен: /add_domain example.com")
            return
        domain = self._normalize_domain(command.args)
        await self.db.add_domain(domain)
        await message.answer(f"Домен <b>{domain}</b> добавлен.")

    async def remove_domain(self, message: Message, command: CommandObject) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        if not command.args:
            await message.answer("Укажи домен: /remove_domain example.com")
            return
        domain = self._normalize_domain(command.args)
        removed = await self.db.remove_domain(domain)
        if removed:
            await message.answer(f"Домен <b>{domain}</b> удалён.")
        else:
            await message.answer("Такого домена нет в списке.")

    async def list_domains(self, message: Message) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        domains = await self.db.list_domains()
        if not domains:
            await message.answer("Доменов пока нет.")
            return
        lines = []
        for domain in domains:
            status = domain.get("last_status", "unknown")
            emoji = {"up": "✅", "down": "❌"}.get(status, "❔")
            last_checked = domain.get("last_checked") or "—"
            error = domain.get("last_error")
            error_part = f"\n    Ошибка: {error}" if error else ""
            lines.append(f"{emoji} <b>{domain['name']}</b> (проверка: {last_checked}){error_part}")
        await message.answer("\n".join(lines))

    async def force_check(self, message: Message, command: CommandObject) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        if not command.args:
            await message.answer("Укажи домен: /check example.com")
            return
        domain = self._normalize_domain(command.args)
        try:
            is_up, error = await self.checker.check_domain_by_name(domain)
        except ValueError:
            await message.answer("Домен не найден. Добавь его через /add_domain")
            return
        if is_up:
            await message.answer(f"✅ <b>{domain}</b> доступен")
        else:
            await message.answer(
                f"❌ <b>{domain}</b> недоступен: {error or 'Unknown error'}"
            )

    async def add_proxy(self, message: Message, command: CommandObject) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        if not command.args:
            await message.answer(
                "Формат: /add_proxy host port [username] [password] [country]."
                " Укажите прокси с турецкой геолокацией, чтобы проверки шли из Турции."
            )
            return
        parts = command.args.split()
        if len(parts) < 2:
            await message.answer("Недостаточно данных. Минимум host и port.")
            return
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            await message.answer("Порт должен быть числом.")
            return
        username: Optional[str] = parts[2] if len(parts) >= 3 else None
        password: Optional[str] = parts[3] if len(parts) >= 4 else None
        country: Optional[str] = parts[4] if len(parts) >= 5 else None
        proxy_id = await self.db.add_proxy(host, port, username, password, country)
        await message.answer(f"Прокси #{proxy_id} добавлен и активирован.")

    async def remove_proxy(self, message: Message, command: CommandObject) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        if not command.args:
            await message.answer("Укажи ID прокси: /remove_proxy 1")
            return
        try:
            proxy_id = int(command.args.strip())
        except ValueError:
            await message.answer("ID должен быть числом.")
            return
        removed = await self.db.remove_proxy(proxy_id)
        if removed:
            await message.answer("Прокси удалён.")
        else:
            await message.answer("Прокси с таким ID не найден.")

    async def list_proxies(self, message: Message) -> None:  # type: ignore[override]
        await self.db.add_subscriber(message.chat.id)
        proxies = await self.db.list_proxies()
        if not proxies:
            await message.answer("Прокси не добавлены.")
            return
        lines = []
        for proxy in proxies:
            label = f"{proxy['host']}:{proxy['port']}"
            if proxy.get("username"):
                label += " (auth)"
            country = proxy.get("country") or "—"
            status = "активен" if proxy.get("is_active") else "неактивен"
            lines.append(f"#{proxy['id']} {label}, страна: {country}, {status}")
        await message.answer("\n".join(lines))
