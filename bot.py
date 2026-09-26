import os
import sys
import re
import socket
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Đảm bảo in tiếng Việt / emoji trên Windows console và tự động flush log
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# Cơ chế khóa Single-Instance: Chống chạy trùng lặp nhiều tiến trình bot
lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    lock_socket.bind(("127.0.0.1", 49152))
except socket.error as e:
    if getattr(e, "errno", None) in [10048, 98] or getattr(e, "winerror", None) == 10048:
        print("⚠️ CẢNH BÁO: Đã có một tiến trình bot khác đang chạy trên máy! Tự động đóng để tránh phản hồi trùng lặp.")
        sys.exit(0)


# Tải cấu hình từ file .env
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

import logging
# Tắt các thông báo khuyến nghị không cần thiết từ thư viện Gemini
logging.getLogger("google_genai").setLevel(logging.ERROR)

# Khởi tạo client Gemini
genai_client = None
try:
    from google import genai
    from google.genai import types
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"Lỗi khởi tạo Gemini SDK: {e}")



def call_gemini(prompt: str, max_tokens: int = 1500) -> str:
    """Gọi model nhanh nhất và tối ưu token (mặc định cho phép tới 1500 tokens để chi tiết hơn)"""
    global genai_client
    
    current_key = os.getenv("GEMINI_API_KEY")
    if not current_key or current_key == "your_gemini_api_key_here":
        return "⚠️ Bạn chưa điền `GEMINI_API_KEY` vào file `.env`!"

    if genai_client is None:
        try:
            from google import genai
            genai_client = genai.Client(api_key=current_key)
        except Exception as e:
            return f"❌ Lỗi khởi tạo Gemini: {e}"

    # Danh sách model ưu tiên (nhẹ nhất, nhanh nhất, ít tốn token nhất đứng đầu)
    model_candidates = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-flash-latest",
    ]

    last_error = None
    for model_name in model_candidates:
        try:
            config = types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.3,
            )
            response = genai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as err:
            last_error = err
            continue

    return f"❌ Lỗi khi gọi AI: {last_error}"


def parse_duration(time_str: str) -> tuple[timedelta | None, str]:
    """Phân tích chuỗi thời gian như: 15p, 30m, 2h, 1d, 45phut"""
    if not time_str:
        return timedelta(hours=1), "1 giờ"

    time_str = time_str.strip().lower()
    match = re.match(r"^(\d+)\s*([a-zA-Zàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]+)$", time_str)
    
    if not match:
        if time_str.isdigit():
            val = int(time_str)
            return timedelta(hours=val), f"{val} giờ"
        return None, ""

    val = int(match.group(1))
    unit = match.group(2)

    if unit in ["m", "min", "mins", "minute", "minutes", "p", "phut", "phút"]:
        return timedelta(minutes=val), f"{val} phút"
    elif unit in ["h", "hr", "hrs", "hour", "hours", "g", "gio", "giờ"]:
        return timedelta(hours=val), f"{val} giờ"
    elif unit in ["d", "day", "days", "n", "ngay", "ngày"]:
        return timedelta(days=val), f"{val} ngày"
    
    return None, ""


