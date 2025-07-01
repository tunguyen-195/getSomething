import os
import sys
import subprocess
import shutil
import zipfile
import urllib.request
import glob
import ctypes
import platform

CUDA_PATHS = [
    os.environ.get('CUDA_PATH', ''),
    r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.0',
    r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8',
    r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.7',
    r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.6',
]

CUDNN_DLL = 'cudnn_ops64_9.dll'


def find_cuda_bin():
    for base in CUDA_PATHS:
        if base and os.path.exists(os.path.join(base, 'bin')):
            return os.path.join(base, 'bin')
    return None

def check_cuda():
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        print(f"[INFO] torch.cuda.is_available(): {cuda_ok}")
        if cuda_ok:
            print(f"[INFO] CUDA version: {torch.version.cuda}")
        else:
            print("[WARN] CUDA không khả dụng với torch!")
        return cuda_ok
    except ImportError:
        print("[ERROR] torch chưa được cài đặt!")
        return False

def check_cudnn(cuda_bin):
    dll_path = os.path.join(cuda_bin, CUDNN_DLL)
    if os.path.exists(dll_path):
        print(f"[INFO] Đã tìm thấy {CUDNN_DLL} tại {dll_path}")
        return True
    else:
        print(f"[WARN] Không tìm thấy {CUDNN_DLL} trong {cuda_bin}")
        return False

def add_cuda_to_path(cuda_bin):
    path = os.environ.get('PATH', '')
    if cuda_bin not in path:
        os.environ['PATH'] = cuda_bin + os.pathsep + path
        print(f"[INFO] Đã thêm {cuda_bin} vào PATH tạm thời cho session này.")
    else:
        print(f"[INFO] {cuda_bin} đã có trong PATH.")

def suggest_cudnn_download(cuda_bin):
    print("""
[HƯỚNG DẪN] Bạn cần tải cuDNN phù hợp với phiên bản CUDA của mình.
- Truy cập: https://developer.nvidia.com/rdp/cudnn-archive
- Đăng nhập, chọn đúng phiên bản CUDA (ví dụ: CUDA 11.x hoặc 12.x)
- Tải bản Windows x64 ZIP, giải nén, copy toàn bộ file .dll trong thư mục bin vào:
  """ + cuda_bin + "\n" + "- Sau đó chạy lại script này để kiểm tra tự động!\n")

def main():
    print("[STEP 1] Kiểm tra CUDA...")
    cuda_bin = find_cuda_bin()
    if not cuda_bin:
        print("[ERROR] Không tìm thấy thư mục CUDA/bin trên máy. Hãy cài đặt CUDA Toolkit!")
        return
    print(f"[INFO] Đã phát hiện CUDA bin: {cuda_bin}")
    add_cuda_to_path(cuda_bin)

    print("[STEP 2] Kiểm tra cudnn_ops64_9.dll...")
    if not check_cudnn(cuda_bin):
        suggest_cudnn_download(cuda_bin)
        return

    print("[STEP 3] Kiểm tra khả năng sử dụng GPU với torch...")
    check_cuda()
    print("[DONE] Môi trường CUDA/cuDNN đã sẵn sàng cho Whisper!")

if __name__ == "__main__":
    main() 