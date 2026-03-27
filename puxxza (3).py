import os 
import requests
import json
import time
import subprocess
import asyncio
import aiohttp
import threading
import psutil
from colorama import init, Fore, Style

init()

# ===== ไฟล์และค่าคงที่ =====
SERVER_LINKS_FILE = "Private_Link.txt"
ACCOUNTS_FILE     = "Account.txt"
CONFIG_FILE       = "Config.json"
KEY_FILE          = "license.json"

# ===== URL ของ Bot API — แก้เป็น IP เซิร์ฟเวอร์ของคุณ =====
BOT_API_URL = os.getenv("BOT_API_URL", "https://YOUR-APP-NAME.onrender.com")

# ===== ตัวแปร Global =====
webhook_url          = None
device_name          = None
interval             = None
stop_webhook_thread  = False
webhook_thread       = None

# ========================================================
#  LICENSE / HWID SYSTEM
# ========================================================

DIVIDER = "+" + "-" * 62 + "+"

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def get_hwid() -> str:
    """ดึง HWID ของอุปกรณ์ (ใช้ Android ID บน Termux)"""
    # วิธีที่ 1: Android ID ผ่าน settings
    try:
        result = subprocess.run(
            ["settings", "get", "secure", "android_id"],
            capture_output=True, text=True, timeout=5
        )
        android_id = result.stdout.strip()
        if android_id and android_id != "null":
            return android_id
    except Exception:
        pass

    # วิธีที่ 2: Serial Number
    try:
        result = subprocess.run(
            ["getprop", "ro.serialno"],
            capture_output=True, text=True, timeout=5
        )
        serial = result.stdout.strip()
        if serial and serial not in ("", "unknown", "0"):
            import hashlib
            return hashlib.md5(serial.encode()).hexdigest()
    except Exception:
        pass

    # วิธีที่ 3: ใช้ MAC Address (fallback)
    try:
        import uuid
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                        for elements in range(0, 8*6, 8)][::-1])
        import hashlib
        return hashlib.md5(mac.encode()).hexdigest()
    except Exception:
        pass

    # วิธีที่ 4: สร้าง HWID แล้วบันทึกถาวร
    hwid_file = os.path.join(os.path.expanduser("~"), ".puxxza_hwid")
    if os.path.exists(hwid_file):
        with open(hwid_file, "r") as f:
            return f.read().strip()
    import uuid
    hwid = str(uuid.uuid4()).replace("-", "")
    with open(hwid_file, "w") as f:
        f.write(hwid)
    return hwid

def load_license() -> dict:
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_license(data: dict):
    with open(KEY_FILE, "w") as f:
        json.dump(data, f)

