# techContext.md

## Công nghệ sử dụng
- **Backend:** Python 3.10+, FastAPI, Celery, Redis, PostgreSQL, SQLAlchemy, Pydantic
- **Frontend:** React 18, TypeScript 4, Material-UI 5, Redux Toolkit, React Query, Socket.io-client
- **AI Models:** Whisper, Vosk, BART, T5, Mistral-7B, Llama-2-7B, **NeMo, WhisperX, pyannote.audio (Speaker Diarization)**
- **DevOps:** Docker, Docker Compose, Nginx, Gunicorn, GitHub Actions
- **Audio Processing:** librosa, pydub, soundfile
- **Monitoring:** Prometheus, Grafana, Loki

## Ràng buộc kỹ thuật
- Chạy offline hoàn toàn
- Hỗ trợ batch, song song, realtime
- Tối ưu cho GPU/CPU local
- Đảm bảo bảo mật dữ liệu
- **UI/UX: cần điều chỉnh color scheme, ưu tiên tone trắng/xám/navy/tím nhạt, tránh xanh pastel quá sáng.**
- **Speaker Diarization: Cho phép bật/tắt, chọn giải pháp (NeMo/WhisperX) ngay từ UI, pipeline backend dạng module, dễ mở rộng.**
