import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  LinearProgress,
  Alert,
  Paper,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  IconButton,
  TextField,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Select,
  InputLabel,
  FormControl,
  CircularProgress,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import DeleteIcon from '@mui/icons-material/Delete';
import AudioFileIcon from '@mui/icons-material/AudioFile';
import CloseIcon from '@mui/icons-material/Close';

interface AudioUploaderProps {
  onNewTask: (task: any) => void;
}

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

const AudioUploader = ({ onNewTask }: AudioUploaderProps) => {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const [cases, setCases] = useState<any[]>([]);
  const [selectedCase, setSelectedCase] = useState<string>('');
  const [openDialog, setOpenDialog] = useState(false);
  const [newCaseName, setNewCaseName] = useState('');
  const [newCaseDesc, setNewCaseDesc] = useState('');
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/v1/cases/`).then(res => res.json()).then(setCases).catch(e => console.error('Error fetching cases:', e));
  }, []);

  const handleCreateCase = async () => {
    if (!newCaseName) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cases/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newCaseName, description: newCaseDesc })
      });
      const data = await res.json();
      fetch(`${API_BASE_URL}/api/v1/cases/`).then(res => res.json()).then(setCases);
      setSelectedCase(data.id);
      setOpenDialog(false);
      setNewCaseName('');
      setNewCaseDesc('');
    } catch (e) {
      console.error('Error creating case:', e);
      setError('Tạo vụ việc thất bại.');
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedCase) {
      setError('Vui lòng chọn vụ việc trước khi chọn file');
      return;
    }
    if (event.target.files) {
      const newFiles = [...event.target.files];
      setFiles(prev => [...prev, ...newFiles]);
      setError(null);
    }
  };

  const handleDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDraggingOver(false);
    if (!selectedCase) {
      setError('Vui lòng chọn vụ việc trước khi kéo thả file');
      return;
    }
    const droppedFiles = Array.from(event.dataTransfer.files).filter(f => f.type.startsWith('audio/'));
    if (droppedFiles.length > 0) {
      setFiles(prev => [...prev, ...droppedFiles]);
      setError(null);
    }
  }, [selectedCase]);

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDraggingOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDraggingOver(false);
  }, []);

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleProcess = async () => {
    if (files.length === 0) {
      setError('Vui lòng chọn file để xử lý');
      return;
    }
    if (!selectedCase) {
      setError('Vui lòng chọn vụ việc trước khi xử lý');
      return;
    }
    setUploading(true);
    setError(null);
    setUploadProgress(0);
    try {
      let completed = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('options', JSON.stringify({
          language: 'vi',
          model_type: 'whisper'
        }));
        formData.append('case_id', selectedCase);
        formData.append('model_name', 'gemma2:9b');

        const totalSize = files.reduce((sum, f) => sum + f.size, 0);
        let uploadedSize = 0;

        await new Promise(resolve => setTimeout(resolve, 500));
        uploadedSize += file.size;
        setUploadProgress(Math.round((uploadedSize / totalSize) * 100));

        const response = await fetch(`${API_BASE_URL}/api/v1/audio/upload`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error('Xử lý thất bại cho file: ' + file.name);
        }
        const data = await response.json();
        // Gọi xử lý file sau khi upload thành công
        const processRes = await fetch(`${API_BASE_URL}/api/v1/audio/process-task/${data.task_id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_name: 'gemma2:9b' })
        });
        if (!processRes.ok) {
          throw new Error('Xử lý file thất bại sau khi upload: ' + file.name);
        }
        const processData = await processRes.json();
        onNewTask({
          id: data.task_id,
          status: 'completed',
          filename: file.name,
          case_id: selectedCase,
        });
        completed++;
      }
      setFiles([]);
      if (inputRef.current) inputRef.current.value = '';
      setSnackbarOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Xử lý thất bại');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const formatBytes = (bytes: number, decimals = 2) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  };

  return (
    <Card sx={{ mb: 4, boxShadow: 6, borderRadius: 4 }}>
      <CardContent>
        <Box display="flex" alignItems="center" justifyContent="space-between" mb={3}>
          <Typography variant="h5" fontWeight={700} color="primary.dark">Xử lý file âm thanh</Typography>
          {uploading && (
            <Box display="flex" alignItems="center">
              <CircularProgress size={24} sx={{ mr: 1 }} />
              <Typography variant="body2" color="text.secondary">Đang tải lên... ({uploadProgress}%)</Typography>
            </Box>
          )}
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box display="flex" alignItems="center" mb={3} gap={2}>
          <FormControl sx={{ minWidth: 300 }} disabled={uploading}>
            <InputLabel id="case-select-label">Chọn vụ việc (Case)</InputLabel>
            <Select
              labelId="case-select-label"
              value={selectedCase}
              label="Chọn vụ việc (Case)"
              onChange={e => setSelectedCase(e.target.value)}
              error={!selectedCase && files.length > 0}
            >
              {!cases.length && (
                <MenuItem value="" disabled>
                  <em>Bạn cần tạo vụ việc trước</em>
                </MenuItem>
              )}
              {cases.map((c: any) => (
                <MenuItem key={c.id} value={c.id}>
                  <Box>
                    <Typography fontWeight={600}>{c.title}</Typography>
                    {c.description && <Typography variant="caption" color="text.secondary">{c.description}</Typography>}
                  </Box>
                </MenuItem>
              ))}
            </Select>
            {!selectedCase && files.length > 0 && (
              <Typography variant="caption" color="error" sx={{ mt: 0.5, ml: 1 }}>
                Vui lòng chọn vụ việc
              </Typography>
            )}
          </FormControl>

          <Button variant="outlined" onClick={() => setOpenDialog(true)} disabled={uploading} sx={{ px: 3, py: 1.5, fontWeight: 600 }}>
            Tạo vụ việc mới
          </Button>
        </Box>

        <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Tạo vụ việc mới</DialogTitle>
          <DialogContent>
            <TextField
              label="Tên vụ việc"
              value={newCaseName}
              onChange={e => setNewCaseName(e.target.value)}
              fullWidth
              sx={{ mb: 2 }}
              autoFocus
              variant="outlined"
            />
            <TextField
              label="Mô tả vụ việc (tuỳ chọn)"
              value={newCaseDesc}
              onChange={e => setNewCaseDesc(e.target.value)}
              fullWidth
              multiline
              minRows={3}
              variant="outlined"
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setOpenDialog(false)} color="secondary">Huỷ</Button>
            <Button onClick={handleCreateCase} variant="contained" disabled={!newCaseName}>Tạo</Button>
          </DialogActions>
        </Dialog>

        <Paper
          sx={{
            p: 4,
            mb: 3,
            border: `2px dashed ${isDraggingOver ? '#1976d2' : '#ccc'}`,
            borderRadius: 4,
            textAlign: 'center',
            cursor: selectedCase && !uploading ? 'pointer' : 'not-allowed',
            backgroundColor: !selectedCase || uploading || isDraggingOver ? '#f5f5f5' : '#e3f2fd',
            transition: 'border-color 0.3s, background-color 0.3s',
          }}
          onDrop={selectedCase && !uploading ? handleDrop : undefined}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <input
            ref={inputRef}
            accept="audio/*"
            style={{ display: 'none' }}
            id="audio-file-input"
            type="file"
            multiple
            onChange={handleFileChange}
            disabled={!selectedCase || uploading}
          />
          <label htmlFor="audio-file-input">
            <Button
              variant="contained"
              component="span"
              startIcon={<CloudUploadIcon />}
              disabled={uploading || !selectedCase}
              sx={{ fontWeight: 600, fontSize: 16, px: 4, py: 2, borderRadius: 3 }}
            >
              Chọn file âm thanh
            </Button>
          </label>
          <Typography variant="body1" color="text.secondary" sx={{ mt: 2, fontWeight: 500 }}>
            hoặc kéo thả file(s) âm thanh vào đây
          </Typography>
          {!selectedCase && (
            <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
              Vui lòng chọn vụ việc trước khi chọn hoặc kéo thả file.
            </Typography>
          )}
        </Paper>

        {files.length > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" fontWeight={600} mb={2}>File đã chọn ({files.length}):</Typography>
            <List sx={{ border: '1px solid #eee', borderRadius: 2, p: 0 }}>
              {files.map((file, idx) => (
                <ListItem
                  key={idx}
                  secondaryAction={
                    <IconButton edge="end" aria-label="delete" onClick={() => removeFile(idx)} disabled={uploading}>
                      <DeleteIcon color="error" />
                    </IconButton>
                  }
                  sx={{
                    borderBottom: idx < files.length - 1 ? '1px solid #eee' : 'none',
                    '&:hover': { bgcolor: '#f5f5f5' },
                  }}
                >
                  <ListItemIcon>
                    <AudioFileIcon color="primary" fontSize="large" />
                  </ListItemIcon>
                  <ListItemText
                    primary={<Typography fontWeight={500}>{file.name}</Typography>}
                    secondary={
                      <Typography variant="body2" color="text.secondary">
                        {formatBytes(file.size)}
                      </Typography>
                    }
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        <Box>
          <Button
            variant="contained"
            color="primary"
            onClick={handleProcess}
            disabled={files.length === 0 || uploading || !selectedCase}
            sx={{ fontWeight: 700, fontSize: 18, px: 4, py: 2, borderRadius: 3 }}
          >
            {uploading ? `Đang xử lý (${uploadProgress}%)` : 'Xử lý File'}
          </Button>
        </Box>

        <Snackbar
          open={snackbarOpen}
          autoHideDuration={6000}
          onClose={() => setSnackbarOpen(false)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert
            onClose={() => setSnackbarOpen(false)}
            severity="success"
            sx={{ width: '100%', fontSize: 16 }}
            action={
              <IconButton
                aria-label="close"
                color="inherit"
                size="small"
                onClick={() => {
                  setSnackbarOpen(false);
                }}
              >
                <CloseIcon fontSize="inherit" />
              </IconButton>
            }
          >
            File(s) đã được tải lên thành công và đang được xử lý!
          </Alert>
        </Snackbar>
      </CardContent>
    </Card>
  );
};

export default AudioUploader; 