def verify_license():
    """ตรวจสอบ License Key กับ Bot API ก่อนเริ่มโปรแกรม"""
    license_data = load_license()
    key = license_data.get("key", "").strip()

    clear()
    print(DIVIDER)
    print("|" + "PUXXZA - ระบบยืนยันตัวตน".center(60) + "|")
    print(DIVIDER)

    if not key:
        print(Fore.YELLOW + "\n  ยังไม่มี License Key ในระบบ" + Style.RESET_ALL)
        key = input("  กรุณาใส่ License Key: ").strip()
        if not key:
            print(Fore.RED + "\n  ❌ ต้องใส่ Key เพื่อใช้งานโปรแกรม" + Style.RESET_ALL)
            time.sleep(2)
            exit(1)

    hwid = get_hwid()
    print(f"\n  กำลังตรวจสอบ Key กับระบบ...")

    try:
        resp = requests.post(
            f"{BOT_API_URL}/verify",
            json={"key": key, "hwid": hwid},
            timeout=10
        )
        data = resp.json()

        if data.get("status") == "ok":
            # บันทึก key ถ้ายังไม่มี
            save_license({"key": key})
            print(Fore.GREEN + f"\n  ✅ ยืนยัน License สำเร็จ — กำลังเข้าสู่ระบบ..." + Style.RESET_ALL)
            time.sleep(1)
            return  # ผ่านการตรวจสอบ

        # กรณีผิดพลาด
        msg = data.get("message", "UNKNOWN")

        if msg == "KEY_NOT_FOUND":
            print(Fore.RED + "\n  ❌ ไม่พบ Key นี้ในระบบ Discord Bot" + Style.RESET_ALL)
            print(Fore.YELLOW + "  กรุณาตรวจสอบ Key อีกครั้งหรือติดต่อผู้ขาย" + Style.RESET_ALL)
            save_license({})  # ลบ key ผิด

        elif msg == "KEY_EXPIRED":
            print(Fore.RED + "\n  ❌ Key ของคุณหมดอายุแล้ว" + Style.RESET_ALL)
            print(Fore.YELLOW + "  กรุณาซื้อ Key ใหม่และใช้คำสั่ง /activate ใน Discord" + Style.RESET_ALL)
            save_license({})  # ลบ key หมดอายุ

        elif msg == "HWID_MISMATCH":
            print(Fore.RED + "\n  ❌ อุปกรณ์นี้ไม่ได้รับอนุญาต" + Style.RESET_ALL)
            print(Fore.CYAN + "\n  Key ถูกใช้งานบนเครื่องอื่นอยู่แล้ว" + Style.RESET_ALL)
            print(Fore.YELLOW + "  วิธีแก้: ใช้คำสั่ง /resethwid ในบอท Discord" + Style.RESET_ALL)
            print(Fore.YELLOW + "  (รีเซ็ตได้ทุก 12 ชั่วโมง)" + Style.RESET_ALL)

        else:
            print(Fore.RED + f"\n  ❌ ข้อผิดพลาด: {msg}" + Style.RESET_ALL)

    except requests.exceptions.ConnectionError:
        print(Fore.RED + "\n  ❌ ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้" + Style.RESET_ALL)
        print(Fore.YELLOW + f"  ตรวจสอบว่า Bot API รันอยู่ที่: {BOT_API_URL}" + Style.RESET_ALL)
    except requests.exceptions.Timeout:
        print(Fore.RED + "\n  ❌ การเชื่อมต่อหมดเวลา" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.RED + f"\n  ❌ ข้อผิดพลาดที่ไม่คาดคิด: {e}" + Style.RESET_ALL)

    print()
    input("  กด Enter เพื่อออกจากโปรแกรม...")
    exit(1)

# ========================================================
#  UI / HEADER
# ========================================================

def print_header():
    clear()
    print(DIVIDER)
    print("|" + " " * 62 + "|")
    print("|" + "PUXXZA - Roblox Auto Rejoin Tool".center(62) + "|")
    print("|" + "พัฒนาสำหรับใช้งานส่วนตัวบน Android / Termux".center(62) + "|")
    print("|" + " " * 62 + "|")
    print(DIVIDER)
    print()

def print_menu():
    print_header()
    menu_items = [
        ("1", "เริ่ม Auto Rejoin สำหรับ Roblox Game"),
        ("2", "ตั้งค่า User ID ให้แต่ละแพ็กเกจ"),
        ("3", "ใช้ ID เกม / ลิงก์เซิร์ฟเวอร์เดียวกันทุกแพ็กเกจ"),
        ("4", "ตั้งค่าเซิร์ฟเวอร์ / ID เกมแยกแต่ละแพ็กเกจ"),
        ("5", "ลบ User ID และ/หรือ ลิงก์เซิร์ฟเวอร์"),
        ("6", "ตั้งค่า / เริ่ม-หยุด Discord Webhook"),
        ("7", "ดึง User ID อัตโนมัติจาก appStorage.json"),
        ("8", "แสดงรายการบัญชี / ลิงก์ที่ตั้งไว้"),
        ("9", "ออกจากโปรแกรม"),
    ]
    for key, label in menu_items:
        print(f"  [{key}]  {label}")
    print()
    return input("พิมพ์หมายเลขที่ต้องการ: ").strip()

def print_status_table(accounts, previous_status=None):
    if previous_status is None:
        previous_status = {}
    clear()
    print(DIVIDER)
    print("|" + "PUXXZA - ตารางสถานะ".center(62) + "|")
    print(DIVIDER)
    header = f"| {'แพ็กเกจ':<22} | {'ชื่อผู้ใช้':<16} | {'สถานะ':<14} |"
    print(header)
    print(DIVIDER)

    status_map = {2: "กำลังเล่นเกม", 1: "รอในล็อบบี้", 0: "ออฟไลน์"}

    for package_name, user_id in accounts:
        username     = get_username(user_id) or user_id
        presence     = check_user_online(user_id)
        status_text  = status_map.get(presence, "ไม่ทราบ")
        color        = Fore.GREEN if presence == 2 else (Fore.YELLOW if presence == 1 else Fore.RED)
        short_pkg    = package_name[-22:] if len(package_name) > 22 else package_name
        print(f"| {short_pkg:<22} | {username:<16} | " + color + f"{status_text:<14}" + Style.RESET_ALL + " |")
        previous_status[user_id] = status_text

    print(DIVIDER)
    print(Fore.CYAN + "  กด q + Enter เพื่อหยุด Auto Rejoin" + Style.RESET_ALL)
    print()
    return previous_status

