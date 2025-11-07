# Cấu Hình Tiếng Việt Mặc Định

## Tổng Quan
Dự án này đã được cấu hình mặc định để sử dụng **tiếng Việt** cho tất cả các chức năng AI và xử lý ngôn ngữ.

## Cấu Hình Mặc Định

### 1. Ngôn Ngữ
- **DEFAULT_LANGUAGE**: `vi` (Tiếng Việt)
- **FORCE_VIETNAMESE_OUTPUT**: `True` (Ép buộc đầu ra tiếng Việt)

### 2. Model AI
- **DEFAULT_AI_MODEL**: `gpt-oss` (Model GPT mặc định)
- **Model dự phòng**: `qwen2.5:7b`, `gemma2:9b`, `deepseek-r1:7b`

### 3. Xử Lý Tự Động
- Tất cả tóm tắt được ép buộc ra tiếng Việt
- Hàm `force_vietnamese_output()` tự động dịch từ tiếng Anh còn sót
- Prompt mạnh mẽ yêu cầu 100% tiếng Việt

## Cách Sử Dụng

### 1. Upload Audio (Tự Động Tiếng Việt)
```bash
POST /api/v1/audio/upload
# Không cần chỉ định model_name - tự động dùng gpt-oss
```

### 2. Xử Lý Task (Tự Động Tiếng Việt)
```bash
POST /api/v1/audio/process-task/{task_id}
# Không cần chỉ định model_name - tự động dùng gpt-oss
```

### 3. Tóm Tắt (Tự Động Tiếng Việt)
```bash
POST /api/v1/audio/summarize-multi
# Không cần chỉ định model_name - tự động dùng gpt-oss
```

## Tùy Chỉnh Model

Nếu muốn sử dụng model khác, vẫn có thể chỉ định:

```bash
POST /api/v1/audio/process-task/{task_id}
{
  "model_name": "qwen2.5:7b",
  "diarization_method": "none"
}
```

## Các Model Hỗ Trợ Tiếng Việt

1. **gpt-oss** (Mặc định) - Chất lượng cao nhất
2. **qwen2.5:7b** - Tốc độ nhanh, chất lượng tốt
3. **gemma2:9b** - Cân bằng giữa tốc độ và chất lượng
4. **deepseek-r1:7b** - Tốt cho tóm tắt
5. **mistral:7b-instruct** - Đa năng
6. **llama3.2:3b** - Nhẹ, nhanh

## Lưu Ý

- Tất cả đầu ra đều được ép buộc tiếng Việt
- Nếu phát hiện tiếng Anh, hệ thống sẽ tự động dịch
- Cảnh báo sẽ hiển thị nếu có từ tiếng Anh không thể dịch tự động
- Không cần thay đổi cấu hình - mọi thứ đã mặc định tiếng Việt

## Kiểm Tra Cấu Hình

```bash
# Kiểm tra Ollama models
ollama list

# Test model gpt-oss
ollama run gpt-oss "Xin chào, hãy trả lời bằng tiếng Việt"
```
