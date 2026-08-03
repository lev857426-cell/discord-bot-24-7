import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import re
import socket
import threading

# ═══════════════════════════════════════════════════════════════
# ИНТЕНТЫ
# ═══════════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ═══════════════════════════════════════════════════════════════
# БОТ
# ═══════════════════════════════════════════════════════════════
bot = commands.Bot(command_prefix="!", intents=intents)

ACCENT = discord.Color.from_rgb(88, 101, 242)   # фиолетовый — основной
SUCCESS = discord.Color.from_rgb(87, 242, 135)  # зелёный
DANGER  = discord.Color.from_rgb(237, 66, 69)   # красный
WARNING = discord.Color.from_rgb(254, 231, 92)  # жёлтый
INFO    = discord.Color.from_rgb(0, 176, 240)   # голубой


def make_embed(
    color: discord.Color,
    title: str,
    description: str = "",
    fields: list[tuple[str, str, bool]] | None = None,
    footer: str | None = None,
    thumbnail: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed


# ═══════════════════════════════════════════════════════════════
# СОБЫТИЯ
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    bot.add_dynamic_items(VerifyDynamicButton)
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="QRXTeam")
    )
    await bot.tree.sync()
    print(f"✅ Бот {bot.user} запущен!")


@bot.event
async def on_member_join(member: discord.Member):
    """Приветственное сообщение при входе на сервер."""
    guild = member.guild

    # Ищем канал с «привет», «general», «welcome» или «основной» в названии
    welcome_channel = discord.utils.find(
        lambda c: any(k in c.name.lower() for k in ("привет", "general", "welcome", "основной", "чат")),
        guild.text_channels,
    )
    if not welcome_channel:
        welcome_channel = guild.system_channel
    if not welcome_channel:
        return

    embed = discord.Embed(
        title="👋 Добро пожаловать!",
        description=(
            f"Привет, {member.mention}! Рады видеть тебя на сервере **{guild.name}**.\n\n"
            "Ознакомься с правилами и хорошо проведи время! 🎉"
        ),
        color=ACCENT,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Участник", value=member.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
    embed.add_field(
        name="📅 Аккаунт создан",
        value=discord.utils.format_dt(member.created_at, style="R"),
        inline=True,
    )
    embed.set_footer(text=f"Участник #{guild.member_count}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

    await welcome_channel.send(embed=embed)


# ═══════════════════════════════════════════════════════════════
# ВЕРИФИКАЦИЯ (DynamicItem — работает после перезапуска)
# ═══════════════════════════════════════════════════════════════
class VerifyDynamicButton(discord.ui.DynamicItem[discord.ui.Button], template=r"verify_(?P<role_id>\d+)"):
    def __init__(self, role_id: int, label: str = "✅ Пройти верификацию"):
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.success,
                custom_id=f"verify_{role_id}",
            )
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match):
        return cls(int(match.group("role_id")))

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Ошибка", "Роль не найдена. Обратитесь к администратору."),
                ephemeral=True,
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=make_embed(INFO, "ℹ️ Уже верифицированы", f"У вас уже есть роль **{role.name}**."),
                ephemeral=True,
            )
            return
        try:
            await interaction.user.add_roles(role, reason="Верификация по кнопке")
            await interaction.response.send_message(
                embed=make_embed(
                    SUCCESS, "✅ Верификация пройдена!",
                    f"Вы получили роль **{role.name}**!",
                    thumbnail=interaction.user.display_avatar.url,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=make_embed(DANGER, "❌ Ошибка", "У бота нет прав для выдачи этой роли."),
                ephemeral=True,
            )


class VerifyButtonView(discord.ui.View):
    def __init__(self, role_id: int, label: str = "✅ Пройти верификацию"):
        super().__init__(timeout=None)
        self.add_item(VerifyDynamicButton(role_id, label))


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: ВЕРИФИКАЦИЯ-КНОПКА
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="верификация-кнопка", description="Создать сообщение верификации через кнопку")
@app_commands.describe(
    роль="Роль, которую получит пользователь",
    заголовок="Заголовок сообщения",
    описание="Текст сообщения",
    текст_кнопки="Надпись на кнопке",
)
@app_commands.checks.has_permissions(manage_roles=True)
async def verify_button_cmd(
    interaction: discord.Interaction,
    роль: discord.Role,
    заголовок: str = "Верификация",
    описание: str = "Нажмите кнопку ниже, чтобы получить доступ к серверу.",
    текст_кнопки: str = "✅ Пройти верификацию",
):
    embed = discord.Embed(title=f"🔐 {заголовок}", description=описание, color=ACCENT)
    embed.set_footer(text=f"Роль: {роль.name}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await interaction.response.send_message("✅ Сообщение создано!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=VerifyButtonView(роль.id, текст_кнопки))


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: БАН
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="бан", description="Заблокировать пользователя на сервере")
@app_commands.describe(участник="Пользователь", причина="Причина бана")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя заблокировать пользователя с равной или более высокой ролью."),
            ephemeral=True,
        )
        return
    try:
        await участник.ban(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(
            embed=make_embed(
                DANGER, "🔨 Пользователь заблокирован",
                fields=[
                    ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("📋 Причина", причина, False),
                ],
                thumbnail=участник.display_avatar.url,
            )
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: КИК
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="кик", description="Выгнать пользователя с сервера")
@app_commands.describe(участник="Пользователь", причина="Причина кика")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя выгнать пользователя с равной или более высокой ролью."),
            ephemeral=True,
        )
        return
    try:
        await участник.kick(reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(
            embed=make_embed(
                WARNING, "👢 Пользователь выгнан",
                fields=[
                    ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("📋 Причина", причина, False),
                ],
                thumbnail=участник.display_avatar.url,
            )
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: МУТ
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="мут", description="Заглушить пользователя (таймаут)")
@app_commands.describe(участник="Пользователь", минуты="Длительность в минутах", причина="Причина")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute_cmd(
    interaction: discord.Interaction,
    участник: discord.Member,
    минуты: int = 10,
    причина: str = "Причина не указана",
):
    if минуты < 1 or минуты > 40320:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Укажите от **1** до **40 320** минут (28 дней)."),
            ephemeral=True,
        )
        return
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Нельзя замутить пользователя с равной или более высокой ролью."),
            ephemeral=True,
        )
        return
    try:
        until = discord.utils.utcnow() + datetime.timedelta(minutes=минуты)
        await участник.timeout(until, reason=f"{причина} | Модератор: {interaction.user}")
        await interaction.response.send_message(
            embed=make_embed(
                INFO, "🔇 Пользователь заглушён",
                fields=[
                    ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                    ("⏱ Длительность", f"{минуты} мин.", True),
                    ("📅 До", discord.utils.format_dt(until, style="R"), True),
                    ("📋 Причина", причина, False),
                ],
                thumbnail=участник.display_avatar.url,
            )
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав. Проверьте иерархию ролей бота."),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: СНЯТИЕ МУТА
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="снятие-мута", description="Снять мут с пользователя")
@app_commands.describe(участник="Пользователь")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute_cmd(interaction: discord.Interaction, участник: discord.Member):
    if not участник.is_timed_out():
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "У этого пользователя нет активного мута."),
            ephemeral=True,
        )
        return
    try:
        await участник.timeout(None)
        await interaction.response.send_message(
            embed=make_embed(
                SUCCESS, "🔊 Мут снят",
                fields=[
                    ("👤 Пользователь", f"{участник.mention} (`{участник}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                ],
                thumbnail=участник.display_avatar.url,
            )
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав для снятия мута."),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: РАЗБАН
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="разбан", description="Разбанить пользователя по ID")
@app_commands.describe(id_пользователя="ID пользователя")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, id_пользователя: str):
    try:
        user = await bot.fetch_user(int(id_пользователя))
    except (ValueError, discord.NotFound):
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Пользователь с таким ID не найден."),
            ephemeral=True,
        )
        return
    try:
        await interaction.guild.unban(user)
        await interaction.response.send_message(
            embed=make_embed(
                SUCCESS, "✅ Пользователь разбанен",
                fields=[
                    ("👤 Пользователь", f"`{user}` (ID: `{user.id}`)", True),
                    ("👮 Модератор", interaction.user.mention, True),
                ],
                thumbnail=user.display_avatar.url,
            )
        )
    except discord.NotFound:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Этот пользователь не в бан-листе."),
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=make_embed(DANGER, "❌ Ошибка", "Недостаточно прав для разбана."),
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════
# КОМАНДА: СКАЗАТЬ
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="сказать", description="Отправить сообщение от имени бота")
@app_commands.describe(текст="Текст сообщения", канал="Канал (по умолчанию — текущий)")
@app_commands.checks.has_permissions(manage_messages=True)
async def say_cmd(interaction: discord.Interaction, текст: str, канал: discord.TextChannel = None):
    target = канал or interaction.channel
    await target.send(текст)
    await interaction.response.send_message(
        embed=make_embed(SUCCESS, "✅ Отправлено", f"Сообщение отправлено в {target.mention}"),
        ephemeral=True,
    )


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
