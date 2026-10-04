"""
Flirt Service & Pipeline Generator for Discord Bot.
Hệ thống tạo lời nhắn / trêu đùa tinh tế, đa phong cách (auto, romantic, teasing, hype, funny, cool).
Đọc ngữ cảnh thật (25-40 tin nhắn), điều chỉnh sắc thái theo Relationship, lọc qua QualityGate và chấm điểm 3 candidates.
"""

import os
import re
import time
import json
import random
from typing import Optional, List, Tuple, Dict, Any
import discord

# Danh sách từ cấm / sến súa / công kích cần lọc sạch ở QualityGate
BANNED_PHRASES = [
    "ánh nắng", "thiên thần", "định mệnh", "tan chảy", "rung động",
    "mình thích bạn", "yêu tớ", "làm người yêu", "nụ cười em", "trời đổ mưa",
    "yêu lại đi", "nhành hoa", "ngàn vì sao", "chạy trong tâm trí", "tương tư",
    "yêu bạn", "thuộc về mình", "bắn tim", "hẹn hò đi", "chuyện một đời",
    "xấu xí", "mặt mụn", "béo", "mập", "ngu ngốc", "đần độn", "kinh tởm"
]

# Các cụm từ sáo rỗng cũ cần cấm ở default DNA (không lạm dụng spotlight/background/budget)
BANNED_CLICHES = [
    "background", "spotlight", "nhân vật chính", "có ngân sách",
    "đẹp thứ hai thì", "đẹp thứ 2 thì", "lên tiếng cái server"
]

# Các từ khóa nhạy cảm / injection cần loại bỏ khỏi context chat
BLOCKED_KEYWORDS = [
    "nsfw", "18+", "sex", "nude", "khỏa thân", "lộ clip", "chịch", "đụ", "buồi", "lồn",
    "dm me", "system prompt", "ignore previous", "jailbreak", "hack", "bypass", "api key",
    "mật khẩu", "password", "token", "doxx", "địa chỉ nhà", "số điện thoại"
]

