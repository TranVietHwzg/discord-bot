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

    chat_logs = "\n".join(messages)
    is_detailed_mode = delta >= timedelta(minutes=45)

    if is_detailed_mode:
        # BẢN CHI TIẾT (2B) cho thời gian >= 45 phút: Tường thuật theo dòng thời gian, trích dẫn, mốc giờ
        prompt = f"""Bạn là chuyên gia phân tích và tóm tắt hội thoại nhóm Discord.
Nhiệm vụ của bạn là đọc toàn bộ đoạn chat trong {readable_time} vừa qua ({len(messages)} tin nhắn) và tạo bản tóm tắt CHI TIẾT, CHÍNH XÁC, KHÔNG BỊA ĐẶT THÔNG TIN.

Yêu cầu nghiêm ngặt:
1. Chỉ sử dụng thông tin có trong đoạn chat, không tự suy đoán hay thêm thắt.
2. Giữ nguyên tên riêng (người nói), số liệu, mốc thời gian, tên game nếu có.
3. Trường "tuong_thuat_dien_bien": viết như một đoạn tường thuật đầy đủ, bám theo ĐÚNG TRÌNH TỰ diễn biến (ai bắt đầu hỏi/nói gì trước, mọi người trao đổi/tranh luận ra sao ở giữa, kết thúc thế nào). Viết đủ dài (6-10 câu), để người đọc không cần lội lại chat vẫn hiểu toàn bộ câu chuyện.
4. Trường "trich_dan_dang_chu_y": chọn ra 1-3 câu nói nguyên văn then chốt, hài hước, hoặc câu chốt kèo của thành viên. Nếu không có câu nào đặc biệt, để mảng rỗng [].
5. Trường "moc_thoi_gian": liệt kê 2-4 mốc thời điểm đáng chú ý nhất khi có sự thay đổi chủ đề hoặc sự kiện lớn (kèm timestamp nếu có).
6. Trả lời DUY NHẤT bằng JSON hợp lệ theo đúng cấu trúc sau:
{{
  "boi_canh": "Bối cảnh mở đầu cuộc trò chuyện (1-2 câu)",
  "tuong_thuat_dien_bien": "Tường thuật đầy đủ diễn biến theo đúng trình tự thời gian (6-10 câu)",
  "moc_thoi_gian": [
    {{"thoi_diem": "VD: 20:15", "su_kien": "Bắt đầu rủ chơi game"}}
  ],
  "trich_dan_dang_chu_y": [
    "Câu nói nguyên văn đáng chú ý 1"
  ],
  "keo_va_quyet_dinh": [
    "Liệt kê các kèo chơi game, hẹn giờ, việc đã chốt (để [] nếu không có)"
  ],
  "khong_khi": "Vui vẻ / Tranh luận / Sôi nổi / Bình thường"
}}

Đoạn chat cần tóm tắt:
\"\"\"
{chat_logs}
\"\"\""""
        max_tokens = 1500
    else:
        # BẢN CƠ BẢN (2A) cho thời gian < 45 phút: Ngắn gọn, 3-5 gạch đầu dòng
        prompt = f"""Bạn là chuyên gia phân tích và tóm tắt hội thoại nhóm Discord.
Nhiệm vụ của bạn là đọc toàn bộ đoạn chat trong {readable_time} vừa qua ({len(messages)} tin nhắn) và tạo bản tóm tắt CHÍNH XÁC, NGẮN GỌN, KHÔNG BỊA ĐẶT THÔNG TIN.

Yêu cầu nghiêm ngặt:
1. Chỉ sử dụng thông tin có trong đoạn chat, không tự suy đoán hay thêm thắt.
2. Giữ nguyên tên riêng (người nói), số liệu, mốc thời gian, tên game nếu có.
3. Không lặp lại nguyên văn tin nhắn, diễn đạt cô đọng bằng tiếng Việt tự nhiên (khoảng 100 - 200 từ).
4. Trả lời DUY NHẤT bằng JSON hợp lệ theo đúng cấu trúc sau:
{{
  "chu_de_chinh": "Tóm tắt 1 câu bao quát về nội dung mọi người đã bàn luận",
  "dien_bien_chinh": [
    "Ý chính 1 (kèm tên người nói nếu quan trọng)",
    "Ý chính 2",
    "Ý chính 3 (tối đa 3 - 5 ý ngắn gọn)"
  ],
  "keo_va_quyet_dinh": [
    "Liệt kê các kèo chơi game, hẹn giờ, việc đã chốt (để [] nếu không có)"
  ],
  "khong_khi": "Vui vẻ / Tranh luận / Sôi nổi / Bình thường"
}}

Đoạn chat cần tóm tắt:
\"\"\"
{chat_logs}
\"\"\""""
        max_tokens = 700

    summary_raw = call_gemini(prompt, max_tokens=max_tokens, response_mime_type="application/json")
    
    # Parse JSON an toàn
    data = None
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", summary_raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
    except Exception as e:
        print(f"Lỗi parse JSON: {e}")

    embed = discord.Embed(
        title=f"📝 Tóm tắt #{channel.name} ({readable_time} vừa qua)" if not is_detailed_mode else f"📜 Tường thuật chi tiết #{channel.name} ({readable_time} vừa qua)",
        color=discord.Color.blue() if not is_detailed_mode else discord.Color.purple(),
        timestamp=datetime.now(timezone.utc),
    )

    if data and isinstance(data, dict):
        if is_detailed_mode:
            # Hiển thị cho Bản Chi Tiết (2B)
            boi_canh = data.get("boi_canh", "").strip()
            if boi_canh:
                embed.add_field(name="📌 Bối cảnh mở đầu", value=boi_canh[:1024], inline=False)

            tuong_thuat = data.get("tuong_thuat_dien_bien", "").strip()
            if tuong_thuat:
                embed.add_field(name="📖 Diễn biến theo dòng sự kiện", value=tuong_thuat[:1024], inline=False)

            moc_tg = data.get("moc_thoi_gian", [])
            if isinstance(moc_tg, list) and moc_tg:
                lines = []
                for item in moc_tg[:5]:
                    if isinstance(item, dict):
                        td = item.get("thoi_diem", "")
                        sk = item.get("su_kien", "")
                        lines.append(f"⏱️ **`{td}`**: {sk}")
                    elif isinstance(item, str):
                        lines.append(f"• {item}")
                if lines:
                    embed.add_field(name="⏰ Mốc thời gian nổi bật", value="\n".join(lines)[:1024], inline=False)

            trich_dan = data.get("trich_dan_dang_chu_y", [])
            if isinstance(trich_dan, list) and trich_dan:
                quotes = [f"> *\"{q.strip()}\"*" for q in trich_dan if str(q).strip()]
                if quotes:
                    embed.add_field(name="💬 Trích dẫn đáng chú ý", value="\n".join(quotes)[:1024], inline=False)

            keo = data.get("keo_va_quyet_dinh", [])
            if isinstance(keo, list) and keo:
                val = "\n".join(f"• {x}" for x in keo if str(x).strip())
                if val:
                    embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value=val[:1024], inline=False)
            elif isinstance(keo, str) and keo.strip() and keo.strip().lower() != "không có":
                embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value=keo[:1024], inline=False)

            khong_khi = data.get("khong_khi", "").strip()
            if khong_khi:
                embed.add_field(name="🎭 Không khí trò chuyện", value=khong_khi[:256], inline=True)
        else:
            # Hiển thị cho Bản Cơ Bản (2A)
            chu_de = data.get("chu_de_chinh", "").strip()
            if chu_de:
                embed.add_field(name="📌 Chủ đề chính", value=chu_de[:1024], inline=False)

            dien_bien = data.get("dien_bien_chinh", [])
            if isinstance(dien_bien, list) and dien_bien:
                val = "\n".join(f"• {x}" for x in dien_bien if str(x).strip())
                if val:
                    embed.add_field(name="💬 Diễn biến nổi bật", value=val[:1024], inline=False)
            elif isinstance(dien_bien, str) and dien_bien.strip():
                embed.add_field(name="💬 Diễn biến nổi bật", value=dien_bien[:1024], inline=False)

            keo = data.get("keo_va_quyet_dinh", [])
            if isinstance(keo, list) and keo:
                val = "\n".join(f"• {x}" for x in keo if str(x).strip())
                if val:
                    embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value=val[:1024], inline=False)
            elif isinstance(keo, str) and keo.strip() and keo.strip().lower() != "không có":
                embed.add_field(name="📋 Kèo hẹn & Việc cần làm", value=keo[:1024], inline=False)

            khong_khi = data.get("khong_khi", "").strip()
            if khong_khi:
                embed.add_field(name="🎭 Không khí", value=khong_khi[:256], inline=True)
    else:
        # Fallback nếu JSON bị lỗi thì hiển thị văn bản thuần
        embed.description = summary_raw[:3900]

    mode_label = "Chi tiết (2B)" if is_detailed_mode else "Cơ bản (2A)"
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

