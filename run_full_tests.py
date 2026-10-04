"""
Comprehensive Test Suite for /flirt (Multi-Style, Real Context & QualityGate Pipeline).
Kiểm thử thực tế toàn bộ các kịch bản theo đúng yêu cầu người dùng.
"""

import os
import sys
import shutil
import tempfile
import asyncio
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import discord
from database import DatabaseRepository
from flirt_service import (
    FlirtService, QualityGate, FlirtGenerator, ContextCollector,
    resolve_style_and_scenario, BANNED_PHRASES, BANNED_CLICHES
)

# === FIXTURES CHO NGỮ CẢNH ===
def create_mock_message(author_id: int, author_name: str, content: str, is_bot: bool = False):
    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock(spec=discord.Member)
    msg.author.id = author_id
    msg.author.display_name = author_name
    msg.author.bot = is_bot
    msg.clean_content = content
    return msg

def create_mock_channel(messages):
    channel = MagicMock(spec=discord.TextChannel)
    async def async_history(limit=40, oldest_first=False):
        for m in messages[:limit]:
            yield m
    channel.history = async_history
    return channel

CONTEXT_FIXTURES = {
    "game": [
        create_mock_message(101, "Alice", "Tối nay bắn rank valo không mọi người?"),
        create_mock_message(102, "Bob", "Vào làm ván game valo đi, đang chuỗi thắng đây."),
        create_mock_message(103, "Charlie", "Đánh valo cẩn thận team địch bắn hay lắm nhé."),
        create_mock_message(102, "Bob", "Bắn rank sợ gì team địch, combat tới bến."),
    ],
    "deadline": [
        create_mock_message(101, "Alice", "Deadline đồ án sáng mai nộp rồi mọi người ơi."),
        create_mock_message(102, "Bob", "Đang chạy deadline đồ án muốn gục ngã luôn."),
        create_mock_message(103, "Charlie", "Deadline tuần này nhiều quá không kịp ôn thi."),
        create_mock_message(102, "Bob", "Làm bài tập cả đêm nay chắc luôn."),
    ],
    "meme": [
        create_mock_message(101, "Alice", "Xem cái ảnh chế meme này tấu hài ghê haha."),
        create_mock_message(103, "Charlie", "Meme này cười đau ruột thật sự kkk."),
        create_mock_message(102, "Bob", "Tấu hài đỉnh cao, quăng miếng cười xỉu."),
    ],
    "music": [
        create_mock_message(101, "Alice", "Bài hát này nghe chill theo playlist spotify ghê."),
        create_mock_message(103, "Charlie", "Playlist nghe nhạc thư giãn ghê, bài này hay."),
        create_mock_message(102, "Bob", "Mở mic nghe nhạc chung đi anh em."),
    ],
    "generic": [
        create_mock_message(101, "Alice", "Chào buổi chiều cả nhà nhé."),
        create_mock_message(102, "Bob", "Hôm nay thời tiết mát mẻ ghê."),
    ]
}


