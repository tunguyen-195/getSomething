import torch
import gc
import os
from prometheus_client import Gauge, start_http_server
import psutil

MAX_WORKERS = 4  # Tối ưu cho 8-16 core, 8GB VRAM usable
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 4))

RAM_GAUGE = Gauge('worker_ram_usage_mb', 'RAM usage in MB')
VRAM_GAUGE = Gauge('worker_vram_usage_mb', 'VRAM usage in MB')

start_http_server(9090)

def log_resource_usage():
    ram = psutil.virtual_memory().used / 1024 / 1024
    RAM_GAUGE.set(ram)
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        vram = pynvml.nvmlDeviceGetMemoryInfo(handle).used / 1024 / 1024
        VRAM_GAUGE.set(vram)
        if vram > 7000:
            print("[ALERT] VRAM usage cao! Cần giảm batch size hoặc giải phóng VRAM.")
    except Exception:
        pass

def run_worker_pool(task_queue):
    """Chạy worker pool song song, tối ưu cho Windows + RTX 4070 SUPER"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        while not task_queue.empty():
            log_resource_usage()
            batch = []
            for _ in range(BATCH_SIZE):
                if not task_queue.empty():
                    batch.append(task_queue.get())
            if batch:
                futures.append(executor.submit(process_batch, batch))
        for future in futures:
            future.result()

def process_batch(batch):
    # Xử lý batch nhỏ, chỉ dùng GPU NVIDIA
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'  # Chỉ dùng GPU NVIDIA
    from src.speech_to_text.transcriber import Transcriber
    transcriber = Transcriber(
        batch_size=int(os.environ.get('WHISPER_BATCH_SIZE', 4)),
        min_segment_length=10,
        max_segment_length=30,
        context_window=5,
        overlap=0.5
    )
    for task in batch:
        try:
            # Ví dụ: nếu task có file_path
            if hasattr(task, 'file_path'):
                transcriber.transcribe(task.file_path, batch_size=transcriber.batch_size)
            # ... xử lý task ...
            pass
        except Exception as e:
            print(f"Error processing task: {e}")
    # Giải phóng RAM/VRAM sau mỗi batch
    torch.cuda.empty_cache()
    gc.collect() 