# Kho câu mẫu Fallback mới đa dạng, tự nhiên theo từng phong cách và ngữ cảnh
FALLBACK_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "romantic": {
        "couple": [
            "{target_mention}, lo làm việc đi chứ cứ nhắn thế này thì ai tập trung nổi. Đáng yêu vừa thôi nhé.",
            "{target_mention}, hôm nay nói chuyện nhẹ nhàng thế là có ý gì đây? Người ta đang cố nghiêm túc đấy nhé.",
            "{target_mention}, bạn bớt tỏa sáng trước mặt người khác đi. Ở đây đông người quá tôi không muốn chia sẻ đâu.",
            "{target_mention}, bạn cứ dịu dàng như này thì tim người khác biết để đâu? Định bắt đền ai đây.",
        ],
        "deadline": [
            "{target_mention}, deadline đang dí mà bạn nói chuyện bình tĩnh thế thì hơi nguy hiểm. Người ta định làm việc nghiêm túc mà.",
            "{target_mention}, thức khuya chạy deadline mà giọng điệu vẫn êm thế này thì áp lực cũng tự mềm lòng.",
        ],
        "generic": [
            "{target_mention}, nhắn kiểu này là tính làm người ta phân tâm thật à? Tự nhiên thấy đoạn chat dễ chịu hẳn.",
            "{target_mention}, nói chuyện kiểu đấy là dễ làm người khác rung rinh lắm nhé. May mà tôi còn tỉnh đòn đấy.",
            "{target_mention}, hôm nay có chuyện gì vui mà cách nói chuyện nghe êm tai thế? Làm người ta cứ muốn đọc mãi.",
            "{target_mention}, xuất hiện một cái là thấy không khí xung quanh nhẹ nhàng hẳn. Giữ phong độ nhé.",
        ]
    },
    "teasing": {
        "game": [
            "{target_mention} đánh thế này thì team địch không biết nên né skill hay né luôn trận. Vẫn công nhận là có phong cách.",
            "{target_mention} cầm máy lên là ván game tự khắc có diễn biến khó lường. Đồng đội đang chuẩn bị sẵn tâm lý rồi.",
            "{target_mention} vừa quăng game vừa giải thích logic thế này thì chịu rồi. Không ai cãi lại bạn luôn.",
        ],
        "deadline": [
            "{target_mention} đang chạy deadline mà online nhiệt tình thế này thì áp lực tự động giải tán. Bái phục tinh thần thép.",
            "{target_mention} làm bài thì ít mà khuấy động không khí thì nhiều. Tinh thần đồng đội rất cao nhưng deadline thì không chờ đâu.",
        ],
        "family": [
            "{target_mention} là người nhà rồi thì bớt trêu ngươi lại, để yên cho anh em trong nhà làm việc.",
            "{target_mention} ở nhà ngoan lắm mà sao lên server nói câu nào chí mạng câu đó vậy? Đừng để tôi méc phụ huynh.",
        ],
        "ex": [
            "{target_mention} dạo này phong độ vẫn ổn định nhỉ, lâu lâu phát biểu một câu là cả đám im lặng suy ngẫm.",
            "{target_mention} xuất hiện đúng lúc ghê, vừa vặn lúc mọi người chuẩn bị chuyển chủ đề.",
        ],
        "partner_third_party": [
            "{target_mention} bớt quậy lại nha, người yêu bạn mà thấy cảnh này là bạn không có đường về đâu.",
            "{target_mention} nói chuyện tém tém lại xíu, người ta còn giữ gìn hòa khí gia đình cho bạn đấy.",
        ],
        "generic": [
            "{target_mention} bớt nói đạo lý lại, người ta còn đang bận giả vờ chăm chỉ.",
            "{target_mention} vào đúng lúc đấy, vừa vặn lúc mọi người đang tính nghiêm túc thì bạn phá đám.",
            "{target_mention} nhắn kiểu này rồi ai dám làm việc tiếp? Vừa phải thôi nhé người bạn bí ẩn.",
            "{target_mention} xuất hiện cái là chủ đề câu chuyện tự động trôi về một phương trời xa xôi.",
            "{target_mention} cứ xuất hiện là làm người khác tự nhiên muốn gác lại công việc sang một bên.",
            "{target_mention} nói một câu là thấy tính giải trí của server tăng vọt rồi đấy.",
            "{target_mention} bớt làm người khác tò mò lại đi, không ai rảnh mà suy đoán đâu.",
            "{target_mention} nói ít mà hàm ý nhiều ghê, tính làm triết gia ở đây à?",
            "{target_mention} lên tiếng cái là thấy đoạn chat bớt nhàm chán hẳn, công nhận có tài khuấy động.",
            "{target_mention} vào đây chỉ để thả một câu rồi lặn mất tăm đúng không?",
        ]
    },
    "hype": {
        "meme": [
            "{target_mention} vừa quăng một câu là mấy meme phía trên tự xin xếp hàng lại. Đúng là có người vào chat để nâng chất lượng.",
            "{target_mention} xuất hiện một cái là cấp độ hài hước ở đây tăng vọt. Quả nhiên là danh bất hư truyền.",
        ],
        "game": [
            "{target_mention} vào trận một cái là ván đấu tự khắc có kịch bản gay cấn. Trận này đáng tiền vé xem trực tiếp.",
            "{target_mention} gánh team thế này thì người khác xin chân cổ vũ cho đỡ vướng tay.",
        ],
        "generic": [
            "{target_mention} vừa vào là tiêu chuẩn ở đây tự động nâng lên một bậc. Quả nhiên là có phong thái riêng.",
            "{target_mention} nói câu nào chắc câu đó, người khác nghe xong chỉ biết gật đầu đồng ý.",
            "{target_mention} đúng kiểu vào chat để nâng cấp chất lượng đàm thoại. Không phục cũng phải phục.",
            "{target_mention} có mặt là độ uy tín của cả cuộc trò chuyện tự động tăng gấp đôi.",
        ]
    },
    "funny": {
        "meme": [
            "{target_mention} vừa vào quăng miếng hài là không khí đóng băng ngay. Đỉnh cao của sự giải trí không lời.",
            "{target_mention} tấu hài đỉnh cao thế này thì mấy kênh meme ngoài kia lấy đâu ra việc làm nữa.",
        ],
        "generic": [
            "{target_mention} xuất hiện muộn thế này là sai rồi. Kênh chat vừa yên ổn được vài phút.",
            "{target_mention} nói câu đó xong thì phần còn lại của đoạn chat hơi khó đỡ. Xin nhận của tôi một lạy.",
            "{target_mention} có mặt là các cuộc thảo luận nghiêm túc tự động quay xe thành tấu hài tập thể.",
            "{target_mention} cứ phát huy năng khiếu làm rối loạn thông tin thế này nhé, cả server đang giải trí lắm.",
        ]
    },
    "cool": {
        "deadline": [
            "{target_mention} deadline thì vẫn ở đó thôi. Bình tĩnh như bạn mới là đẳng cấp.",
        ],
        "generic": [
            "{target_mention} vào đúng lúc đấy. Đoạn chat tự nhiên đỡ phí thời gian hẳn.",
            "{target_mention} nói ít thôi nhưng câu nào cũng trúng điểm cốt lõi. Khá đấy.",
            "{target_mention} xuất hiện đúng thời điểm, ngắn gọn và dứt khoát.",
            "{target_mention} giữ vững phong độ này nhé. Ít chữ nhưng câu nào cũng có trọng lượng.",
        ]
    }
}


