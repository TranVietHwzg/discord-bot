import os
import sys
import base64
import json
import urllib.request
import urllib.error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = "TranVietHwzg/discord-bot"
FILES_TO_UPLOAD = [
    "bot.py",
    "requirements.txt",
    "README.md"
]

def upload_file(token: str, filename: str) -> bool:
    file_path = os.path.join(os.path.dirname(__file__), filename)
    if not os.path.exists(file_path):
        print(f"⚠️ Không tìm thấy file: {filename}, bỏ qua.")
        return False

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    b64_content = base64.b64encode(file_bytes).decode("utf-8")
    api_url = f"https://api.github.com/repos/{REPO}/contents/{filename}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutoUploader-Bot",
    }

    # 1. Lấy SHA hiện tại nếu có
    sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"❌ Lỗi kiểm tra {filename}: HTTP {e.code}")
            return False

    # 2. Đẩy file lên GitHub
    payload = {
        "message": f"🤖 Cập nhật {filename} ({len(file_bytes)} bytes)",
        "content": b64_content,
    }
    if sha:
        payload["sha"] = sha

    try:
        req_put = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="PUT"
        )
        with urllib.request.urlopen(req_put) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            commit_sha = res_data.get("commit", {}).get("sha", "")[:7]
            print(f"✅ Đã upload {filename} -> Commit: {commit_sha}")
            return True
    except Exception as e:
        print(f"❌ Lỗi upload {filename}: {e}")
        return False

def upload_all():
    token = os.getenv("GITHUB_TOKEN")
    if not token and len(sys.argv) > 1:
        token = sys.argv[1].strip()

    if not token:
        print("❌ LỖI: Chưa có GITHUB_TOKEN!")
        print("👉 Vui lòng truyền token: python upload_to_github.py <GITHUB_TOKEN>")
        print("👉 Hoặc thêm dòng `GITHUB_TOKEN=ghp_...` vào file .env")
        return False

    print(f"🚀 Bắt đầu upload các file dự án lên repo {REPO}...")
    success_count = 0
    for fname in FILES_TO_UPLOAD:
        if upload_file(token, fname):
            success_count += 1

    print(f"\n🎉 Hoàn thành upload {success_count}/{len(FILES_TO_UPLOAD)} files lên GitHub!")
    print("🚀 Render sẽ tự động build lại bot trong 1-2 phút.")
    return success_count > 0

if __name__ == "__main__":
    upload_all()
