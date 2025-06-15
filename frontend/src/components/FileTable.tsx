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

  const handleDownload = (url: string) => {
    window.open(url, '_blank');
  };

  const handlePlay = (filename: string) => {
    setAudio(`${API_BASE_URL}/api/v1/audio/public/${encodeURIComponent(filename)}`);
  };

  const handleProcess = (fileId: string) => {
    setProcessingIds(ids => [...ids, fileId]);
    setProcessError(null);
    setProcessSuccess(null);
    const fileObj = files.find(f => f.id === fileId);
    if (!fileObj || !('task_id' in fileObj) || !fileObj.task_id) {
      setProcessError('Không tìm thấy task_id để xử lý file');
      setProcessingIds(ids => ids.filter(id => id !== fileId));
      return;
    }
    fetch(`${API_BASE_URL}/api/v1/audio/process-task/${fileObj.task_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: 'gemma2:9b' })
    })
      .then(res => {
        if (!res.ok) throw new Error('Xử lý thất bại');
        setProcessSuccess('Xử lý thành công!');
        // Polling reload files trong 10 giây để đảm bảo dữ liệu mới nhất
        let count = 0;
        const poll = () => {
          reloadFiles();
          count++;
          if (count < 10) setTimeout(poll, 1000);
        };
        poll();
      })
      .catch(() => setProcessError('Xử lý thất bại'))
      .finally(() => setProcessingIds(ids => ids.filter(id => id !== fileId)));
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
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>File Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {files.map(file => (
                <TableRow
                  key={file.id}
                  hover
                  selected={selectedFileId === file.id}
                  onClick={() => onSelectFile && onSelectFile(file.id)}
                  sx={{ cursor: onSelectFile ? 'pointer' : 'default' }}
                >
                  <TableCell>{file.filename}</TableCell>
                  <TableCell>{file.status}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Tải về"><IconButton onClick={e => { e.stopPropagation(); handleDownload(file.url); }}><CloudDownloadIcon /></IconButton></Tooltip>
                    <Tooltip title="Nghe">
                      <IconButton onClick={e => { e.stopPropagation(); handlePlay(file.filename); }}><PlayArrowIcon /></IconButton>
                    </Tooltip>
                    <Tooltip title="Xử lý">
                      <span>
                        <IconButton onClick={e => { e.stopPropagation(); handleProcess(file.id); }} disabled={processingIds.includes(file.id) || !file.task_id}>
                          {processingIds.includes(file.id) ? <CircularProgress size={20} /> : <AutoFixHighIcon />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title="Visualize">
                      <span>
                        <IconButton onClick={e => { e.stopPropagation(); handleOpenVisualize(file); }} disabled={!file.task_id}>
                          <InsightsIcon color="primary" />
                        </IconButton>
                      </span>
                    </Tooltip>
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