async def process_summarize(channel: discord.TextChannel, duration_str: str, requester: discord.Member | discord.User) -> discord.Embed:
    """Xử lý tóm tắt chi tiết, đầy đủ ngữ cảnh và LUÔN trả về duy nhất 1 Embed súc tích"""
    delta, readable_time = parse_duration(duration_str)
    
    if not delta:
        return discord.Embed(
            title="⚠️ Định dạng thời gian chưa đúng",
            description="Ví dụ hợp lệ: `15p`, `30m`, `1h`, `2h`, `1d`.",
            color=discord.Color.orange(),
        )

    cutoff_time = datetime.now(timezone.utc) - delta

    # Thu thập tin nhắn từ kênh (tối đa 1000 tin nhắn gần nhất để không bỏ sót thông tin)
    messages = []
    async for msg in channel.history(after=cutoff_time, oldest_first=True, limit=1000):
        if msg.author.bot:
            continue
        content = msg.clean_content.strip()
        if not content and not msg.attachments:
            continue
        if not content and msg.attachments:
            content = "[Đã gửi ảnh/tệp]"

        time_str = msg.created_at.strftime("%H:%M")
        messages.append(f"[{time_str}] {msg.author.display_name}: {content}")

    if not messages:
        return discord.Embed(
            title="📭 Không có tin nhắn",
            description=f"Không có tin nhắn nào từ các thành viên trong **{readable_time}** vừa qua.",
            color=discord.Color.light_grey(),
        )

    chat_logs = "\n".join(messages)
    is_long_period = delta >= timedelta(hours=1)

    # Tùy chỉnh độ chi tiết theo khoảng thời gian
    if is_long_period:
        prompt = f"""Bạn là trợ lý AI tóm tắt Discord chuyên nghiệp. Hãy đọc và tóm tắt CHI TIẾT đoạn trò chuyện trong {readable_time} vừa qua ({len(messages)} tin nhắn).
Vì đây là khoảng thời gian dài, hãy cung cấp bản tóm tắt ĐẦY ĐỦ THÔNG TIN, rõ ràng, không tóm lược sơ sài hay cụt ngủn:

1. 📌 **Tổng quan cuộc trò chuyện**: Tóm tắt 1-2 câu về bối cảnh và các chủ đề bao quát được trao đổi.
2. 💬 **Diễn biến & Nội dung chi tiết**:
   - Chia thành các sự việc / nhóm chủ đề cụ thể diễn ra trong khoảng thời gian này.
   - Ghi rõ tên thành viên (`**[Tên]**`) đã nói gì, thảo luận gì, có câu chuyện hài hước, tranh luận, rủ rê hay sự kiện gì đáng chú ý.
   - Giữ lại các chi tiết quan trọng và ngữ cảnh để người không theo dõi kênh vẫn nắm rõ diễn biến.
3. 📋 **Quyết định, Kèo hẹn & Việc cần làm (To-Do)**: Liệt kê các kèo hẹn (chơi game, đi chơi...), quyết định đã chốt, hoặc việc ai phải làm (nếu không có thì ghi "Không có").

Đoạn chat:
---
{chat_logs}
---

Yêu cầu: Viết bằng tiếng Việt tự nhiên, đầy đủ chiều sâu (khoảng 350 - 650 từ), giữ phong cách trò chuyện vui vẻ, trình bày Markdown đẹp mắt."""
        max_tokens = 1500
    else:
        prompt = f"""Bạn là trợ lý AI tóm tắt Discord. Hãy tóm tắt đoạn trò chuyện trong {readable_time} vừa qua ({len(messages)} tin nhắn):

1. 📌 **Chủ đề chính**: Tóm tắt 1-2 câu về chủ đề thảo luận.
2. 💬 **Chi tiết thảo luận**: Gạch đầu dòng cụ thể các ý kiến, ai nói gì (`**[Tên]**`), những điểm thảo luận nổi bật.
3. 📋 **Kết luận / Việc cần làm**: Quyết định hoặc việc cần làm (nếu có).

Đoạn chat:
---
{chat_logs}
---

Yêu cầu: Viết tiếng Việt rõ ràng, đầy đủ ý chính, không quá ngắn (khoảng 200 - 350 từ)."""
        max_tokens = 800

    summary_text = call_gemini(prompt, max_tokens=max_tokens)
    if not summary_text:
        summary_text = "⚠️ Không nhận được phản hồi từ AI."

    # Giới hạn nội dung hiển thị trong 1 Embed duy nhất (Discord cho phép tối đa 4096 ký tự)
    if len(summary_text) > 3900:
        summary_text = summary_text[:3900] + "\n\n*(Xem thêm ở lịch sử chat...)*"

    embed = discord.Embed(
        title=f"📝 Tóm tắt #{channel.name} ({readable_time} vừa qua)",
        description=summary_text,
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )

    embed.set_footer(text=f"Yêu cầu bởi {requester.display_name} • Đã phân tích {len(messages)} tin nhắn")
    return embed


