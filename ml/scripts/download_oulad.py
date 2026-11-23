"""Tải bộ dữ liệu công khai OULAD (Open University Learning Analytics Dataset).

Nguồn: UCI Machine Learning Repository - https://archive.ics.uci.edu/dataset/349
Giấy phép CC BY 4.0: được dùng cho nghiên cứu, phải ghi nguồn khi sử dụng:
  Kuzilek J., Hlosta M., Zdrahal Z. (2017). Open University Learning Analytics dataset.
  Scientific Data 4, 170171. https://doi.org/10.1038/sdata.2017.171

Chạy:  python ml/scripts/download_oulad.py
Kết quả: ml/data/public/oulad/*.csv (khoảng 450 MB, đã nằm trong .gitignore)
"""

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ML_DIR / "data" / "public" / "oulad"
URL = "https://archive.ics.uci.edu/static/public/349/open+university+learning+analytics+dataset.zip"
EXPECTED = [
    "assessments.csv",
    "courses.csv",
    "studentAssessment.csv",
    "studentInfo.csv",
    "studentRegistration.csv",
    "studentVle.csv",
    "vle.csv",
]


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1024 * 1024):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  Đã tải {done / 1e6:.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()


def safe_extract(zip_path: Path, out_dir: Path) -> None:
    """Giải nén, chặn file có đường dẫn trỏ ra ngoài thư mục đích (zip slip)."""
    root = out_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if not (root / member.filename).resolve().is_relative_to(root):
                raise SystemExit(f"File nén có đường dẫn không an toàn: {member.filename}")
        zf.extractall(root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true", help="tải lại dù đã có dữ liệu")
    args = parser.parse_args()

    out: Path = args.out
    if not args.force and all((out / name).exists() for name in EXPECTED):
        print(f"Đã có đủ dữ liệu OULAD trong {out}. Dùng --force để tải lại.")
        return

    out.mkdir(parents=True, exist_ok=True)
    archive = out / "_oulad_download.zip"
    print(f"Đang tải OULAD từ UCI...\n  {URL}")
    download(URL, archive)

    print("Đang giải nén...")
    safe_extract(archive, out)
    archive.unlink()
    # Một số bản phát hành lồng thêm một file zip bên trong (vd anonymisedData.zip)
    for nested in list(out.rglob("*.zip")):
        safe_extract(nested, out)
        nested.unlink()

    # Đưa các file CSV về thẳng thư mục đích nếu chúng nằm trong thư mục con
    for name in EXPECTED:
        if not (out / name).exists():
            found = next(out.rglob(name), None)
            if found:
                shutil.move(str(found), out / name)

    missing = [name for name in EXPECTED if not (out / name).exists()]
    if missing:
        raise SystemExit(f"Thiếu file sau khi giải nén: {', '.join(missing)}")

    print(f"Xong. Dữ liệu ở {out}:")
    for name in EXPECTED:
        print(f"  {name:<26} {(out / name).stat().st_size / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
