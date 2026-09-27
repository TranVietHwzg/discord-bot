import os
import sys
import re
import json
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



def call_gemini(prompt: str, max_tokens: int = 800, response_mime_type: str = "application/json") -> str:
    """Gọi model nhanh nhất và tối ưu token theo định dạng JSON"""
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
                temperature=0.2,
                response_mime_type=response_mime_type,
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

    # Nhận diện chế độ: Thời gian >= 30 phút hoặc trên 20 tin nhắn sẽ kích hoạt Tường thuật Mở rộng Độ dài
    is_high_duration = delta >= timedelta(minutes=30) or len(messages) >= 20

    if is_high_duration:
        # CHẾ ĐỘ THỜI GIAN CAO / NHIỀU TIN NHẮN: Tường thuật chi tiết, mở rộng độ dài tự do, không bỏ sót chi tiết
        dynamic_tokens = min(3000, max(1200, len(messages) * 35))
        prompt = f"""Bạn là chuyên gia phân tích và tóm tắt hội thoại Discord hàng đầu, nắm bắt trọn vẹn và chi tiết mọi diễn biến.
Nhiệm vụ của bạn là đọc toàn bộ {len(messages)} tin nhắn trong {readable_time} vừa qua và tạo bản tường thuật CHI TIẾT, ĐẦY ĐỦ Ý, KHÔNG BỎ SÓT THÔNG TIN QUAN TRỌNG.

Yêu cầu cụ thể:
1. Bám sát 100% nội dung thực tế, không suy diễn hay bịa đặt. Giữ nguyên tên riêng của người nói, mốc giờ, số liệu, tên game/chủ đề.
2. "tuong_thuat_dien_bien": Bạn ĐƯỢC QUYỀN TĂNG ĐỘ DÀI ĐOẠN ĐỂ ĐÁP ỨNG TOÀN BỘ Ý trong cuộc trò chuyện dài. Tường thuật mạch lạc theo đúng trình tự thời gian (ai khơi mào, mọi người bàn luận/tranh cãi những gì, các khúc mắc hay trò đùa, kết cục ra sao). Không được tóm tắt qua loa, phải viết đầy đủ để người đọc nắm trọn vẹn mọi nội dung.
3. "moc_thoi_gian": Liệt kê 2-5 mốc thời gian nổi bật nhất khi có sự thay đổi chủ đề hoặc sự kiện lớn (kèm timestamp HH:MM nếu có).
4. "trich_dan_dang_chu_y": Trích dẫn 1-3 câu nói nguyên văn hài hước, ấn tượng hoặc câu chốt kèo của thành viên. Nếu không có câu nào đặc biệt, để [].
5. "keo_va_quyet_dinh": Liệt kê rõ các kèo chơi game, hẹn giờ, việc đã chốt. Nếu không có, để [].
6. Trả lời DUY NHẤT bằng định dạng JSON hợp lệ theo đúng cấu trúc sau:
{{
  "boi_canh": "Bối cảnh mở đầu cuộc trò chuyện (1-2 câu)",
  "tuong_thuat_dien_bien": "Đoạn tường thuật đầy đủ, chi tiết, mở rộng độ dài thoải mái theo dung lượng chat để không mất ý",
  "moc_thoi_gian": [
    {{"thoi_diem": "VD: 20:15", "su_kien": "Bắt đầu rủ chơi game"}}
  ],
  "trich_dan_dang_chu_y": [
    "Câu nói nguyên văn đáng chú ý 1"
  ],
  "keo_va_quyet_dinh": [
    "Kèo chơi game, hẹn giờ hoặc quyết định đã chốt (để [] nếu không có)"
  ],
  "khong_khi": "Vui vẻ / Tranh luận / Sôi nổi / Hài hước / Bình thường"
}}

Đoạn chat cần tóm tắt:
\"\"\"
{chat_logs}
\"\"\""""
    else:
        # CHẾ ĐỘ THỜI GIAN NGẮN (< 30 phút, ít tin nhắn): Nhanh gọn, súc tích
        dynamic_tokens = 800
        prompt = f"""Bạn là chuyên gia tóm tắt hội thoại Discord nhanh gọn và chính xác.
Nhiệm vụ của bạn là đọc toàn bộ {len(messages)} tin nhắn trong {readable_time} vừa qua và tạo bản tóm tắt súc tích, đầy đủ ý chính.

Yêu cầu:
1. Chỉ sử dụng thông tin có trong đoạn chat, giữ đúng tên người nói, mốc giờ, số liệu nếu có.
2. Trả lời DUY NHẤT bằng JSON hợp lệ theo mẫu sau:
{{
  "boi_canh": "Bối cảnh mở đầu ngắn gọn (1 câu)",
  "tuong_thuat_dien_bien": "Tóm tắt diễn biến chính (3-5 câu súc tích)",
  "moc_thoi_gian": [],
  "trich_dan_dang_chu_y": [],
  "keo_va_quyet_dinh": [
    "Kèo chơi game, hẹn giờ hoặc quyết định đã chốt (nếu có)"
  ],
  "khong_khi": "Vui vẻ / Sôi nổi / Bình thường"
}}

Đoạn chat cần tóm tắt:
\"\"\"
{chat_logs}
\"\"\""""

    summary_raw = call_gemini(prompt, max_tokens=dynamic_tokens, response_mime_type="application/json")
    
    # Parse JSON an toàn
    data = None
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", summary_raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
    except Exception as e:
        print(f"Lỗi parse JSON: {e}")

    embed = discord.Embed(
        title=f"📜 Tường thuật chi tiết #{channel.name} ({readable_time} vừa qua)" if is_high_duration else f"📝 Tóm tắt #{channel.name} ({readable_time} vừa qua)",
        color=discord.Color.purple() if is_high_duration else discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )

    if data and isinstance(data, dict):
        # 1. Bối cảnh mở đầu
        boi_canh = data.get("boi_canh", "").strip()
        if boi_canh:
            embed.add_field(name="📌 Bối cảnh mở đầu", value=boi_canh[:1024], inline=False)

        # 2. Diễn biến sự kiện (Hỗ trợ mở rộng độ dài tự do, chia Phần 1, Phần 2 nếu dài > 1024 ký tự)
        tuong_thuat = data.get("tuong_thuat_dien_bien", "").strip()
        if tuong_thuat:
            if len(tuong_thuat) <= 1024:
                embed.add_field(name="📖 Diễn biến theo dòng sự kiện", value=tuong_thuat, inline=False)
            else:
                # Tách đoạn thông minh theo câu / dòng để không bị cắt ngang giữa chữ
                sentences = re.split(r"(?<=[.!?\n])\s+", tuong_thuat)
                current_chunk = ""
                part_idx = 1
                for s in sentences:
                    if len(current_chunk) + len(s) + 1 > 1000:
                        embed.add_field(name=f"📖 Diễn biến sự kiện (Phần {part_idx})", value=current_chunk.strip(), inline=False)
                        current_chunk = s + " "
                        part_idx += 1
                    else:
                        current_chunk += s + " "
                if current_chunk.strip():
                    embed.add_field(name=f"📖 Diễn biến sự kiện (Phần {part_idx})" if part_idx > 1 else "📖 Diễn biến theo dòng sự kiện", value=current_chunk.strip()[:1024], inline=False)

        # 3. Mốc thời gian nổi bật
        moc_tg = data.get("moc_thoi_gian", [])
        if isinstance(moc_tg, list) and moc_tg:
            lines = []
            for item in moc_tg[:5]:
                if isinstance(item, dict):
                    td = item.get("thoi_diem", "")
                    sk = item.get("su_kien", "")
                    if td and sk:
                        lines.append(f"⏱️ **`{td}`**: {sk}")
                    elif sk:
                        lines.append(f"• {sk}")
                elif isinstance(item, str) and item.strip():
                    lines.append(f"• {item.strip()}")
            if lines:
                embed.add_field(name="⏰ Mốc thời gian nổi bật", value="\n".join(lines)[:1024], inline=False)

        # 4. Trích dẫn đáng chú ý
        trich_dan = data.get("trich_dan_dang_chu_y", [])
        if isinstance(trich_dan, list) and trich_dan:
            quotes = [f"> *\"{str(q).strip()}\"*" for q in trich_dan if str(q).strip()]
            if quotes:
                embed.add_field(name="💬 Trích dẫn đáng chú ý", value="\n".join(quotes)[:1024], inline=False)

        # 5. Kèo hẹn & Việc cần làm
        keo = data.get("keo_va_quyet_dinh", [])
        if isinstance(keo, list) and keo:
            keo_clean = [f"• {str(x).strip()}" for x in keo if str(x).strip()]
            if keo_clean:
                embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value="\n".join(keo_clean)[:1024], inline=False)
        elif isinstance(keo, str) and keo.strip() and keo.strip().lower() not in ["không có", "không", "[]", "none", "rỗng"]:
            embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value=keo.strip()[:1024], inline=False)

        # 6. Không khí trò chuyện
        khong_khi = data.get("khong_khi", "").strip()
        if khong_khi:
            embed.add_field(name="🎭 Không khí trò chuyện", value=f"`{khong_khi[:100]}`", inline=True)
    else:
        # Fallback nếu JSON bị lỗi thì hiển thị văn bản thuần
        embed.description = summary_raw[:3900]

    mode_label = "Chi tiết mở rộng" if is_high_duration else "Cơ bản"
    embed.set_footer(text=f"Yêu cầu bởi {requester.display_name} • Đã phân tích {len(messages)} tin nhắn • Chế độ {mode_label}")
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

    # Xử lý các lệnh có tiền tố (như !tomtat)
    await bot.process_commands(message)


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

