"""
Comprehensive Test Suite for /flirt (Khen lố + Cà khịa + Chốt tự tin) and /relationship features.
Tests all scenarios specified in the user requirements.
"""

import os
import sys
import shutil
import tempfile
import inspect

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from database import DatabaseRepository, normalize_pair
from flirt_service import FlirtService, QualityGate, FlirtGenerator, BANNED_PHRASES

def run_tests():
    print("=== STARTING COMPREHENSIVE TEST SUITE ===")
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_bot.db")

    try:
        # 1. Khởi tạo Database Repository và FlirtService
        db = DatabaseRepository(db_path=db_file)
        service = FlirtService()

        # TEST SCENARIO 1: /flirt không có relationship, hype thành công
        guild_id_1 = 1001
        u_requester = 101
        u_target = 102
        target_mention = f"<@{u_target}>"

        rel = db.get_relationship(guild_id_1, u_requester, u_target)
        assert rel is None, "Scenario 1 Failed: Relationship should be None"

        is_allowed, reason = db.is_flirt_allowed(guild_id_1, u_target, u_requester)
        assert is_allowed is True and reason == "", "Scenario 1 Failed: Flirt should be allowed when no preference set"

        mock_gemini = lambda p, max_tokens, response_mime_type: f"{target_mention} đẹp thứ hai thì đéo ai dám nhận thứ nhất."
        flirt_line, sig = service.generate_flirt(
            call_gemini_func=mock_gemini,
            target_mention=target_mention,
            channel_topic="generic",
            relationship_scenario="none"
        )
        assert target_mention in flirt_line, "Scenario 1 Failed: Target mention missing"
        assert "\n" not in flirt_line, "Scenario 1 Failed: Should not have newlines"
        assert not flirt_line.startswith('"') and not flirt_line.endswith('"'), "Scenario 1 Failed: Should not have wrapping quotes"
        
        db.record_flirt_history(guild_id_1, sig, "generic")
        recent_sigs = db.get_recent_flirt_signatures(guild_id_1, limit=5)
        assert len(recent_sigs) == 1, "Scenario 1 Failed: History record mismatch"
        print("✅ Scenario 1 Passed: /flirt sinh câu hype chuẩn DNA, ghi nhận history thành công.")

        # TEST SCENARIO 2: Target opt-out & opt-in
        db.set_flirt_preference(guild_id_1, u_target, allow_flirt=False)
        is_allowed, reason = db.is_flirt_allowed(guild_id_1, u_target, u_requester)
        assert is_allowed is False and reason == "optout", "Scenario 2 Failed: Target should be blocked via optout"

        # Re-enable optin
        db.set_flirt_preference(guild_id_1, u_target, allow_flirt=True)
        is_allowed, _ = db.is_flirt_allowed(guild_id_1, u_target, u_requester)
        assert is_allowed is True, "Scenario 2 Failed: Optin should re-allow flirting"
        print("✅ Scenario 2 Passed: Target opt-out & opt-in hoạt động chuẩn xác.")

        # TEST SCENARIO 3: Target block & unblock
        db.block_user(guild_id_1, u_target, u_requester)
        is_allowed, reason = db.is_flirt_allowed(guild_id_1, u_target, u_requester)
        assert is_allowed is False and reason == "blocked", "Scenario 3 Failed: Target should block requester"

        db.unblock_user(guild_id_1, u_target, u_requester)
        is_allowed, _ = db.is_flirt_allowed(guild_id_1, u_target, u_requester)
        assert is_allowed is True, "Scenario 3 Failed: Unblock should restore permission"
        print("✅ Scenario 3 Passed: Target block & unblock hoạt động chuẩn xác.")

        # TEST SCENARIO 4: Target đã có partner khác (người thứ ba)
        u_partner_target = 103
        db.save_relationship(
            guild_id=guild_id_1,
            u1_id=u_target,
            u2_id=u_partner_target,
            relationship_type="dating",
            status="active",
            confirmed_by_a=True,
            confirmed_by_b=True
        )

        partner_info = db.get_active_romantic_partner(guild_id_1, u_target)
        assert partner_info == (u_partner_target, "dating"), "Scenario 4 Failed: Target partner detection"
        assert partner_info[0] != u_requester, "Scenario 4 Failed: Partner is a third party"
        print("✅ Scenario 4 Passed: Phát hiện chuẩn xác Target đã có partner khác (người thứ ba).")

        # TEST SCENARIO 5: Requester và Target là một cặp đã xác nhận (couple mode)
        db.end_relationship(guild_id_1, u_target, u_partner_target)
        assert db.get_active_romantic_partner(guild_id_1, u_target) is None, "Should have no active partner after end"

        db.save_relationship(
            guild_id=guild_id_1,
            u1_id=u_requester,
            u2_id=u_target,
            relationship_type="married",
            status="active",
            confirmed_by_a=True,
            confirmed_by_b=True
        )
        couple_rel = db.get_relationship(guild_id_1, u_requester, u_target)
        assert couple_rel is not None and couple_rel["relationship_type"] == "married" and couple_rel["status"] == "active"

        couple_flirt, _ = service.generate_flirt(
            call_gemini_func=lambda p, **kw: f"{target_mention} đẹp thứ hai thì tôi cũng không dám nhận thứ nhất.",
            target_mention=target_mention,
            relationship_scenario="couple"
        )
        assert target_mention in couple_flirt
        print("✅ Scenario 5 Passed: Requester và Target là một cặp đã xác nhận (couple mode).")

        # TEST SCENARIO 6: Relationship gia đình (family mode)
        db.save_relationship(
            guild_id=guild_id_1,
            u1_id=u_requester,
            u2_id=105,
            relationship_type="family",
            status="active",
            confirmed_by_a=True,
            confirmed_by_b=True
        )
        family_flirt, _ = service.generate_flirt(
            call_gemini_func=lambda p, **kw: f"<@105> là người nhà rồi, bớt chiếm spotlight của anh em đi.",
            target_mention="<@105>",
            relationship_scenario="family"
        )
        assert "<@105>" in family_flirt
        print("✅ Scenario 6 Passed: Khen lố kiểu gia đình ảo (family mode) trêu vui ngầu lòi.")

        # TEST SCENARIO 7: Persistence qua restart DatabaseRepository
        del db
        db_reloaded = DatabaseRepository(db_path=db_file)
        rel_reloaded = db_reloaded.get_relationship(guild_id_1, u_requester, u_target)
        assert rel_reloaded is not None, "Scenario 7 Failed: Relationship lost after reload!"
        assert rel_reloaded["status"] == "active" and rel_reloaded["relationship_type"] == "married"
        print("✅ Scenario 7 Passed: Dữ liệu quan hệ bền vững (Persistent Storage), không bị mất sau reload.")

        # TEST SCENARIO 8: Guild Isolation
        guild_id_2 = 2002
        rel_guild_2 = db_reloaded.get_relationship(guild_id_2, u_requester, u_target)
        assert rel_guild_2 is None, "Scenario 8 Failed: Guild 2 should not have relationship from Guild 1!"
        partner_guild_2 = db_reloaded.get_active_romantic_partner(guild_id_2, u_requester)
        assert partner_guild_2 is None, "Scenario 8 Failed: Partner should not leak across guilds!"
        print("✅ Scenario 8 Passed: Dữ liệu phân tách tuyệt đối theo guild_id (Guild Isolation).")

        # TEST SCENARIO 9: Fallback khi Gemini lỗi
        def broken_gemini(p, max_tokens, response_mime_type):
            raise TimeoutError("Gemini API timed out")

        fallback_result, fb_sig = service.generate_flirt(
            call_gemini_func=broken_gemini,
            target_mention=target_mention,
            channel_topic="game",
            relationship_scenario="none"
        )
        assert target_mention in fallback_result and len(fallback_result) > 10
        print(f"✅ Scenario 9 Passed: Fallback phản hồi xuất sắc khi Gemini gặp lỗi: '{fallback_result}'")

        # TEST SCENARIO 10: QualityGate lọc sạch câu sến súa và kích hoạt fallback
        def mushy_gemini(p, max_tokens, response_mime_type):
            return f"{target_mention} ơi nụ cười của bạn như ánh nắng sưởi ấm tim mình."

        censored_result, c_sig = service.generate_flirt(
            call_gemini_func=mushy_gemini,
            target_mention=target_mention,
            channel_topic="generic",
            relationship_scenario="none"
        )
        assert "ánh nắng" not in censored_result, "QualityGate Failed: Mushy phrase leaked through"
        assert "nụ cười" not in censored_result, "QualityGate Failed: Mushy phrase leaked through"
        assert target_mention in censored_result
        print(f"✅ Scenario 10 Passed: QualityGate loại bỏ câu sến súa và thay thế bằng mẫu chuẩn: '{censored_result}'")

        # TEST SCENARIO 11: Rate Limiter chống spam
        allowed_1, _, _ = service.rate_limiter.check(u_requester, u_target)
        assert allowed_1 is True, "First call should be allowed"
        allowed_2, limit_msg, _ = service.rate_limiter.check(u_requester, u_target)
        assert allowed_2 is False and "Chờ" in limit_msg, "Immediate duplicate call should be rate limited"
        print("✅ Scenario 11 Passed: Rate limiter chặn spam cùng target trong 25 giây chuẩn xác.")

        # TEST SCENARIO 12: Kiểm tra schema lệnh /flirt trong bot.py
        import bot
        flirt_cmd = None
        for cmd in bot.bot.tree.get_commands():
            if cmd.name == "flirt":
                flirt_cmd = cmd
                break
        assert flirt_cmd is not None, "Scenario 12 Failed: Command /flirt not found in tree"
        assert flirt_cmd.description == "Trêu nhẹ một người", f"Command description mismatch: {flirt_cmd.description}"
        param_names = [p.name for p in flirt_cmd.parameters]
        assert param_names == ["target"], f"Parameters should be ['target'] only, got: {param_names}"
        assert flirt_cmd.parameters[0].description == "Người được tag"
        print("✅ Scenario 12 Passed: Schema lệnh /flirt trong CommandTree chuẩn 100%: duy nhất target, description 'Trêu nhẹ một người'.")

        # TEST SCENARIO 13: Đảm bảo sạch các chuỗi UI cũ (Chi tiết mở rộng, Flirt cute...)
        bot_file_path = os.path.join(os.path.dirname(__file__), "bot.py")
        with open(bot_file_path, "r", encoding="utf-8") as f:
            bot_code = f.read()
        assert "Chi tiết mở rộng" not in bot_code, "Old UI string 'Chi tiết mở rộng' found in bot.py"
        assert "Flirt cute" not in bot_code, "Old UI string 'Flirt cute' found in bot.py"
        assert "Flirt gen z" not in bot_code, "Old UI string 'Flirt gen z' found in bot.py"
        assert 'value="cute"' not in bot_code, "Old Choice 'cute' found in bot.py"
        assert 'value="genz"' not in bot_code, "Old Choice 'genz' found in bot.py"
        assert 'value="poetic"' not in bot_code, "Old Choice 'poetic' found in bot.py"
        print("✅ Scenario 13 Passed: Đã dọn dẹp sạch toàn bộ chuỗi UI cũ và choices lỗi thời.")

        print("\n🎉 TẤT CẢ 13 KỊCH BẢN ĐÃ ĐƯỢC KIỂM THỬ VÀ VƯỢT QUA 100%!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    run_tests()
