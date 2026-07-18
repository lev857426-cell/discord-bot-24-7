import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
import threading
import socket

# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════
OPG_FACTIONS = ["Арзамасская ОПГ", "Батыревская", "Лыткаринская"]
GOV_FACTIONS = ["Правительство", "ФСБ", "Министерство внутренних дел", "ГИБДД", "Городская больница", "СМИ"]
COOLDOWN_HOURS = 24
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


# ═══════════════════════════════════════════════════════════════
# ИНТЕНТЫ
# ═══════════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.members = True  # Server Members Intent должен быть включён в Dev Portal


# ═══════════════════════════════════════════════════════════════
# БОТ
# ═══════════════════════════════════════════════════════════════
bot = commands.Bot(command_prefix="!", intents=intents)


# ═══════════════════════════════════════════════════════════════
# ХРАНИЛИЩЕ ДАННЫХ (JSON)
# ═══════════════════════════════════════════════════════════════
def load_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cooldowns": {}, "config": {}}

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_config(guild_id: int) -> dict:
    data = load_data()
    return data.get("config", {}).get(str(guild_id), {})

def set_config(guild_id: int, key: str, value):
    data = load_data()
    gid = str(guild_id)
    if "config" not in data:
        data["config"] = {}
    if gid not in data["config"]:
        data["config"][gid] = {}
    data["config"][gid][key] = value
    save_data(data)


# ═══════════════════════════════════════════════════════════════
# СОСТОЯНИЕ В ПАМЯТИ
# ═══════════════════════════════════════════════════════════════
# Предупреждения: { guild_id: { user_id: [причины] } }
warnings: dict[int, dict[int, list[str]]] = {}

# Верификация по реакции: { message_id: {"role_id", "emoji", "guild_id"} }
reaction_verifications: dict[int, dict] = {}