# Thiết lập Intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)


async def start_web_server():
    """Chạy web server nhỏ để Render nhận diện port và kiểm tra trạng thái sống"""
    from aiohttp import web
    app = web.Application()
    async def index(request):
        return web.Response(text="Bot Discord Ueh-TomTat is running 24/7!")
    app.router.add_get("/", index)
    app.router.add_get("/health", index)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web server keep-alive đang chạy tại port {port}")


@bot.event
async def on_ready():
    print(f"✅ Bot đã kết nối thành công: {bot.user}")
    print(f"ID Bot: {bot.user.id}")
    print(f"🌐 Đang phục vụ tại {len(bot.guilds)} server:")
    for g in bot.guilds:
        print(f"   • {g.name}")
    try:
        await bot.tree.sync()
        print("⚡ Đã đồng bộ slash command /tomtat")
    except Exception as e:
        print(f"Lỗi sync: {e}")

    print("---------------------------------------------")
    print("👉 Bot sẵn sàng! Chỉ phản hồi đúng 1 tin nhắn duy nhất.")




@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    print(f"❌ Lỗi lệnh [{ctx.command}]: {error}")


# 1. LỆNH PREFIX: !tomtat [thời_gian] (Chỉ gửi duy nhất 1 Embed)
@bot.command(name="tomtat", aliases=["summary", "tt"])
async def cmd_tomtat(ctx: commands.Context, *, duration: str = "1h"):
    print(f"👉 [PREFIX] !tomtat {duration} từ {ctx.author} tại #{ctx.channel.name}")
    async with ctx.typing():
        embed = await process_summarize(ctx.channel, duration, ctx.author)
        await ctx.send(embed=embed)
        print(f"✅ Đã gửi tóm tắt thành công vào #{ctx.channel.name}!")


# 2. LỆNH SLASH COMMAND: /tomtat [thời_gian] (Chỉ gửi duy nhất 1 Embed)
@bot.tree.command(name="tomtat", description="Tóm tắt tin nhắn kênh siêu nhanh bằng Gemini Flash-Lite")
@app_commands.describe(thoigian="Khoảng thời gian cần tóm tắt (VD: 15p, 30m, 1h, 2h - mặc định 1h)")
async def slash_tomtat(interaction: discord.Interaction, thoigian: str = "1h"):
    print(f"👉 [SLASH] /tomtat {thoigian} từ {interaction.user}")
    await interaction.response.defer(thinking=True)
    embed = await process_summarize(interaction.channel, thoigian, interaction.user)
    await interaction.followup.send(embed=embed)
    print("✅ Đã gửi tóm tắt thành công qua Slash Command!")


# 3. KÍCH HOẠT KHI NHẬN TIN NHẮN HOẶC TAG @BOT (Chỉ gửi duy nhất 1 Embed)
@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # Nếu được tag trực tiếp
    if bot.user in message.mentions and not message.mention_everyone:
        clean_text = message.content.replace(f"<@{bot.user.id}>", "").strip()
        duration = clean_text if clean_text else "1h"
        print(f"👉 [MENTION] @Bot {duration} từ {message.author} tại #{message.channel.name}")
        
        async with message.channel.typing():
            embed = await process_summarize(message.channel, duration, message.author)
            await message.reply(embed=embed)
            print(f"✅ Đã gửi tóm tắt thành công vào #{message.channel.name}!")
        return

async def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_discord_bot_token_here":
        print("❌ Chưa cấu hình DISCORD_TOKEN trong .env!")
        return

    try:
        await start_web_server()
    except Exception as e:
        print(f"Lỗi khởi động web server: {e}")

    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

