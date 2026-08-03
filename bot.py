import asyncio
import datetime
import json
import os
import random
import re
import socket
import threading

import discord
from discord import app_commands
from discord.ext import commands

# ═══════════════════════════════════════════════════════════════
# ИНТЕНТЫ
# ═══════════════════════════════════════════════════════════════
intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)

ACCENT  = discord.Color.from_rgb(88,  101, 242)
SUCCESS = discord.Color.from_rgb(87,  242, 135)
DANGER  = discord.Color.from_rgb(237,  66,  69)
WARNING = discord.Color.from_rgb(254, 231,  92)
INFO    = discord.Color.from_rgb(0,   176, 240)
GOLD    = discord.Color.from_rgb(255, 215,   0)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

giveaways: dict[int, dict] = {}
clickers:  dict[int, dict] = {}

# ─── Все события логов ──────────────────────────────────────
LOG_EVENTS_PAGE1 = [
    ("channel_create",  "Канал создан"),
    ("channel_delete",  "Канал удалён"),
    ("channel_update",  "Канал изменён"),
    ("emoji_add",       "Эмодзи добавлен"),
    ("emoji_remove",    "Эмодзи удалён"),
    ("emoji_update",    "Эмодзи изменён"),
    ("ban",             "Блокировка выдана"),
    ("unban",           "Блокировка убрана"),
    ("member_join",     "Пользователь присоединился"),
    ("member_leave",    "Пользователь покинул"),
    ("member_update",   "Участник изменён"),
    ("timeout_add",     "Тайм-аут выдан"),
    ("timeout_remove",  "Тайм-аут снят"),
    ("guild_update",    "Сервер изменён"),
    ("invite_create",   "Приглашение создано"),
    ("invite_delete",   "Приглашение удалено"),
]
LOG_EVENTS_PAGE2 = [
    ("message_delete",  "Сообщение удалено"),
    ("bulk_delete",     "Массовое удаление"),
    ("message_edit",    "Сообщение изменено"),
    ("role_create",     "Роль создана"),
    ("role_delete",     "Роль удалена"),
    ("role_add",        "Роль добавлена"),
    ("role_remove",     "Роль убрана"),
    ("role_update",     "Роль изменена"),
    ("sticker_add",     "Стикер добавлен"),
    ("sticker_remove",  "Стикер удалён"),
    ("sticker_update",  "Стикер изменён"),
    ("thread_create",   "Ветка создана"),
    ("thread_delete",   "Ветка удалена"),
    ("thread_update",   "Ветка изменена"),
    ("voice_join",      "Голосовое подключение"),
    ("voice_leave",     "Голосовое отключение"),
]


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def make_embed(color, title, description="", fields=None, footer=None, thumbnail=None):
    e = discord.Embed(title=title, description=description, color=color)
    e.timestamp = datetime.datetime.now(datetime.timezone.utc)
    if fields:
        for n, v, i in fields:
            e.add_field(name=n, value=v, inline=i)
    if footer:
        e.set_footer(text=footer)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return e


