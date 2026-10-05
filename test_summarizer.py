"""
Kiểm thử chức năng Tóm Tắt Hội Thoại Discord (Pure Summarizer Bot).
Xác minh rằng bot chỉ còn tính năng tóm tắt, đã loại bỏ hoàn toàn flirt và relationship.
"""

import sys
import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import discord
import bot

def test_summarizer_suite():
    print("=== BẮT ĐẦU KIỂM THỬ BOT TÓM TẮT BAN ĐẦU ===")

    # 1. Kiểm tra parse_duration
    print("\n--- TEST 1: Kiểm tra parse_duration ---")
    test_cases = [
        ("15p", timedelta(minutes=15), "15 phút"),
        ("30m", timedelta(minutes=30), "30 phút"),
        ("1h", timedelta(hours=1), "1 giờ"),
        ("2h", timedelta(hours=2), "2 giờ"),
        ("1d", timedelta(days=1), "1 ngày"),
        ("45phut", timedelta(minutes=45), "45 phút"),
        ("2gio", timedelta(hours=2), "2 giờ"),
        ("3", timedelta(hours=3), "3 giờ"),
    ]
    for raw, exp_delta, exp_str in test_cases:
        delta, readable = bot.parse_duration(raw)
        assert delta == exp_delta, f"Delta mismatch for {raw}: {delta} vs {exp_delta}"
        assert readable == exp_str, f"Readable mismatch for {raw}: {readable} vs {exp_str}"
        print(f"  ✓ '{raw}' -> {readable} ({delta})")

    # 2. Kiểm tra CommandTree (Chỉ có duy nhất /tomtat)
    print("\n--- TEST 2: Kiểm tra CommandTree Slash Commands ---")
    commands = bot.bot.tree.get_commands()
    cmd_names = [c.name for c in commands]
    print(f"  Danh sách Slash Commands hiện có: {cmd_names}")
    
    assert "tomtat" in cmd_names, "Lệnh /tomtat phải có trong CommandTree"
    assert "flirt" not in cmd_names, "Lệnh /flirt PHẢI BỊ XÓA HOÀN TOÀN"
    assert "relationship" not in cmd_names, "Nhóm lệnh /relationship PHẢI BỊ XÓA HOÀN TOÀN"
    assert "flirt_optout" not in cmd_names, "Lệnh /flirt_optout PHẢI BỊ XÓA HOÀN TOÀN"
    assert "flirt_optin" not in cmd_names, "Lệnh /flirt_optin PHẢI BỊ XÓA HOÀN TOÀN"
    assert "flirt_block" not in cmd_names, "Lệnh /flirt_block PHẢI BỊ XÓA HOÀN TOÀN"
    assert "flirt_unblock" not in cmd_names, "Lệnh /flirt_unblock PHẢI BỊ XÓA HOÀN TOÀN"
    print("  ✓ CommandTree sạch sẽ: Chỉ còn duy nhất /tomtat, không còn bất kỳ lệnh flirt/relationship nào.")

    # 3. Kiểm tra Prefix Commands
    print("\n--- TEST 3: Kiểm tra Prefix Commands ---")
    prefix_cmds = [c.name for c in bot.bot.commands]
    assert "tomtat" in prefix_cmds, "Lệnh !tomtat phải có"
    tomtat_cmd = bot.bot.get_command("tomtat")
    assert "summary" in tomtat_cmd.aliases, "Alias !summary phải có"
    assert "tt" in tomtat_cmd.aliases, "Alias !tt phải có"
    print(f"  ✓ Lệnh prefix !tomtat với aliases {tomtat_cmd.aliases} hoạt động chuẩn xác.")

    # 4. Kiểm tra process_summarize trả về Embed hợp lệ
    print("\n--- TEST 4: Kiểm tra process_summarize ---")
    async def async_test_summarize():
        # Mock channel có tin nhắn
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "chung"
        
        async def mock_history(after=None, oldest_first=True, limit=1000):
            for i in range(5):
                msg = MagicMock(spec=discord.Message)
                msg.author = MagicMock()
                msg.author.bot = False
                msg.author.display_name = f"User{i}"
                msg.clean_content = f"Nội dung tin nhắn số {i}"
                msg.attachments = []
                msg.created_at = MagicMock()
                msg.created_at.strftime = lambda fmt: "12:00"
                yield msg
        mock_channel.history = mock_history

        mock_user = MagicMock()
        mock_user.display_name = "Admin"

        embed = await bot.process_summarize(mock_channel, "30m", mock_user)
        assert isinstance(embed, discord.Embed), "Output phải là discord.Embed"
        assert "chung" in embed.title, "Title embed phải có tên channel"
        assert len(embed.fields) > 0 or embed.description, "Embed phải chứa nội dung tóm tắt"
        assert "Admin" in embed.footer.text, "Footer phải ghi nhận người yêu cầu"
        print(f"  ✓ Embed tóm tắt được tạo thành công: '{embed.title}' ({len(embed.fields)} fields)")

    asyncio.run(async_test_summarize())

    # 5. Kiểm tra source code không còn import flirt / database
    print("\n--- TEST 5: Kiểm tra code bot.py sạch không còn import thừa ---")
    with open("bot.py", "r", encoding="utf-8") as f:
        code = f.read()
    assert "flirt_service" not in code, "Không được import flirt_service trong bot.py"
    assert "relationship_views" not in code, "Không được import relationship_views trong bot.py"
    assert "DatabaseRepository" not in code, "Không được import DatabaseRepository trong bot.py"
    print("  ✓ Source code bot.py hoàn toàn tinh gọn, không còn vết tích của flirt/relationship.")

    print("\n🎉 TẤT CẢ CÁC BÀI TEST TÓM TẮT ĐÃ VƯỢT QUA 100%!")

if __name__ == "__main__":
    test_summarizer_suite()
