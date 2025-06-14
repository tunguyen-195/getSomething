#!/usr/bin/env python3
"""
Script sinh SECRET_KEY an toàn cho ứng dụng web.
Có thể in ra màn hình hoặc lưu vào file.
"""
import secrets
import argparse
from pathlib import Path

def generate_secret_key(length: int = 32) -> str:
    """Sinh một SECRET_KEY an toàn."""
    return secrets.token_urlsafe(length)

def main():
    parser = argparse.ArgumentParser(description="Sinh SECRET_KEY an toàn cho ứng dụng.")
    parser.add_argument(
        "-l", "--length", type=int, default=32, help="Độ dài key (mặc định: 32)"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="Lưu SECRET_KEY vào file (tùy chọn)"
    )
    args = parser.parse_args()

    key = generate_secret_key(args.length)

    if args.output:
        args.output.write_text(key)
        print(f"Đã lưu SECRET_KEY vào {args.output}")
    else:
        print(f"SECRET_KEY: {key}")

if __name__ == "__main__":
    main() 