def parse_duration(text: str) -> int | None:
    m = re.fullmatch(r"(\d+)([smhd])", text.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def fmt_duration(s: int) -> str:
    if s < 60:   return f"{s}с"
    if s < 3600: return f"{s//60}м {s%60}с"
    return f"{s//3600}ч {(s%3600)//60}м"


# ═══════════════════════════════════════════════════════════════
# ХРАНИЛИЩЕ
# ═══════════════════════════════════════════════════════════════
def load_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_log_config(guild_id: int) -> dict:
    data = load_data()
    gid = str(guild_id)
    return data.get("logs", {}).get(gid, {"channel_id": None, "events": {}})


def toggle_log_event(guild_id: int, event: str):
    data = load_data()
    gid = str(guild_id)
    data.setdefault("logs", {}).setdefault(gid, {"channel_id": None, "events": {}})
    cfg = data["logs"][gid]["events"]
    cfg[event] = not cfg.get(event, True)
    save_data(data)


def set_log_channel(guild_id: int, channel_id: int):
    data = load_data()
    gid = str(guild_id)
    data.setdefault("logs", {}).setdefault(gid, {"channel_id": None, "events": {}})
    data["logs"][gid]["channel_id"] = channel_id
    save_data(data)


async def send_log(guild: discord.Guild, event: str, embed: discord.Embed):
    cfg = get_log_config(guild.id)
    if not cfg["events"].get(event, True):
        return
    ch_id = cfg.get("channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return
    try:
        await ch.send(embed=embed)
    except discord.Forbidden:
        pass


# ═══════════════════════════════════════════════════════════════
# СОБЫТИЯ
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    bot.add_dynamic_items(VerifyDynamicButton)
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="QRXTeam")
    )
    await bot.tree.sync()
    print(f"✅ Бот {bot.user} запущен!")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    # Приветствие
    ch = discord.utils.find(
        lambda c: any(k in c.name.lower() for k in ("привет", "general", "welcome", "основной", "чат")),
        guild.text_channels,
    ) or guild.system_channel
    if ch:
        embed = discord.Embed(
            title="👋 Добро пожаловать!",
            description=f"Привет, {member.mention}! Рады видеть тебя на **{guild.name}**. 🎉",
            color=ACCENT,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="👤 Участник", value=member.mention, inline=True)
        embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
        embed.add_field(name="📅 Создан", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.set_footer(text=f"Участник #{guild.member_count}")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        await ch.send(embed=embed)

    # Лог
    log_embed = make_embed(
        SUCCESS, "📥 Пользователь присоединился",
        fields=[
            ("👤 Пользователь", f"{member.mention} (`{member}`)", True),
            ("🆔 ID", str(member.id), True),
            ("📅 Аккаунт создан", discord.utils.format_dt(member.created_at, "R"), True),
        ],
        thumbnail=member.display_avatar.url,
        footer=f"Участников: {guild.member_count}",
    )
    await send_log(guild, "member_join", log_embed)


@bot.event
async def on_member_remove(member: discord.Member):
    embed = make_embed(
        DANGER, "📤 Пользователь покинул сервер",
        fields=[
            ("👤 Пользователь", f"`{member}` (ID: `{member.id}`)", True),
            ("📅 Был на сервере с", discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "—", True),
        ],
        thumbnail=member.display_avatar.url,
        footer=f"Участников: {member.guild.member_count}",
    )
    await send_log(member.guild, "member_leave", embed)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    embed = make_embed(
        DANGER, "🔨 Пользователь заблокирован",
        fields=[("👤 Пользователь", f"`{user}` (ID: `{user.id}`)", True)],
        thumbnail=user.display_avatar.url,
    )
    await send_log(guild, "ban", embed)


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    embed = make_embed(
        SUCCESS, "✅ Пользователь разблокирован",
        fields=[("👤 Пользователь", f"`{user}` (ID: `{user.id}`)", True)],
        thumbnail=user.display_avatar.url,
    )
    await send_log(guild, "unban", embed)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    guild = after.guild
    # Тайм-аут выдан
    if not before.is_timed_out() and after.is_timed_out():
        embed = make_embed(
            WARNING, "🔇 Тайм-аут выдан",
            fields=[
                ("👤 Пользователь", after.mention, True),
                ("📅 До", discord.utils.format_dt(after.timed_out_until, "R"), True),
            ],
            thumbnail=after.display_avatar.url,
        )
        await send_log(guild, "timeout_add", embed)
        return
    # Тайм-аут снят
    if before.is_timed_out() and not after.is_timed_out():
        embed = make_embed(SUCCESS, "🔊 Тайм-аут снят",
                           fields=[("👤 Пользователь", after.mention, True)],
                           thumbnail=after.display_avatar.url)
        await send_log(guild, "timeout_remove", embed)
        return
    # Роль добавлена
    added_roles = [r for r in after.roles if r not in before.roles]
    for role in added_roles:
        embed = make_embed(SUCCESS, "➕ Роль добавлена",
                           fields=[("👤 Пользователь", after.mention, True), ("🎭 Роль", role.mention, True)],
                           thumbnail=after.display_avatar.url)
        await send_log(guild, "role_add", embed)
    # Роль убрана
    removed_roles = [r for r in before.roles if r not in after.roles]
    for role in removed_roles:
        embed = make_embed(DANGER, "➖ Роль убрана",
                           fields=[("👤 Пользователь", after.mention, True), ("🎭 Роль", role.name, True)],
                           thumbnail=after.display_avatar.url)
        await send_log(guild, "role_remove", embed)
    # Общее обновление участника (ник и т.д.)
    if before.nick != after.nick or before.display_name != after.display_name:
        embed = make_embed(INFO, "✏️ Участник изменён",
                           fields=[
                               ("👤 Пользователь", after.mention, True),
                               ("📝 Было", before.display_name, True),
                               ("📝 Стало", after.display_name, True),
                           ],
                           thumbnail=after.display_avatar.url)
        await send_log(guild, "member_update", embed)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    embed = make_embed(SUCCESS, "📁 Канал создан",
                       fields=[("📌 Канал", f"#{channel.name}", True), ("🗂 Тип", str(channel.type), True)])
    await send_log(channel.guild, "channel_create", embed)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    embed = make_embed(DANGER, "🗑 Канал удалён",
                       fields=[("📌 Канал", f"#{channel.name}", True), ("🗂 Тип", str(channel.type), True)])
    await send_log(channel.guild, "channel_delete", embed)


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name == after.name:
        return
    embed = make_embed(INFO, "✏️ Канал изменён",
                       fields=[("📌 Было", f"#{before.name}", True), ("📌 Стало", after.mention, True)])
    await send_log(after.guild, "channel_update", embed)


@bot.event
async def on_guild_role_create(role: discord.Role):
    embed = make_embed(SUCCESS, "🎭 Роль создана",
                       fields=[("🎭 Роль", role.mention, True), ("🎨 Цвет", str(role.color), True)])
    await send_log(role.guild, "role_create", embed)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    embed = make_embed(DANGER, "🗑 Роль удалена",
                       fields=[("🎭 Роль", role.name, True), ("🆔 ID", str(role.id), True)])
    await send_log(role.guild, "role_delete", embed)


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    changes = []
    if before.name != after.name:
        changes.append(f"Название: **{before.name}** → **{after.name}**")
    if before.color != after.color:
        changes.append(f"Цвет: `{before.color}` → `{after.color}`")
    if not changes:
        return
    embed = make_embed(INFO, "✏️ Роль изменена",
                       fields=[("🎭 Роль", after.mention, True), ("📝 Изменения", "\n".join(changes), False)])
    await send_log(after.guild, "role_update", embed)


@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.author.bot:
        return
    embed = make_embed(
        DANGER, "🗑 Сообщение удалено",
        fields=[
            ("👤 Автор", message.author.mention, True),
            ("📌 Канал", message.channel.mention, True),
            ("💬 Текст", message.content[:500] if message.content else "*[без текста]*", False),
        ],
        thumbnail=message.author.display_avatar.url,
    )
    await send_log(message.guild, "message_delete", embed)


@bot.event
async def on_bulk_message_delete(messages: list[discord.Message]):
    if not messages or not messages[0].guild:
        return
    guild = messages[0].guild
    channel = messages[0].channel
    embed = make_embed(DANGER, "🗑 Массовое удаление сообщений",
                       fields=[("📌 Канал", channel.mention, True), ("🔢 Количество", str(len(messages)), True)])
    await send_log(guild, "bulk_delete", embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not after.guild or after.author.bot or before.content == after.content:
        return
    embed = make_embed(
        INFO, "✏️ Сообщение изменено",
        fields=[
            ("👤 Автор", after.author.mention, True),
            ("📌 Канал", after.channel.mention, True),
            ("📝 Было", before.content[:300] if before.content else "*[пусто]*", False),
            ("📝 Стало", after.content[:300] if after.content else "*[пусто]*", False),
        ],
        thumbnail=after.author.display_avatar.url,
        footer="Нажмите ссылку, чтобы перейти",
    )
    await send_log(after.guild, "message_edit", embed)


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    if before.name == after.name:
        return
    embed = make_embed(INFO, "✏️ Сервер изменён",
                       fields=[("📝 Было", before.name, True), ("📝 Стало", after.name, True)])
    await send_log(after, "guild_update", embed)


@bot.event
async def on_invite_create(invite: discord.Invite):
    embed = make_embed(
        SUCCESS, "🔗 Приглашение создано",
        fields=[
            ("🔗 Ссылка", invite.url, True),
            ("👤 Создал", invite.inviter.mention if invite.inviter else "—", True),
            ("⏱ Истекает", str(invite.max_age) + "с" if invite.max_age else "Никогда", True),
        ],
    )
    await send_log(invite.guild, "invite_create", embed)


@bot.event
async def on_invite_delete(invite: discord.Invite):
    embed = make_embed(DANGER, "🔗 Приглашение удалено",
                       fields=[("🔗 Код", invite.code, True)])
    await send_log(invite.guild, "invite_delete", embed)


@bot.event
async def on_guild_emojis_update(guild: discord.Guild, before: list, after: list):
    before_ids = {e.id for e in before}
    after_ids  = {e.id for e in after}
    for e in after:
        if e.id not in before_ids:
            embed = make_embed(SUCCESS, "😀 Эмодзи добавлен",
                               fields=[("Эмодзи", str(e), True), ("Название", e.name, True)])
            await send_log(guild, "emoji_add", embed)
    for e in before:
        if e.id not in after_ids:
            embed = make_embed(DANGER, "😀 Эмодзи удалён",
                               fields=[("Название", e.name, True)])
            await send_log(guild, "emoji_remove", embed)
    for e_new in after:
        e_old = next((e for e in before if e.id == e_new.id), None)
        if e_old and e_old.name != e_new.name:
            embed = make_embed(INFO, "✏️ Эмодзи изменён",
                               fields=[("Было", e_old.name, True), ("Стало", e_new.name, True)])
            await send_log(guild, "emoji_update", embed)


@bot.event
async def on_guild_stickers_update(guild: discord.Guild, before: list, after: list):
    before_ids = {s.id for s in before}
    after_ids  = {s.id for s in after}
    for s in after:
        if s.id not in before_ids:
            embed = make_embed(SUCCESS, "🪧 Стикер добавлен", fields=[("Название", s.name, True)])
            await send_log(guild, "sticker_add", embed)
    for s in before:
        if s.id not in after_ids:
            embed = make_embed(DANGER, "🪧 Стикер удалён", fields=[("Название", s.name, True)])
            await send_log(guild, "sticker_remove", embed)
    for s_new in after:
        s_old = next((s for s in before if s.id == s_new.id), None)
        if s_old and s_old.name != s_new.name:
            embed = make_embed(INFO, "✏️ Стикер изменён",
                               fields=[("Было", s_old.name, True), ("Стало", s_new.name, True)])
            await send_log(guild, "sticker_update", embed)


@bot.event
async def on_thread_create(thread: discord.Thread):
    embed = make_embed(SUCCESS, "🧵 Ветка создана",
                       fields=[("📌 Ветка", thread.mention, True), ("📁 Родитель", thread.parent.mention if thread.parent else "—", True)])
    await send_log(thread.guild, "thread_create", embed)


@bot.event
async def on_thread_delete(thread: discord.Thread):
    embed = make_embed(DANGER, "🗑 Ветка удалена",
                       fields=[("📌 Ветка", thread.name, True)])
    await send_log(thread.guild, "thread_delete", embed)


@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread):
    if before.name == after.name:
        return
    embed = make_embed(INFO, "✏️ Ветка изменена",
                       fields=[("📝 Было", before.name, True), ("📝 Стало", after.mention, True)])
    await send_log(after.guild, "thread_update", embed)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel is None and after.channel is not None:
        embed = make_embed(SUCCESS, "🎙 Голосовое подключение",
                           fields=[("👤 Пользователь", member.mention, True), ("📢 Канал", after.channel.mention, True)],
                           thumbnail=member.display_avatar.url)
        await send_log(member.guild, "voice_join", embed)
    elif before.channel is not None and after.channel is None:
        embed = make_embed(DANGER, "🔇 Голосовое отключение",
                           fields=[("👤 Пользователь", member.mention, True), ("📢 Канал", before.channel.mention, True)],
                           thumbnail=member.display_avatar.url)
        await send_log(member.guild, "voice_leave", embed)


# ═══════════════════════════════════════════════════════════════
# ПАНЕЛЬ ЛОГОВ
# ═══════════════════════════════════════════════════════════════
def _build_logs_embed(guild_id: int, page: int) -> discord.Embed:
    embed = discord.Embed(
        title="🛡 Панель управления логами",
        description="Настройте события для отправки логов сервера.",
        color=ACCENT,
    )
    embed.set_footer(text=f"Страница {page}/2")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return embed


class LogsPanelView(discord.ui.View):
    def __init__(self, guild_id: int, page: int = 1):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.page = page
        self._build()

    def _build(self):
        events = LOG_EVENTS_PAGE1 if self.page == 1 else LOG_EVENTS_PAGE2
        cfg = get_log_config(self.guild_id)
        enabled_map = cfg.get("events", {})

        for i, (key, label) in enumerate(events):
            enabled = enabled_map.get(key, True)
            btn = discord.ui.Button(
                label=f"{'✅' if enabled else '❌'} {label}",
                style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
                custom_id=f"logbtn_{key}",
                row=i // 4,
            )
            btn.callback = self._make_toggle(key)
            self.add_item(btn)

        # Навигация
        if self.page == 1:
            nav = discord.ui.Button(
                label="Вперёд ▶", style=discord.ButtonStyle.primary,
                custom_id="log_nav_next", row=4,
            )
            nav.callback = self._nav(2)
        else:
            nav = discord.ui.Button(
                label="◀ Назад", style=discord.ButtonStyle.danger,
                custom_id="log_nav_prev", row=4,
            )
            nav.callback = self._nav(1)
        self.add_item(nav)

    def _make_toggle(self, key: str):
        async def callback(interaction: discord.Interaction):
            toggle_log_event(self.guild_id, key)
            new_view = LogsPanelView(self.guild_id, self.page)
            await interaction.response.edit_message(
                embed=_build_logs_embed(self.guild_id, self.page),
                view=new_view,
            )
        return callback

    def _nav(self, target: int):
        async def callback(interaction: discord.Interaction):
            new_view = LogsPanelView(self.guild_id, target)
            await interaction.response.edit_message(
                embed=_build_logs_embed(self.guild_id, target),
                view=new_view,
            )
        return callback


@bot.tree.command(name="логи", description="Настроить систему логов сервера")
@app_commands.describe(канал="Канал для отправки логов")
@app_commands.checks.has_permissions(manage_guild=True)
async def logs_cmd(interaction: discord.Interaction, канал: discord.TextChannel):
    set_log_channel(interaction.guild.id, канал.id)
    view = LogsPanelView(interaction.guild.id, page=1)
    embed = _build_logs_embed(interaction.guild.id, 1)
    await interaction.response.send_message(
        embed=embed, view=view, ephemeral=True
    )


# ═══════════════════════════════════════════════════════════════
# ВЕРИФИКАЦИЯ
# ═══════════════════════════════════════════════════════════════
class VerifyDynamicButton(discord.ui.DynamicItem[discord.ui.Button], template=r"verify_(?P<role_id>\d+)"):
    def __init__(self, role_id: int, label: str = "✅ Пройти верификацию"):
        super().__init__(
            discord.ui.Button(label=label, style=discord.ButtonStyle.success, custom_id=f"verify_{role_id}")
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(int(match.group("role_id")))

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Ошибка", "Роль не найдена."), ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message(
                embed=make_embed(INFO, "ℹ️ Уже верифицированы", f"У вас уже есть роль **{role.name}**."), ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Верификация по кнопке")
            await interaction.response.send_message(
                embed=make_embed(SUCCESS, "✅ Верификация пройдена!", f"Вы получили роль **{role.name}**!",
                                 thumbnail=interaction.user.display_avatar.url), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Ошибка", "У бота нет прав для выдачи роли."), ephemeral=True)


class VerifyButtonView(discord.ui.View):
    def __init__(self, role_id: int, label: str = "✅ Пройти верификацию"):
        super().__init__(timeout=None)
        self.add_item(VerifyDynamicButton(role_id, label))


@bot.tree.command(name="верификация-кнопка", description="Создать сообщение верификации через кнопку")
@app_commands.describe(роль="Роль", заголовок="Заголовок", описание="Текст", текст_кнопки="Надпись на кнопке")
@app_commands.checks.has_permissions(manage_roles=True)
async def verify_button_cmd(interaction: discord.Interaction, роль: discord.Role,
                             заголовок: str = "Верификация",
                             описание: str = "Нажмите кнопку ниже, чтобы получить доступ к серверу.",
                             текст_кнопки: str = "✅ Пройти верификацию"):
    embed = discord.Embed(title=f"🔐 {заголовок}", description=описание, color=ACCENT)
    embed.set_footer(text=f"Роль: {роль.name}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await interaction.response.send_message("✅ Создано!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=VerifyButtonView(роль.id, текст_кнопки))


# ═══════════════════════════════════════════════════════════════
# ТИКЕТЫ
# ═══════════════════════════════════════════════════════════════
class OrderModal(discord.ui.Modal, title="Создание заказа"):
    details = discord.ui.TextInput(label="Опишите ваш заказ", style=discord.TextStyle.paragraph,
                                   required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await _create_ticket(interaction, kind="order", details=self.details.value)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Обычный тикет", style=discord.ButtonStyle.primary, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = discord.utils.find(
            lambda c: c.name == f"тикет-{interaction.user.name.lower().replace(' ', '-')}",
            interaction.guild.text_channels)
        if existing:
            return await interaction.response.send_message(
                embed=make_embed(WARNING, "⚠️ Тикет уже открыт", f"У вас уже есть тикет: {existing.mention}"),
                ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await _create_ticket(interaction, kind="ticket")

    @discord.ui.button(label="🛒 Создать заказ", style=discord.ButtonStyle.success, custom_id="ticket_order")
    async def open_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = discord.utils.find(
            lambda c: c.name == f"заказ-{interaction.user.name.lower().replace(' ', '-')}",
            interaction.guild.text_channels)
        if existing:
            return await interaction.response.send_message(
                embed=make_embed(WARNING, "⚠️ Заказ уже открыт", f"У вас уже есть заказ: {existing.mention}"),
                ephemeral=True)
        await interaction.response.send_modal(OrderModal())


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels and \
                interaction.user.name.lower().replace(" ", "-") not in interaction.channel.name:
            return await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Нет прав", "Вы не можете закрыть этот тикет."), ephemeral=True)
        await interaction.response.send_message(
            embed=make_embed(WARNING, "⏳ Закрытие...", "Канал будет удалён через 5 секунд."))
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Тикет закрыт — {interaction.user}")
        except discord.Forbidden:
            pass


async def _create_ticket(interaction: discord.Interaction, kind: str, details: str = ""):
    guild = interaction.guild
    user  = interaction.user
    prefix = "тикет" if kind == "ticket" else "заказ"
    name   = f"{prefix}-{user.name.lower().replace(' ', '-')}"
    category = discord.utils.find(
        lambda c: any(k in c.name.lower() for k in ("тикет", "ticket", "поддержка", "support")),
        guild.categories)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    for role in guild.roles:
        if role.permissions.manage_channels:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    try:
        channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
    except discord.Forbidden:
        msg = embed=make_embed(DANGER, "❌ Ошибка", "У бота нет прав для создания каналов.")
        if not interaction.response.is_done():
            return await interaction.response.send_message(embed=msg, ephemeral=True)
        return await interaction.followup.send(embed=msg, ephemeral=True)

    if kind == "ticket":
        embed = discord.Embed(title="🎫 Тикет открыт",
                              description=f"Привет, {user.mention}!\n\nОпишите вашу проблему и ожидайте ответа.", color=ACCENT)
    else:
        embed = discord.Embed(title="🛒 Заказ создан",
                              description=f"Привет, {user.mention}!\n\n**Детали:**\n{details}\n\nМенеджер свяжется скоро.", color=SUCCESS)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 Создал", value=user.mention, inline=True)
    embed.add_field(name="📅 Открыт", value=discord.utils.format_dt(datetime.datetime.now(datetime.timezone.utc), "R"), inline=True)
    embed.set_footer(text=f"ID: {user.id}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await channel.send(content=user.mention, embed=embed, view=TicketControlView())

    reply = make_embed(SUCCESS, "✅ Создано!", f"Ваш канал: {channel.mention}")
    if not interaction.response.is_done():
        await interaction.response.send_message(embed=reply, ephemeral=True)
    else:
        await interaction.followup.send(embed=reply, ephemeral=True)


@bot.tree.command(name="тикет-панель", description="Создать панель тикетов")
@app_commands.describe(заголовок="Заголовок", описание="Текст")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_panel_cmd(interaction: discord.Interaction,
                            заголовок: str = "Поддержка",
                            описание: str = "Нажмите на кнопку ниже, чтобы открыть тикет или создать заказ."):
    embed = discord.Embed(title=f"🎫 {заголовок}", description=описание, color=ACCENT)
    embed.add_field(name="🎫 Обычный тикет", value="Вопросы, жалобы, апелляции", inline=True)
    embed.add_field(name="🛒 Создать заказ",  value="Оформление заказа", inline=True)
    embed.set_footer(text="Один пользователь — один открытый тикет")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await interaction.response.send_message("✅ Панель создана!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=TicketPanelView())


# ═══════════════════════════════════════════════════════════════
# РОЗЫГРЫШ
# ═══════════════════════════════════════════════════════════════
class GiveawayView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Участвовать", style=discord.ButtonStyle.primary, custom_id="giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = giveaways.get(self.message_id)
        if not data:
            return await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Розыгрыш завершён", "Этот розыгрыш уже закончился."), ephemeral=True)
        uid = interaction.user.id
        if uid in data["participants"]:
            data["participants"].discard(uid)
            text = f"Вы вышли из розыгрыша. Участников: **{len(data['participants'])}**"
            await interaction.response.send_message(embed=make_embed(WARNING, "🚪 Вышли", text), ephemeral=True)
        else:
            data["participants"].add(uid)
            text = f"Вы участвуете! Удачи! Всего: **{len(data['participants'])}**"
            await interaction.response.send_message(embed=make_embed(SUCCESS, "🎉 Вы участвуете!", text), ephemeral=True)
        try:
            msg = await interaction.channel.fetch_message(self.message_id)
            embed = msg.embeds[0]
            for i, f in enumerate(embed.fields):
                if "участник" in f.name.lower():
                    embed.set_field_at(i, name=f.name, value=str(len(data["participants"])), inline=f.inline)
                    break
            await msg.edit(embed=embed)
        except Exception:
            pass


async def _end_giveaway(message_id: int):
    data = giveaways.get(message_id)
    if not data:
        return
    guild   = bot.get_guild(data["guild_id"])
    channel = guild and guild.get_channel(data["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        giveaways.pop(message_id, None)
        return
    participants = list(data["participants"])
    wc = min(data["winners"], len(participants))
    embed = discord.Embed(title="🎊 Розыгрыш завершён!", color=GOLD)
    embed.add_field(name="🏆 Приз", value=data["prize"], inline=False)
    if not participants:
        embed.add_field(name="😔 Победители", value="Никто не участвовал.", inline=False)
    else:
        winners = random.sample(participants, wc)
        mentions = " ".join(f"<@{w}>" for w in winners)
        embed.add_field(name=f"🥇 Победител{'ь' if wc==1 else 'и'}", value=mentions, inline=False)
        embed.add_field(name="👥 Участников", value=str(len(participants)), inline=True)
        await channel.send(content=mentions,
                           embed=make_embed(GOLD, "🎊 Поздравляем!", f"Вы выиграли **{data['prize']}**! 🏆"))
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="🎉 Завершён", style=discord.ButtonStyle.secondary, disabled=True))
    await msg.edit(embed=embed, view=view)
    giveaways.pop(message_id, None)


@bot.tree.command(name="розыгрыш", description="Запустить розыгрыш")
@app_commands.describe(приз="Что разыгрывается", время="30s / 5m / 2h / 1d", победители="Количество победителей")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_cmd(interaction: discord.Interaction, приз: str, время: str, победители: int = 1):
    seconds = parse_duration(время)
    if not seconds or seconds < 10:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Неверный формат", "Примеры: `30s`, `5m`, `2h`, `1d`. Минимум 10 секунд."), ephemeral=True)
    ends_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    embed = discord.Embed(title="🎉 РОЗЫГРЫШ!", color=GOLD)
    embed.add_field(name="🏆 Приз", value=приз, inline=False)
    embed.add_field(name="⏰ Конец", value=discord.utils.format_dt(ends_at, "R"), inline=True)
    embed.add_field(name="🥇 Победителей", value=str(победители), inline=True)
    embed.add_field(name="👥 Участников", value="0", inline=True)
    embed.set_footer(text="Нажмите кнопку, чтобы участвовать")
    embed.timestamp = ends_at
    await interaction.response.send_message("✅ Розыгрыш запущен!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    view = GiveawayView(msg.id)
    await msg.edit(view=view)
    giveaways[msg.id] = {"prize": приз, "winners": победители, "participants": set(),
                          "channel_id": interaction.channel.id, "guild_id": interaction.guild.id, "task": None}
    async def _task():
        await asyncio.sleep(seconds)
        await _end_giveaway(msg.id)
    giveaways[msg.id]["task"] = asyncio.create_task(_task())


@bot.tree.command(name="розыгрыш-завершить", description="Досрочно завершить розыгрыш")
@app_commands.describe(id_сообщения="ID сообщения розыгрыша")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end_cmd(interaction: discord.Interaction, id_сообщения: str):
    try:
        mid = int(id_сообщения)
    except ValueError:
        return await interaction.response.send_message(embed=make_embed(DANGER, "❌ Ошибка", "Неверный ID."), ephemeral=True)
    if mid not in giveaways:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Не найден", "Розыгрыш с таким ID не найден."), ephemeral=True)
    data = giveaways[mid]
    if data["task"]:
        data["task"].cancel()
    await _end_giveaway(mid)
    await interaction.response.send_message(embed=make_embed(SUCCESS, "✅ Завершено", "Розыгрыш завершён досрочно."), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# КЛИКЕР
# ═══════════════════════════════════════════════════════════════
class ClickerView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="👆 Клик! (0)", style=discord.ButtonStyle.success, custom_id="clicker_click")
    async def click(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = clickers.get(self.message_id)
        if not data:
            return await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Игра завершена", "Соревнование уже закончилось."), ephemeral=True)
        uid = interaction.user.id
        data["scores"][uid] = data["scores"].get(uid, 0) + 1
        total = sum(data["scores"].values())
        button.label = f"👆 Клик! ({total})"
        await interaction.response.edit_message(view=self)


async def _end_clicker(message_id: int):
    data = clickers.get(message_id)
    if not data:
        return
    guild   = bot.get_guild(data["guild_id"])
    channel = guild and guild.get_channel(data["channel_id"])
    if not channel:
        return
    scores = data["scores"]
    embed  = discord.Embed(title="🏁 Соревнование завершено!", color=GOLD)
    if not scores:
        embed.description = "Никто не нажал ни разу 😢"
    else:
        sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winner_id, winner_clicks = sorted_s[0]
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i+1}.`'} <@{uid}> — **{cnt}** кликов"
                 for i, (uid, cnt) in enumerate(sorted_s[:10])]
        embed.description = "\n".join(lines)
        embed.add_field(name="🏆 Победитель", value=f"<@{winner_id}> с **{winner_clicks}** кликами!", inline=False)
        embed.add_field(name="👆 Всего", value=str(sum(scores.values())), inline=True)
        embed.add_field(name="👥 Участников", value=str(len(scores)), inline=True)
        await channel.send(content=f"<@{winner_id}>",
                           embed=make_embed(GOLD, "🏆 Победитель!", f"<@{winner_id}> набрал **{winner_clicks}** кликов! 🎉"))
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=f"👆 Завершено ({sum(scores.values())} кликов)",
                                    style=discord.ButtonStyle.secondary, disabled=True))
    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=embed, view=view)
    except Exception:
        await channel.send(embed=embed)
    clickers.pop(message_id, None)


@bot.tree.command(name="кликер", description="Кто больше кликнет за время")
@app_commands.describe(время="Длительность: 30s / 2m / 1h")
@app_commands.checks.has_permissions(manage_guild=True)
async def clicker_cmd(interaction: discord.Interaction, время: str = "60s"):
    seconds = parse_duration(время)
    if not seconds or seconds < 5 or seconds > 3600:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Неверный формат", "Примеры: `30s`, `2m`, `1h`. От 5с до 1ч."), ephemeral=True)
    ends_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    embed = discord.Embed(title="👆 СОРЕВНОВАНИЕ ПО КЛИКАМ!",
                          description=f"Жми кнопку как можно чаще!\nВремя: **{fmt_duration(seconds)}**\n\n⏰ Конец: {discord.utils.format_dt(ends_at, 'R')}",
                          color=ACCENT)
    embed.set_footer(text="Нажимайте кнопку — считаются все клики!")
    embed.timestamp = ends_at
    await interaction.response.send_message("✅ Соревнование запущено!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    view = ClickerView(msg.id)
    await msg.edit(view=view)
    clickers[msg.id] = {"scores": {}, "channel_id": interaction.channel.id, "guild_id": interaction.guild.id, "task": None}
    async def _task():
        await asyncio.sleep(seconds)
        await _end_clicker(msg.id)
    clickers[msg.id]["task"] = asyncio.create_task(_task())


# ═══════════════════════════════════════════════════════════════
# МОДЕРАЦИЯ
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="бан", description="Заблокировать пользователя на сервере")
@app_commands.describe(участник="Пользователь", причина="Причина")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя заблокировать пользователя с равной или более высокой ролью."), ephemeral=True)
    try:
        await участник.ban(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            DANGER, "🔨 Пользователь заблокирован",
            fields=[("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("📋 Причина", причина, False)],
            thumbnail=участник.display_avatar.url))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."), ephemeral=True)


@bot.tree.command(name="кик", description="Выгнать пользователя с сервера")
@app_commands.describe(участник="Пользователь", причина="Причина")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя выгнать пользователя с равной или более высокой ролью."), ephemeral=True)
    try:
        await участник.kick(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            WARNING, "👢 Пользователь выгнан",
            fields=[("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("📋 Причина", причина, False)],
            thumbnail=участник.display_avatar.url))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав."), ephemeral=True)


@bot.tree.command(name="мут", description="Заглушить пользователя")
@app_commands.describe(участник="Пользователь", минуты="Длительность в минутах", причина="Причина")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute_cmd(interaction: discord.Interaction, участник: discord.Member,
                   минуты: int = 10, причина: str = "Причина не указана"):
    if минуты < 1 or минуты > 40320:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Укажите от **1** до **40 320** минут."), ephemeral=True)
    if участник.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя замутить пользователя с равной или более высокой ролью."), ephemeral=True)
    try:
        until = discord.utils.utcnow() + datetime.timedelta(minutes=минуты)
        await участник.timeout(until, reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            INFO, "🔇 Пользователь заглушён",
            fields=[("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("⏱ Длительность", f"{минуты} мин.", True),
                    ("📅 До", discord.utils.format_dt(until, "R"), True),
                    ("📋 Причина", причина, False)],
            thumbnail=участник.display_avatar.url))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав."), ephemeral=True)


@bot.tree.command(name="снятие-мута", description="Снять мут с пользователя")
@app_commands.describe(участник="Пользователь")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute_cmd(interaction: discord.Interaction, участник: discord.Member):
    if not участник.is_timed_out():
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "У пользователя нет активного мута."), ephemeral=True)
    try:
        await участник.timeout(None)
        await interaction.response.send_message(embed=make_embed(
            SUCCESS, "🔊 Мут снят",
            fields=[("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True)],
            thumbnail=участник.display_avatar.url))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав."), ephemeral=True)


@bot.tree.command(name="разбан", description="Разбанить пользователя по ID")
@app_commands.describe(id_пользователя="ID пользователя")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, id_пользователя: str):
    try:
        user = await bot.fetch_user(int(id_пользователя))
    except (ValueError, discord.NotFound):
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Пользователь с таким ID не найден."), ephemeral=True)
    try:
        await interaction.guild.unban(user)
        await interaction.response.send_message(embed=make_embed(
            SUCCESS, "✅ Пользователь разбанен",
            fields=[("👤 Пользователь", f"`{user}` (ID: `{user.id}`)", True),
                    ("👮 Модератор", interaction.user.mention, True)],
            thumbnail=user.display_avatar.url))
    except discord.NotFound:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Этот пользователь не в бан-листе."), ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав."), ephemeral=True)


@bot.tree.command(name="сказать", description="Отправить сообщение от имени бота")
@app_commands.describe(текст="Текст сообщения", канал="Канал (по умолчанию — текущий)")
@app_commands.checks.has_permissions(manage_messages=True)
async def say_cmd(interaction: discord.Interaction, текст: str, канал: discord.TextChannel = None):
    target = канал or interaction.channel
    await target.send(текст)
    await interaction.response.send_message(
        embed=make_embed(SUCCESS, "✅ Отправлено", f"Сообщение отправлено в {target.mention}"), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИК ОШИБОК
# ═══════════════════════════════════════════════════════════════
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "У вас недостаточно прав для этой команды."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = f"Боту не хватает прав: `{', '.join(error.missing_permissions)}`"
    else:
        msg = str(error)
    embed = make_embed(DANGER, "❌ Ошибка", msg)
    if not interaction.response.is_done():
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# ВЕБ-СЕРВЕР (для UptimeRobot)
# ═══════════════════════════════════════════════════════════════
def run_webserver():
    port = int(os.environ.get("PORT", 8080))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.listen(5)
    print(f"HTTP сервер запущен на порту {port}")
    while True:
        try:
            conn, _ = sock.accept()
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nOK")
            conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════
token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN не задан!")

if os.environ.get("RENDER"):
    threading.Thread(target=run_webserver, daemon=True).start()

bot.run(token)
