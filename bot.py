import discord
from discord.ext import commands
import os
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


# ═══════════════════════════════════════════════════════════════
# СОБЫТИЯ
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="QRXTeam")
    )
    await bot.tree.sync()
    print(f"✅ Бот {bot.user} запущен!")


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
token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN не задан!")

if os.environ.get("RENDER"):
    t = threading.Thread(target=run_webserver, daemon=True)
    t.start()

bot.run(token)