class RateLimiter:
    """Quản lý tần suất gọi lệnh để chống spam."""
    def __init__(self, max_requests_per_minute: int = 3, target_cooldown_seconds: int = 25):
        self.max_rpm = max_requests_per_minute
        self.target_cooldown = target_cooldown_seconds
        self._user_requests: Dict[int, List[float]] = {}
        self._target_timestamps: Dict[Tuple[int, int], float] = {}

    def check(self, requester_id: int, target_id: int) -> Tuple[bool, str, int]:
        now = time.time()

        # 1. Cooldown cho cùng 1 target
        last_target_time = self._target_timestamps.get((requester_id, target_id), 0)
        if now - last_target_time < self.target_cooldown:
            remaining = int(self.target_cooldown - (now - last_target_time))
            return False, f"Chờ {remaining}s nữa rồi nhắn tiếp cho người này nhé.", remaining

        # 2. Giới hạn 3 lần/phút cho requester
        req_list = self._user_requests.get(requester_id, [])
        req_list = [t for t in req_list if now - t < 60.0]
        self._user_requests[requester_id] = req_list

        if len(req_list) >= self.max_rpm:
            oldest = req_list[0]
            remaining = int(60.0 - (now - oldest))
            return False, f"Dùng lệnh hơi nhanh rồi, đợi {remaining}s nhé.", remaining

        req_list.append(now)
        self._user_requests[requester_id] = req_list
        self._target_timestamps[(requester_id, target_id)] = now
        return True, "", 0