# ========================================================
#  CONFIG
# ========================================================

def load_config():
    global webhook_url, device_name, interval
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        webhook_url = cfg.get("webhook_url")
        device_name = cfg.get("device_name")
        interval    = cfg.get("interval")
    else:
        webhook_url = device_name = interval = None

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({"webhook_url": webhook_url, "device_name": device_name, "interval": interval}, f)

# ========================================================
#  ROBLOX UTILITIES
# ========================================================

def get_roblox_packages():
    result = subprocess.run(
        "pm list packages | grep 'roblox'",
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        return [line.split(":")[1].strip() for line in result.stdout.splitlines()]
    return []

def kill_roblox_processes():
    print(Fore.YELLOW + "กำลังปิด Roblox ทุกแพ็กเกจ..." + Style.RESET_ALL)
    for pkg in get_roblox_packages():
        os.system(f"pkill -f {pkg}")
    time.sleep(2)

def kill_roblox_process(package_name):
    os.system(f"pkill -f {package_name}")
    time.sleep(2)

def launch_roblox(package_name, server_link, total):
    try:
        subprocess.run(
            ["am", "start", "-n",
             f"{package_name}/com.roblox.client.startup.ActivitySplash",
             "-d", server_link],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(Fore.GREEN + f"  เปิด Roblox: {package_name}" + Style.RESET_ALL)
        time.sleep(10)
        subprocess.run(
            ["am", "start", "-n",
             f"{package_name}/com.roblox.client.ActivityProtocolLaunch",
             "-d", server_link],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(Fore.GREEN + f"  เข้าเซิร์ฟเวอร์: {server_link}" + Style.RESET_ALL)
        time.sleep(10)
    except Exception as e:
        print(Fore.RED + f"  ข้อผิดพลาด ({package_name}): {e}" + Style.RESET_ALL)

def format_server_link(raw):
    if "roblox.com" in raw:
        return raw
    if raw.isdigit():
        return f"roblox://placeID={raw}"
    print(Fore.RED + "ลิงก์ไม่ถูกต้อง กรุณาใส่ Game ID หรือ Private Server Link" + Style.RESET_ALL)
    return None

# ========================================================
#  ROBLOX API
# ========================================================

def get_username(user_id):
    try:
        r = requests.get(f"https://users.roblox.com/v1/users/{user_id}", timeout=8)
        r.raise_for_status()
        return r.json().get("name", "ไม่ทราบ")
    except Exception:
        return None

def check_user_online(user_id):
    try:
        r = requests.post(
            "https://presence.roblox.com/v1/presence/users",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"userIds": [user_id]}),
            timeout=8
        )
        r.raise_for_status()
        return r.json()["userPresences"][0]["userPresenceType"]
    except Exception:
        return None

async def get_user_id_async(username):
    url     = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": True}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload,
                                headers={"Content-Type": "application/json"}) as resp:
            data = await resp.json()
            if data.get("data"):
                return data["data"][0]["id"]
    return None

# ========================================================
#  FILE HELPERS
# ========================================================

def save_server_links(server_links):
    with open(SERVER_LINKS_FILE, "w") as f:
        for pkg, link in server_links:
            f.write(f"{pkg},{link}\n")

def load_server_links():
    links = []
    if os.path.exists(SERVER_LINKS_FILE):
        with open(SERVER_LINKS_FILE, "r") as f:
            for line in f:
                parts = line.strip().split(",", 1)
                if len(parts) == 2:
                    links.append((parts[0], parts[1]))
    return links

def save_accounts(accounts):
    with open(ACCOUNTS_FILE, "w") as f:
        for pkg, uid in accounts:
            f.write(f"{pkg},{uid}\n")

def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r") as f:
            for line in f:
                parts = line.strip().split(",", 1)
                if len(parts) == 2:
                    accounts.append((parts[0], parts[1]))
    return accounts

def find_userid_from_file(file_path):
    try:
        with open(file_path, "r") as f:
            content = f.read()
        idx = content.find('"UserId":"')
        if idx == -1:
            return None
        idx += len('"UserId":"')
        end = content.find('"', idx)
        return content[idx:end] if end != -1 else None
    except IOError:
        return None

