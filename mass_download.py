import argparse
import html
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests

# ==== Regex dasar untuk parsing URL Google Drive ====
RX_FOLDER_ID = re.compile(r"drive\.google\.com/drive/folders/([^/?#]+)")
RX_FILE_ID   = re.compile(r"drive\.google\.com/file/d/([^/?#]+)")
RX_RESOURCEKEY = re.compile(r"[?&]resourcekey=([^&#]+)", re.IGNORECASE)

# ==== Util ====
INVALID_FS_CHARS = r'<>:"/\\|?*'
INVALID_FS_PATTERN = re.compile(r'[<>:"/\\|?*]')

def sanitize_name(name: str, max_len: int = 180) -> str:
    if not name:
        return "Untitled"
    name = INVALID_FS_PATTERN.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    # hindari nama khusus Windows
    reserved = {"CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
                "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"}
    if name.upper() in reserved:
        name = f"_{name}_"
    return name[:max_len].rstrip(" .")

def extract_kind_id(url: str):
    url = url.strip()
    m = RX_FOLDER_ID.search(url)
    if m:  # folder
        return "folder", m.group(1)
    m = RX_FILE_ID.search(url)
    if m:  # file
        return "file", m.group(1)
    # fallback id=...
    if "id=" in url:
        _id = url.split("id=", 1)[1].split("&", 1)[0]
        return "file", _id
    return None, None

def extract_resourcekey(url: str) -> Optional[str]:
    m = RX_RESOURCEKEY.search(url)
    return m.group(1) if m else None

def get_folder_name_from_web(folder_url: str, timeout: int = 20) -> str:
    """
    Ambil nama folder asli dari <title> halaman Google Drive public.
    """
    resp = requests.get(folder_url, timeout=timeout)
    resp.raise_for_status()
    # <title>Nama Folder - Google Drive</title>
    m = re.search(r"<title>(.*?) - Google Drive</title>", resp.text, flags=re.IGNORECASE|re.DOTALL)
    if m:
        return sanitize_name(html.unescape(m.group(1)).strip())
    return None

def tool_exists(tool: str) -> bool:
    from shutil import which
    return which(tool) is not None

def run(cmd_list, cwd: Optional[Path] = None) -> int:
    try:
        p = subprocess.run(cmd_list, cwd=str(cwd) if cwd else None)
        return p.returncode
    except FileNotFoundError:
        return 127

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

# ==== Download backends ====
def download_with_gdown_folder(url: str, out_dir: Path, cookies_path: Optional[Path] = None) -> bool:
    """
    Pakai gdown CLI untuk folder. Return True jika sukses (exit 0).
    Coba dengan cookies (jika ada), lalu fallback tanpa cookies.
    """
    if not tool_exists("gdown"):
        return False
    ensure_dir(out_dir)

    # coba dengan cookies kalau ada
    if cookies_path and cookies_path.exists():
        cmd = ["gdown", "--folder", url, "--out", str(out_dir), "--remaining-ok", "--fuzzy", "--cookies", str(cookies_path)]
        print(">> gdown (with cookies):", " ".join(shlex.quote(c) for c in cmd))
        rc = run(cmd)
        if rc == 0:
            return True
        print(f"[gdown] with cookies failed (rc={rc}), trying without cookies...")

    # tanpa cookies
    cmd = ["gdown", "--folder", url, "--out", str(out_dir), "--remaining-ok", "--fuzzy"]
    print(">> gdown:", " ".join(shlex.quote(c) for c in cmd))
    rc = run(cmd)
    return rc == 0

def download_with_gdown_file(file_id: str, out_dir: Path, cookies_path: Optional[Path] = None) -> bool:
    """
    Pakai gdown CLI untuk file tunggal (by id). Return True kalau sukses.
    """
    if not tool_exists("gdown"):
        return False
    ensure_dir(out_dir)

    if cookies_path and cookies_path.exists():
        cmd = ["gdown", f"--id", file_id, "--out", str(out_dir), "--fuzzy", "--cookies", str(cookies_path)]
        print(">> gdown (with cookies):", " ".join(shlex.quote(c) for c in cmd))
        rc = run(cmd)
        if rc == 0:
            return True
        print(f"[gdown] with cookies failed (rc={rc}), trying without cookies...)")

    cmd = ["gdown", f"--id", file_id, "--out", str(out_dir), "--fuzzy"]
    print(">> gdown:", " ".join(shlex.quote(c) for c in cmd))
    rc = run(cmd)
    return rc == 0

