import asyncio
import datetime
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
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Цвета ───────────────────────────────────────────────────
ACCENT  = discord.Color.from_rgb(88,  101, 242)
SUCCESS = discord.Color.from_rgb(87,  242, 135)
DANGER  = discord.Color.from_rgb(237,  66,  69)
WARNING = discord.Color.from_rgb(254, 231,  92)
INFO    = discord.Color.from_rgb(0,   176, 240)
GOLD    = discord.Color.from_rgb(255, 215,   0)

# ─── Состояние в памяти ──────────────────────────────────────
# { message_id: {prize, end_time, winners, participants: set, channel_id, guild_id, task} }
giveaways: dict[int, dict] = {}
# { message_id: {end_time, scores: {uid: int}, channel_id, guild_id, task} }
clickers:  dict[int, dict] = {}


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def make_embed(
    color: discord.Color,
    title: str,
    description: str = "",
    fields: list[tuple[str, str, bool]] | None = None,
    footer: str | None = None,
    thumbnail: str | None = None,
) -> discord.Embed:
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
    """Парсит '30s', '5m', '2h', '1d' → секунды. None если не распознано."""
    m = re.fullmatch(r"(\d+)([smhd])", text.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м {seconds % 60}с"
    h = seconds // 3600
    return f"{h}ч {(seconds % 3600) // 60}м"


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
    ch = discord.utils.find(
        lambda c: any(k in c.name.lower() for k in ("привет", "general", "welcome", "основной", "чат")),
        guild.text_channels,
    ) or guild.system_channel
    if not ch:
        return
    embed = discord.Embed(
        title="👋 Добро пожаловать!",
        description=(
            f"Привет, {member.mention}! Рады видеть тебя на **{guild.name}**.\n"
            "Ознакомься с правилами и хорошо проведи время! 🎉"
        ),
        color=ACCENT,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Участник", value=member.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
    embed.add_field(name="📅 Создан", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.set_footer(text=f"Участник #{guild.member_count}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await ch.send(embed=embed)


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
    details = discord.ui.TextInput(
        label="Опишите ваш заказ",
        placeholder="Что именно вы хотите заказать?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await _create_ticket(interaction, kind="order", details=self.details.value)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Обычный тикет", style=discord.ButtonStyle.primary, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Проверяем, нет ли уже открытого тикета
        existing = discord.utils.find(
            lambda c: c.name == f"тикет-{interaction.user.name.lower().replace(' ', '-')}",
            interaction.guild.text_channels
        )
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
            interaction.guild.text_channels
        )
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
    user = interaction.user
    prefix = "тикет" if kind == "ticket" else "заказ"
    name = f"{prefix}-{user.name.lower().replace(' ', '-')}"

    # Ищем категорию тикетов
    category = discord.utils.find(
        lambda c: any(k in c.name.lower() for k in ("тикет", "ticket", "поддержка", "support")),
        guild.categories,
    )

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    # Добавляем права для ролей с manage_channels
    for role in guild.roles:
        if role.permissions.manage_channels:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
    except discord.Forbidden:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Ошибка", "У бота нет прав для создания каналов."), ephemeral=True)
        else:
            await interaction.followup.send(
                embed=make_embed(DANGER, "❌ Ошибка", "У бота нет прав для создания каналов."), ephemeral=True)
        return

    if kind == "ticket":
        embed = discord.Embed(
            title="🎫 Тикет открыт",
            description=(
                f"Привет, {user.mention}! Ваш тикет создан.\n\n"
                "Опишите вашу проблему и ожидайте ответа от администрации.\n"
                "Когда вопрос решён — нажмите кнопку ниже."
            ),
            color=ACCENT,
        )
    else:
        embed = discord.Embed(
            title="🛒 Заказ создан",
            description=(
                f"Привет, {user.mention}! Ваш заказ принят.\n\n"
                f"**Детали заказа:**\n{details}\n\n"
                "Менеджер свяжется с вами в ближайшее время."
            ),
            color=SUCCESS,
        )

    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 Создал", value=user.mention, inline=True)
    embed.add_field(name="📅 Открыт", value=discord.utils.format_dt(datetime.datetime.now(datetime.timezone.utc), "R"), inline=True)
    embed.set_footer(text=f"ID: {user.id}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    await channel.send(content=user.mention, embed=embed, view=TicketControlView())

    if not interaction.response.is_done():
        await interaction.response.send_message(
            embed=make_embed(SUCCESS, "✅ Создано!", f"Ваш канал: {channel.mention}"), ephemeral=True)
    else:
        await interaction.followup.send(
            embed=make_embed(SUCCESS, "✅ Создано!", f"Ваш канал: {channel.mention}"), ephemeral=True)


@bot.tree.command(name="тикет-панель", description="Создать панель тикетов")
@app_commands.describe(заголовок="Заголовок панели", описание="Текст панели")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_panel_cmd(interaction: discord.Interaction,
                            заголовок: str = "Поддержка",
                            описание: str = "Нажмите на кнопку ниже, чтобы открыть тикет или создать заказ."):
    embed = discord.Embed(title=f"🎫 {заголовок}", description=описание, color=ACCENT)
    embed.add_field(name="🎫 Обычный тикет", value="Вопросы, жалобы, апелляции", inline=True)
    embed.add_field(name="🛒 Создать заказ", value="Оформление заказа у администрации", inline=True)
    embed.set_footer(text="Каждый пользователь может иметь только один открытый тикет")
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
                embed=make_embed(DANGER, "❌ Розыгрыш не найден", "Этот розыгрыш уже завершён."), ephemeral=True)
        uid = interaction.user.id
        if uid in data["participants"]:
            data["participants"].discard(uid)
            await interaction.response.send_message(
                embed=make_embed(WARNING, "🚪 Вы вышли", "Вы покинули розыгрыш."), ephemeral=True)
        else:
            data["participants"].add(uid)
            await interaction.response.send_message(
                embed=make_embed(SUCCESS, "🎉 Вы участвуете!", f"Удачи! Всего участников: **{len(data['participants'])}**"), ephemeral=True)

        # Обновляем счётчик на кнопке
        try:
            msg = await interaction.channel.fetch_message(self.message_id)
            embed = msg.embeds[0]
            # Обновляем поле с участниками
            for i, field in enumerate(embed.fields):
                if "участник" in field.name.lower():
                    embed.set_field_at(i, name=field.name, value=str(len(data["participants"])), inline=field.inline)
                    break
            await msg.edit(embed=embed)
        except Exception:
            pass


async def _end_giveaway(message_id: int):
    data = giveaways.get(message_id)
    if not data:
        return
    guild = bot.get_guild(data["guild_id"])
    channel = guild and guild.get_channel(data["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        giveaways.pop(message_id, None)
        return

    participants = list(data["participants"])
    winners_count = min(data["winners"], len(participants))

    embed = discord.Embed(title="🎊 Розыгрыш завершён!", color=GOLD)
    embed.add_field(name="🏆 Приз", value=data["prize"], inline=False)

    if not participants:
        embed.add_field(name="😔 Победители", value="Никто не участвовал.", inline=False)
        embed.set_footer(text="Нет победителей")
    else:
        winners = random.sample(participants, winners_count)
        winner_mentions = " ".join(f"<@{w}>" for w in winners)
        embed.add_field(name=f"🥇 Победител{'ь' if winners_count == 1 else 'и'}", value=winner_mentions, inline=False)
        embed.add_field(name="👥 Участников", value=str(len(participants)), inline=True)
        embed.set_footer(text="Поздравляем победителей!")
        await channel.send(
            content=winner_mentions,
            embed=make_embed(GOLD, "🎊 Поздравляем!", f"Вы выиграли **{data['prize']}**! 🏆"))

    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Деактивируем кнопку
    view = discord.ui.View()
    btn = discord.ui.Button(label="🎉 Розыгрыш завершён", style=discord.ButtonStyle.secondary, disabled=True)
    view.add_item(btn)
    await msg.edit(embed=embed, view=view)
    giveaways.pop(message_id, None)


@bot.tree.command(name="розыгрыш", description="Запустить розыгрыш")
@app_commands.describe(
    приз="Что разыгрывается",
    время="Длительность: 30s / 5m / 2h / 1d",
    победители="Количество победителей",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_cmd(interaction: discord.Interaction,
                        приз: str, время: str, победители: int = 1):
    seconds = parse_duration(время)
    if not seconds or seconds < 10:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Неверный формат", "Примеры: `30s`, `5m`, `2h`, `1d`. Минимум 10 секунд."),
            ephemeral=True)
    if победители < 1:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Минимум 1 победитель."), ephemeral=True)

    ends_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    embed = discord.Embed(title="🎉 РОЗЫГРЫШ!", color=GOLD)
    embed.add_field(name="🏆 Приз", value=приз, inline=False)
    embed.add_field(name="⏰ Конец", value=discord.utils.format_dt(ends_at, "R"), inline=True)
    embed.add_field(name=f"🥇 Победителей", value=str(победители), inline=True)
    embed.add_field(name="👥 Участников", value="0", inline=True)
    embed.set_footer(text="Нажмите кнопку, чтобы участвовать")
    embed.timestamp = ends_at

    await interaction.response.send_message("✅ Розыгрыш запущен!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)

    view = GiveawayView(msg.id)
    await msg.edit(view=view)

    giveaways[msg.id] = {
        "prize": приз,
        "winners": победители,
        "participants": set(),
        "channel_id": interaction.channel.id,
        "guild_id": interaction.guild.id,
        "task": None,
    }

    async def _task():
        await asyncio.sleep(seconds)
        await _end_giveaway(msg.id)

    task = asyncio.create_task(_task())
    giveaways[msg.id]["task"] = task


@bot.tree.command(name="розыгрыш-завершить", description="Досрочно завершить розыгрыш")
@app_commands.describe(id_сообщения="ID сообщения розыгрыша")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end_cmd(interaction: discord.Interaction, id_сообщения: str):
    try:
        mid = int(id_сообщения)
    except ValueError:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Неверный ID."), ephemeral=True)
    if mid not in giveaways:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Не найден", "Розыгрыш с таким ID не найден."), ephemeral=True)
    data = giveaways[mid]
    if data["task"]:
        data["task"].cancel()
    await _end_giveaway(mid)
    await interaction.response.send_message(
        embed=make_embed(SUCCESS, "✅ Завершено", "Розыгрыш завершён досрочно."), ephemeral=True)


@bot.tree.command(name="розыгрыш-перезапустить", description="Выбрать нового победителя")
@app_commands.describe(id_сообщения="ID сообщения завершённого розыгрыша")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll_cmd(interaction: discord.Interaction, id_сообщения: str):
    try:
        msg = await interaction.channel.fetch_message(int(id_сообщения))
    except Exception:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Сообщение не найдено в этом канале."), ephemeral=True)
    # Получаем участников из реакций/упоминаний невозможно после сброса, поэтому просто уведомляем
    await interaction.response.send_message(
        embed=make_embed(WARNING, "⚠️ Перезапуск", "Используйте `/розыгрыш` чтобы запустить новый розыгрыш."),
        ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# КЛИКЕР — кто больше кликнет за время
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
                embed=make_embed(DANGER, "❌ Игра завершена", "Это соревнование уже закончилось."), ephemeral=True)

        uid = interaction.user.id
        data["scores"][uid] = data["scores"].get(uid, 0) + 1
        total = sum(data["scores"].values())

        # Обновляем надпись на кнопке
        button.label = f"👆 Клик! ({total})"
        await interaction.response.edit_message(view=self)


async def _end_clicker(message_id: int):
    data = clickers.get(message_id)
    if not data:
        return
    guild = bot.get_guild(data["guild_id"])
    channel = guild and guild.get_channel(data["channel_id"])
    if not channel:
        return

    scores = data["scores"]
    embed = discord.Embed(title="🏁 Соревнование завершено!", color=GOLD)

    if not scores:
        embed.description = "Никто не нажал ни разу 😢"
    else:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winner_id, winner_clicks = sorted_scores[0]
        total = sum(scores.values())

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, count) in enumerate(sorted_scores[:10]):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{medal} <@{uid}> — **{count}** кликов")

        embed.description = "\n".join(lines)
        embed.add_field(name="🏆 Победитель", value=f"<@{winner_id}> с **{winner_clicks}** кликами!", inline=False)
        embed.add_field(name="👆 Всего кликов", value=str(total), inline=True)
        embed.add_field(name="👥 Участников", value=str(len(scores)), inline=True)
        embed.set_footer(text="Поздравляем победителя!")

        await channel.send(
            content=f"<@{winner_id}>",
            embed=make_embed(GOLD, "🏆 Победитель!", f"<@{winner_id}> набрал **{winner_clicks}** кликов! 🎉"))

    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label=f"👆 Игра завершена ({sum(scores.values())} кликов)",
        style=discord.ButtonStyle.secondary, disabled=True))

    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=embed, view=view)
    except Exception:
        await channel.send(embed=embed)

    clickers.pop(message_id, None)


@bot.tree.command(name="кликер", description="Кто больше кликнет за время — соревнование по кликам")
@app_commands.describe(время="Длительность: 30s / 2m / 1h")
@app_commands.checks.has_permissions(manage_guild=True)
async def clicker_cmd(interaction: discord.Interaction, время: str = "60s"):
    seconds = parse_duration(время)
    if not seconds or seconds < 5 or seconds > 3600:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Неверный формат", "Примеры: `30s`, `2m`, `1h`. От 5 секунд до 1 часа."),
            ephemeral=True)

    ends_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    embed = discord.Embed(
        title="👆 СОРЕВНОВАНИЕ ПО КЛИКАМ!",
        description=(
            f"Жми кнопку как можно чаще!\n"
            f"У вас **{fmt_duration(seconds)}**.\n\n"
            f"⏰ Конец: {discord.utils.format_dt(ends_at, 'R')}"
        ),
        color=ACCENT,
    )
    embed.set_footer(text="Нажимайте кнопку — считаются все клики!")
    embed.timestamp = ends_at

    await interaction.response.send_message("✅ Соревнование запущено!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)

    view = ClickerView(msg.id)
    await msg.edit(view=view)

    clickers[msg.id] = {
        "scores": {},
        "channel_id": interaction.channel.id,
        "guild_id": interaction.guild.id,
        "task": None,
    }

    async def _task():
        await asyncio.sleep(seconds)
        await _end_clicker(msg.id)

    task = asyncio.create_task(_task())
    clickers[msg.id]["task"] = task


# ═══════════════════════════════════════════════════════════════
# МОДЕРАЦИЯ
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="бан", description="Заблокировать пользователя на сервере")
@app_commands.describe(участник="Пользователь", причина="Причина")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя заблокировать пользователя с равной или более высокой ролью."),
            ephemeral=True)
    try:
        await участник.ban(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            DANGER, "🔨 Пользователь заблокирован",
            fields=[
                ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                ("👮 Модератор", interaction.user.mention, True),
                ("📋 Причина", причина, False),
            ],
            thumbnail=участник.display_avatar.url,
        ))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."), ephemeral=True)


