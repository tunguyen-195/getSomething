import React, { useEffect, useState, useCallback } from 'react';
import {
  Card,
  CardContent,
  Typography,
  List,
  ListItem,
  ListItemText,
  Chip,
  Box,
  CircularProgress,
  IconButton,
  Collapse,
  Button,
  Divider,
  LinearProgress,
  TextField,
  Checkbox,
  Tooltip,
  Avatar,
  Grid,
  Paper,
  MenuItem,
  Select,
  InputLabel,
  FormControl,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Alert,
  Backdrop
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import DownloadIcon from '@mui/icons-material/Download';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import SummarizeIcon from '@mui/icons-material/Summarize';
import AudiotrackIcon from '@mui/icons-material/Audiotrack';
import dayjs from 'dayjs';
import CaseListItem from './CaseListItem';
import TaskListItem from './TaskListItem';
import { AlertColor } from '@mui/material/Alert';
import SearchIcon from '@mui/icons-material/Search';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';

interface Task {
  id: string;
  status: string;
  filename: string;
  result?: any;
  created_at?: string;
  updated_at?: string;
  summary?: string;
  transcript?: string;
  case_id?: string;
}

interface Case {
  id: string;
  case_code: string;
  title: string;
  description?: string;
  tasks: Task[];
}

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

const TaskList = () => {
  const [cases, setCases] = useState<Case[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [date, setDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [loading, setLoading] = useState(false);
  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [selectedTasks, setSelectedTasks] = useState<string[]>([]);
  const [multiSummary, setMultiSummary] = useState<string | null>(null);
  const [multiSummarizing, setMultiSummarizing] = useState(false);
  const [selectedCaseForSummary, setSelectedCaseForSummary] = useState<string>('');
  const [caseSummary, setCaseSummary] = useState<string | null>(null);
  const [caseSummarizing, setCaseSummarizing] = useState(false);
  const [editContextOpen, setEditContextOpen] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [userContextPrompt, setUserContextPrompt] = useState('');
  const [resummarizing, setResummarizing] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: AlertColor }>({ open: false, message: '', severity: 'success' });
  const [expandedSummaryId, setExpandedSummaryId] = useState<string | null>(null);
  const [savedSummaries, setSavedSummaries] = useState<any[]>([]);
  const [processSuccess, setProcessSuccess] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [openCreateCase, setOpenCreateCase] = useState(false);
  const [newCaseName, setNewCaseName] = useState('');
  const [newCaseDesc, setNewCaseDesc] = useState('');
  const [creatingCase, setCreatingCase] = useState(false);
  const [searchActive, setSearchActive] = useState(false);

  const fetchCases = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cases`);
      const data = await res.json();
      setCases(data);
      if (data.length > 0) {
        setSelectedCaseForSummary(data[0].id);
      }
    } catch (e) {
      console.error('Error fetching cases:', e);
    }
  };

  const fetchTasks = async (filterDate?: string, filterCaseId?: string) => {
    setLoading(true);
    let url = `${API_BASE_URL}/api/v1/audio/tasks`;
    const queryParams = new URLSearchParams();
    if (filterDate) {
      queryParams.append('date', filterDate);
    }
    if (filterCaseId) {
      queryParams.append('case_id', filterCaseId);
    }

    if (queryParams.toString()) {
        url += `?${queryParams.toString()}`;
    }

    try {
      console.log('[fetchTasks] Fetching:', url);
      const res = await fetch(url);
      console.log('[fetchTasks] Response:', res);
      const data = await res.json();
      console.log('[fetchTasks] Data:', data);
      if (filterCaseId) {
          setTasks(prevTasks => {
              const tasksWithoutCurrentCase = prevTasks.filter(task => task.case_id !== filterCaseId);
              return [...tasksWithoutCurrentCase, ...data];
          });
      } else {
          setTasks(data);
      }

    } catch (e) {
      console.error('Error fetching tasks:', e);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchCases();
    fetchTasks(date);
  }, [date]);

  useEffect(() => {
    if (processSuccess) {
      fetchCases();
      fetchTasks(date);
    }
    // eslint-disable-next-line
  }, [processSuccess]);

  // Polling tự động cập nhật trạng thái task
  useEffect(() => {
    const interval = setInterval(() => {
      // Lấy danh sách các task đang xử lý
      const processingTasks = tasks.filter(t => t.status === 'pending' || t.status === 'processing');
      if (processingTasks.length > 0) {
        fetchTasks(date);
      }
    }, 3000); // 3 giây
    return () => clearInterval(interval);
  }, [tasks, date]);

  const casesWithTasks = cases.map(caseItem => ({
    ...caseItem,
    tasks: tasks.filter(task => String(task.case_id) === String(caseItem.id)).sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf())
  })).sort((a, b) => {
    // Sắp xếp theo task mới nhất trong case
    const aLatest = a.tasks[0]?.created_at ? dayjs(a.tasks[0].created_at).valueOf() : 0;
    const bLatest = b.tasks[0]?.created_at ? dayjs(b.tasks[0].created_at).valueOf() : 0;
    return bLatest - aLatest;
  });

  const handleToggleExpandCase = (caseId: string) => {
    if (expandedCaseId !== caseId) {
      setExpandedCaseId(caseId);
      setExpandedTaskId(null);
      fetchTasks(undefined, caseId);
    } else {
      setExpandedCaseId(null);
      setExpandedTaskId(null);
    }
  };

  const handleToggleExpandTask = (taskId: string | null) => {
    setExpandedTaskId(expandedTaskId === taskId ? null : taskId);
    setExpandedSummaryId(null);
  };

  const handleToggleExpandSummary = (summaryId: string | null) => {
    setExpandedSummaryId(expandedSummaryId === summaryId ? null : summaryId);
  };

  const handleSelectTask = (taskId: string) => {
    setSelectedTasks(prev => prev.includes(taskId) ? prev.filter(id => id !== taskId) : [...prev, taskId]);
  };

  const handleDownloadTask = (task: Task) => {
    if (task.result) {
      const blob = new Blob([JSON.stringify(task.result, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `result_${task.id}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  const handleEditTaskContext = (task: Task) => {
    setUserContextPrompt(task.result?.user_context_prompt || '');
    setEditingTaskId(task.id);
    setEditContextOpen(true);
  };

  const handleSaveContext = async () => {
    if (!editingTaskId) return;
    setTasks(prevTasks => prevTasks.map(task =>
      task.id === editingTaskId
        ? { ...task, result: { ...task.result, user_context_prompt: userContextPrompt } }
        : task
    ));
    try {
      await fetch(`${API_BASE_URL}/api/v1/audio/tasks/${editingTaskId}/context`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_context_prompt: userContextPrompt }),
      });
      setSnackbar({ open: true, message: 'Lưu prompt bổ sung thành công!', severity: 'success' });
    } catch (e) {
      console.error('Error saving context:', e);
      setSnackbar({ open: true, message: 'Lưu prompt bổ sung thất bại!', severity: 'error' });
    }
    setEditContextOpen(false);
    setEditingTaskId(null);
  };

  const handleResummarizeTask = async () => {
    if (!editingTaskId) return;
    setResummarizing(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/audio/tasks/${editingTaskId}/resummarize`, { method: 'POST' });
      const data = await res.json();
      setTasks(prevTasks => prevTasks.map(task =>
        task.id === editingTaskId
          ? { ...task, result: { ...task.result, summary: data.summary } }
          : task
      ));
      setSnackbar({ open: true, message: 'Tóm tắt lại thành công!', severity: 'success' });
    } catch (e) {
      console.error('Error resummarizing:', e);
      setSnackbar({ open: true, message: 'Tóm tắt lại thất bại!', severity: 'error' });
    }
    setResummarizing(false);
    setEditContextOpen(false);
    setEditingTaskId(null);
  };

  const handleMultiSummarize = async () => {
    setMultiSummarizing(true);
    setMultiSummary(null);
    try {
      const selectedTasksData = tasks.filter(t => selectedTasks.includes(t.id) && t.result && (t.result.transcription || t.result.text));
      const transcripts = selectedTasksData.map(t => t.result.transcription || t.result.text || '');
      const res = await fetch(`${API_BASE_URL}/api/v1/audio/summarize-multi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcripts, model_name: 'gemma2:9b' }),
      });
      const data = await res.json();
      setMultiSummary(data.summary || data.result || '');
      setSnackbar({ open: true, message: 'Tóm tắt nhiều file thành công!', severity: 'success' });
    } catch (e) {
      console.error('Error summarizing multi files:', e);
      setMultiSummary('Tóm tắt thất bại.');
      setSnackbar({ open: true, message: 'Tóm tắt nhiều file thất bại!', severity: 'error' });
    } finally {
      setMultiSummarizing(false);
    }
  };

  const handleCaseSummarize = async () => {
    if (!selectedCaseForSummary) return;
    setCaseSummarizing(true);
    setCaseSummary(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/audio/summarize-case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: selectedCaseForSummary, model_name: 'gemma2:9b' }),
      });
      const data = await res.json();
      setCaseSummary(data.summary || data.result || '');
      setSnackbar({ open: true, message: 'Tóm tắt theo vụ việc thành công!', severity: 'success' });
    } catch (e) {
      console.error('Error summarizing case:', e);
      setCaseSummary('Tóm tắt theo vụ việc thất bại.');
      setSnackbar({ open: true, message: 'Tóm tắt theo vụ việc thất bại!', severity: 'error' });
    } finally {
      setCaseSummarizing(false);
    }
  };

  const handleSaveSummary = (type: 'multi' | 'case') => {
    const summaryContent = type === 'multi' ? multiSummary : caseSummary;
    if (!summaryContent) return;
    const summaryObj = {
      id: `${type}-summary-${Date.now()}`,
      type,
      created_at: new Date().toISOString(),
      case: type === 'case' ? cases.find(c => c.id === selectedCaseForSummary) : null,
      files: type === 'multi'
        ? tasks.filter(t => selectedTasks.includes(t.id))
        : tasks.filter(t => t.case_id === (cases.find(c => c.id === selectedCaseForSummary)?.case_code)),
      content: summaryContent,
    };
    setSavedSummaries(prev => [summaryObj, ...prev]);
    setSnackbar({ open: true, message: 'Đã lưu bản tóm tắt!', severity: 'success' });
  };

  const handleCreateCase = async () => {
    if (!newCaseName) return;
    setCreatingCase(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/cases/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newCaseName, description: newCaseDesc })
      });
      const data = await res.json();
      setOpenCreateCase(false);
      setNewCaseName('');
      setNewCaseDesc('');
      fetchCases();
      setSnackbar({ open: true, message: 'Tạo vụ việc mới thành công!', severity: 'success' });
    } catch (e) {
      setSnackbar({ open: true, message: 'Tạo vụ việc thất bại.', severity: 'error' });
    }
    setCreatingCase(false);
  };

  return (
    <Card sx={{ mb: 4, boxShadow: '0 2px 8px #b388ff11', borderRadius: 2, background: 'linear-gradient(135deg, #fffde7 0%, #e3f2fd 60%, #b9f6ca 100%)', border: '1px solid #b388ff', transition: 'box-shadow 0.3s, background 0.3s', ':hover': { boxShadow: '0 8px 32px #7c4dff22', background: 'linear-gradient(90deg, #7c4dff 0%, #43e97b 100%)' } }}>
      <CardContent>
        {/* Sidebar Sticky Header */}
        <Box sx={{ position: 'sticky', top: 0, zIndex: 10, background: 'linear-gradient(135deg, #fffde7 0%, #e3f2fd 60%, #b9f6ca 100%)', pb: 2, mb: 2 }}>
          <Box display="flex" alignItems="center" gap={2} mb={2}>
            <Button
              variant="contained"
              color="primary"
              sx={{
                minWidth: 0,
                px: 1.5,
                py: 1,
                borderRadius: 1.5,
                fontWeight: 700,
                fontSize: 15,
                boxShadow: '0 2px 8px #b388ff22',
                textTransform: 'none',
                transition: 'all 0.2s',
                height: 40,
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                ':hover': { background: 'linear-gradient(90deg,#43e97b 0%,#38f9d7 100%)', color: '#222' },
              }}
              onClick={() => setOpenCreateCase(true)}
              startIcon={<AddIcon sx={{ fontSize: 22 }} />}
            >
              <span style={{ whiteSpace: 'nowrap' }}>Tạo Case</span>
            </Button>
            {/* Search Button/Input */}
            <Box
              sx={{
                position: 'relative',
                minWidth: searchActive ? 180 : 40,
                maxWidth: searchActive ? 320 : 40,
                height: 40,
                border: '1.5px solid #b388ff',
                borderRadius: 1.5,
                background: '#fff',
                boxShadow: searchActive ? '0 2px 8px #b388ff22' : 'none',
                display: 'flex',
                alignItems: 'center',
                px: searchActive ? 1.5 : 0,
                transition: 'all 0.3s cubic-bezier(.4,2,.6,1)',
                overflow: 'hidden',
                cursor: 'pointer',
              }}
              onClick={() => { if (!searchActive) { setSearchActive(true); setSearchFocused(true); } }}
              onBlur={() => { setSearchFocused(false); setSearchActive(false); }}
              tabIndex={0}
            >
              {!searchActive && (
                <IconButton size="small" sx={{ ml: 0.5 }}>
                  <SearchIcon />
                </IconButton>
              )}
              {searchActive && (
                <>
                  <SearchIcon sx={{ mr: 1, color: '#b388ff' }} />
                  <TextField
                    value={searchValue}
                    onChange={e => setSearchValue(e.target.value)}
                    onFocus={() => setSearchFocused(true)}
                    onBlur={() => setSearchFocused(false)}
                    placeholder="Tìm kiếm vụ việc..."
                    variant="standard"
                    InputProps={{ disableUnderline: true, style: { fontSize: 16, fontWeight: 500, background: 'none' } }}
                    sx={{ flex: 1, background: 'none', minWidth: 80 }}
                    autoFocus
                  />
                  {searchValue && (
                    <IconButton size="small" sx={{ ml: 0.5 }} onClick={e => { e.stopPropagation(); setSearchValue(''); }}>
                      <CloseIcon />
                    </IconButton>
                  )}
                </>
              )}
            </Box>
          </Box>
        </Box>

        {/* Dialog tạo case mới */}
        <Dialog open={openCreateCase} onClose={() => setOpenCreateCase(false)} maxWidth="sm" fullWidth>
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
              disabled={creatingCase}
            />
            <TextField
              label="Mô tả vụ việc (tuỳ chọn)"
              value={newCaseDesc}
              onChange={e => setNewCaseDesc(e.target.value)}
              fullWidth
              multiline
              minRows={3}
              variant="outlined"
              disabled={creatingCase}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setOpenCreateCase(false)} color="secondary" disabled={creatingCase}>Huỷ</Button>
            <Button onClick={handleCreateCase} variant="contained" disabled={!newCaseName || creatingCase}>Tạo</Button>
          </DialogActions>
        </Dialog>

        {loading ? (
          <Box display="flex" justifyContent="center" alignItems="center" height={200}>
            <CircularProgress />
            <Typography variant="h6" color="text.secondary" sx={{ ml: 2 }}>Đang tải dữ liệu...</Typography>
          </Box>
        ) : casesWithTasks.filter(c => c.title.toLowerCase().includes(searchValue.toLowerCase())).length === 0 ? (
          <Typography variant="body2" color="text.secondary">Không có vụ việc nào phù hợp.</Typography>
        ) : (
          casesWithTasks.filter(c => c.title.toLowerCase().includes(searchValue.toLowerCase())).map(caseItem => (
            <CaseListItem
              key={caseItem.id}
              caseItem={caseItem}
              isExpanded={expandedCaseId === caseItem.id}
              onToggleExpand={handleToggleExpandCase}
              selectedTasks={selectedTasks}
              onSelectTask={handleSelectTask}
              onDownloadTask={handleDownloadTask}
              onEditTaskContext={handleEditTaskContext}
              editingTaskId={editingTaskId}
              resummarizing={resummarizing}
              expandedTaskId={expandedTaskId}
              onToggleExpandTask={handleToggleExpandTask}
              expandedSummaryId={expandedSummaryId}
              onToggleExpandSummary={handleToggleExpandSummary}
            />
          ))
        )}

        <Box mt={4} display="flex" alignItems="center" gap={3}>
          <Typography variant="h6" fontWeight={700} color="primary.dark">Tóm tắt tổng hợp / Theo vụ việc</Typography>
          <TextField
            select
            size="small"
            label="Chọn vụ việc"
            value={selectedCaseForSummary}
            onChange={(e) => setSelectedCaseForSummary(e.target.value)}
            sx={{ width: 200 }}
          >
            {cases.map((caseItem) => (
              <MenuItem key={caseItem.id} value={caseItem.id}>
                {caseItem.title}
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="contained"
            color="secondary"
            startIcon={<SummarizeIcon />}
            disabled={selectedTasks.length < 1 || multiSummarizing}
            onClick={handleMultiSummarize}
            sx={{ fontWeight: 600, fontSize: 15, px: 3, py: 1.5 }}
          >
            Tóm tắt các file đã chọn ({selectedTasks.length})
          </Button>
          <Button
            variant="outlined"
            color="primary"
            startIcon={<SummarizeIcon />}
            disabled={!selectedCaseForSummary || caseSummarizing}
            onClick={handleCaseSummarize}
            sx={{ fontWeight: 600, fontSize: 15, px: 3, py: 1.5 }}
          >
            Tóm tắt toàn bộ vụ việc
          </Button>
          {multiSummarizing && <CircularProgress size={24} />}
          {caseSummarizing && <CircularProgress size={24} />}
        </Box>

        {(multiSummary || caseSummary) && (
          <Box mt={3} p={3} bgcolor="#e1f5fe" borderRadius={3} boxShadow={2}>
            <Typography variant="h6" color="primary" fontWeight={700} mb={2}>Kết quả tóm tắt:</Typography>
            <Typography variant="body1" color="text.primary" sx={{ whiteSpace: 'pre-wrap' }}>
              {multiSummary || caseSummary}
            </Typography>
            {(multiSummary || caseSummary) && (
              <Button
                variant="contained"
                color="primary"
                sx={{ mt: 2, fontWeight: 600 }}
                onClick={() => handleSaveSummary(multiSummary ? 'multi' : 'case')}
              >
                Lưu bản tóm tắt này
              </Button>
            )}
          </Box>
        )}

        {savedSummaries.length > 0 && (
          <Box mt={4}>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={2}>Các bản tóm tắt đã lưu</Typography>
            {savedSummaries.map(summary => (
              <Paper key={summary.id} sx={{ p: 3, mb: 2, borderRadius: 3, background: '#fffde7' }}>
                <Typography variant="subtitle1" fontWeight={700} color="primary">{summary.type === 'case' ? 'Tóm tắt vụ việc' : 'Tóm tắt nhiều file'}</Typography>
                <Typography variant="caption" color="text.secondary">{new Date(summary.created_at).toLocaleString()}</Typography>
                {summary.case && (
                  <Typography variant="body2" color="text.secondary">Vụ việc: {summary.case.title}</Typography>
                )}
                {summary.files && summary.files.length > 0 && (
                  <Typography variant="body2" color="text.secondary">File liên quan: {summary.files.map((f: { filename: string }) => f.filename).join(', ')}</Typography>
                )}
                <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>{summary.content}</Typography>
              </Paper>
            ))}
          </Box>
        )}

        <Dialog open={editContextOpen} onClose={() => setEditContextOpen(false)} maxWidth="md" fullWidth>
          <DialogTitle>Bổ sung ngữ cảnh cho tóm tắt</DialogTitle>
          <DialogContent>
            <TextField
              label="Prompt bổ sung ngữ cảnh (bạn muốn nhấn mạnh điều gì khi tóm tắt?)"
              value={userContextPrompt}
              onChange={e => setUserContextPrompt(e.target.value)}
              multiline
              minRows={4}
              fullWidth
              sx={{ fontFamily: 'monospace' }}
              disabled={resummarizing}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditContextOpen(false)} disabled={resummarizing}>Huỷ</Button>
            <Button onClick={handleSaveContext} variant="contained" disabled={resummarizing}>Lưu</Button>
            <Button onClick={handleResummarizeTask} variant="outlined" color="secondary" disabled={resummarizing}>
              {resummarizing ? 'Đang tóm tắt lại...' : 'Tóm tắt lại'}
            </Button>
          </DialogActions>
          <Backdrop open={resummarizing} sx={{ zIndex: 1301, color: '#fff' }}>
            <CircularProgress color="inherit" />
            <Typography sx={{ ml: 2 }}>Đang tóm tắt lại...</Typography>
          </Backdrop>
        </Dialog>

        <Snackbar open={snackbar.open} autoHideDuration={4000} onClose={() => setSnackbar({ ...snackbar, open: false })} anchorOrigin={{ vertical: 'top', horizontal: 'center' }}>
          <Alert elevation={6} variant="filled" onClose={() => setSnackbar({ ...snackbar, open: false })} severity={snackbar.severity} sx={{ fontSize: 16 }}>
            {snackbar.message}
          </Alert>
        </Snackbar>

      </CardContent>
    </Card>
  );
};

export default TaskList; 