# Ожидание скриншота: { user_id: {category, nickname, rank, faction, guild_id, review_channel_id, user_mention, user_tag} }
pending_screenshot: dict[int, dict] = {}


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def make_embed(color: discord.Color, title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return embed

def check_cooldown(guild_id: int, user_id: int) -> float | None:
    """Возвращает оставшиеся секунды КД или None, если КД нет."""
    data = load_data()
    last = data.get("cooldowns", {}).get(str(guild_id), {}).get(str(user_id))
    if last is not None:
        elapsed = datetime.datetime.now().timestamp() - last
        remaining = COOLDOWN_HOURS * 3600 - elapsed
        if remaining > 0:
            return remaining
    return None

def set_cooldown(guild_id: int, user_id: int):
    data = load_data()
    gid, uid = str(guild_id), str(user_id)
    if "cooldowns" not in data:
        data["cooldowns"] = {}
    if gid not in data["cooldowns"]:
        data["cooldowns"][gid] = {}
    data["cooldowns"][gid][uid] = datetime.datetime.now().timestamp()
    save_data(data)

def reset_cooldown(guild_id: int, user_id: int):
    data = load_data()
    gid, uid = str(guild_id), str(user_id)
    if gid in data.get("cooldowns", {}):
        data["cooldowns"][gid].pop(uid, None)
    save_data(data)


# ═══════════════════════════════════════════════════════════════
# СОБЫТИЯ
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Бот {bot.user} запущен!")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Только ЛС
    if not isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)
        return

    user_id = message.author.id

    # Отмена заявки
    if message.content.strip().lower() in ["отмена", "cancel", "отменить"]:
        if user_id in pending_screenshot:
            app = pending_screenshot.pop(user_id)
            reset_cooldown(app["guild_id"], user_id)
            await message.channel.send(
                embed=make_embed(
                    discord.Color.light_grey(),
                    "🚫 Заявка отменена",
                    "Ваша заявка отменена. Вы можете подать повторно в любое время."
                )
            )
        else:
            await message.channel.send(
                embed=make_embed(discord.Color.light_grey(), "ℹ️ Нет активных заявок", "У вас нет активных заявок.")
            )
        return

    # Получен скриншот
    if user_id in pending_screenshot:
        if not message.attachments:
            await message.channel.send(
                embed=make_embed(
                    discord.Color.yellow(),
                    "📎 Прикрепите скриншот",
                    "Пожалуйста, отправьте **изображение** со скриншотом статистики.\n"
                    "Чтобы отменить заявку — напишите **`отмена`**."
                )
            )
            return

        app = pending_screenshot.pop(user_id)
        review_channel = bot.get_channel(app["review_channel_id"])

        if not review_channel:
            await message.channel.send(
                embed=make_embed(
                    discord.Color.red(),
                    "❌ Ошибка",
                    "Канал рассмотрения недоступен. Обратитесь к администратору."
                )
            )
            return

        category_label = "ОПГ" if app["category"] == "opg" else "Гос. организация"
        embed = discord.Embed(
            title=f"📋 Заявка на роль — {category_label}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="👤 Пользователь", value=f"{app['user_mention']} (`{app['user_tag']}`)", inline=False)
        embed.add_field(name="🎮 Никнейм в игре", value=app["nickname"], inline=True)
        embed.add_field(name="🏅 Ранг", value=app["rank"], inline=True)
        embed.add_field(name="🏴 Фракция", value=app["faction"], inline=True)
        embed.set_image(url=message.attachments[0].url)
        embed.set_footer(text=f"ID пользователя: {user_id}")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

        view = ApplicationReviewView(app_data=app)
        await review_channel.send(embed=embed, view=view)

        await message.channel.send(
            embed=make_embed(
                discord.Color.green(),
                "✅ Заявка отправлена!",
                "Ваша заявка передана модераторам на рассмотрение.\n"
                "Ожидайте ответ в личных сообщениях."
            )
        )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    if payload.message_id not in reaction_verifications:
        return
    data = reaction_verifications[payload.message_id]
    if str(payload.emoji) != data["emoji"]:
        return
    guild = bot.get_guild(data["guild_id"])
    if not guild:
        return
    member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    if not member:
        return
    role = guild.get_role(data["role_id"])
    if role and role not in member.roles:
        await member.add_roles(role, reason="Верификация по реакции")
        try:
            await member.send(embed=make_embed(discord.Color.green(), "✅ Верификация пройдена",
                f"Вы получили роль **{role.name}** на сервере **{guild.name}**!"))
        except discord.Forbidden:
            pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.message_id not in reaction_verifications:
        return
    data = reaction_verifications[payload.message_id]
    if str(payload.emoji) != data["emoji"]:
        return
    guild = bot.get_guild(data["guild_id"])
    if not guild:
        return
    member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    if not member:
        return
    role = guild.get_role(data["role_id"])
    if role and role in member.roles:
        await member.remove_roles(role, reason="Реакция убрана")


# ═══════════════════════════════════════════════════════════════
# МОДАЛ: ФОРМА ЗАЯВКИ
# ═══════════════════════════════════════════════════════════════
class ApplicationModal(discord.ui.Modal, title="Подача заявки"):
    nickname = discord.ui.TextInput(
        label="Укажите свой полный никнейм",
        placeholder="Например: Maxim_Apache",
        required=True,
        max_length=50
    )
    rank = discord.ui.TextInput(
        label="Укажите ваш порядковый ранг (только цифра)",
        placeholder="Например: 3",
        required=True,
        max_length=10
    )

    def __init__(self, category: str, faction: str, review_channel_id: int, guild_id: int):
        super().__init__()
        self.category = category
        self.faction = faction
        self.review_channel_id = review_channel_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        pending_screenshot[user_id] = {
            "category": self.category,
            "nickname": self.nickname.value,
            "rank": self.rank.value,
            "faction": self.faction,
            "guild_id": self.guild_id,
            "review_channel_id": self.review_channel_id,
            "user_mention": interaction.user.mention,
            "user_tag": str(interaction.user),
            "user_id": user_id
        }
        set_cooldown(self.guild_id, user_id)

        await interaction.response.send_message(
            embed=make_embed(
                discord.Color.blurple(),
                "📸 Отправьте скриншот",
                "Форма принята! Теперь отправьте **скриншот статистики** в личные сообщения боту.\n\n"
                "Чтобы отменить заявку — напишите в ЛС боту: **`отмена`**"
            ),
            ephemeral=True
        )

        try:
            await interaction.user.send(
                embed=make_embed(
                    discord.Color.blurple(),
                    "📸 Требуется скриншот",
                    f"Вы подали заявку на роль **{self.faction}**.\n\n"
                    "Отправьте скриншот статистики прямо сюда.\n"
                    "Чтобы отменить — напишите **`отмена`**."
                )
            )
        except discord.Forbidden:
            pending_screenshot.pop(user_id, None)
            reset_cooldown(self.guild_id, user_id)
            await interaction.followup.send(
                embed=make_embed(
                    discord.Color.red(),
                    "❌ Закрыты личные сообщения",
                    "Разрешите ЛС от участников сервера и попробуйте снова."
                ),
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════
# VIEW: ВЫБОР ФРАКЦИИ
# ═══════════════════════════════════════════════════════════════
class FactionSelectView(discord.ui.View):
    def __init__(self, category: str, review_channel_id: int, guild_id: int):
        super().__init__(timeout=60)
        factions = OPG_FACTIONS if category == "opg" else GOV_FACTIONS

        select = discord.ui.Select(
            placeholder="Выберите фракцию...",
            options=[discord.SelectOption(label=f, value=f) for f in factions]
        )

        async def callback(inter: discord.Interaction):
            faction = select.values[0]
            await inter.response.send_modal(
                ApplicationModal(category, faction, review_channel_id, guild_id)
            )

        select.callback = callback
        self.add_item(select)


# ═══════════════════════════════════════════════════════════════
# VIEW: РАССМОТРЕНИЕ ЗАЯВКИ (для модераторов)
# ═══════════════════════════════════════════════════════════════
class ApplicationReviewView(discord.ui.View):
    def __init__(self, app_data: dict):
        super().__init__(timeout=None)
        self.app_data = app_data

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Нет прав для рассмотрения заявок.", ephemeral=True)
            return False
        return True

    def _disable_all(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perms(interaction):
            return

        guild = bot.get_guild(self.app_data["guild_id"])
        faction = self.app_data["faction"]

        self._disable_all()
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.add_field(name="✅ Решение", value=f"Одобрено — {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # Пингуем роль фракции в канале рассмотрения
        role = discord.utils.get(guild.roles, name=faction)
        if role:
            await interaction.channel.send(
                f"{role.mention} — заявка одобрена! "
                f"Пользователь {self.app_data['user_mention']} (`{self.app_data['nickname']}`) "
                f"ожидает выдачи роли **{faction}** (ранг {self.app_data['rank']})."
            )
        else:
            await interaction.channel.send(
                f"⚠️ Роль **{faction}** не найдена на сервере. Выдайте роль пользователю "
                f"{self.app_data['user_mention']} вручную."
            )

        # Уведомляем пользователя в ЛС
        try:
            member = guild.get_member(self.app_data["user_id"]) or await guild.fetch_member(self.app_data["user_id"])
            await member.send(embed=make_embed(
                discord.Color.green(),
                "✅ Заявка одобрена!",
                f"Ваша заявка на роль **{faction}** одобрена!\n"
                f"Ожидайте — ответственные за фракцию скоро выдадут вам роль на сервере."
            ))
        except (discord.Forbidden, discord.NotFound):
            pass

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perms(interaction):
            return

        self._disable_all()
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.add_field(name="❌ Решение", value=f"Отклонено — {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        guild = bot.get_guild(self.app_data["guild_id"])
        try:
            member = guild.get_member(self.app_data["user_id"]) or await guild.fetch_member(self.app_data["user_id"])
            await member.send(embed=make_embed(
                discord.Color.red(),
                "❌ Заявка отклонена",
                f"Ваша заявка на роль **{self.app_data['faction']}** отклонена.\n"
                "Повторная подача будет доступна через 24 часа."
            ))
        except (discord.Forbidden, discord.NotFound):
            pass

    @discord.ui.button(label="🚫 Отменить заявку", style=discord.ButtonStyle.secondary)
    async def cancel_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perms(interaction):
            return

        self._disable_all()
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.light_grey()
        embed.add_field(name="🚫 Решение", value=f"Отменено — {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        reset_cooldown(self.app_data["guild_id"], self.app_data["user_id"])

        guild = bot.get_guild(self.app_data["guild_id"])
        try:
            member = guild.get_member(self.app_data["user_id"]) or await guild.fetch_member(self.app_data["user_id"])
            await member.send(embed=make_embed(
                discord.Color.light_grey(),
                "🚫 Заявка отменена",
                f"Ваша заявка на роль **{self.app_data['faction']}** отменена администратором.\n"
                "Вы можете подать заявку повторно."
            ))
        except (discord.Forbidden, discord.NotFound):
            pass


# ═══════════════════════════════════════════════════════════════
# VIEW: ОСНОВНОЕ СООБЩЕНИЕ ОПГ
# ═══════════════════════════════════════════════════════════════
class OPGMessageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Получить роль", style=discord.ButtonStyle.success, emoji="🎭", custom_id="opg_get_role")
    async def get_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        remaining = check_cooldown(interaction.guild.id, interaction.user.id)
        if remaining:
            h, m = int(remaining // 3600), int((remaining % 3600) // 60)
            await interaction.response.send_message(
                embed=make_embed(discord.Color.red(), "⏳ Кулдаун",
                    f"Вы уже подавали заявку. Следующая возможна через **{h}ч {m}мин**."),
                ephemeral=True
            )
            return

        cfg = get_config(interaction.guild.id)
        review_channel_id = cfg.get("opg_review_channel")
        if not review_channel_id:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.red(), "❌ Ошибка", "Канал рассмотрения не настроен. Обратитесь к администратору."),
                ephemeral=True
            )
            return

        view = FactionSelectView("opg", review_channel_id, interaction.guild.id)
        await interaction.response.send_message(
            embed=make_embed(discord.Color.blurple(), "🎭 Выберите фракцию ОПГ",
                "\n".join(f"• {f}" for f in OPG_FACTIONS)),
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Роль СС", style=discord.ButtonStyle.secondary, emoji="👑", custom_id="opg_role_ss")
    async def role_ss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=make_embed(discord.Color.gold(), "👑 Роль СС",
                "Для получения роли Совета Сервера обратитесь к администратору."),
            ephemeral=True
        )

    @discord.ui.button(label="Снять роли", style=discord.ButtonStyle.danger, emoji="🚫", custom_id="opg_remove_roles")
    async def remove_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        removed = []
        for faction in OPG_FACTIONS:
            role = discord.utils.get(interaction.guild.roles, name=faction)
            if role and role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Снятие роли ОПГ по запросу")
                removed.append(role.name)

        if removed:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.orange(), "🚫 Роли сняты", f"Удалены роли: **{', '.join(removed)}**"),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.light_grey(), "ℹ️ Нет ролей", "У вас нет активных ролей ОПГ."),
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════
# VIEW: ОСНОВНОЕ СООБЩЕНИЕ ГОС
# ═══════════════════════════════════════════════════════════════
class GOVMessageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Получить роль", style=discord.ButtonStyle.success, emoji="🏛", custom_id="gov_get_role")
    async def get_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        remaining = check_cooldown(interaction.guild.id, interaction.user.id)
        if remaining:
            h, m = int(remaining // 3600), int((remaining % 3600) // 60)
            await interaction.response.send_message(
                embed=make_embed(discord.Color.red(), "⏳ Кулдаун",
                    f"Вы уже подавали заявку. Следующая возможна через **{h}ч {m}мин**."),
                ephemeral=True
            )
            return

        cfg = get_config(interaction.guild.id)
        review_channel_id = cfg.get("gov_review_channel")
        if not review_channel_id:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.red(), "❌ Ошибка", "Канал рассмотрения не настроен. Обратитесь к администратору."),
                ephemeral=True
            )
            return

        view = FactionSelectView("gov", review_channel_id, interaction.guild.id)
        await interaction.response.send_message(
            embed=make_embed(discord.Color.blurple(), "🏛 Выберите организацию",
                "\n".join(f"• {f}" for f in GOV_FACTIONS)),
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Роль СС", style=discord.ButtonStyle.secondary, emoji="👑", custom_id="gov_role_ss")
    async def role_ss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=make_embed(discord.Color.gold(), "👑 Роль СС",
                "Для получения роли Совета Сервера обратитесь к администратору."),
            ephemeral=True
        )

    @discord.ui.button(label="Снять роли", style=discord.ButtonStyle.danger, emoji="🚫", custom_id="gov_remove_roles")
    async def remove_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        removed = []
        for faction in GOV_FACTIONS:
            role = discord.utils.get(interaction.guild.roles, name=faction)
            if role and role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Снятие роли гос. организации по запросу")
                removed.append(role.name)

        if removed:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.orange(), "🚫 Роли сняты", f"Удалены роли: **{', '.join(removed)}**"),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=make_embed(discord.Color.light_grey(), "ℹ️ Нет ролей", "У вас нет активных ролей гос. организаций."),
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ: СОЗДАНИЕ ПОСТОВ ЗАЯВОК
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="запрос-опг", description="Создать сообщение для подачи заявок на роль ОПГ")
@app_commands.describe(канал_рассмотрения="Канал, куда будут поступать заявки для проверки")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_opg(interaction: discord.Interaction, канал_рассмотрения: discord.TextChannel):
    set_config(interaction.guild.id, "opg_review_channel", канал_рассмотрения.id)

    embed = discord.Embed(
        title="Роли ОПГ! 🎭",
        description=(
            "Уважаемые игроки! Тут вы сможете получить роли ОПГ. "
            "Следуйте инструкциям после нажатия на кнопку **«Получить роль»**!\n\n"
            "**Порядок подачи:**\n"
            "1. Нажмите на кнопку ниже.\n"
            "2. Заполните форму.\n"
            "3. Отправьте скрин статистики в личные сообщения бота."
        ),
        color=discord.Color.from_rgb(180, 30, 30)
    )
    embed.set_footer(text=f"КД: {COOLDOWN_HOURS} часов")

    bot.add_view(OPGMessageView())
    await interaction.response.send_message("✅ Сообщение ОПГ создано!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=OPGMessageView())


@bot.tree.command(name="запрос-гос", description="Создать сообщение для подачи заявок на роль гос. организации")
@app_commands.describe(канал_рассмотрения="Канал, куда будут поступать заявки для проверки")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_gov(interaction: discord.Interaction, канал_рассмотрения: discord.TextChannel):
    set_config(interaction.guild.id, "gov_review_channel", канал_рассмотрения.id)

    embed = discord.Embed(
        title="Роли гос. организаций! 🏛",
        description=(
            "Уважаемые игроки! Тут вы сможете получить роли гос. организаций. "
            "Следуйте инструкциям после нажатия на кнопку **«Получить роль»**!\n\n"
            "**Порядок подачи:**\n"
            "1. Нажмите на кнопку ниже.\n"
            "2. Заполните форму.\n"
            "3. Отправьте скрин статистики в личные сообщения бота."
        ),
        color=discord.Color.from_rgb(30, 80, 180)
    )
    embed.set_footer(text=f"КД: {COOLDOWN_HOURS} часов")

    bot.add_view(GOVMessageView())
    await interaction.response.send_message("✅ Сообщение гос. организаций создано!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=GOVMessageView())


# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ: МОДЕРАЦИЯ
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="бан", description="Заблокировать пользователя на сервере")
@app_commands.describe(участник="Пользователь для блокировки", причина="Причина")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(
            embed=make_embed(discord.Color.red(), "❌ Ошибка", "Нельзя заблокировать пользователя с равной или более высокой ролью."),
            ephemeral=True
        )
        return
    await участник.ban(reason=f"{причина} | Модератор: {interaction.user}")
    await interaction.response.send_message(embed=make_embed(
        discord.Color.red(), "🔨 Пользователь заблокирован",
        f"**Пользователь:** {участник.mention}\n**Причина:** {причина}\n**Модератор:** {interaction.user.mention}"
    ))


@bot.tree.command(name="кик", description="Выгнать пользователя с сервера")
@app_commands.describe(участник="Пользователь для кика", причина="Причина")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(
            embed=make_embed(discord.Color.red(), "❌ Ошибка", "Нельзя выгнать пользователя с равной или более высокой ролью."),
            ephemeral=True
        )
        return
    await участник.kick(reason=f"{причина} | Модератор: {interaction.user}")
    await interaction.response.send_message(embed=make_embed(
        discord.Color.orange(), "👢 Пользователь выгнан",
        f"**Пользователь:** {участник.mention}\n**Причина:** {причина}\n**Модератор:** {interaction.user.mention}"
    ))


@bot.tree.command(name="мут", description="Заглушить пользователя")
@app_commands.describe(участник="Пользователь", минуты="Длительность в минутах", причина="Причина")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute_cmd(interaction: discord.Interaction, участник: discord.Member, минуты: int = 10, причина: str = "Причина не указана"):
    if минуты < 1 or минуты > 40320:
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Укажите от 1 до 40 320 минут."), ephemeral=True)
        return
    if участник.top_role >= interaction.user.top_role:
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Нельзя заглушить пользователя с равной или более высокой ролью."), ephemeral=True)
        return
    until = discord.utils.utcnow() + datetime.timedelta(minutes=минуты)
    await участник.timeout(until, reason=f"{причина} | Модератор: {interaction.user}")
    await interaction.response.send_message(embed=make_embed(
        discord.Color.dark_grey(), "🔇 Пользователь заглушён",
        f"**Пользователь:** {участник.mention}\n**Длительность:** {минуты} мин.\n**Причина:** {причина}\n**Модератор:** {interaction.user.mention}"
    ))


@bot.tree.command(name="размут", description="Снять мут с пользователя")
@app_commands.describe(участник="Пользователь")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute_cmd(interaction: discord.Interaction, участник: discord.Member):
    if not участник.is_timed_out():
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "У пользователя нет активного мута."), ephemeral=True)
        return
    await участник.timeout(None)
    await interaction.response.send_message(embed=make_embed(
        discord.Color.green(), "🔊 Мут снят",
        f"**Пользователь:** {участник.mention}\n**Модератор:** {interaction.user.mention}"
    ))


