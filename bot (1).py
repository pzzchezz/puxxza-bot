import discord
from discord import app_commands
from discord.ext import commands, tasks
from aiohttp import web
import aiohttp
import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from database import (
    init_db, create_key, get_key, get_all_keys, delete_key,
    activate_key, get_user_key, verify_key_hwid, reset_hwid,
    cleanup_expired_keys, get_user_balance, add_balance,
    save_transaction, complete_transaction, get_transaction
)

# ========================================================
#  CONFIG
# ========================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
INWCLOUD_KEY  = os.getenv("INWCLOUD_API_KEY", "")
PORT          = int(os.getenv("PORT", "8080"))           # Render inject PORT อัตโนมัติ
ADMIN_IDS     = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

INWCLOUD_BASE = "https://api.inwcloud.shop"
BOT_NAME      = "PUXXZATJ"

# ========================================================
#  INIT
# ========================================================
init_db()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ========================================================
#  HELPERS
# ========================================================

def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in ADMIN_IDS:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    return False

def fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def days_left(expires_at: float) -> int:
    remaining = expires_at - datetime.now().timestamp()
    return max(0, int(remaining // 86400))

# ========================================================
#  HTTP API — ให้ puxxza.py เรียก POST /verify
# ========================================================

async def handle_verify(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        key  = data.get("key", "").strip()
        hwid = data.get("hwid", "").strip()
        if not key or not hwid:
            return web.json_response({"status": "error", "message": "MISSING_PARAMS"}, status=400)
        success, msg = verify_key_hwid(key, hwid)
        if success:
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "error", "message": msg}, status=403)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_health(request: web.Request) -> web.Response:
    """Health check ให้ Render ping ไม่ให้หลับ"""
    return web.json_response({"status": "ok", "bot": BOT_NAME})

async def start_http_server():
    app = web.Application()
    app.router.add_post("/verify", handle_verify)
    app.router.add_get("/", handle_health)          # Render health check
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[API] HTTP server running on port {PORT}")

# ========================================================
#  BOT EVENTS
# ========================================================

@bot.event
async def on_ready():
    await bot.tree.sync()
    cleanup_task.start()
    print(f"[BOT] {BOT_NAME} พร้อมแล้ว — {bot.user}")

@tasks.loop(hours=1)
async def cleanup_task():
    deleted = cleanup_expired_keys()
    if deleted:
        print(f"[DB] ลบคีย์หมดอายุ {deleted} รายการ")

# ========================================================
#  ADMIN COMMANDS
# ========================================================

@bot.tree.command(name="createkey", description="[Admin] สร้างคีย์ใหม่")
@app_commands.describe(days="จำนวนวันที่คีย์ใช้ได้")
async def cmd_createkey(interaction: discord.Interaction, days: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        return
    if days <= 0:
        await interaction.response.send_message("❌ จำนวนวันต้องมากกว่า 0", ephemeral=True)
        return
    key = create_key(days)
    embed = discord.Embed(title="✅ สร้างคีย์สำเร็จ", color=0x2ecc71)
    embed.add_field(name="🔑 คีย์", value=f"```{key}```", inline=False)
    embed.add_field(name="⏳ ระยะเวลา", value=f"{days} วัน", inline=True)
    embed.set_footer(text=BOT_NAME)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="listkeys", description="[Admin] ดูคีย์ทั้งหมดในระบบ")
async def cmd_listkeys(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        return
    cleanup_expired_keys()
    keys = get_all_keys()
    if not keys:
        await interaction.response.send_message("📭 ไม่มีคีย์ในระบบ", ephemeral=True)
        return
    now = datetime.now().timestamp()
    embed = discord.Embed(title="📋 รายการคีย์ทั้งหมด", color=0x3498db)
    embed.set_footer(text=f"ทั้งหมด {len(keys)} คีย์ | {BOT_NAME}")
    for k in keys[:15]:
        active = now < k["expires_at"]
        status = "✅ ใช้ได้" if active else "❌ หมดอายุ"
        owner  = f"<@{k['discord_id']}>" if k["discord_id"] else "_(ยังไม่มีเจ้าของ)_"
        hwid   = "🔒 ล็อค" if k["hwid"] else "🔓 ยังไม่ล็อค"
        d_left = days_left(k["expires_at"])
        embed.add_field(
            name=f"`{k['key']}`",
            value=(
                f"สถานะ: {status} | เหลือ {d_left} วัน\n"
                f"เจ้าของ: {owner}\n"
                f"HWID: {hwid} | หมดอายุ: {fmt_date(k['expires_at'])}"
            ),
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="deletekey", description="[Admin] ลบคีย์ออกจากระบบ")
@app_commands.describe(key="คีย์ที่ต้องการลบ")
async def cmd_deletekey(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        return
    if delete_key(key.strip()):
        await interaction.response.send_message(f"✅ ลบคีย์ `{key}` เรียบร้อยแล้ว", ephemeral=True)
    else:
        await interaction.response.send_message("❌ ไม่พบคีย์นี้ในระบบ", ephemeral=True)


@bot.tree.command(name="givebalance", description="[Admin] เติมเงินให้ผู้ใช้")
@app_commands.describe(user="ผู้ใช้ที่ต้องการเติมเงิน", amount="จำนวนเงิน")
async def cmd_givebalance(interaction: discord.Interaction, user: discord.Member, amount: float):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ ไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ จำนวนเงินต้องมากกว่า 0", ephemeral=True)
        return
    add_balance(str(user.id), amount)
    balance = get_user_balance(str(user.id))
    await interaction.response.send_message(
        f"✅ เติมเงิน **{amount:.2f} บาท** ให้ {user.mention} เรียบร้อย\n"
        f"ยอดปัจจุบัน: **{balance:.2f} บาท**",
        ephemeral=True
    )

# ========================================================
#  USER COMMANDS — KEY
# ========================================================

@bot.tree.command(name="activate", description="เปิดใช้งานคีย์")
@app_commands.describe(key="คีย์ที่ได้รับมา")
async def cmd_activate(interaction: discord.Interaction, key: str):
    await interaction.response.defer(ephemeral=True)
    discord_id = str(interaction.user.id)
    key = key.strip()
    existing = get_user_key(discord_id)
    if existing:
        now = datetime.now().timestamp()
        if now < existing["expires_at"]:
            await interaction.followup.send(
                f"❌ คุณมีคีย์ที่ยังใช้งานอยู่แล้ว\n"
                f"คีย์: `{existing['key']}`\n"
                f"หมดอายุ: {fmt_date(existing['expires_at'])}",
                ephemeral=True
            )
            return
    key_data = get_key(key)
    if not key_data:
        await interaction.followup.send("❌ ไม่พบคีย์นี้ในระบบ", ephemeral=True)
        return
    now = datetime.now().timestamp()
    if now > key_data["expires_at"]:
        await interaction.followup.send("❌ คีย์นี้หมดอายุแล้ว", ephemeral=True)
        return
    if key_data["discord_id"] and key_data["discord_id"] != discord_id:
        await interaction.followup.send("❌ คีย์นี้ถูกใช้งานโดยบัญชีอื่นแล้ว", ephemeral=True)
        return
    success = activate_key(key, discord_id)
    if success:
        embed = discord.Embed(title="✅ เปิดใช้งานคีย์สำเร็จ", color=0x2ecc71)
        embed.add_field(name="🔑 คีย์", value=f"```{key}```", inline=False)
        embed.add_field(name="📅 หมดอายุ", value=fmt_date(key_data["expires_at"]), inline=True)
        embed.add_field(name="⏳ เหลือ", value=f"{days_left(key_data['expires_at'])} วัน", inline=True)
        embed.set_footer(text=f"{BOT_NAME} | ใช้ /mykey เพื่อดูข้อมูลคีย์")
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send("❌ ไม่สามารถเปิดใช้งานคีย์ได้ กรุณาลองอีกครั้ง", ephemeral=True)


@bot.tree.command(name="mykey", description="ตรวจสอบคีย์และวันหมดอายุของคุณ")
async def cmd_mykey(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    key_data = get_user_key(discord_id)
    if not key_data:
        await interaction.response.send_message(
            "❌ คุณยังไม่มีคีย์ในระบบ\nใช้คำสั่ง `/activate <key>` เพื่อเปิดใช้งาน",
            ephemeral=True
        )
        return
    now = datetime.now().timestamp()
    if now > key_data["expires_at"]:
        cleanup_expired_keys()
        await interaction.response.send_message(
            "❌ คีย์ของคุณหมดอายุแล้วและถูกลบออกจากระบบ\nกรุณาซื้อคีย์ใหม่",
            ephemeral=True
        )
        return
    hwid_status = "🔒 ล็อคแล้ว (ใช้งานอยู่)" if key_data["hwid"] else "🔓 ยังไม่ได้ล็อค HWID"
    d = days_left(key_data["expires_at"])
    color = 0x2ecc71 if d > 3 else 0xe74c3c
    embed = discord.Embed(title="🔑 ข้อมูลคีย์ของคุณ", color=color)
    embed.add_field(name="คีย์", value=f"```{key_data['key']}```", inline=False)
    embed.add_field(name="📅 หมดอายุ", value=fmt_date(key_data["expires_at"]), inline=True)
    embed.add_field(name="⏳ เหลืออีก", value=f"{d} วัน", inline=True)
    embed.add_field(name="HWID", value=hwid_status, inline=False)
    embed.set_footer(text="⚠️ คีย์ใกล้หมดอายุแล้ว!" if d <= 3 else BOT_NAME)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="resethwid", description="รีเซ็ต HWID (รอ 12 ชั่วโมงระหว่างการรีเซ็ต)")
async def cmd_resethwid(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    success, msg = reset_hwid(discord_id)
    if success:
        embed = discord.Embed(
            title="✅ รีเซ็ต HWID สำเร็จ",
            description="คุณสามารถใช้งาน puxxza.py บนเครื่องใหม่ได้แล้ว\nการรีเซ็ตครั้งต่อไปจะทำได้อีกใน **12 ชั่วโมง**",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        if msg == "NO_KEY":
            await interaction.response.send_message("❌ คุณยังไม่มีคีย์ในระบบ", ephemeral=True)
        elif msg.startswith("COOLDOWN"):
            _, h, m = msg.split(":")
            await interaction.response.send_message(
                f"⏳ ต้องรออีก **{h} ชั่วโมง {m} นาที** ก่อนรีเซ็ต HWID ได้อีกครั้ง",
                ephemeral=True
            )

# ========================================================
#  USER COMMANDS — TOP-UP
# ========================================================

@bot.tree.command(name="balance", description="ดูยอดเงินคงเหลือ")
async def cmd_balance(interaction: discord.Interaction):
    bal = get_user_balance(str(interaction.user.id))
    await interaction.response.send_message(
        f"💰 ยอดเงินคงเหลือของคุณ: **{bal:.2f} บาท**",
        ephemeral=True
    )


@bot.tree.command(name="topup", description="เติมเงินด้วย PromptPay QR Code")
@app_commands.describe(amount="จำนวนเงินที่ต้องการเติม (บาท)")
async def cmd_topup(interaction: discord.Interaction, amount: float):
    await interaction.response.defer(ephemeral=True)
    if amount < 1:
        await interaction.followup.send("❌ จำนวนขั้นต่ำ 1 บาท", ephemeral=True)
        return
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{INWCLOUD_BASE}/v1/promptpay/generate",
            json={"amount": amount},
            headers={"Authorization": f"Bearer {INWCLOUD_KEY}"}
        ) as resp:
            data = await resp.json()
    if data.get("status") != "success":
        await interaction.followup.send(f"❌ {data.get('message', 'เกิดข้อผิดพลาด')}", ephemeral=True)
        return
    tx_id  = data["data"]["transactionId"]
    qr_url = data["data"]["qr_url"]
    amt    = data["data"]["amount"]
    save_transaction(tx_id, str(interaction.user.id), float(amt), "promptpay")
    embed = discord.Embed(title="💳 เติมเงินด้วย PromptPay", color=0xf39c12)
    embed.add_field(name="จำนวนเงิน", value=f"**{amt} บาท**", inline=True)
    embed.add_field(name="Transaction ID", value=f"`{tx_id}`", inline=False)
    embed.set_image(url=qr_url)
    embed.set_footer(text="สแกน QR Code แล้วใช้ /checkpay <transaction_id> เพื่อยืนยัน")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="checkpay", description="ตรวจสอบการชำระเงิน PromptPay")
@app_commands.describe(transaction_id="Transaction ID ที่ได้จากคำสั่ง /topup")
async def cmd_checkpay(interaction: discord.Interaction, transaction_id: str):
    await interaction.response.defer(ephemeral=True)
    discord_id = str(interaction.user.id)
    tx = get_transaction(transaction_id.strip())
    if not tx or tx["discord_id"] != discord_id:
        await interaction.followup.send("❌ ไม่พบ Transaction นี้ในระบบ", ephemeral=True)
        return
    if tx["status"] == "completed":
        await interaction.followup.send("✅ Transaction นี้ยืนยันแล้ว", ephemeral=True)
        return
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{INWCLOUD_BASE}/v1/promptpay/check",
            json={"transactionId": transaction_id},
            headers={"Authorization": f"Bearer {INWCLOUD_KEY}"}
        ) as resp:
            data = await resp.json()
    if data.get("status") == "success":
        amount = float(data.get("amount", tx["amount"]))
        add_balance(discord_id, amount)
        complete_transaction(transaction_id)
        balance = get_user_balance(discord_id)
        embed = discord.Embed(title="✅ เติมเงินสำเร็จ", color=0x2ecc71)
        embed.add_field(name="ได้รับเงิน", value=f"+{amount:.2f} บาท", inline=True)
        embed.add_field(name="ยอดคงเหลือ", value=f"**{balance:.2f} บาท**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
    elif data.get("status") == "pending":
        remaining = data.get("time_remaining", 0)
        mins = remaining // 60
        await interaction.followup.send(
            f"⏳ ยังไม่ได้ชำระเงิน กรุณาสแกน QR ก่อน\nหมดเวลาใน {mins} นาที",
            ephemeral=True
        )
    else:
        await interaction.followup.send(f"❌ {data.get('message', 'เกิดข้อผิดพลาด')}", ephemeral=True)


@bot.tree.command(name="redeemvoucher", description="เติมเงินด้วยซอง TrueWallet")
@app_commands.describe(voucher_link="ลิงก์ซองของขวัญ TrueMoney (gift.truemoney.com/...)")
async def cmd_redeemvoucher(interaction: discord.Interaction, voucher_link: str):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{INWCLOUD_BASE}/v1/truewallet/redeem",
            json={"voucher_link": voucher_link.strip()},
            headers={"Authorization": f"Bearer {INWCLOUD_KEY}"}
        ) as resp:
            data = await resp.json()
    if data.get("status") == "success":
        amount = float(data["data"]["amount"])
        add_balance(str(interaction.user.id), amount)
        balance = get_user_balance(str(interaction.user.id))
        embed = discord.Embed(title="✅ เติมเงิน TrueWallet สำเร็จ", color=0x2ecc71)
        embed.add_field(name="ได้รับเงิน", value=f"+{amount:.2f} บาท", inline=True)
        embed.add_field(name="ยอดคงเหลือ", value=f"**{balance:.2f} บาท**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {data.get('message', 'เกิดข้อผิดพลาด')}", ephemeral=True)


@bot.tree.command(name="help", description="แสดงคำสั่งทั้งหมด")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(title=f"📖 {BOT_NAME} — คู่มือคำสั่ง", color=0x9b59b6)
    embed.add_field(
        name="🔑 คีย์",
        value=(
            "`/activate <key>` — เปิดใช้งานคีย์\n"
            "`/mykey` — ดูคีย์และวันหมดอายุ\n"
            "`/resethwid` — รีเซ็ต HWID (รอ 12 ชม.)\n"
        ),
        inline=False
    )
    embed.add_field(
        name="💰 เงิน",
        value=(
            "`/balance` — ดูยอดเงิน\n"
            "`/topup <amount>` — เติมเงิน PromptPay\n"
            "`/checkpay <id>` — ยืนยันการชำระเงิน\n"
            "`/redeemvoucher <link>` — เติมเงิน TrueWallet\n"
        ),
        inline=False
    )
    if is_admin(interaction):
        embed.add_field(
            name="🛠 Admin",
            value=(
                "`/createkey <days>` — สร้างคีย์ใหม่\n"
                "`/listkeys` — ดูคีย์ทั้งหมด\n"
                "`/deletekey <key>` — ลบคีย์\n"
                "`/givebalance <user> <amount>` — เติมเงินให้ผู้ใช้\n"
            ),
            inline=False
        )
    embed.set_footer(text=BOT_NAME)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ========================================================
#  MAIN — รัน Bot + HTTP Server พร้อมกัน
# ========================================================

async def main():
    await start_http_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
