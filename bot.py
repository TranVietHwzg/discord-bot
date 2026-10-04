import os
import sys
import re
import json
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from database import DatabaseRepository
from flirt_service import FlirtService
from relationship_views import ProposalView, RELATIONSHIP_NAMES

# Khởi tạo Database Repository và Flirt Service
db = DatabaseRepository()
flirt_service = FlirtService()


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
        print("⚡ Đã đồng bộ slash command (/tomtat, /flirt, /relationship, /flirt_optout...)")
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


# ==========================================
# 3. LỆNH SLASH COMMAND: /flirt VÀ QUẢN LÝ QUYỀN RIÊNG TƯ
# ==========================================

@bot.tree.command(name="flirt", description="Gửi lời tán tỉnh/thả thính dễ thương, an toàn tới một thành viên")
@app_commands.describe(
    target="Thành viên bạn muốn gửi lời tán tỉnh",
    style="Phong cách: cute (dễ thương), funny (hài hước), poetic (thơ mộng), genz (trẻ trung)"
)
@app_commands.choices(style=[
    app_commands.Choice(name="Dễ thương (Cute) ✨", value="cute"),
    app_commands.Choice(name="Hài hước (Funny) 🎭", value="funny"),
    app_commands.Choice(name="Thơ mộng (Poetic) 📜", value="poetic"),
    app_commands.Choice(name="Gen Z bắt trend ⚡", value="genz"),
])
async def slash_flirt(interaction: discord.Interaction, target: discord.Member, style: Optional[str] = None):
    # 1. Không cho phép tán tỉnh chính mình
    if target.id == interaction.user.id:
        await interaction.response.send_message(
            "😅 Bạn không thể tự tán tỉnh chính mình đâu nha! Hãy chọn một người bạn khác trong server nhé.",
            ephemeral=True
        )
        return

    # 2. Không cho phép tán tỉnh bot
    if target.bot:
        await interaction.response.send_message(
            "🤖 Bot chỉ là trợ lý ảo thôi, không biết rung động đâu nè! Hãy chọn một thành viên khác trong server nhé.",
            ephemeral=True
        )
        return

    guild_id = interaction.guild_id or 0

    # 3. Kiểm tra cài đặt riêng tư của đối phương (opt-out / block)
    is_allowed, reason = db.is_flirt_allowed(guild_id, target.id, interaction.user.id)
    if not is_allowed:
        if reason == "optout":
            await interaction.response.send_message(
                f"🔒 **{target.display_name}** đã tắt tính năng nhận lời tán tỉnh (`/flirt_optout`). Hãy tôn trọng quyền riêng tư của bạn ấy nhé!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"🔒 Bạn không thể gửi lời tán tỉnh tới **{target.display_name}**.",
                ephemeral=True
            )
        return

    # 4. Kiểm tra rate limit chống spam
    allowed_rate, limit_msg, _ = flirt_service.rate_limiter.check(interaction.user.id, target.id)
    if not allowed_rate:
        await interaction.response.send_message(f"⏳ {limit_msg}", ephemeral=True)
        return

    # Defer interaction vì việc phân tích ngữ cảnh và gọi AI có thể mất 1-3 giây
    await interaction.response.defer(thinking=True)

    # 5. Kiểm tra quan hệ tình cảm của requester và target với người thứ ba
    requester_partner = db.get_active_romantic_partner(guild_id, interaction.user.id)
    target_partner = db.get_active_romantic_partner(guild_id, target.id)

    # Nếu người gửi đang có người yêu/vợ chồng khác
    if requester_partner and requester_partner[0] != target.id:
        partner_m = interaction.guild.get_member(requester_partner[0]) if interaction.guild else None
        partner_name = partner_m.mention if partner_m else f"<@{requester_partner[0]}>"
        rel_label = "kết hôn" if requester_partner[1] == "married" else "hẹn hò"
        embed = discord.Embed(
            title="👀 Khoan đã nào...",
            description=(
                f"Ủa kì nha {interaction.user.mention}! Bạn đang {rel_label} với {partner_name} rồi mà, "
                f"sao lại đi 'thả thính' {target.mention} thế này? Hãy chung thủy với nửa kia của mình nhé! 🛑"
            ),
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed)
        return

    # Nếu người nhận đã có người yêu/vợ chồng khác
    if target_partner and target_partner[0] != interaction.user.id:
        partner_m = interaction.guild.get_member(target_partner[0]) if interaction.guild else None
        partner_name = partner_m.mention if partner_m else f"<@{target_partner[0]}>"
        rel_label = "kết hôn" if target_partner[1] == "married" else "hẹn hò"
        embed = discord.Embed(
            title="🌸 Hoa đã có chủ!",
            description=(
                f"Rất tiếc cho {interaction.user.mention} nha! {target.mention} đã {rel_label} với {partner_name} rồi. "
                f"Tôn trọng hạnh phúc của người khác và đừng 'đập chậu cướp hoa' nhé! 🛡️"
            ),
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed)
        return

    # 6. Kiểm tra quan hệ trực tiếp giữa requester và target
    direct_rel = db.get_relationship(guild_id, interaction.user.id, target.id)
    scenario = "none"
    rel_label = ""

    if direct_rel and direct_rel.get("status") == "active":
        r_type = direct_rel.get("relationship_type")
        if r_type in ["dating", "married"]:
            scenario = "couple"
            rel_label = "Vợ chồng" if r_type == "married" else "Người yêu"
        elif r_type == "family":
            scenario = "family"
            rel_label = "Người trong gia đình"

    # Nếu có quan hệ gia đình ảo: chỉ trêu đùa vui vẻ, không tạo tán tỉnh tình cảm
    if scenario == "family":
        embed = discord.Embed(
            title="👨‍👩‍👧 Người một nhà mà!",
            description=(
                f"Nè {interaction.user.mention}, hai bạn đã nhận là người trong gia đình ({rel_label}) rồi đó! "
                f"Lo mà yêu thương nhau kiểu gia đình đi chứ tán tỉnh gì ở đây hả! 😂"
            ),
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)
        return

    # 7. Thu thập ngữ cảnh an toàn từ 15-25 tin nhắn gần nhất
    safe_topics = "trò chuyện vui vẻ"
    if isinstance(interaction.channel, discord.TextChannel):
        safe_topics = await flirt_service.collect_safe_topics(interaction.channel)

    # 8. Sinh câu tán tỉnh qua Gemini hoặc Fallback template
    flirt_line = flirt_service.generate_flirt_line(
        call_gemini_func=call_gemini,
        requester_name=interaction.user.display_name,
        target_name=target.display_name,
        style=style or "cute",
        recent_topics=safe_topics,
        relationship_scenario=scenario,
        relationship_label=rel_label
    )

    # 9. Gửi lời tán tỉnh công khai trong kênh
    style_names = {
        "cute": "Dễ thương ✨",
        "funny": "Hài hước 🎭",
        "poetic": "Thơ mộng 📜",
        "genz": "Gen Z ⚡"
    }
    style_display = style_names.get(style.lower() if style else "cute", "Ngọt ngào 💖")

    embed = discord.Embed(
        title=f"💌 Lời tán tỉnh từ {interaction.user.display_name}",
        description=f"{target.mention}\n\n> *\"{flirt_line}\"*",
        color=discord.Color.pink() if scenario == "couple" else discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc)
    )
    if scenario == "couple":
        embed.set_footer(text=f"Dành riêng cho {rel_label} của mình • Phong cách: {style_display}")
    else:
        embed.set_footer(text=f"Người gửi: {interaction.user.display_name} • Phong cách: {style_display}")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="flirt_optout", description="Tắt tính năng nhận lời tán tỉnh từ người khác trong server này")