@bot.tree.command(name="предупреждение", description="Выдать предупреждение")
@app_commands.describe(участник="Пользователь", причина="Причина")
@app_commands.checks.has_permissions(kick_members=True)
async def warn_cmd(interaction: discord.Interaction, участник: discord.Member, причина: str = "Причина не указана"):
    gid, uid = interaction.guild.id, участник.id
    if gid not in warnings: warnings[gid] = {}
    if uid not in warnings[gid]: warnings[gid][uid] = []
    warnings[gid][uid].append(причина)
    count = len(warnings[gid][uid])
    await interaction.response.send_message(embed=make_embed(
        discord.Color.yellow(), "⚠️ Предупреждение выдано",
        f"**Пользователь:** {участник.mention}\n**Причина:** {причина}\n**Всего:** {count}\n**Модератор:** {interaction.user.mention}"
    ))
    try:
        await участник.send(embed=make_embed(discord.Color.yellow(), f"⚠️ Предупреждение — {interaction.guild.name}",
            f"**Причина:** {причина}\n**Всего предупреждений:** {count}"))
    except discord.Forbidden:
        pass


@bot.tree.command(name="предупреждения", description="Посмотреть предупреждения пользователя")
@app_commands.describe(участник="Пользователь")
@app_commands.checks.has_permissions(kick_members=True)
async def warnings_cmd(interaction: discord.Interaction, участник: discord.Member):
    user_warns = warnings.get(interaction.guild.id, {}).get(участник.id, [])
    if not user_warns:
        await interaction.response.send_message(embed=make_embed(discord.Color.green(), "✅ Нет предупреждений", f"У {участник.mention} нет предупреждений."), ephemeral=True)
        return
    список = "\n".join(f"**{i+1}.** {w}" for i, w in enumerate(user_warns))
    await interaction.response.send_message(embed=make_embed(discord.Color.yellow(), f"⚠️ Предупреждения — {участник.display_name}", список), ephemeral=True)


