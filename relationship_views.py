"""
Discord UI Views for Relationship Proposals (Buttons & Interactive Confirmation).
"""

from typing import Optional, Dict
import discord

RELATIONSHIP_NAMES: Dict[str, str] = {
    "dating": "Hẹn hò / Người yêu 💖",
    "married": "Kết hôn / Vợ chồng 💍",
    "family": "Gia đình / Người nhà 🏡",
    "friend": "Bạn thân / Tri kỷ 🤝",
    "ex": "Người cũ 🥀",
}


class ProposalView(discord.ui.View):
    """View chứa 2 nút Đồng ý / Từ chối cho lời đề nghị mối quan hệ hai chiều."""

    def __init__(
        self,
        db_repo,
        guild_id: int,
        requester: discord.Member,
        target: discord.Member,
        relationship_type: str,
        timeout: float = 120.0
    ):
        super().__init__(timeout=timeout)
        self.db = db_repo
        self.guild_id = guild_id
        self.requester = requester
        self.target = target
        self.relationship_type = relationship_type
        self.type_name = RELATIONSHIP_NAMES.get(relationship_type, relationship_type)
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Chỉ cho phép người được đề nghị (target) bấm nút phản hồi."""
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                f"⚠️ Lời đề nghị này được gửi riêng cho {self.target.mention}. Bạn không thể bấm thay người khác!",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Đồng ý", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Lưu vào database mối quan hệ active đã xác nhận 2 phía
        success = self.db.save_relationship(
            guild_id=self.guild_id,
            u1_id=self.requester.id,
            u2_id=self.target.id,
            relationship_type=self.relationship_type,
            status="active",
            confirmed_by_a=True,
            confirmed_by_b=True,
            source_id=str(interaction.id)
        )

        # Vô hiệu hóa nút
        for child in self.children:
            child.disabled = True

        if success:
            embed = discord.Embed(
                title="🎉 Mối Quan Hệ Đã Được Thiết Lập!",
                description=(
                    f"Chúc mừng {self.target.mention} đã chính thức **đồng ý** lời đề nghị từ {self.requester.mention}!\n\n"
                    f"✨ Mối quan hệ: **{self.type_name}**\n"
                    f"Server: **{interaction.guild.name if interaction.guild else ''}**"
                ),
                color=discord.Color.pink() if self.relationship_type in ["dating", "married"] else discord.Color.green(),
            )
            embed.set_footer(text="Dữ liệu đã được lưu trữ bền vững vào hệ thống.")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("❌ Có lỗi xảy ra khi lưu dữ liệu. Vui lòng thử lại sau!", ephemeral=True)

        self.stop()

    @discord.ui.button(label="Từ chối", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="💔 Lời Đề Nghị Bị Từ Chối",
            description=f"{self.target.mention} đã từ chối lời đề nghị mối quan hệ từ {self.requester.mention}.",
            color=discord.Color.dark_grey()
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                embed = discord.Embed(
                    title="⏱️ Lời Đề Nghị Đã Hết Hạn",
                    description=f"Lời đề nghị mối quan hệ giữa {self.requester.mention} và {self.target.mention} đã hết thời gian phản hồi (120s).",
                    color=discord.Color.light_grey()
                )
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass
