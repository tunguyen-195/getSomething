import React, { useEffect, useRef, useState } from 'react';
import { ThemeProvider, CssBaseline, Box, AppBar, Toolbar, Typography, Paper, Drawer, List, ListItem, ListItemText, Divider, IconButton, InputBase, Button, CircularProgress, Tabs, Tab, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Accordion, AccordionSummary, AccordionDetails, Snackbar, Alert, Tooltip, Chip, Menu, MenuItem } from '@mui/material';
import { lightTheme, darkTheme } from './theme';
import DarkModeToggle from './components/DarkModeToggle';
import SearchIcon from '@mui/icons-material/Search';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import DeleteIcon from '@mui/icons-material/Delete';
import SortIcon from '@mui/icons-material/Sort';
import TranscriptPanel from './components/TranscriptPanel';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FolderIcon from '@mui/icons-material/Folder';
import FileCard from './components/FileCard';
import TranscribeDialog from './components/TranscribeDialog';
import SummarizeDialog from './components/SummarizeDialog';
import CompactUploader from './components/CompactUploader';
import FileTable from './components/FileTable';
import VisualizationDialog from './components/VisualizationDialog';
import AnalysisPanel from './components/AnalysisPanel';
import DiarizationPanel from './components/DiarizationPanel';
import { apiFetch, getCurrentUser, login, logout } from './api/client';

interface Case {
  id: string;
  case_code: string;
  title: string;
  description?: string;
  status_id?: string;
  priority_id?: string;
  created_by?: string;
  created_at?: string;
  summaries?: string[];
  transcripts?: string[];
}

const drawerWidth = 320;