@bot.tree.command(name="очистить", description="Удалить сообщения в канале")
@app_commands.describe(количество="Количество (1–100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_cmd(interaction: discord.Interaction, количество: int = 10):
    if количество < 1 or количество > 100:
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Укажите число от 1 до 100."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=количество)
    await interaction.followup.send(embed=make_embed(discord.Color.blurple(), "🗑️ Удалено", f"Удалено сообщений: **{len(deleted)}**"), ephemeral=True)


@bot.tree.command(name="разбан", description="Разбанить пользователя по ID")
@app_commands.describe(id_пользователя="ID пользователя")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_cmd(interaction: discord.Interaction, id_пользователя: str):
    try:
        user = await bot.fetch_user(int(id_пользователя))
    except (ValueError, discord.NotFound):
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Пользователь не найден."), ephemeral=True)
        return
    try:
        await interaction.guild.unban(user)
        await interaction.response.send_message(embed=make_embed(
            discord.Color.green(), "✅ Разбанен",
            f"**Пользователь:** {user.mention}\n**Модератор:** {interaction.user.mention}"
        ))
    except discord.NotFound:
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Пользователь не в бан-листе."), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ: ВЕРИФИКАЦИЯ
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="верификация-реакция", description="Создать сообщение верификации через реакцию")
@app_commands.describe(роль="Роль для выдачи", эмодзи="Эмодзи", заголовок="Заголовок", описание="Текст")
@app_commands.checks.has_permissions(manage_roles=True)
async def verify_reaction(interaction: discord.Interaction, роль: discord.Role, эмодзи: str = "✅",
                          заголовок: str = "Верификация", описание: str = "Поставьте реакцию ниже, чтобы получить доступ к серверу."):
    embed = discord.Embed(title=f"✅ {заголовок}", description=f"{описание}\n\nПоставьте реакцию {эмодзи}", color=discord.Color.green())
    embed.set_footer(text=f"Роль: {роль.name}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await interaction.response.send_message("📨 Отправлено!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction(эмодзи)
    reaction_verifications[msg.id] = {"role_id": роль.id, "emoji": эмодзи, "guild_id": interaction.guild.id}


class VerifyButton(discord.ui.View):
    def __init__(self, role_id: int, label: str = "Пройти верификацию"):
        super().__init__(timeout=None)
        self.role_id = role_id
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.success, emoji="✅", custom_id=f"verify_{role_id}")
        btn.callback = self.button_callback
        self.add_item(btn)

    async def button_callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", "Роль не найдена."), ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(embed=make_embed(discord.Color.blurple(), "ℹ️ Уже верифицированы", f"У вас уже есть роль **{role.name}**."), ephemeral=True)
            return
        await interaction.user.add_roles(role, reason="Верификация по кнопке")
        await interaction.response.send_message(embed=make_embed(discord.Color.green(), "✅ Верификация пройдена!", f"Вы получили роль **{role.name}**!"), ephemeral=True)


