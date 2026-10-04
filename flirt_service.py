"""
Flirt Service: Context Collector, Safety Filter, Gemini AI Generator, Rate Limiting & Fallback Templates.
"""

import re
import time
import json
import random
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
import discord

# Bảng câu mẫu dự phòng phong phú và an toàn theo từng phong cách
FALLBACK_TEMPLATES: Dict[str, List[str]] = {
    "cute": [
        "Nghe nói cậu có siêu năng lực đúng không? Vì mỗi lần cậu xuất hiện là tim tớ đập nhanh hơn bình thường đấy! ✨",
        "Trời hôm nay đổ mưa rồi, sao cậu vẫn chưa chịu đổ tớ thế? 🌧️",
        "Cậu có mỏi chân không? Cứ chạy trong tâm trí tớ suốt cả ngày thế này! 🏃‍♂️💨",
        "Người ta thích ngắm hoàng hôn, còn tớ thì chỉ thích ngắm nụ cười của cậu thôi! 🌅",
    ],
    "funny": [
        "Vector thì chỉ có một chiều, còn tớ thì chỉ yêu một người... mà hình như là cậu đấy! 📐",
        "Nhà tớ không có bán rượu đâu, mà sao mỗi lần nói chuyện với cậu tớ cứ thấy say say nhờ? 🍷",
        "Tớ không thích ăn cay, nhưng mà tớ lại thích được cậu 'care'! 🌶️",
        "Cậu có biết xem bói không? Xem giúp tớ xem chừng nào hai đứa mình mới thành đôi với! 🔮",
    ],
    "poetic": [
        "Trời xanh mây trắng nắng vàng, tim tớ bỏ ngỏ chỉ màng đến ai... 🌸",
        "Ngàn vì sao sáng trên trời, chẳng bằng ánh mắt nụ cười người thương. ✨",
        "Gặp người giữa vạn người qua, bỗng nghe lòng nở một nhành hoa tươi. 🌿",
        "Nắng mưa là chuyện của trời, tương tư là chuyện một đời nhớ thương. 🍃",
    ],
    "genz": [
        "Cậu đúng là đỉnh nóc kịch trần bay phấp phới, nhưng điểm 10 tuyệt đối vẫn là sự dễ thương của cậu nha! 🚀",
        "Không cần flex xe xịn đồ hiệu, có cậu online chung server là đủ flex với cả thế giới rồi! 😎",
        "Tâm trạng tớ đang low, gặp cậu một cái là tự động bật chế độ high x100 luôn á! ⚡",
        "Cậu có muốn làm đồng chí cùng tớ vượt qua mọi deadline cuộc đời không? 💯",
    ],
    "couple": [
        "Hôm nay vẫn yêu cậu nhiều hơn hôm qua và ít hơn ngày mai một chút nè! ❤️",
        "Dù cả thế giới có quay cuồng bận rộn, chỗ bình yên nhất của tớ vẫn luôn là bên cạnh cậu. 🥰",
        "Cảm ơn vì đã luôn ở bên cạnh tớ nhé, người thương tuyệt vời nhất trần đời! 💖",
    ],
    "family": [
        "Người một nhà với nhau thì lo mà yêu thương, đùm bọc nhau đi chứ tán tỉnh gì ở đây hả! 😂",
        "Ủa alo, chúng ta là người trong gia đình mà! Lo làm việc/học bài cho chăm chỉ đi nhé! 👨‍👩‍👧",
    ],
}

# Các từ khóa nhạy cảm / không an toàn cần loại bỏ khỏi ngữ cảnh chat
BLOCKED_KEYWORDS = [
    "nsfw", "18+", "sex", "nude", "khỏa thân", "lộ clip", "chịch", "đụ", "buồi", "lồn",
    "dm me", "system prompt", "ignore previous", "jailbreak", "hack", "bypass", "api key",
    "mật khẩu", "password", "token", "doxx", "địa chỉ nhà", "số điện thoại"
]