@bot.tree.command(name="кик", description="Выгнать пользователя с сервера")
@app_commands.describe(участник="Пользователь", причина="Причина")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя выгнать пользователя с равной или более высокой ролью."),
            ephemeral=True)
    try:
        await участник.kick(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            WARNING, "👢 Пользователь выгнан",
            fields=[
                ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                ("👮 Модератор", interaction.user.mention, True),
                ("📋 Причина", причина, False),
            ],
            thumbnail=участник.display_avatar.url,
        ))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."), ephemeral=True)


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
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя замутить пользователя с равной или более высокой ролью."),
            ephemeral=True)
    try:
        until = discord.utils.utcnow() + datetime.timedelta(minutes=минуты)
        await участник.timeout(until, reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(embed=make_embed(
            INFO, "🔇 Пользователь заглушён",
            fields=[
                ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                ("👮 Модератор", interaction.user.mention, True),
                ("⏱ Длительность", f"{минуты} мин.", True),
                ("📅 До", discord.utils.format_dt(until, "R"), True),
                ("📋 Причина", причина, False),
            ],
            thumbnail=участник.display_avatar.url,
        ))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав."), ephemeral=True)


@bot.tree.command(name="снятие-мута", description="Снять мут с пользователя")
@app_commands.describe(участник="Пользователь")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute_cmd(interaction: discord.Interaction, участник: discord.Member):
    if not участник.is_timed_out():
        return await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "У этого пользователя нет активного мута."), ephemeral=True)
    try:
        await участник.timeout(None)
        await interaction.response.send_message(embed=make_embed(
            SUCCESS, "🔊 Мут снят",
            fields=[
                ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                ("👮 Модератор", interaction.user.mention, True),
            ],
            thumbnail=участник.display_avatar.url,
        ))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав для снятия мута."), ephemeral=True)


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
            fields=[
                ("👤 Пользователь", f"`{user}` (ID: `{user.id}`)", True),
                ("👮 Модератор", interaction.user.mention, True),
            ],
            thumbnail=user.display_avatar.url,
        ))
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