@bot.tree.command(name="верификация-кнопка", description="Создать сообщение верификации через кнопку")
@app_commands.describe(роль="Роль для выдачи", заголовок="Заголовок", описание="Текст", текст_кнопки="Текст кнопки")
@app_commands.checks.has_permissions(manage_roles=True)
async def verify_button(interaction: discord.Interaction, роль: discord.Role,
                        заголовок: str = "Верификация", описание: str = "Нажмите кнопку ниже, чтобы получить доступ.",
                        текст_кнопки: str = "Пройти верификацию"):
    embed = discord.Embed(title=f"✅ {заголовок}", description=описание, color=discord.Color.green())
    embed.set_footer(text=f"Роль: {роль.name}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await interaction.response.send_message("📨 Отправлено!", ephemeral=True)
    await interaction.channel.send(embed=embed, view=VerifyButton(role_id=роль.id, label=текст_кнопки))


# ═══════════════════════════════════════════════════════════════
# ОБРАБОТЧИК ОШИБОК
# ═══════════════════════════════════════════════════════════════
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "У вас нет прав для этой команды."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = f"Боту не хватает прав: `{', '.join(error.missing_permissions)}`"
    else:
        msg = str(error)

    if not interaction.response.is_done():
        await interaction.response.send_message(embed=make_embed(discord.Color.red(), "❌ Ошибка", msg), ephemeral=True)
    else:
        await interaction.followup.send(embed=make_embed(discord.Color.red(), "❌ Ошибка", msg), ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# ВЕБ-СЕРВЕР (для UptimeRobot — чтобы бот не засыпал)
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
import asyncio

token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN не задан!")

# Регистрируем persistent views при запуске
bot.add_view(OPGMessageView())
bot.add_view(GOVMessageView())

# Бот запускается в фоновом потоке
def run_bot():
    asyncio.run(bot.start(token))

threading.Thread(target=run_bot, daemon=True).start()

# HTTP-сервер на главном потоке — отвечает 200 на любой запрос (GET/HEAD/etc)
run_webserver()