# ========================================================
#  DISCORD WEBHOOK
# ========================================================

def get_system_info():
    mem = psutil.virtual_memory()
    return {
        "cpu":        psutil.cpu_percent(interval=1),
        "mem_total":  mem.total,
        "mem_used":   mem.used,
        "mem_avail":  mem.available,
        "uptime":     time.time() - psutil.boot_time(),
    }

def capture_screenshot():
    path = "/data/data/com.termux/files/home/screenshot.png"
    os.system(f"screencap -p {path}")
    return path

def _build_status_embed(accounts):
    status_map = {2: "กำลังเล่น", 1: "ในล็อบบี้", 0: "ออฟไลน์"}
    lines = []
    for pkg, uid in accounts:
        uname    = get_username(uid) or uid
        presence = check_user_online(uid)
        status   = status_map.get(presence, "ไม่ทราบ")
        lines.append(f"{uname} ({pkg[-20:]}) — {status}")
    return {
        "title": f"[PUXXZA] สถานะ Roblox — {device_name}",
        "color": 3447003,
        "description": "\n".join(lines) if lines else "ไม่มีบัญชี",
    }

def _build_system_embed():
    si = get_system_info()
    return {
        "title": f"[PUXXZA] ข้อมูลระบบ — {device_name}",
        "color": 15258703,
        "fields": [
            {"name": "CPU",         "value": f"{si['cpu']}%",                                   "inline": True},
            {"name": "RAM ที่ใช้",  "value": f"{si['mem_used'] / si['mem_total'] * 100:.1f}%",  "inline": True},
            {"name": "RAM ว่าง",    "value": f"{si['mem_avail'] / si['mem_total'] * 100:.1f}%", "inline": True},
            {"name": "RAM รวม",     "value": f"{si['mem_total'] / (1024**3):.2f} GB",           "inline": True},
            {"name": "Uptime",      "value": f"{si['uptime'] / 3600:.2f} ชั่วโมง",             "inline": True},
        ],
        "image": {"url": "attachment://screenshot.png"},
    }

def _send_to_webhook(embeds, screenshot_path=None):
    payload = {"embeds": embeds, "username": device_name or "PUXXZA"}
    if screenshot_path and os.path.exists(screenshot_path):
        with open(screenshot_path, "rb") as img:
            requests.post(
                webhook_url,
                data={"payload_json": json.dumps(payload)},
                files={"file": ("screenshot.png", img)},
                timeout=15,
            )
    else:
        requests.post(webhook_url, json=payload, timeout=15)

def send_webhook_loop(accounts_ref):
    global stop_webhook_thread
    while not stop_webhook_thread:
        try:
            screenshot = capture_screenshot()
            embeds = [_build_status_embed(accounts_ref()), _build_system_embed()]
            _send_to_webhook(embeds, screenshot)
            print(Fore.GREEN + "  ส่ง Webhook สำเร็จ" + Style.RESET_ALL)
        except Exception as e:
            print(Fore.RED + f"  ส่ง Webhook ล้มเหลว: {e}" + Style.RESET_ALL)
        time.sleep((interval or 5) * 60)

def send_rejoin_alert(username, package_name):
    if not webhook_url:
        return
    embed = {
        "title": "[PUXXZA] แจ้งเตือน — ออกจากเกม",
        "color": 15158332,
        "fields": [
            {"name": "บัญชี",        "value": username,     "inline": True},
            {"name": "แพ็กเกจ",      "value": package_name, "inline": True},
            {"name": "การดำเนินการ", "value": "กำลัง Rejoin อัตโนมัติ", "inline": False},
        ],
    }
    try:
        _send_to_webhook([embed])
    except Exception:
        pass

def start_webhook_thread(accounts_getter):
    global webhook_thread, stop_webhook_thread
    stop_webhook_thread = False
    webhook_thread = threading.Thread(
        target=send_webhook_loop, args=(accounts_getter,), daemon=True
    )
    webhook_thread.start()
    print(Fore.GREEN + "  Webhook Thread เริ่มทำงาน" + Style.RESET_ALL)

def stop_webhook():
    global stop_webhook_thread
    stop_webhook_thread = True
    print(Fore.YELLOW + "  หยุด Webhook Thread แล้ว" + Style.RESET_ALL)

