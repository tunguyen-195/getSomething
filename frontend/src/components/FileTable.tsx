import React, { useEffect, useState } from 'react';
import { Box, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, IconButton, Button, CircularProgress, Typography, Snackbar, Alert, Tooltip } from '@mui/material';
import CloudDownloadIcon from '@mui/icons-material/CloudDownload';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import InsightsIcon from '@mui/icons-material/Insights';
import InvestigationSummaryCard from './InvestigationSummaryCard';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import AudioPlayer from 'react-h5-audio-player';
import 'react-h5-audio-player/lib/styles.css';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import AccessTimeIcon from '@mui/icons-material/AccessTime';

interface FileInfo {
  id: string;
  filename: string;
  status: string;
  url: string;
  task_id?: string;
}

interface FileTableProps {
  caseId: string;
  onSelectFile?: (fileId: string) => void;
  selectedFileId?: string | null;
}

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

const FileTable: React.FC<FileTableProps> = ({ caseId, onSelectFile, selectedFileId }) => {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audio, setAudio] = useState<string | null>(null);
  const [processingIds, setProcessingIds] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [processSuccess, setProcessSuccess] = useState<string | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);
  const [openFileId, setOpenFileId] = useState<string | null>(null);
  const [taskData, setTaskData] = useState<any>(null);
  const [taskLoading, setTaskLoading] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  const reloadFiles = () => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE_URL}/api/v1/cases/${caseId}/files`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to load files');
        return res.json();
      })
      .then(data => {
        setFiles(data);
        setLoading(false);
      })
      .catch(() => {
        setError('Failed to load files');
        setLoading(false);
      });
  };

  useEffect(() => {
    reloadFiles();
    // eslint-disable-next-line
  }, [caseId]);

  // Polling trạng thái task cho từng file có task_id
  useEffect(() => {
    const interval = setInterval(() => {
      files.forEach(file => {
        if (file.task_id && (!file.status || file.status === 'pending' || file.status === 'processing')) {
          fetch(`${API_BASE_URL}/api/v1/audio/tasks/${file.task_id}`)
            .then(res => res.json())
            .then(data => {
              setFiles(prevFiles => prevFiles.map(f => f.id === file.id ? { ...f, status: data.status } : f));
            })
            .catch(() => {});
        }
      });
    }, 3000);
    return () => clearInterval(interval);
  }, [files]);

  const handleDownload = (url: string) => {
    window.open(url, '_blank');
  };

  const handlePlay = (filename: string) => {
    setAudio(`${API_BASE_URL}/api/v1/audio/public/${encodeURIComponent(filename)}`);
  };

  const handleProcess = async (taskId: string) => {
    if (!taskId) {
      setError('Không tìm thấy task_id cho file này!');
      return;
    }
    setFiles(prev => prev.map(f => (f.task_id === taskId || f.id === taskId ? { ...f, status: 'processing' } : f)));
    setProcessingIds(prev => [...prev, taskId]);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/audio/process-task/${taskId}`, { method: 'POST' });
      if (!res.ok) throw new Error('Xử lý thất bại');
      const updated = await res.json();
      setFiles(prev => prev.map(f => (f.task_id === taskId || f.id === taskId ? { ...f, status: updated.status } : f)));
      setProcessSuccess('Xử lý thành công!');
      let count = 0;
      const poll = () => {
        reloadFiles();
        count++;
        if (count < 10) setTimeout(poll, 1000);
      };
      poll();
    } catch (e) {
      setError('Xử lý thất bại');
    } finally {
      setProcessingIds(prev => prev.filter(id => id !== taskId));
    }
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    setLoading(true);
    setUploadError(null);
    setUploadSuccess(false);
    const filesArr = Array.from(e.target.files);
    Promise.all(filesArr.map(file => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('case_id', caseId);
      return fetch(`${API_BASE_URL}/api/v1/audio/upload`, {
        method: 'POST',
        body: formData,
      });
    }))
      .then(responses => {
        if (responses.some(res => !res.ok)) throw new Error('Upload failed');
        setUploadSuccess(true);
        return fetch(`${API_BASE_URL}/api/v1/cases/${caseId}/files`).then(res2 => res2.json());
      })
      .then(data => setFiles(data))
      .catch(() => setUploadError('Upload failed'))
      .finally(() => setLoading(false));
  };

  const handleOpenVisualize = (file: FileInfo) => {
    if (!file.task_id) return;
    setOpenFileId(file.id);
    setTaskLoading(true);
    setTaskError(null);
    setTaskData(null);
    fetch(`${API_BASE_URL}/api/v1/audio/tasks/${file.task_id}`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch task data');
        return res.json();
      })
      .then(data => setTaskData(data))
      .catch(() => setTaskError('Failed to fetch task data'))
      .finally(() => setTaskLoading(false));
  };

  const handleCloseVisualize = () => {
    setOpenFileId(null);
    setTaskData(null);
    setTaskError(null);
    setTaskLoading(false);
  };

  return (
    <Box>
      <Box display="flex" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight={700} sx={{ flexGrow: 1 }}>Files</Typography>
        <Button
          variant="outlined"
          component="label"
          startIcon={<UploadFileIcon />}
        >
          Upload
          <input type="file" hidden onChange={handleUpload} accept="audio/*" multiple />
        </Button>
      </Box>
      {loading ? (
        <Box display="flex" justifyContent="center" alignItems="center" height={120}>
          <CircularProgress />
        </Box>
      ) : error ? (
        <Typography color="error">{error}</Typography>
      ) : files.length === 0 ? (
        <Box textAlign="center" color="text.secondary" py={4}>
          <Typography>Chưa có file audio nào cho vụ việc này.</Typography>
          <Typography variant="body2" mt={1}>Nhấn <b>Upload</b> để tải file audio lên.</Typography>
        </Box>
      ) : (
        <TableContainer sx={(theme) => ({
          borderRadius: 1.5,
          boxShadow: theme.palette.mode === 'dark' ? '0 4px 24px #7c4dff18' : '0 2px 8px #b388ff11',
          background: theme.palette.mode === 'dark'
            ? 'linear-gradient(135deg, #23272f 0%, #2e2e3a 100%)'
            : 'linear-gradient(135deg, #fffde7 0%, #e3f2fd 60%, #b9f6ca 100%)',
          border: theme.palette.mode === 'dark' ? '1px solid #7c4dff' : '1px solid #e0e7ef',
          transition: 'box-shadow 0.3s',
          width: '100%',
          maxWidth: 900,
          margin: '0 auto',
          p: 2,
          '&:hover': { boxShadow: theme.palette.mode === 'dark' ? '0 8px 32px #7c4dff33' : '0 4px 16px #7c4dff33' },
        })}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={(theme) => ({
                  color: theme.palette.mode === 'dark' ? theme.palette.text.primary : undefined,
                  background: 'transparent',
                  borderBottom: theme.palette.mode === 'dark' ? '1px solid #3a2e4f' : undefined,
                })}>Tên file</TableCell>
                <TableCell sx={(theme) => ({
                  minWidth: 120,
                  textAlign: 'center',
                  verticalAlign: 'middle',
                  color: theme.palette.mode === 'dark' ? theme.palette.text.primary : undefined,
                  background: 'transparent',
                  borderBottom: theme.palette.mode === 'dark' ? '1px solid #3a2e4f' : undefined,
                })}>Trạng thái</TableCell>
                <TableCell sx={(theme) => ({
                  minWidth: 220,
                  textAlign: 'center',
                  verticalAlign: 'middle',
                  color: theme.palette.mode === 'dark' ? theme.palette.text.primary : undefined,
                  background: 'transparent',
                  borderBottom: theme.palette.mode === 'dark' ? '1px solid #3a2e4f' : undefined,
                })}>Hành động</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {files.map((file, idx) => (
                <TableRow
                  key={file.filename}
                  hover
                  sx={(theme) => ({
                    background: theme.palette.mode === 'dark' ? 'transparent' : undefined,
                    '&:hover': {
                      background: theme.palette.mode === 'dark' ? 'rgba(124,77,255,0.08)' : undefined,
                    },
                  })}
                >
                  <TableCell>{file.filename}</TableCell>
                  <TableCell sx={{ textAlign: 'center', verticalAlign: 'middle' }}>
                    {processingIds.includes(file.id) ? (
                      <Tooltip title="Đang xử lý"><CircularProgress size={20} color="primary" /></Tooltip>
                    ) : file.status === 'completed' ? (
                      <Tooltip title="Hoàn thành"><CheckCircleIcon color="success" /></Tooltip>
                    ) : file.status === 'processing' ? (
                      <Tooltip title="Đang xử lý"><CircularProgress size={20} color="primary" /></Tooltip>
                    ) : file.status === 'failed' ? (
                      <Tooltip title="Lỗi"><ErrorIcon color="error" /></Tooltip>
                    ) : (
                      <Tooltip title="Chờ xử lý"><AccessTimeIcon color="disabled" /></Tooltip>
                    )}
                  </TableCell>
                  <TableCell sx={{ minWidth: 220, textAlign: 'center', verticalAlign: 'middle', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                    <IconButton
                      key="download"
                      onClick={() => handleDownload(file.url)}
                      sx={{
                        borderRadius: '50%',
                        width: 40,
                        height: 40,
                        background: 'rgba(255,255,255,0.35)',
                        backdropFilter: 'blur(6px)',
                        boxShadow: '0 2px 8px #7c4dff22',
                        color: '#7c4dff',
                        transition: 'background 0.25s, color 0.25s',
                        '&:hover': {
                          background: 'linear-gradient(90deg, #7c4dff 0%, #43e97b 100%)',
                          color: '#fff',
                          boxShadow: '0 4px 16px #7c4dff33',
                        },
                        mr: 1.2,
                      }}
                    >
                      <CloudDownloadIcon fontSize="medium" />
                    </IconButton>
                    <IconButton
                      key="play"
                      onClick={() => handlePlay(file.filename)}
                      sx={{
                        borderRadius: '50%',
                        width: 40,
                        height: 40,
                        background: 'rgba(255,255,255,0.35)',
                        backdropFilter: 'blur(6px)',
                        boxShadow: '0 2px 8px #43e97b22',
                        color: '#43e97b',
                        transition: 'background 0.25s, color 0.25s',
                        '&:hover': {
                          background: 'linear-gradient(90deg, #43e97b 0%, #7c4dff 100%)',
                          color: '#fff',
                          boxShadow: '0 4px 16px #43e97b33',
                        },
                        mr: 1.2,
                      }}
                    >
                      <PlayArrowIcon fontSize="medium" />
                    </IconButton>
                    <IconButton
                      key="visualize"
                      onClick={() => handleOpenVisualize(file)}
                      sx={{
                        borderRadius: '50%',
                        width: 40,
                        height: 40,
                        background: 'rgba(255,255,255,0.35)',
                        backdropFilter: 'blur(6px)',
                        boxShadow: '0 2px 8px #ffd60022',
                        color: '#ffd600',
                        transition: 'background 0.25s, color 0.25s',
                        '&:hover': {
                          background: 'linear-gradient(90deg, #ffd600 0%, #7c4dff 100%)',
                          color: '#fff',
                          boxShadow: '0 4px 16px #ffd60033',
                        },
                      }}
                    >
                      <InsightsIcon fontSize="medium" />
                    </IconButton>
                    <Button
                      variant="contained"
                      color="primary"
                      size="small"
                      startIcon={<AutoFixHighIcon />}
                      sx={(theme) => ({
                        boxShadow: '0 2px 8px #7c4dff22',
                        borderRadius: 0.75,
                        fontWeight: 700,
                        textTransform: 'none',
                        minWidth: 110,
                        px: 2,
                        py: 1,
                        color: '#fff',
                        background: theme.palette.primary.main,
                        transition: 'background 0.2s',
                        ml: 1.2,
                        '&:hover': {
                          background: theme.palette.primary.dark,
                          color: '#fff',
                        },
                      })}
                      onClick={() => handleProcess(file.task_id || file.id)}
                    >
                      Xử lý
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {audio && (
        <Box mt={2}>
          <AudioPlayer
            src={audio}
            autoPlay
            showJumpControls
            customAdditionalControls={[]}
            layout="horizontal"
            style={{ width: '100%' }}
            onEnded={() => setAudio(null)}
          />
        </Box>
      )}
      <Snackbar open={!!uploadError} autoHideDuration={4000} onClose={() => setUploadError(null)}>
        <Alert severity="error" onClose={() => setUploadError(null)}>{uploadError}</Alert>
      </Snackbar>
      <Snackbar open={uploadSuccess} autoHideDuration={2000} onClose={() => setUploadSuccess(false)}>
        <Alert severity="success" onClose={() => setUploadSuccess(false)}>Upload thành công!</Alert>
      </Snackbar>
      <Snackbar open={!!processSuccess} autoHideDuration={2000} onClose={() => setProcessSuccess(null)}>
        <Alert severity="success" onClose={() => setProcessSuccess(null)}>{processSuccess}</Alert>
      </Snackbar>
      <Snackbar open={!!processError} autoHideDuration={4000} onClose={() => setProcessError(null)}>
        <Alert severity="error" onClose={() => setProcessError(null)}>{processError}</Alert>
      </Snackbar>
      {openFileId && (
        <Dialog open={!!openFileId} onClose={handleCloseVisualize} maxWidth="md" fullWidth>
          <DialogTitle>Data Visualization</DialogTitle>
          <DialogContent>
            <>
              {taskLoading ? (
                <Box display="flex" justifyContent="center" alignItems="center" minHeight={200}><CircularProgress /></Box>
              ) : taskError ? (
                <Alert severity="error">{taskError}</Alert>
              ) : taskData ? (
                taskData.result?.summary || taskData.result?.context_analysis ? (
                  <InvestigationSummaryCard summary={taskData.result?.summary} contextAnalysis={taskData.result?.context_analysis} taskId={taskData.result?.task_id || (files.find(f => f.id === openFileId)?.task_id) || taskData.id} />
                ) : (
                  <Box minHeight={200} display="flex" alignItems="center" justifyContent="center"><Typography color="text.secondary">No data to visualize.</Typography></Box>
                )
              ) : null}
            </>
          </DialogContent>
        </Dialog>
      )}
    </Box>
  );
};

export default FileTable; 