async def slash_flirt_optout(interaction: discord.Interaction):
    guild_id = interaction.guild_id or 0
    db.set_flirt_preference(guild_id, interaction.user.id, allow_flirt=False)
    await interaction.response.send_message(
        "🔒 Bạn đã **tắt** tính năng nhận lời tán tỉnh (`/flirt`) trong server này. Người khác sẽ không thể dùng bot để tán tỉnh bạn nữa.",
        ephemeral=True
    )


@bot.tree.command(name="flirt_optin", description="Bật lại tính năng nhận lời tán tỉnh từ người khác trong server này")
async def slash_flirt_optin(interaction: discord.Interaction):
    guild_id = interaction.guild_id or 0
    db.set_flirt_preference(guild_id, interaction.user.id, allow_flirt=True)
    await interaction.response.send_message(
        "🔓 Bạn đã **bật** lại tính năng nhận lời tán tỉnh (`/flirt`) trong server này.",
        ephemeral=True
    )


@bot.tree.command(name="flirt_block", description="Chặn một thành viên cụ thể không cho dùng /flirt nhắm đến bạn")
@app_commands.describe(target="Thành viên bạn muốn chặn")
async def slash_flirt_block(interaction: discord.Interaction, target: discord.Member):
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ Bạn không thể tự chặn chính mình!", ephemeral=True)
        return
    guild_id = interaction.guild_id or 0
    db.block_user(guild_id, interaction.user.id, target.id)
    await interaction.response.send_message(
        f"🚫 Đã chặn **{target.display_name}** không cho dùng `/flirt` với bạn trong server này.",
        ephemeral=True
    )