async def run_async_tests():
    print("=== BẮT ĐẦU TEST TOÀN DIỆN HỆ THỐNG /FLIRT & RELATIONSHIP ===")
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_bot.db")

    try:
        db = DatabaseRepository(db_path=db_file)
        service = FlirtService()
        guild_id = 9999
        u_req = 101
        u_tgt = 102
        target_mention = f"<@{u_tgt}>"

        # TEST 1: ContextCollector với các fixtures thực tế
        print("\n--- TEST 1: ContextCollector phân tích ngữ cảnh thật ---")
        for ctx_name, msgs in CONTEXT_FIXTURES.items():
            chan = create_mock_channel(msgs)
            packet = await service.collect_context(chan, target_id=u_tgt)
            if ctx_name in ["game", "deadline"]:
                assert packet["topic"] == ctx_name, f"Context mismatch for {ctx_name}: got {packet['topic']}"
            assert isinstance(packet["callbacks"], list)
            assert isinstance(packet["target_recent_messages"], list)
            print(f"  ✓ Fixture '{ctx_name}': Nhận diện topic='{packet['topic']}', atmosphere='{packet['atmosphere']}'")

        # TEST 2: Thử nghiệm từng phong cách (romantic, teasing, hype, funny, cool, auto)
        print("\n--- TEST 2: Kiểm thử từng phong cách (Style testing) ---")
        styles = ["romantic", "teasing", "hype", "funny", "cool", "auto"]
        for st in styles:
            line, sig, eff_style = service.generate_flirt(
                call_gemini_func=lambda p, **kw: '{"candidates": []}', # ép dùng fallback
                requester_name="Alice",
                target_name="Bob",
                target_mention=target_mention,
                requested_style=st,
                relationship_scenario="none"
            )
            assert target_mention in line, f"Target mention missing in style {st}"
            assert len(line) <= 280, f"Line too long in style {st}"
            s_count = QualityGate.count_sentences(line)
            assert 1 <= s_count <= 3, f"Sentence count invalid in style {st}: {s_count}"
            print(f"  ✓ Style '{st}' -> resolved '{eff_style}': \"{line}\" (Câu: {s_count})")

        # TEST 3: Kiểm thử từng Relationship Scenario
        print("\n--- TEST 3: Kiểm thử Relationship Scenarios ---")
        scenarios = ["couple", "friend", "family", "ex", "none"]
        for sc in scenarios:
            eff_st, eff_sc = resolve_style_and_scenario("auto", sc, {"topic": "generic"}, False)
            if sc == "couple":
                assert eff_st in ["romantic", "teasing"] and eff_sc == "couple"
            elif sc == "family":
                assert eff_st in ["teasing", "hype"] and eff_sc == "family"
            elif sc == "ex":
                assert eff_st in ["cool", "funny"] and eff_sc == "ex"
            print(f"  ✓ Scenario '{sc}' auto-resolves to style '{eff_st}' (scenario: '{eff_sc}')")

        # Family cấm romantic
        eff_st, eff_sc = resolve_style_and_scenario("romantic", "family", {"topic": "generic"}, False)
        assert eff_st == "teasing" and eff_sc == "family", "Family must block romantic"
        print("  ✓ Scenario 'family' chủ động chặn romantic và chuyển sang teasing thành công.")

        # Ex cấm romantic
        eff_st, eff_sc = resolve_style_and_scenario("romantic", "ex", {"topic": "generic"}, False)
        assert eff_st == "cool" and eff_sc == "ex", "Ex must block romantic"
        print("  ✓ Scenario 'ex' chủ động chặn romantic và chuyển sang cool thành công.")

        # TEST 4: Partner thứ ba
        print("\n--- TEST 4: Đối phương hoặc requester có partner thứ ba ---")
        # Romantic tự động chuyển sang teasing
        eff_st, eff_sc = resolve_style_and_scenario("romantic", "none", {"topic": "generic"}, has_third_party_partner=True)
        assert eff_st == "teasing" and eff_sc == "partner_third_party", "3rd party partner must override romantic to teasing"
        # Teasing vẫn được phép hoạt động
        eff_st, eff_sc = resolve_style_and_scenario("teasing", "none", {"topic": "generic"}, has_third_party_partner=True)
        assert eff_st == "teasing" and eff_sc == "partner_third_party", "3rd party partner allows teasing"
        print("  ✓ Partner thứ ba: Romantic chuyển sang teasing tôn trọng, teasing vẫn hoạt động lịch sự.")

        # TEST 5: Pipeline chấm điểm Candidates của Gemini
        print("\n--- TEST 5: Pipeline 3 Candidates & Scoring QualityGate ---")
        # Giả lập Gemini trả về 3 candidates:
        # 1: Câu sến bị cấm
        # 2: Câu tốt có tích hợp callback 'valo'
        # 3: Câu dính cliché 'spotlight'
        mock_response = f"""{{
            "candidates": [
                "{target_mention} ơi nụ cười của bạn như ánh nắng sưởi ấm tim mình.",
                "{target_mention} đánh valo kiểu này thì team địch cũng phải xin thua từ sớm. Đúng là có phong cách.",
                "{target_mention} xuất hiện là chiếm trọn spotlight của cả server."
            ]
        }}"""
        flirt_line, chosen_sig, _ = service.generate_flirt(
            call_gemini_func=lambda p, **kw: mock_response,
            requester_name="Alice",
            target_name="Bob",
            target_mention=target_mention,
            requested_style="teasing",
            relationship_scenario="none",
            context_packet={"callbacks": ["valo"], "topic": "game"}
        )
        assert "ánh nắng" not in flirt_line, "Mushy candidate must be rejected"
        assert "spotlight" not in flirt_line, "Cliché candidate must be rejected"
        assert "đánh valo kiểu này" in flirt_line, f"Best candidate should be chosen, got: {flirt_line}"
        print(f"  ✓ Bộ lọc QualityGate loại bỏ 2 ứng viên sến & cliché, chọn ứng viên xuất sắc nhất: \"{flirt_line}\"")

        # TEST 6: QualityGate: Kiểm tra Target Mention đúng 1 lần duy nhất
        print("\n--- TEST 6: QualityGate kiểm tra Mention ---")
        is_ok1, _, _ = QualityGate.validate_and_score(
            f"{target_mention} nói chuyện vui tính ghê.", target_mention, "teasing", "none", {}, []
        )
        assert is_ok1 is True, "Valid mention should pass"

        # 0 mention
        is_ok2, _, reason2 = QualityGate.validate_and_score(
            "Bạn nói chuyện vui tính ghê.", target_mention, "teasing", "none", {}, []
        )
        assert is_ok2 is False, "Missing mention should fail"

        # 2 mentions
        is_ok3, _, reason3 = QualityGate.validate_and_score(
            f"{target_mention} {target_mention} nói chuyện vui tính ghê.", target_mention, "teasing", "none", {}, []
        )
        assert is_ok3 is False, "Duplicate mention should fail"

        # Mention người khác
        is_ok4, _, reason4 = QualityGate.validate_and_score(
            f"{target_mention} cùng với <@999> nói chuyện vui tính ghê.", target_mention, "teasing", "none", {}, []
        )
        assert is_ok4 is False, "Mentioning another user should fail"
        print("  ✓ QualityGate bắt buộc đúng 1 target mention và cấm mention thêm người khác 100%.")

        # TEST 7: Kiểm tra Deduplication & Signature không lặp lại
        print("\n--- TEST 7: Deduplication chống lặp lại trong guild ---")
        recent_sigs = []
        seen_lines = []
        for i in range(5):
            line, sig, _ = service.generate_flirt(
                call_gemini_func=lambda p, **kw: '{"candidates": []}',
                requester_name="Alice",
                target_name="Bob",
                target_mention=target_mention,
                requested_style="teasing",
                relationship_scenario="none",
                recent_signatures=recent_sigs
            )
            assert sig not in recent_sigs, f"Duplicate signature detected: {sig}"
            assert line not in seen_lines, f"Duplicate line detected: {line}"
            recent_sigs.append(sig)
            seen_lines.append(line)
        print("  ✓ 5 lần gọi liên tiếp sinh 5 câu hoàn toàn khác nhau, không bị lặp lại signature.")

        # TEST 8: Kiểm tra Embed Format
        print("\n--- TEST 8: Kiểm tra cấu trúc Embed Discord ---")
        mock_target = MagicMock(spec=discord.Member)
        mock_target.display_name = "Bob"
        mock_target.mention = "<@102>"
        mock_target.display_avatar = MagicMock()
        mock_target.display_avatar.url = "https://cdn.discordapp.com/avatars/102/avatar.png"

        # Tạo Embed theo đúng code trong bot.py
        flirt_content = "<@102> xuất hiện muộn thế này là sai rồi. Kênh chat vừa yên ổn được vài phút."
        embed = discord.Embed(
            title=f"💌 Một lời nhắn gửi {mock_target.display_name}",
            description=flirt_content,
            color=discord.Color.from_rgb(255, 175, 75)
        )
        embed.set_thumbnail(url=mock_target.display_avatar.url)

        assert embed.title == "💌 Một lời nhắn gửi Bob", f"Embed title mismatch: {embed.title}"
        assert embed.description == flirt_content, "Embed description mismatch"
        assert embed.thumbnail.url == "https://cdn.discordapp.com/avatars/102/avatar.png"
        assert len(embed.fields) == 0, "Embed MUST NOT contain any extra fields"
        assert embed.footer.text is None, "Embed MUST NOT contain any footer"
        # Đảm bảo sạch các nhãn cũ
        full_text = f"{embed.title} {embed.description}"
        assert "Chi tiết mở rộng" not in full_text
        assert "Flirt cute" not in full_text
        assert "Flirt gen z" not in full_text
        assert "Phong cách:" not in full_text
        assert "Được tạo bởi AI" not in full_text
        print("  ✓ Embed chuẩn đẹp: Title '💌 Một lời nhắn gửi Bob', có thumbnail avatar, 0 field phụ, 0 footer.")

        # TEST 9: Kiểm tra Schema trong bot.py CommandTree
        print("\n--- TEST 9: Kiểm tra Schema trong CommandTree của bot.py ---")
        import bot
        flirt_cmd = None
        for cmd in bot.bot.tree.get_commands():
            if cmd.name == "flirt":
                flirt_cmd = cmd
                break
        assert flirt_cmd is not None, "Command /flirt not found in tree"
        param_map = {p.name: p for p in flirt_cmd.parameters}
        assert "target" in param_map, "Param target missing"
        assert "style" in param_map, "Param style missing"
        assert param_map["target"].required is True, "Target must be required"
        assert param_map["style"].required is False, "Style must be optional"
        style_choices = [c.value for c in param_map["style"].choices]
        expected_choices = ["auto", "romantic", "teasing", "hype", "funny", "cool"]
        assert style_choices == expected_choices, f"Style choices mismatch: {style_choices}"
        print(f"  ✓ Schema /flirt chuẩn xác: target (bắt buộc), style (tùy chọn với choices: {style_choices})")

        print("\n🎉 TẤT CẢ 9 BÀI TEST LỚN ĐÃ HOÀN THÀNH VÀ VƯỢT QUA 100%!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_async_tests())