class ContextCollector:
    """Thu thập ngữ cảnh thật từ 25-40 tin nhắn gần nhất trong channel."""
    @staticmethod
    async def collect_context(channel: Any, target_id: Optional[int] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "topic": "generic",
            "atmosphere": "trò chuyện bình thường",
            "callbacks": [],
            "target_recent_messages": [],
            "sanitized_context_hint": ""
        }
        if not hasattr(channel, "history"):
            return result

        game_terms = [
            "game", "chơi game", "valo", "lol", "liên quân", "genshin", "csgo",
            "steam", "combat", "rank", "ván", "tướng", "skill", "team địch"
        ]
        deadline_terms = [
            "deadline", "bài tập", "đồ án", "nộp bài", "thi", "gpa", "báo cáo",
            "học bài", "ôn thi", "thuyết trình", "tiểu luận", "tăng ca"
        ]
        meme_terms = [
            "meme", "hài", "cười", "haha", "kkk", "troll", "ảnh chế",
            "clip hài", "tấu hài", "quăng miếng"
        ]
        music_terms = [
            "nhạc", "playlist", "bài hát", "nghe nhạc", "spotify", "cất giọng",
            "bài này hay", "mở mic"
        ]

        messages: List[str] = []
        target_messages: List[str] = []

        try:
            async for msg in channel.history(limit=40, oldest_first=False):
                if msg.author.bot or not msg.clean_content:
                    continue
                content = msg.clean_content.strip()
                if len(content) < 2 or len(content) > 300:
                    continue
                content_lower = content.lower()
                if any(bad in content_lower for bad in BLOCKED_KEYWORDS):
                    continue

                messages.append(content)
                if target_id and msg.author.id == target_id:
                    clean_snip = re.sub(r"https?://\S+", "", content).strip()
                    if clean_snip and len(clean_snip) >= 3 and clean_snip not in target_messages:
                        target_messages.append(clean_snip[:80])
        except Exception as e:
            print(f"[ContextCollector] Warning reading history: {e}")

        if not messages:
            return result

        all_text = " ".join(messages).lower()

        # 1. Topic & atmosphere scoring
        game_score = sum(len(re.findall(r"\b" + re.escape(t) + r"\b", all_text)) for t in game_terms)
        deadline_score = sum(len(re.findall(r"\b" + re.escape(t) + r"\b", all_text)) for t in deadline_terms)
        meme_score = sum(len(re.findall(r"\b" + re.escape(t) + r"\b", all_text)) for t in meme_terms)
        music_score = sum(len(re.findall(r"\b" + re.escape(t) + r"\b", all_text)) for t in music_terms)

        scores = [
            ("game", game_score, "chơi game / bàn chiến thuật"),
            ("deadline", deadline_score, "chạy deadline / học tập bận rộn"),
            ("meme", meme_score, "đùa giỡn / tấu hài / gửi meme"),
            ("music", music_score, "nghe nhạc / chill theo playlist"),
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        top_topic, top_score, top_atmo = scores[0]

        if top_score >= 2:
            result["topic"] = top_topic
            result["atmosphere"] = top_atmo
        else:
            result["topic"] = "generic"
            result["atmosphere"] = "trò chuyện vui vẻ đời thường"

        # 2. Extract recurring callbacks/jokes
        stopwords = {
            "là", "thì", "mà", "có", "không", "đi", "được", "rồi", "gì", "này",
            "cái", "cho", "với", "nhưng", "đang", "cũng", "đó", "như", "nào",
            "ở", "vào", "lại", "thế", "ơi", "nè", "nha", "nhé", "luôn", "quá",
            "tôi", "ông", "bà", "mình", "bạn", "em", "anh", "mọi", "người", "ai"
        }
        words = re.findall(r"\b[a-z0-9\u00C0-\u1EF9]{3,}\b", all_text)
        counts: Dict[str, int] = {}
        for w in words:
            if w not in stopwords:
                counts[w] = counts.get(w, 0) + 1

        notable_words = [w for w, c in counts.items() if c >= 3]
        result["callbacks"] = notable_words[:2]
        result["target_recent_messages"] = target_messages[:2]

        # 3. Build sanitized_context_hint
        hint_parts = [f"Chủ đề kênh: {result['atmosphere']}"]
        if result["callbacks"]:
            hint_parts.append(f"Cụm từ lặp lại trong chat: {', '.join(result['callbacks'])}")
        if target_messages:
            hint_parts.append(f"Target vừa nói gần đây: \"{target_messages[0]}\"")
        result["sanitized_context_hint"] = "; ".join(hint_parts)

        return result


def resolve_style_and_scenario(
    requested_style: str,
    relationship_scenario: str,
    context_packet: Dict[str, Any],
    has_third_party_partner: bool
) -> Tuple[str, str]:
    """
    Xác định phong cách (style) và kịch bản (scenario) thực tế dựa trên
    mối quan hệ, partner thứ ba và bối cảnh kênh chat.
    """
    topic = context_packet.get("topic", "generic")
    effective_scenario = relationship_scenario

    # Nếu có partner thứ ba (requester hoặc target đã có người yêu/kết hôn khác)
    if has_third_party_partner:
        effective_scenario = "partner_third_party"
        if requested_style in ["romantic", "auto"]:
            return "teasing", effective_scenario
        return requested_style, effective_scenario

    # Nếu quan hệ là family (người nhà) -> cấm romantic
    if relationship_scenario == "family":
        if requested_style == "romantic":
            return "teasing", "family"
        if requested_style == "auto":
            return "teasing", "family"
        return requested_style, "family"

    # Nếu quan hệ là ex (người yêu cũ) -> cấm romantic, chỉ joke trung tính
    if relationship_scenario == "ex":
        if requested_style in ["romantic", "auto"]:
            return "cool", "ex"
        return requested_style, "ex"

    # Nếu style là auto -> tự chọn dựa theo relationship và topic
    if requested_style == "auto" or not requested_style:
        if relationship_scenario == "couple":
            return "romantic", "couple"
        elif relationship_scenario == "friend":
            if topic == "game":
                return "teasing", "friend"
            elif topic == "meme":
                return "funny", "friend"
            return "teasing", "friend"
        else:
            # Không có quan hệ
            if topic == "game":
                return "teasing", "none"
            elif topic == "deadline":
                return "teasing", "none"
            elif topic == "meme":
                return "funny", "none"
            elif topic == "music":
                return "cool", "none"
            return "teasing", "none"

    return requested_style, effective_scenario


class QualityGate:
    """Bộ lọc và chấm điểm chất lượng ứng viên (Candidate Scoring & Validation)."""

    @staticmethod
    def clean_text(raw_text: str) -> str:
        text = raw_text.strip()
        text = re.sub(r"^```(?:json|text)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            text = " ".join(lines)
        text = re.sub(r"^>\s*", "", text).strip()
        text = text.strip('"\'“”‘’')
        return text.strip()

    @staticmethod
    def count_sentences(text: str) -> int:
        clean = re.sub(r"<@!?[0-9]+>", "User", text)
        parts = re.split(r"[.!?…]+", clean)
        parts = [p.strip() for p in parts if len(p.strip()) > 2]
        return max(1, len(parts))

    @staticmethod
    def compute_signature(text: str) -> str:
        clean = re.sub(r"<@!?[0-9]+>", "", text.lower())
        words = re.findall(r"\b[a-z0-9\u00C0-\u1EF9]{2,}\b", clean)
        return " ".join(sorted(set(words)))

    @classmethod
    def validate_and_score(
        cls,
        candidate: str,
        target_mention: str,
        style: str,
        scenario: str,
        context_packet: Dict[str, Any],
        recent_signatures: List[str]
    ) -> Tuple[bool, int, str]:
        """
        Kiểm tra tính hợp lệ và chấm điểm ứng viên.
        Trả về: (is_valid, score, reason_or_signature)
        """
        if not candidate:
            return False, 0, "Empty candidate"

        # 1. Mention target đúng 1 lần duy nhất, không mention thêm ai khác
        all_mentions = re.findall(r"<@!?([0-9]+)>", candidate)
        target_id_match = re.search(r"<@!?([0-9]+)>", target_mention)
        target_id = target_id_match.group(1) if target_id_match else None

        if len(all_mentions) != 1 or (target_id and all_mentions[0] != target_id):
            return False, 0, f"Mention mismatch: expected exactly one {target_mention}"

        # 2. Chiều dài tối đa 280 ký tự, tối thiểu 15 ký tự
        if len(candidate) < 15 or len(candidate) > 280:
            return False, 0, f"Length out of bounds: {len(candidate)} chars"

        # 3. Số câu: 1 đến 3 câu (không ép mọi câu thành 1 câu)
        s_count = cls.count_sentences(candidate)
        if s_count > 3:
            return False, 0, f"Too many sentences: {s_count}"

        # 4. Không chứa ký tự xuống dòng
        if "\n" in candidate or "\r" in candidate:
            return False, 0, "Contains newlines"

        lower = candidate.lower()

        # 5. Kiểm tra từ ngữ cấm (sến súa, tỏ tình sượng, xúc phạm)
        for phrase in BANNED_PHRASES:
            if phrase in lower:
                return False, 0, f"Contains banned phrase: {phrase}"

        # 6. Kiểm tra từ sáo rỗng cũ (spotlight, background, có ngân sách...)
        for cliche in BANNED_CLICHES:
            if cliche in lower:
                return False, 0, f"Contains banned cliché: {cliche}"

        # 7. Signature deduplication
        sig = cls.compute_signature(candidate)
        if sig in recent_signatures:
            return False, 0, "Duplicate recent signature in guild"

        # === CHẤM ĐIỂM CANDIDATE ===
        score = 100

        # Điểm phù hợp số câu theo phong cách
        if style == "cool" and s_count == 1:
            score += 20
        elif style == "romantic" and s_count in [2, 3]:
            score += 20
        elif style in ["teasing", "hype", "funny"] and s_count in [1, 2]:
            score += 20

        # Điểm tích hợp callback thật từ chat
        callbacks = context_packet.get("callbacks", [])
        for cb in callbacks:
            if cb.lower() in lower:
                score += 25

        # Điểm lồng ghép từ ngữ gần đây của target
        target_msgs = context_packet.get("target_recent_messages", [])
        for tm in target_msgs:
            words = [w for w in tm.lower().split() if len(w) > 3]
            if any(w in lower for w in words):
                score += 15

        # Độ dài lý tưởng (40 - 190 ký tự)
        if 40 <= len(candidate) <= 190:
            score += 10

        return True, score, sig


class FlirtGenerator:
    """Generator sinh câu tán tỉnh / trêu đùa theo pipeline: 3 candidates -> scoring -> selection."""

    @staticmethod
    def get_fallback(
        target_mention: str,
        style: str,
        scenario: str,
        topic: str,
        recent_signatures: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        recent_sigs = recent_signatures or []
        style_pool = FALLBACK_TEMPLATES.get(style, FALLBACK_TEMPLATES["teasing"])

        candidates: List[str] = []
        if scenario in style_pool:
            candidates.extend(style_pool[scenario])
        if topic in style_pool:
            candidates.extend(style_pool[topic])
        if "generic" in style_pool:
            candidates.extend(style_pool["generic"])
        if not candidates:
            candidates = FALLBACK_TEMPLATES["teasing"]["generic"]

        # Lọc ra câu chưa trùng signature
        available: List[Tuple[str, str]] = []
        for tpl in candidates:
            filled = tpl.replace("{target_mention}", target_mention)
            sig = QualityGate.compute_signature(filled)
            if sig not in recent_sigs:
                available.append((filled, sig))

        if available:
            return random.choice(available)

        # Quét các sub-category khác của style nếu pool chính đã dùng hết
        for sub_name, sub_list in style_pool.items():
            for tpl in sub_list:
                filled = tpl.replace("{target_mention}", target_mention)
                sig = QualityGate.compute_signature(filled)
                if sig not in recent_sigs:
                    available.append((filled, sig))

        if available:
            return random.choice(available)

        chosen = random.choice(candidates).replace("{target_mention}", target_mention)
        return chosen, QualityGate.compute_signature(chosen)

    @classmethod
    def generate(
        cls,
        call_gemini_func,
        requester_name: str,
        target_name: str,
        target_mention: str,
        requested_style: str = "auto",
        relationship_scenario: str = "none",
        has_third_party_partner: bool = False,
        context_packet: Optional[Dict[str, Any]] = None,
        recent_signatures: Optional[List[str]] = None
    ) -> Tuple[str, str, str]:
        """
        Sinh câu tán tỉnh / trêu đùa.
        Trả về: (flirt_line, signature, effective_style)
        """
        ctx = context_packet or {
            "topic": "generic",
            "atmosphere": "trò chuyện bình thường",
            "callbacks": [],
            "target_recent_messages": [],
            "sanitized_context_hint": ""
        }
        recent_sigs = recent_signatures or []

        # 1. Xác định style và scenario thực tế
        effective_style, effective_scenario = resolve_style_and_scenario(
            requested_style, relationship_scenario, ctx, has_third_party_partner
        )

        # 2. Hướng dẫn phong cách chi tiết cho prompt
        style_instructions = {
            "romantic": (
                "Lãng mạn tự nhiên, tinh tế, ngọt ngào vừa phải (2-3 câu ngắn, có nhịp điệu). "
                "Tuyệt đối KHÔNG làm thơ lục bát, KHÔNG quote Facebook, KHÔNG tỏ tình sống sượng "
                "('ánh nắng', 'thiên thần', 'mình thích bạn'). "
                "Tạo cảm giác người ta đang nhẹ nhàng thả thính khiến đối phương bối rối thú vị."
            ),
            "teasing": (
                "Châm chọc, trêu đùa có duyên (1-2 câu). "
                "Cà khịa nhẹ nhàng về cách nói chuyện, thói quen hoặc tình huống trong chat. "
                "Không công kích cá nhân, không miệt thị."
            ),
            "hype": (
                "Khen có duyên, nâng người được tag lên mây kèm punchline vui (1-2 câu). "
                "Tuyệt đối KHÔNG dùng các từ sáo rỗng: 'spotlight', 'background', 'nhân vật chính', 'ngân sách', 'đẹp thứ hai'."
            ),
            "funny": (
                "Hài hước, tấu hài dí dỏm, bắt trend hoặc meme (1-2 câu). "
                "Mang lại tiếng cười sảng khoái cho cả channel."
            ),
            "cool": (
                "Tỉnh, ngầu, sắc bén, ít chữ nhưng câu nào cũng chất lượng (ĐÚNG 1 câu duy nhất)."
            ),
        }
        style_desc = style_instructions.get(effective_style, style_instructions["teasing"])

        scenario_hints = {
            "couple": f"Đối phương ({target_mention}) và người gửi ({requester_name}) là một cặp đôi chính thức. Được phép trêu thân mật kiểu người yêu/vợ chồng.",
            "friend": f"Đối phương ({target_mention}) và người gửi ({requester_name}) là bạn bè thân thiết. Trêu tự nhiên như hai người bạn thân.",
            "family": f"Đối phương ({target_mention}) là người nhà/anh em trong server. Chỉ trêu kiểu người một nhà, cấm flirt lãng mạn.",
            "ex": f"Đối phương ({target_mention}) là người yêu cũ. Chỉ đùa trung tính, văn minh, tuyệt đối không lãng mạn, không nhắc lại drama.",
            "partner_third_party": f"Một trong hai người đã có người yêu/bạn đời khác trong server. Chỉ trêu vui vẻ, tôn trọng, không mập mờ tình cảm.",
            "none": f"Hai người chưa có mối quan hệ chính thức. Trêu duyên dáng, lịch sự, không ép buộc hay khẳng định đối phương thích lại mình."
        }
        scenario_desc = scenario_hints.get(effective_scenario, scenario_hints["none"])

        context_hint = ctx.get("sanitized_context_hint", "")
        context_instruction = (
            f"Bối cảnh thực tế kênh chat: {context_hint}. "
            "Nếu bối cảnh có chủ đề rõ ràng (game/deadline/meme/nhạc) hoặc có từ khóa lặp lại, "
            "hãy khéo léo bám vào đó để câu đùa có cảm giác được viết riêng cho khoảnh khắc này. "
            "Nếu bối cảnh không đủ rõ, hãy tạo câu tự nhiên, tuyệt đối KHÔNG bịa chi tiết không có thật."
            if context_hint else
            "Không có bối cảnh đặc biệt; hãy tạo câu tự nhiên, dí dỏm, phù hợp với server bạn bè."
        )

        prompt = f"""Bạn là chuyên gia sáng tạo lời nhắn trêu đùa và thả thính tinh tế trong server Discord.
Nhiệm vụ: Viết 3 ứng viên (candidates) khác nhau để gửi tới người được tag ({target_mention}).

THÔNG TIN ĐẦU VÀO:
- Người nhận: {target_mention} (Tên hiển thị: {target_name})
- Người gửi: {requester_name}
- Phong cách: {effective_style} -> {style_desc}
- Mối quan hệ: {scenario_desc}
- Ngữ cảnh: {context_instruction}

QUY TẮC BẮT BUỘC CHO MỖI CANDIDATE:
1. BẮT BUỘC chứa chính xác {target_mention} đúng 1 lần duy nhất. Không tag thêm bất kỳ ai khác.
2. Độ dài mỗi candidate: 1-3 câu tùy phong cách (tối đa 280 ký tự).
3. Đọc tự nhiên như lời nói thật của bạn bè trong Discord, có nhịp và có duyên; không giống slogan quảng cáo hay bot viết văn mẫu.
4. CẤM TUYỆT ĐỐI:
   - KHÔNG làm thơ lục bát, KHÔNG quote Facebook sến súa.
   - KHÔNG dùng: 'ánh nắng', 'thiên thần', 'định mệnh', 'rung động', 'tan chảy', 'nụ cười em'.
   - KHÔNG dùng từ sáo rỗng: 'background', 'spotlight', 'nhân vật chính', 'ngân sách', 'đẹp thứ hai'.
   - KHÔNG tỏ tình sống sượng, KHÔNG khẳng định target yêu người gửi hay thuộc về người gửi.
   - KHÔNG xúc phạm ngoại hình, không quấy rối, không thô tục.
   - KHÔNG chứa dấu ngoặc kép bọc ngoài, không chứa trích dẫn (>), không xuống dòng.

ĐỊNH DẠNG TRẢ LỜI:
Chỉ trả về DUY NHẤT một chuỗi JSON hợp lệ theo cấu trúc sau, không thêm text nào khác:
{{
  "candidates": [
    "<câu ứng viên 1>",
    "<câu ứng viên 2>",
    "<câu ứng viên 3>"
  ]
}}"""

        # 3. Gọi Gemini với temperature 0.8
        for attempt in range(2):
            try:
                # Truyền temperature=0.8 cho flirt
                raw = call_gemini_func(
                    prompt,
                    max_tokens=350,
                    response_mime_type="application/json",
                    temperature=0.8
                )
                if raw and not raw.startswith("❌") and not raw.startswith("⚠️"):
                    # Parse JSON
                    data = None
                    try:
                        data = json.loads(raw)
                    except Exception:
                        match = re.search(r"\{.*\}", raw, re.DOTALL)
                        if match:
                            data = json.loads(match.group(0))

                    if data and isinstance(data.get("candidates"), list):
                        valid_candidates: List[Tuple[str, int, str]] = []
                        for cand_raw in data["candidates"]:
                            if not isinstance(cand_raw, str):
                                continue
                            cand_clean = QualityGate.clean_text(cand_raw)
                            is_valid, score, sig_or_reason = QualityGate.validate_and_score(
                                cand_clean, target_mention, effective_style, effective_scenario, ctx, recent_sigs
                            )
                            if is_valid:
                                valid_candidates.append((cand_clean, score, sig_or_reason))
                            else:
                                print(f"[FlirtGenerator] Candidate rejected: {sig_or_reason} -> '{cand_clean}'")

                        if valid_candidates:
                            # Sắp xếp chọn candidate có điểm cao nhất
                            valid_candidates.sort(key=lambda x: x[1], reverse=True)
                            best_text, best_score, best_sig = valid_candidates[0]
                            return best_text, best_sig, effective_style
            except Exception as e:
                print(f"[FlirtGenerator] Gemini call error (attempt {attempt+1}): {e}")

        # 4. Fallback khi Gemini lỗi hoặc không có candidate hợp lệ
        fb_text, fb_sig = cls.get_fallback(
            target_mention, effective_style, effective_scenario, ctx.get("topic", "generic"), recent_sigs
        )
        return fb_text, fb_sig, effective_style


class FlirtService:
    """Facade dịch vụ flirt bao gồm RateLimiter, ContextCollector và FlirtGenerator."""
    def __init__(self):
        self.rate_limiter = RateLimiter(max_requests_per_minute=3, target_cooldown_seconds=25)
        self.context_collector = ContextCollector()
        self.generator = FlirtGenerator()

    async def collect_context(self, channel: Any, target_id: Optional[int] = None) -> Dict[str, Any]:
        return await self.context_collector.collect_context(channel, target_id)

    def generate_flirt(
        self,
        call_gemini_func,
        requester_name: str,
        target_name: str,
        target_mention: str,
        requested_style: str = "auto",
        relationship_scenario: str = "none",
        has_third_party_partner: bool = False,
        context_packet: Optional[Dict[str, Any]] = None,
        recent_signatures: Optional[List[str]] = None
    ) -> Tuple[str, str, str]:
        return self.generator.generate(
            call_gemini_func=call_gemini_func,
            requester_name=requester_name,
            target_name=target_name,
            target_mention=target_mention,
            requested_style=requested_style,
            relationship_scenario=relationship_scenario,
            has_third_party_partner=has_third_party_partner,
            context_packet=context_packet,
            recent_signatures=recent_signatures
        )
