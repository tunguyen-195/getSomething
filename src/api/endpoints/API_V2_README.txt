# API v2 Endpoints Summary

Created: src/api/endpoints/audio_v2.py

Endpoints:
1. POST /upload - Upload only
2. POST /batch-upload - Multiple files
3. POST /transcribe/{task_id} - Transcribe step (async/sync)
4. POST /summarize/{task_id} - Summarize step (async/sync)  
5. POST /visualize/{task_id} - Visualize step (async/sync)
6. GET /tasks/{task_id}/status - Status polling
7. POST /batch-transcribe - Parallel transcription

Features:
- Async + Sync modes for all operations
- Celery task dispatch
- Status polling support
- Error handling
- Batch operations

Next: Update router + Frontend integration