def download_with_rclone_folder(remote: str, folder_id: str, out_dir: Path, resource_key: Optional[str] = None,
                                export_formats: str = "docx,xlsx,pptx,pdf",
                                transfers: int = 8, checkers: int = 8, tpslimit: int = 4) -> bool:
    """
    rclone copy isi folder by --drive-root-folder-id.
    """
    if not tool_exists("rclone"):
        return False
    ensure_dir(out_dir)
    cmd = [
        "rclone", "copy", f"{remote}:", str(out_dir),
        "--drive-root-folder-id", folder_id,
        "--drive-export-formats", export_formats,
        "--progress", "--transfers", str(transfers),
        "--checkers", str(checkers), "--tpslimit", str(tpslimit),
    ]
    if resource_key:
        cmd.extend(["--drive-resource-key", resource_key])
    print(">> rclone:", " ".join(shlex.quote(c) for c in cmd))
    rc = run(cmd)
    return rc == 0

# ==== Main Logic ====
def process_link(url: str, out_root: Path, cookies_path: Optional[Path], rclone_remote: Optional[str]) -> None:
    kind, _id = extract_kind_id(url)
    if not _id:
        print(f"[SKIP] Link tidak dikenali: {url}")
        return

    if kind == "folder":
        # ambil nama folder asli via web
        folder_url = f"https://drive.google.com/drive/folders/{_id}"
        rk = extract_resourcekey(url)
        name_from_web = None
        try:
            name_from_web = get_folder_name_from_web(folder_url if not rk else f"{folder_url}?resourcekey={rk}")
        except Exception as e:
            print(f"[WARN] Gagal ambil nama folder: {e}")

        safe_name = sanitize_name(name_from_web or _id)
        local_dir = out_root / f"{safe_name} ({_id})"
        ensure_dir(local_dir)

        # gdown folder (cookies -> no cookies)
        ok = download_with_gdown_folder(folder_url if not rk else f"{folder_url}?resourcekey={rk}",
                                        local_dir, cookies_path=cookies_path)
        if ok:
            print(f"[OK] gdown folder: {safe_name}")
            return

        # fallback: rclone (kalau disediakan)
        if rclone_remote:
            print("[INFO] gdown gagal, mencoba rclone...")
            ok2 = download_with_rclone_folder(rclone_remote, _id, local_dir, resource_key=rk)
            if ok2:
                print(f"[OK] rclone folder: {safe_name}")
                return

        print(f"[ERR] Gagal download folder ini: {url}")

    else:
        # file tunggal → simpan ke subfolder berdasarkan nama file (jika bisa diambil), kalau tidak pakai file_{id}
        # Ambil nama file via uc?view=... (best-effort, optional)
        safe_name = f"file_{_id}"
        local_dir = out_root / safe_name
        ensure_dir(local_dir)

        ok = download_with_gdown_file(_id, local_dir, cookies_path=cookies_path)
        if ok:
            print(f"[OK] gdown file: {_id}")
            return

        print(f"[ERR] Gagal download file ini: {url}")

def read_links_file(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"links file not found: {path}")
    lines = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines

def main():
    ap = argparse.ArgumentParser(description="Bulk download Google Drive public links (folder/file) with gdown CLI + cookies & rclone fallback.")
    ap.add_argument("-i", "--input", required=True, help="links.txt (1 link per baris)")
    ap.add_argument("-o", "--out", default="downloads_named", help="root output dir")
    ap.add_argument("--cookies", default="cookies.txt", help="path cookies.txt (opsional, jika ada dipakai duluan)")
    ap.add_argument("--remote", default=None, help="rclone remote name (opsional, contoh: gdrive). Jika diisi, dipakai sebagai fallback.")
    args = ap.parse_args()

    out_root = Path(args.out).resolve()
    ensure_dir(out_root)

    cookies_path = Path(args.cookies).resolve() if args.cookies else None
    links = read_links_file(Path(args.input).resolve())

    print(f"Output dir : {out_root}")
    print(f"Links      : {len(links)}")
    print(f"Cookies    : {cookies_path if (cookies_path and cookies_path.exists()) else 'None/Not used'}")
    print(f"rclone     : {args.remote if args.remote else 'Disabled'}")

    for idx, url in enumerate(links, 1):
        print(f"\n[{idx}/{len(links)}] Processing: {url}")
        try:
            process_link(url, out_root, cookies_path if (cookies_path and cookies_path.exists()) else None, args.remote)
        except Exception as e:
            print(f"[ERR] {url} -> {e}")

    print("\n✅ Selesai.")

if __name__ == "__main__":
    sys.exit(main())