@bot.tree.command(name="flirt_unblock", description="Bỏ chặn một thành viên khỏi danh sách chặn /flirt")
@app_commands.describe(target="Thành viên bạn muốn bỏ chặn")
async def slash_flirt_unblock(interaction: discord.Interaction, target: discord.Member):
    guild_id = interaction.guild_id or 0
    success = db.unblock_user(guild_id, interaction.user.id, target.id)
    if success:
        await interaction.response.send_message(f"✅ Đã bỏ chặn **{target.display_name}**.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ Bạn chưa từng chặn **{target.display_name}**.", ephemeral=True)


# ==========================================
# 4. HỆ THỐNG QUẢN LÝ MỐI QUAN HỆ (/relationship)
# ==========================================

relationship_group = app_commands.Group(name="relationship", description="Quản lý mối quan hệ ảo trong server")


@relationship_group.command(name="propose", description="Gửi lời đề nghị thiết lập mối quan hệ với một thành viên")
@app_commands.describe(
    target="Thành viên bạn muốn thiết lập mối quan hệ",
    type="Loại mối quan hệ muốn thiết lập"
)
@app_commands.choices(type=[
    app_commands.Choice(name="Hẹn hò / Người yêu (Dating) 💖", value="dating"),
    app_commands.Choice(name="Kết hôn / Vợ chồng (Married) 💍", value="married"),
    app_commands.Choice(name="Gia đình / Người nhà (Family) 🏡", value="family"),
    app_commands.Choice(name="Bạn thân / Tri kỷ (Friend) 🤝", value="friend"),
    app_commands.Choice(name="Người yêu cũ (Ex) 🥀", value="ex"),
])
async def slash_relationship_propose(interaction: discord.Interaction, target: discord.Member, type: str):
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ Bạn không thể tự thiết lập mối quan hệ với chính mình!", ephemeral=True)
        return

    if target.bot:
        await interaction.response.send_message("🤖 Không thể thiết lập mối quan hệ với bot!", ephemeral=True)
        return

    guild_id = interaction.guild_id or 0

    # Nếu thiết lập hẹn hò/kết hôn: kiểm tra đối phương hoặc bản thân đã có partner chưa
    if type in ["dating", "married"]:
        req_partner = db.get_active_romantic_partner(guild_id, interaction.user.id)
        if req_partner and req_partner[0] != target.id:
            partner_m = interaction.guild.get_member(req_partner[0]) if interaction.guild else None
            p_name = partner_m.display_name if partner_m else f"User ID {req_partner[0]}"
            await interaction.response.send_message(
                f"❌ Bạn đang có mối quan hệ với **{p_name}**. Hãy dùng `/relationship end` trước khi bắt đầu mối quan hệ mới!",
                ephemeral=True
            )
            return

        tgt_partner = db.get_active_romantic_partner(guild_id, target.id)
        if tgt_partner and tgt_partner[0] != interaction.user.id:
            partner_m = interaction.guild.get_member(tgt_partner[0]) if interaction.guild else None
            p_name = partner_m.display_name if partner_m else f"User ID {tgt_partner[0]}"
            await interaction.response.send_message(
                f"❌ **{target.display_name}** hiện đã có mối quan hệ với **{p_name}** trong server này!",
                ephemeral=True
            )
            return

    # Kiểm tra xem 2 người đã có mối quan hệ này chưa
    existing = db.get_relationship(guild_id, interaction.user.id, target.id)
    if existing and existing.get("status") == "active" and existing.get("relationship_type") == type:
        type_name = RELATIONSHIP_NAMES.get(type, type)
        await interaction.response.send_message(
            f"ℹ️ Hai bạn đã là **{type_name}** của nhau trong server rồi!",
            ephemeral=True
        )
        return

    type_name = RELATIONSHIP_NAMES.get(type, type)
    view = ProposalView(db, guild_id, interaction.user, target, type)

    embed = discord.Embed(
        title="💌 Lời Đề Nghị Mối Quan Hệ",
        description=(
            f"{target.mention}, bạn vừa nhận được lời đề nghị thiết lập mối quan hệ từ {interaction.user.mention}!\n\n"
            f"✨ Mối quan hệ: **{type_name}**\n\n"
            f"👉 Vui lòng nhấn nút bên dưới để phản hồi (Thời hạn: 2 phút)."
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc)
    )

    await interaction.response.send_message(content=target.mention, embed=embed, view=view)
    view.message = await interaction.original_response()