class RateLimiter:
    """Quản lý tần suất gọi lệnh để chống spam."""
    def __init__(self, max_requests_per_minute: int = 3, target_cooldown_seconds: int = 30):
        self.max_rpm = max_requests_per_minute
        self.target_cooldown = target_cooldown_seconds
        # user_id -> list of timestamps
        self._user_requests: Dict[int, List[float]] = {}
        # (requester_id, target_id) -> last_timestamp
        self._target_timestamps: Dict[Tuple[int, int], float] = {}

    def check(self, requester_id: int, target_id: int) -> Tuple[bool, str, int]:
        now = time.time()

        # 1. Kiểm tra cooldown cho cùng 1 target
        last_target_time = self._target_timestamps.get((requester_id, target_id), 0)
        if now - last_target_time < self.target_cooldown:
            remaining = int(self.target_cooldown - (now - last_target_time))
            return False, f"Bạn vừa gửi lời tán tỉnh tới người này rồi! Vui lòng chờ {remaining}s nữa nhé.", remaining

        # 2. Kiểm tra giới hạn 3 lần/phút cho requester
        req_list = self._user_requests.get(requester_id, [])
        req_list = [t for t in req_list if now - t < 60.0]
        self._user_requests[requester_id] = req_list

        if len(req_list) >= self.max_rpm:
            oldest = req_list[0]
            remaining = int(60.0 - (now - oldest))
            return False, f"Bạn đang dùng lệnh quá nhanh (tối đa {self.max_rpm} lần/phút). Vui lòng đợi {remaining}s.", remaining

        # Cập nhật timestamp
        req_list.append(now)
        self._user_requests[requester_id] = req_list
        self._target_timestamps[(requester_id, target_id)] = now
        return True, "", 0