def setup_webhook(accounts_getter):
    global webhook_url, device_name, interval
    stop_webhook()
    print_header()
    print("-- ตั้งค่า Discord Webhook --\n")
    webhook_url = input("URL Webhook ของ Discord: ").strip()
    device_name = input("ชื่อที่จะแสดงใน Discord: ").strip()
    interval    = int(input("ส่งข้อมูลทุกกี่นาที: ").strip())
    save_config()
    start_webhook_thread(accounts_getter)

# ========================================================
#  MENU HANDLERS
# ========================================================

def menu_auto_rejoin(accounts_ref):
    server_links = load_server_links()
    accounts     = load_accounts()

    if not accounts:
        print(Fore.RED + "ยังไม่มี User ID กรุณาตั้งค่าก่อน (เมนู 2 หรือ 7)" + Style.RESET_ALL)
        return
    if not server_links:
        print(Fore.RED + "ยังไม่มีลิงก์เซิร์ฟเวอร์ กรุณาตั้งค่าก่อน (เมนู 3 หรือ 4)" + Style.RESET_ALL)
        return

    print_header()
    force_min = input("บังคับ Rejoin ทุกกี่นาที (0 = ไม่บังคับ): ").strip()
    force_interval = int(force_min) * 60 if force_min.isdigit() else 0

    if webhook_url and device_name and interval:
        start_webhook_thread(load_accounts)

    print(Fore.YELLOW + "ปิด Roblox ทั้งหมดก่อนเริ่ม..." + Style.RESET_ALL)
    kill_roblox_processes()
    time.sleep(5)

    for pkg, link in server_links:
        launch_roblox(pkg, link, len(server_links))

    previous_status = {}
    start_time      = time.time()
    stop_flag       = threading.Event()

    def listen_quit():
        while True:
            cmd = input()
            if cmd.strip().lower() == "q":
                stop_flag.set()
                break

    threading.Thread(target=listen_quit, daemon=True).start()

    link_map = {pkg: link for pkg, link in server_links}

    while not stop_flag.is_set():
        for pkg, uid in accounts:
            if stop_flag.is_set():
                break

            if not uid.isdigit():
                new_id = asyncio.run(get_user_id_async(uid))
                if new_id:
                    uid = str(new_id)

            username     = get_username(uid) or uid
            presence     = check_user_online(uid)
            server_link  = link_map.get(pkg, "")

            if presence != 2:
                print(Fore.RED + f"  {username} ออกจากเกมหรือออฟไลน์ กำลังตรวจสอบ..." + Style.RESET_ALL)
                for attempt in range(5):
                    time.sleep(3)
                    presence = check_user_online(uid)
                    if presence == 2:
                        break
                    print(Fore.YELLOW + f"  ลองที่ {attempt + 1}/5..." + Style.RESET_ALL)

                if presence != 2:
                    send_rejoin_alert(username, pkg)
                    print(Fore.RED + f"  {username} ออกจากเกม กำลัง Rejoin..." + Style.RESET_ALL)
                    kill_roblox_process(pkg)
                    launch_roblox(pkg, server_link, len(server_links))

            time.sleep(5)

        if not stop_flag.is_set():
            time.sleep(55)

        if force_interval > 0 and (time.time() - start_time) >= force_interval:
            print(Fore.YELLOW + "ถึงเวลา Rejoin บังคับ..." + Style.RESET_ALL)
            kill_roblox_processes()
            time.sleep(5)
            for pkg, link in server_links:
                launch_roblox(pkg, link, len(server_links))
            start_time = time.time()

        if not stop_flag.is_set():
            previous_status = print_status_table(accounts, previous_status)

    stop_webhook()
    print(Fore.CYAN + "หยุด Auto Rejoin เรียบร้อย" + Style.RESET_ALL)

def menu_set_userids():
    packages = get_roblox_packages()
    if not packages:
        print(Fore.RED + "ไม่พบแพ็กเกจ Roblox บนอุปกรณ์" + Style.RESET_ALL)
        return
    accounts = []
    for pkg in packages:
        val = input(f"  User ID หรือชื่อผู้ใช้สำหรับ {pkg}: ").strip()
        if val.isdigit():
            accounts.append((pkg, val))
        else:
            uid = asyncio.run(get_user_id_async(val))
            if uid:
                accounts.append((pkg, str(uid)))
                print(Fore.GREEN + f"  ได้ User ID: {uid}" + Style.RESET_ALL)
            else:
                manual = input("  ไม่พบ ID กรุณาใส่ User ID ตรง ๆ: ").strip()
                accounts.append((pkg, manual))
    save_accounts(accounts)
    print(Fore.GREEN + "บันทึก User ID เรียบร้อย" + Style.RESET_ALL)