async function apiErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.clone().json();
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    return detail ? `HTTP ${response.status}: ${detail}` : `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

function SummaryAccordionItem({ summary, idx, highlightSummary }: { summary: string, idx: number, highlightSummary: (s: string) => React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Accordion defaultExpanded={idx === 0} sx={{ mb: 2 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography fontWeight={600}>File {idx + 1}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Box display="flex" alignItems="center" mb={2}>
          <Button
            onClick={handleCopy}
            variant="outlined"
            color={copied ? 'success' : 'primary'}
            size="small"
            startIcon={<ContentCopyIcon />}
            sx={{ mr: 2 }}
          >
            {copied ? 'Đã copy' : 'Copy'}
          </Button>
          <Typography variant="body2" color="text.secondary">{copied ? 'Đã copy vào clipboard!' : ''}</Typography>
        </Box>
        {highlightSummary(summary)}
      </AccordionDetails>
    </Accordion>
  );
}

function App() {
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [cases, setCases] = useState<Case[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [selectedCase, setSelectedCase] = useState<Case | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [searchActive, setSearchActive] = useState(false);
  const [searchFocus, setSearchFocus] = useState(false);
  const [tab, setTab] = useState(0);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [createCaseOpen, setCreateCaseOpen] = useState(false);
  const [newCaseTitle, setNewCaseTitle] = useState('');
  const [newCaseDesc, setNewCaseDesc] = useState('');
  const [creatingCase, setCreatingCase] = useState(false);

  // V2 API - Modular workflow state
  const [transcribeDialogOpen, setTranscribeDialogOpen] = useState(false);
  const [summarizeDialogOpen, setSummarizeDialogOpen] = useState(false);
  const [visualizeDialogOpen, setVisualizeDialogOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [visualizeTaskId, setVisualizeTaskId] = useState<string | null>(null);
  const pollingIntervalsRef = useRef<Map<string, NodeJS.Timeout>>(new Map());
  const [files, setFiles] = useState<any[]>([]);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' as 'success' | 'error' | 'info' | 'warning' });
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Sorting State
  const [caseSortBy, setCaseSortBy] = useState<'created_at' | 'title'>('created_at');
  const [caseOrder, setCaseOrder] = useState<'asc' | 'desc'>('desc');
  const [sortMenuAnchor, setSortMenuAnchor] = useState<null | HTMLElement>(null);

  const API_V2_BASE = '/api/v1/audio/v2';

  const mapApiFile = (f: any) => ({
    task_id: f.task_id || f.id,
    audio_id: f.audio_id || f.id,
    filename: f.filename,
    status: f.status || 'uploaded',
    duration: f.duration,
    num_speakers: f.num_speakers,
    has_diarization: f.has_diarization,
    has_visualization: f.has_visualization,
    visualization_data: f.visualization_data,
    transcript: f.transcript,
    summary: f.summary,
    formatted_transcript: f.formatted_transcript,
    segments: f.segments,
    context_analysis: f.context_analysis,
    created_at: f.created_at,
    download_url: f.download_url,
  });

  useEffect(() => {
    getCurrentUser()
      .then(user => {
        setCurrentUser(user);
        setLoginOpen(!user);
      })
      .finally(() => setAuthChecked(true));
    const onAuthRequired = () => setLoginOpen(true);
    const onRateLimited = () => setSnackbar({ open: true, message: 'Too many requests. Please wait and retry.', severity: 'warning' });
    window.addEventListener('auth:required', onAuthRequired);
    window.addEventListener('api:rate-limited', onRateLimited);
    return () => {
      window.removeEventListener('auth:required', onAuthRequired);
      window.removeEventListener('api:rate-limited', onRateLimited);
    };
  }, []);

  // Centralized fetch function
  const fetchCases = async () => {
    if (!currentUser) {
      setCases([]);
      setSelectedCase(null);
      setLoadingCases(false);
      return;
    }
    setLoadingCases(true);
    try {
      const res = await apiFetch(`/api/v1/cases?sort_by=${caseSortBy}&order=${caseOrder}`, {
        cache: 'no-store',
        headers: { 'Pragma': 'no-cache', 'Cache-Control': 'no-cache' }
      });
      if (res.status === 401) {
        setCases([]);
        setSelectedCase(null);
        setLoginOpen(true);
        return;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      const data = await res.json();
      const nextCases = Array.isArray(data) ? data : [];
      setCases(nextCases);
      if (!selectedCase && nextCases.length > 0) {
        setSelectedCase(nextCases[0]);
      } else if (selectedCase && !nextCases.some((c: Case) => c.id === selectedCase.id)) {
        setSelectedCase(nextCases[0] || null);
      }
    } catch (err) {
      console.error('Failed to fetch cases:', err);
      setCases([]);
    } finally {
      setLoadingCases(false);
    }
  };

  useEffect(() => {
    if (authChecked && currentUser) {
      fetchCases();
    } else if (authChecked && !currentUser) {
      setCases([]);
      setFiles([]);
      setSelectedCase(null);
    }
  }, [authChecked, currentUser, caseSortBy, caseOrder]);

  // Load files when case selected
  const fetchFiles = async () => {
    if (selectedCase && currentUser) {
      try {
        const res = await apiFetch(`/api/v1/audio?case_id=${selectedCase.id}`);
        if (!res.ok) {
          setFiles([]);
          return;
        }
        const data = await res.json();
        const fileList = Array.isArray(data) ? data : [];
        const mappedFiles = fileList.map(mapApiFile);
        setFiles(mappedFiles);
      } catch (err) {
        console.error('Failed to load files:', err);
        setFiles([]);
      }
    } else {
      setFiles([]);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, [selectedCase]);

  const filteredCases = (Array.isArray(cases) ? cases : []).filter(c =>
    c.title.toLowerCase().includes(search.toLowerCase()) ||
    c.case_code.toLowerCase().includes(search.toLowerCase())
  );

  const toggleMode = () => setMode(prev => (prev === 'light' ? 'dark' : 'light'));

  const handleCreateCase = async () => {
    // Validation
    if (!newCaseTitle.trim()) {
      setSnackbar({
        open: true,
        message: '⚠️ Vui lòng nhập tên case',
        severity: 'warning'
      });
      return;
    }

    setCreatingCase(true);
    try {
      const response = await apiFetch('/api/v1/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newCaseTitle.trim(),
          description: newCaseDesc.trim()
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      // Update UI by refetching to respect sort order
      await fetchCases();
      setSelectedCase(data); // Select the new case

      // Close dialog and reset form
      setCreateCaseOpen(false);
      setNewCaseTitle('');
      setNewCaseDesc('');

      // Show success message
      setSnackbar({
        open: true,
        message: `✅ Case "${data.title}" đã được tạo thành công!`,
        severity: 'success'
      });
    } catch (error: any) {
      console.error('Failed to create case:', error);
      setSnackbar({
        open: true,
        message: `❌ Lỗi: Không thể tạo case. ${error.message || 'Unknown error'}`,
        severity: 'error'
      });
    } finally {
      setCreatingCase(false);
    }
  };

  const handleDeleteCase = async (caseId: string, caseTitle: string, event: React.MouseEvent) => {
    // Stop event propagation to prevent selecting the case
    event.stopPropagation();

    // Confirm deletion
    if (!window.confirm(`Bạn có chắc muốn xóa case "${caseTitle}"?\n\nThao tác này không thể hoàn tác.`)) {
      return;
    }

    try {
      const response = await apiFetch(`/api/v1/cases/${caseId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Update UI by refetching
      await fetchCases();

      // If deleted case was selected, select first remaining case logic handled by fetchCases effect if needed?
      // Actually fetchCases might not reset selection.
      if (selectedCase?.id === caseId) {
        setSelectedCase(null); // Or let the user pick
      }

      // Show success message
      setSnackbar({
        open: true,
        message: `✅ Case "${caseTitle}" đã được xóa`,
        severity: 'success'
      });
    } catch (error: any) {
      console.error('Failed to delete case:', error);
      setSnackbar({
        open: true,
        message: `❌ Lỗi: Không thể xóa case. ${error.message || 'Unknown error'}`,
        severity: 'error'
      });
    }
  };

  // V2 API handlers
  const handleTranscribe = async (options: any) => {
    if (!selectedTaskId) return;
    try {
      const response = await apiFetch(`${API_V2_BASE}/transcribe/${selectedTaskId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enable_diarization: options.enable_diarization,
          diarization_method: options.diarization_method || 'pyannote',
          language: 'vi',
          fast_mode: options.fast_mode,
          async_mode: true
        })
      });
      if (!response.ok) throw new Error('Failed');
      const result = await response.json();
      setFiles(prev => prev.map(f => f.task_id === selectedTaskId ? { ...f, status: 'transcribing' } : f));
      setTranscribeDialogOpen(false);
      setSnackbar({ open: true, message: '🎙️ Transcription started! Please wait...', severity: 'info' });

      // Start polling for status updates
      startPolling(selectedTaskId, 'transcribing');
    } catch (error) {
      setSnackbar({ open: true, message: 'Failed to start', severity: 'error' });
    }
  };

  const handleSummarize = async (options: any) => {
    if (!selectedTaskId) return;
    try {
      const response = await apiFetch(`${API_V2_BASE}/summarize/${selectedTaskId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: options.modelName,
          summary_type: options.summaryType || 'investigation',
          include_context: true,
          async_mode: true
        })
      });
      if (!response.ok) throw new Error('Failed');
      setFiles(prev => prev.map(f => f.task_id === selectedTaskId ? { ...f, status: 'summarizing' } : f));
      setSummarizeDialogOpen(false);
      setSnackbar({ open: true, message: '📊 Summarization started! Please wait...', severity: 'info' });

      // Start polling for status updates
      startPolling(selectedTaskId, 'summarizing');
    } catch (error) {
      setSnackbar({ open: true, message: 'Failed to start', severity: 'error' });
    }
  };

  // Polling function to check task status
  const startPolling = (taskId: string, initialStatus: string) => {
    // Clear existing polling for this task
    const existingInterval = pollingIntervalsRef.current.get(taskId);
    if (existingInterval) {
      clearInterval(existingInterval);
    }

    const pollInterval = setInterval(async () => {
      try {
        // Use v2 status endpoint for better data
        const response = await apiFetch(`${API_V2_BASE}/tasks/${taskId}/status`);
        if (!response.ok) {
          clearInterval(pollInterval);
          pollingIntervalsRef.current.delete(taskId);
          return;
        }

        const statusData = await response.json();
        const currentStatus = statusData.status;

        // Update file status and data
        setFiles(prev => prev.map(f => {
          if (f.task_id === taskId) {
            const updated = { ...f, status: currentStatus };
            // Update transcript if available
            if (statusData.transcript) {
              updated.transcript = statusData.transcript;
            }
            // Update summary if available
            if (statusData.summary) {
              updated.summary = statusData.summary;
            }
            // Update other fields
            if (statusData.num_speakers !== undefined) {
              updated.num_speakers = statusData.num_speakers;
            }
            if (statusData.duration !== undefined) {
              updated.duration = statusData.duration;
            }
            if (statusData.has_visualization !== undefined) {
              updated.has_visualization = statusData.has_visualization;
            }
            if (statusData.visualization_data) {
              updated.visualization_data = statusData.visualization_data;
            }
            if (statusData.segments) {
              updated.segments = statusData.segments;
            }
            if (statusData.context_analysis) {
              updated.context_analysis = statusData.context_analysis;
            }
            if (statusData.audio_id) {
              updated.audio_id = statusData.audio_id;
            }
            if (statusData.download_url) {
              updated.download_url = statusData.download_url;
            }
            return updated;
          }
          return f;
        }));

        // Stop polling if task is complete or failed
        if (currentStatus === 'transcribed' || currentStatus === 'summarized' || currentStatus === 'visualized' || currentStatus === 'failed') {
          clearInterval(pollInterval);
          pollingIntervalsRef.current.delete(taskId);

          if (currentStatus === 'transcribed') {
            setSnackbar({ open: true, message: '✅ Transcription completed!', severity: 'success' });
            void fetchFiles();
          } else if (currentStatus === 'summarized') {
            setSnackbar({ open: true, message: '✅ Summarization completed!', severity: 'success' });
            void fetchFiles();
          } else if (currentStatus === 'visualized') {
            setSnackbar({ open: true, message: '✅ Visualization completed!', severity: 'success' });
            void fetchFiles();
          } else if (currentStatus === 'failed') {
            setSnackbar({ open: true, message: `❌ Task failed: ${statusData.error || 'Unknown error'}`, severity: 'error' });
          }
        }
      } catch (error) {
        console.error('Polling error:', error);
        // Continue polling on error (might be temporary)
      }
    }, 2000); // Poll every 2 seconds

    // Store interval for cleanup
    pollingIntervalsRef.current.set(taskId, pollInterval);
  };

  useEffect(() => {
    return () => {
      pollingIntervalsRef.current.forEach(interval => clearInterval(interval));
      pollingIntervalsRef.current.clear();
    };
  }, []);

  function highlightSummary(summary: string) {
    if (!summary) return null;
    const keywordRegex = /(\b(?:người|địa điểm|thời gian|quyết định|hành động|cảm xúc|chủ đề|thông tin nhạy cảm|thực thể|mục tiêu|kết quả|liên hệ|mối quan hệ|tên|số điện thoại|email|địa chỉ|sự kiện|vai trò|tóm tắt|key points|entities|privacy)\b)/gi;
    const blocks = summary.split(/\n|\r|\u2022|\-/).filter(Boolean);
    return (
      <Box>
        {blocks.map((block, idx) => (
          <Typography key={idx} variant="body1" sx={{ mb: 1, lineHeight: 1.7 }}>
            <span style={{ color: '#1976d2', fontWeight: 700, marginRight: 6 }}>•</span>
            {block.split(keywordRegex).map((part, i) =>
              keywordRegex.test(part) ? <b key={i} style={{ color: '#d32f2f' }}>{part}</b> : part
            )}
          </Typography>
        ))}
      </Box>
    );
  }

  const handleLogin = async () => {
    try {
      const result = await login(loginUsername, loginPassword);
      setCurrentUser(result.user);
      setLoginOpen(false);
      setLoginPassword('');
    } catch (error) {
      setSnackbar({ open: true, message: 'Đăng nhập thất bại', severity: 'error' });
    }
  };

  const handleLogout = async () => {
    await logout();
    setCurrentUser(null);
    setCases([]);
    setFiles([]);
    setSelectedCase(null);
    setLoginOpen(true);
  };

  if (!authChecked) {
    return (
      <ThemeProvider theme={mode === 'light' ? lightTheme : darkTheme}>
        <CssBaseline />
        <Box minHeight="100vh" display="flex" alignItems="center" justifyContent="center">
          <CircularProgress />
        </Box>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={mode === 'light' ? lightTheme : darkTheme}>
      <CssBaseline />
      <AppBar
        position="fixed"
        sx={{
          zIndex: 1300,
          bgcolor: 'background.paper',
          borderBottom: '1px solid',
          borderColor: 'divider',
          boxShadow: 'none',
        }}
        color="default"
        elevation={0}
      >
        <Toolbar sx={{ display: 'flex', alignItems: 'center', gap: 1.5, minHeight: 60, height: 60 }}>
          <IconButton edge="start" color="inherit" onClick={() => setSidebarOpen(!sidebarOpen)}>
            <MenuIcon />
          </IconButton>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <img
              src={mode === 'dark' ? '/logo/white_on_trans.png' : '/logo/trans_bg.png'}
              alt="Cherry2"
              style={{ height: 36, width: 'auto' }}
            />
            <Typography
              variant="h5"
              sx={{
                fontWeight: 700,
                color: 'primary.main',
                letterSpacing: '-0.01em',
                display: { xs: 'none', sm: 'block' },
              }}
            >
              Cherry<span style={{ fontWeight: 800, opacity: 0.7 }}>2</span>
            </Typography>
          </Box>
          <Box sx={{ flexGrow: 1 }} />
          {currentUser && (
            <Typography variant="body2" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
              {currentUser.username}
            </Typography>
          )}
          {currentUser && (
            <Button size="small" variant="outlined" onClick={handleLogout}>
              Logout
            </Button>
          )}
          <DarkModeToggle mode={mode} toggleMode={toggleMode} />
        </Toolbar>
      </AppBar>
      <Drawer
        variant="persistent"
        open={sidebarOpen}
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
            bgcolor: 'background.paper',
            borderRight: '1px solid',
            borderColor: 'divider',
            pt: 8,
          },
        }}
      >
        <Toolbar />
        <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {/* Sidebar Actions */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mb: 1 }}>
            <Button
              variant="contained"
              color="primary"
              onClick={() => setCreateCaseOpen(true)}
              startIcon={<AddIcon />}
              fullWidth
              sx={{ justifyContent: 'flex-start' }}
            >
              New Case
            </Button>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  px: 1.5,
                  py: 1,
                  borderRadius: 1,
                  bgcolor: 'background.default',
                  border: '1px solid',
                  borderColor: 'divider',
                  flex: 1
                }}
              >
                <SearchIcon sx={{ color: 'text.secondary', fontSize: 20 }} />
                <InputBase
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search..."
                  sx={{ flex: 1, fontSize: 14 }}
                />
                {search && (
                  <IconButton size="small" onClick={() => setSearch('')}>
                    <CloseIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                )}
              </Box>
              <Tooltip title="Sắp xếp">
                <IconButton
                  onClick={(e) => setSortMenuAnchor(e.currentTarget)}
                  sx={{
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                    bgcolor: Boolean(sortMenuAnchor) ? 'rgba(0,0,0,0.05)' : 'transparent'
                  }}
                >
                  <SortIcon />
                </IconButton>
              </Tooltip>
            </Box>
            <Menu
              anchorEl={sortMenuAnchor}
              open={Boolean(sortMenuAnchor)}
              onClose={() => setSortMenuAnchor(null)}
              MenuListProps={{ sx: { py: 0 } }}
            >
              <MenuItem
                selected={caseSortBy === 'created_at' && caseOrder === 'desc'}
                onClick={() => { setCaseSortBy('created_at'); setCaseOrder('desc'); setSortMenuAnchor(null); }}
              >
                Mới nhất
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'created_at' && caseOrder === 'asc'}
                onClick={() => { setCaseSortBy('created_at'); setCaseOrder('asc'); setSortMenuAnchor(null); }}
              >
                Cũ nhất
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'title' && caseOrder === 'asc'}
                onClick={() => { setCaseSortBy('title'); setCaseOrder('asc'); setSortMenuAnchor(null); }}
              >
                Tên (A-Z)
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'title' && caseOrder === 'desc'}
                onClick={() => { setCaseSortBy('title'); setCaseOrder('desc'); setSortMenuAnchor(null); }}
              >
                Tên (Z-A)
              </MenuItem>
            </Menu>
          </Box>
          <Divider />
          {loadingCases ? (
            <Box display="flex" justifyContent="center" alignItems="center" height={120}>
              <CircularProgress />
            </Box>
          ) : (
            <List sx={{ px: 1 }}>
              {filteredCases.map(c => (
                <ListItem
                  button
                  key={c.id}
                  selected={selectedCase?.id === c.id}
                  onClick={() => setSelectedCase(c)}
                  sx={{
                    borderRadius: 1,
                    mb: 0.5,
                    px: 1.5,
                    py: 1,
                    bgcolor: selectedCase?.id === c.id ? 'rgba(225, 29, 72, 0.1)' : 'transparent',
                    border: '1px solid',
                    borderColor: selectedCase?.id === c.id ? 'primary.main' : 'transparent',
                    '&:hover': {
                      bgcolor: 'rgba(225, 29, 72, 0.06)',
                    },
                  }}
                >
                  <FolderIcon sx={{ color: selectedCase?.id === c.id ? 'primary.main' : 'text.secondary', mr: 1.5 }} />
                  <ListItemText
                    primary={<Typography fontWeight={500} fontSize={14} color={selectedCase?.id === c.id ? 'primary.main' : 'text.primary'}>{c.title}</Typography>}
                    secondary={c.description ? <Typography variant="caption" color="text.secondary" noWrap>{c.description}</Typography> : null}
                  />
                  <IconButton
                    size="small"
                    onClick={(e) => handleDeleteCase(c.id, c.title, e)}
                    sx={{ opacity: 0.5, '&:hover': { opacity: 1, color: 'error.main' } }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Drawer>
      <Box sx={{ ml: sidebarOpen ? `${drawerWidth}px` : 0, transition: 'margin 0.2s', p: 3, pt: 10, minHeight: '100vh', bgcolor: 'background.default' }}>
        {selectedCase ? (
          <Paper elevation={0} sx={{ p: 3, maxWidth: 960, mx: 'auto' }}>
            <Typography variant="h5" fontWeight={600} mb={1}>
              {selectedCase.title}
            </Typography>
            {selectedCase.description && (
              <Typography variant="body2" color="text.secondary" mb={3}>
                {selectedCase.description}
              </Typography>
            )}
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
              <Tab label="📁 Overview" />
              <Tab label="📝 Transcript" />
              <Tab label="🎤 Diarization" />
              <Tab label="📋 Summary" />
              <Tab label="📊 Analysis" />
            </Tabs>
            {tab === 0 && (
              <Box display="flex" flexDirection="column" gap={2}>
                {/* Compact Upload Bar */}
                <CompactUploader
                  caseId={selectedCase.id}
                  onUploadComplete={() => {
                    fetchFiles();
                    setSnackbar({ open: true, message: '✅ Upload successful!', severity: 'success' });
                  }}
                />

                {/* File Table */}
                <FileTable
                  files={files}
                  onTranscribe={(taskId) => {
                    setSelectedTaskId(taskId);
                    setTranscribeDialogOpen(true);
                  }}
                  onSummarize={(taskId) => {
                    setSelectedTaskId(taskId);
                    setSummarizeDialogOpen(true);
                  }}
                  onVisualize={async (taskId) => {
                    const file = files.find(f => f.task_id === taskId);
                    if (!file) return;
                    try {
                      setSnackbar({ open: true, message: '🎨 Generating visualization...', severity: 'info' });
                      const response = await apiFetch(`${API_V2_BASE}/visualize/${taskId}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ visualization_type: 'all' })
                      });
                      if (!response.ok) throw new Error(await apiErrorMessage(response));
                      await fetchFiles();
                      setVisualizeTaskId(taskId);
                      setVisualizeDialogOpen(true);
                      setSnackbar({ open: true, message: '✅ Visualization ready!', severity: 'success' });
                    } catch (error: any) {
                      setSnackbar({ open: true, message: `❌ Error: ${error.message}`, severity: 'error' });
                    }
                  }}
                  onDelete={async (taskId) => {
                    const file = files.find(f => f.task_id === taskId);
                    if (!file || !window.confirm(`Xóa file "${file.filename}"?`)) return;
                    try {
                      await apiFetch(`/api/v1/audio/${file.audio_id || taskId}`, { method: 'DELETE' });
                      fetchFiles();
                      setSnackbar({ open: true, message: '✅ File deleted', severity: 'success' });
                    } catch (err: any) {
                      setSnackbar({ open: true, message: `❌ Delete failed`, severity: 'error' });
                    }
                  }}
                />
              </Box>
            )}
            {tab === 1 && selectedFileId ? <TranscriptPanel fileId={selectedFileId} /> : tab === 1 ? (
              files.filter(f => f.transcript).length > 0 ? (
                <Box>
                  <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                    <Typography variant="h6" fontWeight={700}>📝 Transcript các file</Typography>
                    <Chip
                      label={`${files.filter(f => f.transcript).length} file(s)`}
                      size="small"
                      sx={{ bgcolor: '#43a047', color: '#fff' }}
                    />
                  </Box>
                  {files.filter(f => f.transcript).map((file, idx) => (
                    <Accordion key={file.task_id} defaultExpanded={idx === 0} sx={{ mb: 2, borderRadius: '12px !important', border: '1px solid rgba(67, 160, 71, 0.3)', '&:before': { display: 'none' } }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(67, 160, 71, 0.05)', borderRadius: '12px 12px 0 0' }}>
                        <Box display="flex" alignItems="center" gap={2} width="100%">
                          <Typography fontWeight={600} flex={1}>📄 {file.filename}</Typography>
                          {file.num_speakers && (
                            <Chip label={`${file.num_speakers} speakers`} size="small" variant="outlined" />
                          )}
                          {file.duration && (
                            <Chip label={`${Math.floor(file.duration / 60)}:${String(Math.floor(file.duration % 60)).padStart(2, '0')}`} size="small" variant="outlined" />
                          )}
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ pt: 2 }}>
                        <Box display="flex" justifyContent="flex-end" mb={1}>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<ContentCopyIcon />}
                            onClick={() => {
                              navigator.clipboard.writeText(file.transcript || '');
                              setSnackbar({ open: true, message: '✅ Transcript copied!', severity: 'success' });
                            }}
                            sx={{ borderRadius: '8px', textTransform: 'none', color: '#43a047', borderColor: '#43a047' }}
                          >
                            Copy
                          </Button>
                        </Box>
                        <Paper sx={{ p: 2, bgcolor: 'rgba(67, 160, 71, 0.03)', borderRadius: '12px', maxHeight: 400, overflow: 'auto' }}>
                          <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.8 }}>{file.transcript}</Typography>
                        </Paper>
                      </AccordionDetails>
                    </Accordion>
                  ))}
                  {/* Pending files without transcript */}
                  {files.filter(f => !f.transcript && f.status !== 'uploaded').length > 0 && (
                    <Box mt={2}>
                      <Typography variant="subtitle2" color="text.secondary" mb={1}>
                        ⏳ Đang xử lý ({files.filter(f => !f.transcript && f.status !== 'uploaded').length} files)
                      </Typography>
                    </Box>
                  )}
                </Box>
              ) : (
                <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
                  <Typography color="text.secondary">Chưa có transcript nào. Hãy chạy Transcribe cho các file audio.</Typography>
                </Paper>
              )
            ) : null}
            {/* Diarization Tab (tab 2) */}
            {tab === 2 && (
              <DiarizationPanel
                segments={files.filter(f => f.segments?.length > 0).flatMap(f => f.segments || [])}
                duration={files.reduce((sum, f) => sum + (f.duration || 0), 0)}
              />
            )}
            {/* Summary Tab (tab 3) */}
            {tab === 3 && (
              files.filter(f => f.summary).length > 0 ? (
                <Box>
                  <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                    <Typography variant="h6" fontWeight={700}>📋 Summary các file</Typography>
                    <Chip
                      label={`${files.filter(f => f.summary).length} file(s)`}
                      size="small"
                      sx={{ bgcolor: '#ff9800', color: '#fff' }}
                    />
                  </Box>
                  {files.filter(f => f.summary).map((file, idx) => (
                    <Accordion key={file.task_id} defaultExpanded={idx === 0} sx={{ mb: 2, borderRadius: '12px !important', border: '1px solid rgba(255, 152, 0, 0.3)', '&:before': { display: 'none' } }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(255, 152, 0, 0.05)', borderRadius: '12px 12px 0 0' }}>
                        <Box display="flex" alignItems="center" gap={2} width="100%">
                          <Typography fontWeight={600} flex={1}>📄 {file.filename}</Typography>
                          {file.num_speakers && (
                            <Chip label={`${file.num_speakers} speakers`} size="small" variant="outlined" />
                          )}
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ pt: 2 }}>
                        <Box display="flex" justifyContent="flex-end" mb={1}>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<ContentCopyIcon />}
                            onClick={() => {
                              navigator.clipboard.writeText(file.summary || '');
                              setSnackbar({ open: true, message: '✅ Summary copied!', severity: 'success' });
                            }}
                            sx={{ borderRadius: '8px', textTransform: 'none', color: '#ff9800', borderColor: '#ff9800' }}
                          >
                            Copy
                          </Button>
                        </Box>
                        <Paper sx={{ p: 2, bgcolor: 'rgba(255, 152, 0, 0.03)', borderRadius: '12px', maxHeight: 400, overflow: 'auto' }}>
                          <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.8 }}>{file.summary}</Typography>
                        </Paper>
                      </AccordionDetails>
                    </Accordion>
                  ))}
                </Box>
              ) : (
                <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
                  <Typography color="text.secondary">Chưa có summary nào. Hãy chạy Summarize cho các file đã transcribe.</Typography>
                </Paper>
              )
            )}
            {/* Analysis Tab (tab 4) */}
            {tab === 4 && (
              <AnalysisPanel files={files} caseId={selectedCase.id} mode={mode} />
            )}

          </Paper>
        ) : (
          <Typography variant="h6" color="text.secondary">No case selected.</Typography>
        )}
      </Box>
      <Dialog open={createCaseOpen} onClose={() => setCreateCaseOpen(false)}>
        <DialogTitle>Tạo Case mới</DialogTitle>
        <DialogContent>
          <TextField
            label="Tên vụ việc"
            value={newCaseTitle}
            onChange={e => setNewCaseTitle(e.target.value)}
            fullWidth
            margin="normal"
            required
          />
          <TextField
            label="Mô tả"
            value={newCaseDesc}
            onChange={e => setNewCaseDesc(e.target.value)}
            fullWidth
            margin="normal"
            multiline
            minRows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setCreateCaseOpen(false)}
            variant="outlined"
            color="primary"
            sx={{
              borderRadius: '12px',
              fontWeight: 700,
              textTransform: 'none',
              px: 3,
              py: 1.2,
              mr: 1.5,
              borderWidth: 2,
              '&:hover': {
                borderColor: 'primary.dark',
                color: 'primary.dark',
              },
            }}
            disabled={creatingCase}
          >
            Huỷ
          </Button>
          <Button
            onClick={handleCreateCase}
            variant="contained"
            color="primary"
            sx={{
              borderRadius: '12px',
              fontWeight: 700,
              textTransform: 'none',
              px: 3,
              py: 1.2,
              boxShadow: '0 2px 8px #b388ff22',
              '&:hover': {
                background: 'primary.dark',
                color: '#fff',
              },
            }}
            disabled={!newCaseTitle || creatingCase}
          >
            {creatingCase ? <CircularProgress size={20} /> : 'Tạo'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* V2 API - Transcribe Dialog */}
      <TranscribeDialog
        open={transcribeDialogOpen}
        onClose={() => setTranscribeDialogOpen(false)}
        onConfirm={handleTranscribe}
        filename={selectedTaskId || ''}
      />

      {/* V2 API - Summarize Dialog */}
      <SummarizeDialog
        open={summarizeDialogOpen}
        onClose={() => setSummarizeDialogOpen(false)}
        onConfirm={handleSummarize}
      />

      {/* V2 API - Visualization Dialog */}
      <VisualizationDialog
        open={visualizeDialogOpen}
        onClose={() => setVisualizeDialogOpen(false)}
        taskId={visualizeTaskId}
      />

      <Dialog open={loginOpen} disableEscapeKeyDown>
        <DialogTitle>Login</DialogTitle>
        <DialogContent sx={{ pt: 1, minWidth: 360 }}>
          <TextField
            label="Username or email"
            value={loginUsername}
            onChange={e => setLoginUsername(e.target.value)}
            fullWidth
            margin="normal"
            autoFocus
          />
          <TextField
            label="Password"
            type="password"
            value={loginPassword}
            onChange={e => setLoginPassword(e.target.value)}
            fullWidth
            margin="normal"
            onKeyDown={e => {
              if (e.key === 'Enter') handleLogin();
            }}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleLogin}
            variant="contained"
            disabled={!loginUsername.trim() || !loginPassword}
          >
            Login
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snackbar.severity} variant="filled" onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </ThemeProvider >
  );
}

export default App;