@relationship_group.command(name="status", description="Xem trạng thái mối quan hệ trong server")
@app_commands.describe(target="Thành viên bạn muốn xem (để trống để xem của bản thân)")
async def slash_relationship_status(interaction: discord.Interaction, target: Optional[discord.Member] = None):
    guild_id = interaction.guild_id or 0
    member = target or interaction.user

    rels = db.get_user_relationships(guild_id, member.id)
    if not rels:
        await interaction.response.send_message(
            f"ℹ️ **{member.display_name}** hiện chưa có mối quan hệ nào được ghi nhận trong server này.",
            ephemeral=True
        )
        return

    lines = []
    for r in rels:
        partner_id = r["user_b_id"] if r["user_a_id"] == member.id else r["user_a_id"]
        partner_m = interaction.guild.get_member(partner_id) if interaction.guild else None
        partner_mention = partner_m.mention if partner_m else f"<@{partner_id}>"
        rel_label = RELATIONSHIP_NAMES.get(r["relationship_type"], r["relationship_type"])
        lines.append(f"• **{rel_label}**: {partner_mention}")

    embed = discord.Embed(
        title=f"💞 Hồ Sơ Mối Quan Hệ: {member.display_name}",
        description="\n".join(lines),
        color=discord.Color.purple(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Server: {interaction.guild.name if interaction.guild else ''}")
    await interaction.response.send_message(embed=embed)


@relationship_group.command(name="end", description="Chấm dứt mối quan hệ hiện tại với một thành viên")
@app_commands.describe(target="Thành viên bạn muốn chấm dứt mối quan hệ")
async def slash_relationship_end(interaction: discord.Interaction, target: discord.Member):
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ Bạn không thể tự chấm dứt mối quan hệ với chính mình!", ephemeral=True)
        return

    guild_id = interaction.guild_id or 0
    existing = db.get_relationship(guild_id, interaction.user.id, target.id)

    if not existing or existing.get("status") != "active":
        await interaction.response.send_message(
            f"ℹ️ Bạn và **{target.display_name}** hiện không có mối quan hệ nào đang hoạt động.",
            ephemeral=True
        )
        return

    r_type = existing.get("relationship_type", "")
    type_name = RELATIONSHIP_NAMES.get(r_type, r_type)

    db.end_relationship(guild_id, interaction.user.id, target.id)

    embed = discord.Embed(
        title="💔 Mối Quan Hệ Đã Chấm Dứt",
        description=f"Mối quan hệ **{type_name}** giữa {interaction.user.mention} và {target.mention} đã chính thức kết thúc.",
        color=discord.Color.dark_grey(),
        timestamp=datetime.now(timezone.utc)
    )
    await interaction.response.send_message(embed=embed)


# Đăng ký relationship_group vào bot tree
bot.tree.add_group(relationship_group)


# 5. KÍCH HOẠT KHI NHẬN TIN NHẮN HOẶC TAG @BOT (Chỉ gửi duy nhất 1 Embed)
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