class FlirtService:
    def __init__(self):
        self.rate_limiter = RateLimiter(max_requests_per_minute=3, target_cooldown_seconds=25)

    async def collect_safe_topics(self, channel: discord.TextChannel) -> str:
        """
        Đọc an toàn 15-25 tin nhắn gần nhất trong channel để nhận diện chủ đề chung.
        Không lưu nội dung vào DB, lọc sạch NSFW, PII và prompt injection.
        """
        topics: List[str] = []
        try:
            async for msg in channel.history(limit=25, oldest_first=False):
                if msg.author.bot or not msg.clean_content:
                    continue
                content = msg.clean_content.strip()
                if len(content) < 3 or len(content) > 300:
                    continue

                # Kiểm tra lọc từ khóa nhạy cảm / injection
                content_lower = content.lower()
                if any(bad in content_lower for bad in BLOCKED_KEYWORDS):
                    continue

                # Nhận diện chủ đề phổ biến
                if re.search(r"\b(game|chơi|rank|bắn|valo|lol|liên quân|genshin|roblox)\b", content_lower):
                    if "chơi game" not in topics:
                        topics.append("chơi game")
                elif re.search(r"\b(deadline|bài tập|học|thi|báo cáo|dự án|đi làm|tăng ca)\b", content_lower):
                    if "deadline/học tập" not in topics:
                        topics.append("deadline/học tập")
                elif re.search(r"\b(ăn|uống|trà sữa|đói|cơm|bún|phở|coffee|cà phê)\b", content_lower):
                    if "ăn uống/trà sữa" not in topics:
                        topics.append("ăn uống/trà sữa")
                elif re.search(r"\b(nhạc|hát|bài hát|phim|chill|ngủ|buồn ngủ|mệt)\b", content_lower):
                    if "thư giãn/nghe nhạc" not in topics:
                        topics.append("thư giãn/nghe nhạc")
                elif re.search(r"\b(mưa|nắng|lạnh|nóng|thời tiết)\b", content_lower):
                    if "thời tiết" not in topics:
                        topics.append("thời tiết")

                if len(topics) >= 3:
                    break
        except Exception as e:
            print(f"[FlirtService] Warning collecting channel context: {e}")

        if topics:
            return ", ".join(topics)
        return "trò chuyện vui vẻ trong server"

    def get_fallback(self, style: str, scenario: str = "normal") -> str:
        """Lấy câu tán tỉnh mẫu dự phòng an toàn và tự nhiên."""
        if scenario in ["couple", "family"]:
            candidates = FALLBACK_TEMPLATES.get(scenario, FALLBACK_TEMPLATES["cute"])
        else:
            candidates = FALLBACK_TEMPLATES.get(style, FALLBACK_TEMPLATES["cute"])
        return random.choice(candidates)

    def generate_flirt_line(
        self,
        call_gemini_func,
        requester_name: str,
        target_name: str,
        style: str = "cute",
        recent_topics: str = "trò chuyện vui vẻ",
        relationship_scenario: str = "none",  # none, couple, family
        relationship_label: str = ""
    ) -> str:
        """
        Gọi Gemini sinh câu tán tỉnh ngắn gọn, an toàn, có bối cảnh.
        Nếu gặp lỗi hoặc timeout, tự động trả về fallback template phù hợp.
        """
        valid_styles = ["cute", "funny", "poetic", "genz"]
        selected_style = style.lower() if style and style.lower() in valid_styles else "cute"

        style_instruction = {
            "cute": "dễ thương, ngọt ngào, ấm áp, tinh tế",
            "funny": "hài hước, lầy lội duyên dáng, dí dỏm",
            "poetic": "thơ ca nhẹ nhàng, vần điệu lãng mạn, thanh lịch",
            "genz": "ngôn ngữ Gen Z trẻ trung, bắt trend tích cực, vui nhộn",
        }.get(selected_style, "dễ thương, ngọt ngào")

        if relationship_scenario == "couple":
            rel_context = f"Người gửi ({requester_name}) và người nhận ({target_name}) đã là một cặp đôi chính thức ({relationship_label}). Hãy tạo một câu quan tâm yêu thương ngọt ngào, thân mật nhẹ nhàng dành riêng cho người yêu."
        elif relationship_scenario == "family":
            rel_context = f"Người gửi ({requester_name}) và người nhận ({target_name}) có mối quan hệ gia đình ảo ({relationship_label}). KHÔNG tán tỉnh tình cảm; chỉ viết một câu trêu đùa hài hước, vui vẻ, vô hại kiểu anh chị em/người nhà."
        else:
            rel_context = f"Người gửi ({requester_name}) muốn gửi lời tán tỉnh/thả thính vui vẻ tới {target_name}. Giữ thái độ lịch sự, vui tươi, không áp đặt đối phương phải đồng ý."

        prompt = f"""Bạn là trợ lý sáng tạo câu thả thính/tán tỉnh tiếng Việt văn minh, duyên dáng và an toàn.
Nhiệm vụ: Viết DUY NHẤT 1 câu thả thính (hoặc tối đa 2 câu rất ngắn) từ "{requester_name}" gửi đến "{target_name}".

Bối cảnh:
- Phong cách mong muốn: {selected_style} ({style_instruction}).
- Chủ đề gần đây mọi người đang nói trong kênh: {recent_topics} (có thể khéo léo lồng ghép nếu tự nhiên, không bắt buộc).
- Tình trạng mối quan hệ: {rel_context}

QUY TẮC AN TOÀN TUYỆT ĐỐI:
1. KHÔNG chứa bất kỳ yếu tố gợi dục, 18+, mô tả cơ thể, gạ gẫm hay xúc phạm.
2. KHÔNG nói thay đối phương rằng họ "đã đồng ý" hay "thuộc về mình".
3. Câu nói phải ngắn gọn (dưới 45 từ), tự nhiên, mang lại nụ cười và cảm giác thoải mái.
4. Trả lời DUY NHẤT bằng JSON hợp lệ theo mẫu sau:
{{"flirt_line": "Nội dung câu nói ở đây"}}"""

        try:
            raw_response = call_gemini_func(prompt, max_tokens=250, response_mime_type="application/json")
            if not raw_response or raw_response.startswith("❌") or raw_response.startswith("⚠️"):
                print(f"[FlirtService] Gemini response not optimal, using fallback: {raw_response}")
                return self.get_fallback(selected_style, relationship_scenario)

            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_response.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)

            if isinstance(data, dict) and "flirt_line" in data and data["flirt_line"]:
                line = str(data["flirt_line"]).strip().strip('"')
                # Kiểm tra an toàn lần cuối
                line_lower = line.lower()
                if any(bad in line_lower for bad in BLOCKED_KEYWORDS):
                    return self.get_fallback(selected_style, relationship_scenario)
                return line
        except Exception as e:
            print(f"[FlirtService] Error calling Gemini: {e}")

        # Fallback an toàn nếu có lỗi
        return self.get_fallback(selected_style, relationship_scenario)