def menu_same_link():
    packages = get_roblox_packages()
    raw      = input("  ใส่ Game ID หรือ Private Server Link: ").strip()
    link     = format_server_link(raw)
    if link:
        save_server_links([(pkg, link) for pkg in packages])
        print(Fore.GREEN + "บันทึกลิงก์เรียบร้อย" + Style.RESET_ALL)

def menu_diff_links():
    packages     = get_roblox_packages()
    server_links = []
    for pkg in packages:
        raw  = input(f"  ลิงก์สำหรับ {pkg}: ").strip()
        link = format_server_link(raw)
        if link:
            server_links.append((pkg, link))
    save_server_links(server_links)
    print(Fore.GREEN + "บันทึกลิงก์เรียบร้อย" + Style.RESET_ALL)

def menu_delete():
    print("  [1] ลบ User ID")
    print("  [2] ลบลิงก์เซิร์ฟเวอร์")
    print("  [3] ลบทั้งคู่")
    ch = input("  เลือก: ").strip()
    if ch in ("1", "3") and os.path.exists(ACCOUNTS_FILE):
        os.remove(ACCOUNTS_FILE)
        print(Fore.GREEN + "ลบ User ID แล้ว" + Style.RESET_ALL)
    if ch in ("2", "3") and os.path.exists(SERVER_LINKS_FILE):
        os.remove(SERVER_LINKS_FILE)
        print(Fore.GREEN + "ลบลิงก์เซิร์ฟเวอร์แล้ว" + Style.RESET_ALL)

def menu_auto_userid():
    packages = get_roblox_packages()
    accounts = []
    for pkg in packages:
        path = f"/data/data/{pkg}/files/appData/LocalStorage/appStorage.json"
        uid  = find_userid_from_file(path)
        if uid:
            accounts.append((pkg, uid))
            print(Fore.GREEN + f"  {pkg}: {uid}" + Style.RESET_ALL)
        else:
            print(Fore.RED + f"  ไม่พบ User ID สำหรับ {pkg}" + Style.RESET_ALL)
    if accounts:
        save_accounts(accounts)
        print(Fore.GREEN + "บันทึก User ID เรียบร้อย" + Style.RESET_ALL)
        raw  = input("ใส่ Game ID หรือลิงก์เซิร์ฟเวอร์: ").strip()
        link = format_server_link(raw)
        if link:
            save_server_links([(pkg, link) for pkg, _ in accounts])
            print(Fore.GREEN + "บันทึกลิงก์เรียบร้อย" + Style.RESET_ALL)

def menu_list():
    accounts     = load_accounts()
    server_links = load_server_links()
    link_map     = {pkg: link for pkg, link in server_links}
    print_header()
    print(DIVIDER)
    print("|" + "รายการบัญชี / ลิงก์".center(62) + "|")
    print(DIVIDER)
    for pkg, uid in accounts:
        uname = get_username(uid) or uid
        link  = link_map.get(pkg, "(ยังไม่ตั้งค่า)")
        print(Fore.CYAN + f"  แพ็กเกจ : {pkg}" + Style.RESET_ALL)
        print(f"  ผู้ใช้  : {uname} (ID: {uid})")
        print(f"  ลิงก์   : {link}")
        print()

# ========================================================
#  MAIN — เพิ่ม verify_license() ก่อนทุกอย่าง
# ========================================================

def main():
    # ตรวจสอบ License ก่อนใช้งาน
    verify_license()

    load_config()
    while True:
        choice = print_menu()

        if choice == "1":
            menu_auto_rejoin(load_accounts)
        elif choice == "2":
            menu_set_userids()
        elif choice == "3":
            menu_same_link()
        elif choice == "4":
            menu_diff_links()
        elif choice == "5":
            menu_delete()
        elif choice == "6":
            setup_webhook(load_accounts)
        elif choice == "7":
            menu_auto_userid()
        elif choice == "8":
            menu_list()
            input("\nกด Enter เพื่อกลับเมนูหลัก...")
        elif choice == "9":
            stop_webhook()
            print(Fore.CYAN + "\nออกจาก PUXXZA เรียบร้อย" + Style.RESET_ALL)
            break
        else:
            print(Fore.RED + "ตัวเลือกไม่ถูกต้อง" + Style.RESET_ALL)

        if choice != "9":
            input("\nกด Enter เพื่อกลับเมนูหลัก...")

if __name__ == "__main__":
    main()
