# 🔧 Sửa lỗi MCP Fetch Server

## 📋 Vấn đề
Cursor báo lỗi khi khởi động MCP server "fetch":
```
"fetch": {
  "command": "python",
  "args": ["-m", "mcp_server_fetch"]
}
```

## ✅ Giải pháp

### Bước 1: Xác nhận package đã được cài đặt
Package `mcp-server-fetch` đã được cài đặt trong Python system:
- ✅ `mcp-server-fetch` version 2025.4.7
- ✅ Python path: `C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe`

### Bước 2: Sửa cấu hình MCP trong Cursor

1. **Mở Cursor Settings:**
   - Nhấn `Ctrl + ,` (hoặc `File > Preferences > Settings`)
   - Tìm kiếm "MCP" hoặc "Model Context Protocol"

2. **Cập nhật cấu hình MCP server "fetch":**

   **Cách 1: Dùng full path đến Python (Khuyến nghị)**
   ```json
   {
     "mcpServers": {
       "fetch": {
         "command": "C:\\Users\\Admin\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
         "args": ["-m", "mcp_server_fetch"]
       }
     }
   }
   ```

   **Cách 2: Đảm bảo Python trong PATH**
   - Kiểm tra `python --version` trong terminal
   - Đảm bảo Python trong PATH trỏ đến đúng nơi đã cài `mcp-server-fetch`

3. **Nếu dùng virtual environment:**
   ```json
   {
     "mcpServers": {
       "fetch": {
         "command": "D:\\Workspace\\SpeechToInfomation\\venv\\Scripts\\python.exe",
         "args": ["-m", "mcp_server_fetch"]
       }
     }
   }
   ```
   ⚠️ **Lưu ý:** Cần cài `mcp-server-fetch` trong venv:
   ```bash
   venv\Scripts\python.exe -m pip install mcp-server-fetch
   ```

### Bước 3: Restart Cursor
Sau khi cập nhật cấu hình, restart Cursor để áp dụng thay đổi.

## 🔍 Kiểm tra

Chạy lệnh sau để xác nhận module hoạt động:
```bash
python -m mcp_server_fetch --help
```

Nếu thấy help message, module đã hoạt động đúng.

## 📝 Ghi chú

- MCP servers được cấu hình trong Cursor settings (không phải trong project)
- Có thể cấu hình global hoặc per-workspace
- Đảm bảo Python interpreter được chỉ định đúng với nơi đã cài package

