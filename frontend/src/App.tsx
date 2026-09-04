import React, { useEffect, useRef, useState } from 'react';
import { ThemeProvider, CssBaseline, Box, AppBar, Toolbar, Typography, Paper, Drawer, List, ListItem, ListItemText, Divider, IconButton, InputBase, Button, CircularProgress, LinearProgress, Tabs, Tab, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Accordion, AccordionSummary, AccordionDetails, Snackbar, Alert, Tooltip, Chip, Menu, MenuItem, Pagination, useMediaQuery } from '@mui/material';
import { lightTheme, darkTheme } from './theme';
import DarkModeToggle from './components/DarkModeToggle';
import SearchIcon from '@mui/icons-material/Search';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import DeleteIcon from '@mui/icons-material/Delete';
import SortIcon from '@mui/icons-material/Sort';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FolderIcon from '@mui/icons-material/Folder';
import CancelOutlinedIcon from '@mui/icons-material/CancelOutlined';
import FileCard from './components/FileCard';
import TranscribeDialog from './components/TranscribeDialog';
import SummarizeDialog from './components/SummarizeDialog';
import CompactUploader from './components/CompactUploader';
import FileTable from './components/FileTable';
import BatchSummaryDialog from './components/BatchSummaryDialog';
import BatchSummaryResults from './components/BatchSummaryResults';
import SummaryVariants from './components/SummaryVariants';
import VisualizationDialog from './components/VisualizationDialog';
import AnalysisPanel from './components/AnalysisPanel';
import DiarizationPanel from './components/DiarizationPanel';
import DateTimeText from './components/DateTimeText';
import {
  apiFetch,
  AudioBatchApiError,
  audioBatchResumeStorageKey,
  cancelAudioBatch,
  getAudioBatch,
  getAudioBatchSummary,
  getCurrentUser,
  isAudioBatchSummaryTerminal,
  isAudioBatchProcessing,
  isAudioBatchTerminal,
  login,
  logout,
  normalizeSummaryUserPrompt,
  orderTaskIdsByBatch,
  parseAudioBatchResumeRecord,
  transcribeAudioBatch,
} from './api/client';
import type {
  AudioBatchResponse,
  AudioBatchSummaryJob,
  SummaryDialogOptions,
} from './api/client';
import { countTranscriptWords } from './utils/transcriptText';
import { summaryDisplayText } from './utils/summaryDisplay';

interface Case {
  id: string;
  case_code: string;
  title: string;
  description?: string;
  status_id?: string;
  priority_id?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  summaries?: string[];
  transcripts?: string[];
}

const batchStatusLabel: Record<string, string> = {
  created: 'Đã upload',
  queued: 'Đang chờ',
  processing: 'Đang xử lý',
  succeeded: 'Hoàn tất',
  partially_succeeded: 'Hoàn tất một phần',
  failed: 'Thất bại',
  cancel_requested: 'Đang hủy',
  cancelled: 'Đã hủy',
  uploaded: 'Đã upload',
  transcribing: 'Đang chuyển biên',
  transcribed: 'Đã chuyển biên',
};

function BatchProgressRegion({
  batch,
  errorCode,
  cancelling,
  onCancel,
}: {
  batch: AudioBatchResponse;
  errorCode: string | null;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const terminalCount = batch.completed_count + batch.failed_count + batch.cancelled_count;
  const progress = Math.round((terminalCount / batch.requested_count) * 100);
  return (
    <Box
      aria-label="Tiến độ batch audio"
      sx={{ py: 2, my: 2, borderTop: '1px solid', borderBottom: '1px solid', borderColor: 'divider' }}
    >
      <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1}>
        <Typography variant="subtitle2" fontWeight={700}>Batch đang hoạt động</Typography>
        <Chip size="small" label={batchStatusLabel[batch.status] ?? batch.status} />
        <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          {batch.id}
        </Typography>
        <Box flex={1} />
        {!isAudioBatchTerminal(batch.status) && batch.status !== 'cancel_requested' && (
          <Button
            size="small"
            color="error"
            variant="outlined"
            startIcon={<CancelOutlinedIcon />}
            disabled={cancelling}
            onClick={onCancel}
          >
            {cancelling ? 'Đang hủy...' : 'Hủy batch'}
          </Button>
        )}
      </Box>
      <LinearProgress variant="determinate" value={progress} sx={{ mb: 0.75 }} />
      <Typography variant="caption" color="text.secondary">
        {terminalCount}/{batch.requested_count} kết thúc · {batch.completed_count} thành công · {batch.failed_count} lỗi · {batch.cancelled_count} hủy
      </Typography>
      {(errorCode || batch.error_code) && (
        <Alert severity="error" sx={{ mt: 1 }}>
          Batch chưa thể hoàn tất ({errorCode ?? batch.error_code}).
        </Alert>
      )}
      <Box
        component="ol"
        sx={{ m: 0, mt: 1.5, pl: 3, display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 0.75 }}
      >
        {batch.items.map(item => (
          <Box component="li" key={item.task_id} sx={{ minWidth: 0, pr: 1 }}>
            <Box display="flex" alignItems="center" gap={1} minWidth={0}>
              <Typography variant="body2" noWrap title={item.original_filename} flex={1}>
                {item.original_filename}
              </Typography>
              <Chip
                size="small"
                label={batchStatusLabel[item.status] ?? item.status}
                color={item.status === 'failed' ? 'error' : item.status === 'transcribed' ? 'success' : 'default'}
              />
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

const drawerWidth = 320;
const CASE_PAGE_SIZE = 50;

function SummaryAccordionItem({ summary, idx, highlightSummary }: { summary: string, idx: number, highlightSummary: (s: string) => React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const displaySummary = summaryDisplayText({ summary });
  const handleCopy = () => {
    navigator.clipboard.writeText(displaySummary);
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
        {highlightSummary(displaySummary)}
      </AccordionDetails>
    </Accordion>
  );
}

function App() {
  const isDesktopViewport = useMediaQuery('(min-width:900px)');
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [cases, setCases] = useState<Case[]>([]);
  const [casePage, setCasePage] = useState(1);
  const [caseTotal, setCaseTotal] = useState(0);
  const [loadingCases, setLoadingCases] = useState(false);
  const [selectedCase, setSelectedCase] = useState<Case | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(isDesktopViewport);
  const [search, setSearch] = useState('');
  const [searchActive, setSearchActive] = useState(false);
  const [searchFocus, setSearchFocus] = useState(false);
  const [tab, setTab] = useState(0);
  const [analysisTaskId, setAnalysisTaskId] = useState<string | null>(null);
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
  const pollingRequestsRef = useRef<Set<string>>(new Set());
  const batchContextVersionRef = useRef(0);
  const [files, setFiles] = useState<any[]>([]);
  const [activeBatch, setActiveBatch] = useState<AudioBatchResponse | null>(null);
  const [batchErrorCode, setBatchErrorCode] = useState<string | null>(null);
  const [batchActionBusy, setBatchActionBusy] = useState(false);
  const [batchSelectedTaskIds, setBatchSelectedTaskIds] = useState<string[]>([]);
  const [pendingBatchTranscribeTaskIds, setPendingBatchTranscribeTaskIds] = useState<string[]>([]);
  const [batchSummaryDialogOpen, setBatchSummaryDialogOpen] = useState(false);
  const [batchSummaryJob, setBatchSummaryJob] = useState<AudioBatchSummaryJob | null>(null);
  const [batchSummaryErrorCode, setBatchSummaryErrorCode] = useState<string | null>(null);
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

  useEffect(() => {
    setSidebarOpen(isDesktopViewport);
  }, [isDesktopViewport]);

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
    summary_type: f.summary_type,
    summary_state: f.summary_state,
    summary_authority: f.summary_authority,
    summary_notice: f.summary_notice,
    summary_preview: f.summary_preview,
    summary_variants: f.summary_variants || f.result?.summary_variants,
    summary_runtime: f.summary_runtime,
    formatted_transcript: f.formatted_transcript,
    segments: f.segments,
    diarization: f.diarization || f.result?.diarization,
    context_analysis: f.context_analysis,
    created_at: f.created_at,
    download_url: f.download_url,
    updated_at: f.updated_at,
    batch_id: f.batch_id,
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
  const fetchCases = async (page = casePage, searchTerm = search) => {
    if (!currentUser) {
      setCases([]);
      setCaseTotal(0);
      setSelectedCase(null);
      setLoadingCases(false);
      return;
    }
    setLoadingCases(true);
    try {
      const params = new URLSearchParams({
        sort_by: caseSortBy,
        order: caseOrder,
        compact: 'true',
        limit: String(CASE_PAGE_SIZE),
        offset: String((page - 1) * CASE_PAGE_SIZE),
      });
      if (searchTerm.trim()) {
        params.set('search', searchTerm.trim());
      }
      const res = await apiFetch(`/api/v1/cases/?${params.toString()}`, {
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
      const totalHeader = Number(res.headers.get('x-total-count'));
      setCaseTotal(Number.isFinite(totalHeader) ? totalHeader : nextCases.length);
      setCases(nextCases);
      setSelectedCase(current => {
        if (!current && nextCases.length > 0) return nextCases[0];
        if (current && !nextCases.some((c: Case) => c.id === current.id)) return nextCases[0] || null;
        return current;
      });
    } catch (err) {
      console.error('Failed to fetch cases:', err);
      setCases([]);
    } finally {
      setLoadingCases(false);
    }
  };

  useEffect(() => {
    let timer: number | undefined;
    if (authChecked && currentUser) {
      timer = window.setTimeout(() => void fetchCases(), search.trim() ? 250 : 0);
    } else if (authChecked && !currentUser) {
      setCases([]);
      setCaseTotal(0);
      setFiles([]);
      setSelectedCase(null);
    }
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [authChecked, currentUser, caseSortBy, caseOrder, casePage, search]);

  // Load files when case selected
  const fetchFiles = async () => {
    if (selectedCase && currentUser) {
      try {
        const res = await apiFetch(`/api/v1/audio/?case_id=${selectedCase.id}`);
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

  const batchStorageKey = selectedCase && currentUser
    ? audioBatchResumeStorageKey(currentUser.id ?? currentUser.username, selectedCase.id)
    : null;

  useEffect(() => {
    const contextVersion = ++batchContextVersionRef.current;
    setActiveBatch(null);
    setBatchSelectedTaskIds([]);
    setBatchSummaryJob(null);
    setBatchErrorCode(null);
    setBatchSummaryErrorCode(null);
    setBatchSummaryDialogOpen(false);
    setPendingBatchTranscribeTaskIds([]);
    if (!batchStorageKey || !selectedCase) return;

    const rawRecord = window.localStorage.getItem(batchStorageKey);
    const resumeRecord = parseAudioBatchResumeRecord(rawRecord);
    if (!resumeRecord) {
      if (rawRecord !== null) window.localStorage.removeItem(batchStorageKey);
      return;
    }

    const restore = async () => {
      try {
        const restoredBatch = await getAudioBatch(resumeRecord.batch_id);
        if (batchContextVersionRef.current !== contextVersion) return;
        if (String(restoredBatch.case_id) !== String(selectedCase.id)) {
          window.localStorage.removeItem(batchStorageKey);
          setBatchErrorCode('BATCH_CASE_MISMATCH');
          return;
        }
        setActiveBatch(restoredBatch);
        setBatchSelectedTaskIds(orderTaskIdsByBatch(restoredBatch, resumeRecord.selected_task_ids ?? []));

        if (resumeRecord.summary_job_id) {
          try {
            const restoredSummary = await getAudioBatchSummary(restoredBatch.id, resumeRecord.summary_job_id);
            if (batchContextVersionRef.current === contextVersion) setBatchSummaryJob(restoredSummary);
          } catch (error) {
            if (batchContextVersionRef.current !== contextVersion) return;
            const code = error instanceof AudioBatchApiError ? error.code : 'BATCH_SUMMARY_STATUS_UNAVAILABLE';
            setBatchSummaryErrorCode(code);
            if (error instanceof AudioBatchApiError && [400, 403, 404].includes(error.status)) {
              window.localStorage.setItem(batchStorageKey, JSON.stringify({
                batch_id: restoredBatch.id,
                selected_task_ids: resumeRecord.selected_task_ids ?? [],
              }));
            }
          }
        }
      } catch (error) {
        if (batchContextVersionRef.current !== contextVersion) return;
        const code = error instanceof AudioBatchApiError ? error.code : 'BATCH_STATUS_UNAVAILABLE';
        setBatchErrorCode(code);
        if (error instanceof AudioBatchApiError && [400, 403, 404].includes(error.status)) {
          window.localStorage.removeItem(batchStorageKey);
        }
      }
    };
    void restore();
  }, [batchStorageKey, selectedCase?.id]);

  useEffect(() => {
    if (!activeBatch) return;
    const itemByTaskId = new Map(activeBatch.items.map(item => [item.task_id, item]));
    setFiles(current => current.map(file => {
      const item = itemByTaskId.get(file.task_id);
      return item ? { ...file, batch_id: activeBatch.id, status: item.status } : file;
    }));
  }, [activeBatch]);

  useEffect(() => {
    if (!batchStorageKey || !activeBatch) return;
    const previous = parseAudioBatchResumeRecord(window.localStorage.getItem(batchStorageKey));
    window.localStorage.setItem(batchStorageKey, JSON.stringify({
      batch_id: activeBatch.id,
      ...(previous?.summary_job_id ? { summary_job_id: previous.summary_job_id } : {}),
      selected_task_ids: orderTaskIdsByBatch(activeBatch, batchSelectedTaskIds),
    }));
  }, [activeBatch?.id, batchSelectedTaskIds, batchStorageKey]);

  useEffect(() => {
    if (!activeBatch || !isAudioBatchProcessing(activeBatch.status)) return;
    let stopped = false;
    let timer: number | undefined;
    let failureCount = 0;
    let completedCount = activeBatch.completed_count;

    const schedule = (delay: number) => {
      if (!stopped) timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      try {
        const nextBatch = await getAudioBatch(activeBatch.id);
        if (stopped) return;
        failureCount = 0;
        setBatchErrorCode(null);
        setActiveBatch(nextBatch);
        if (nextBatch.completed_count > completedCount || isAudioBatchTerminal(nextBatch.status)) {
          completedCount = nextBatch.completed_count;
          void fetchFiles();
        }
        if (isAudioBatchProcessing(nextBatch.status)) schedule(2000);
      } catch (error) {
        if (stopped) return;
        const code = error instanceof AudioBatchApiError ? error.code : 'BATCH_STATUS_UNAVAILABLE';
        setBatchErrorCode(code);
        if (error instanceof AudioBatchApiError && [400, 403, 404].includes(error.status)) {
          if (batchStorageKey) window.localStorage.removeItem(batchStorageKey);
          return;
        }
        failureCount += 1;
        schedule(Math.min(15000, 2000 * (2 ** Math.min(failureCount, 3))));
      }
    };
    schedule(1500);
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeBatch?.id, activeBatch?.status, batchStorageKey]);

  useEffect(() => {
    if (!batchSummaryJob || isAudioBatchSummaryTerminal(batchSummaryJob.status)) return;
    let stopped = false;
    let timer: number | undefined;
    let failureCount = 0;
    const poll = async () => {
      try {
        const nextJob = await getAudioBatchSummary(batchSummaryJob.batch_id, batchSummaryJob.summary_job_id);
        if (stopped) return;
        failureCount = 0;
        setBatchSummaryErrorCode(null);
        setBatchSummaryJob(nextJob);
        if (!isAudioBatchSummaryTerminal(nextJob.status)) {
          timer = window.setTimeout(() => void poll(), 2000);
        }
      } catch (error) {
        if (stopped) return;
        setBatchSummaryErrorCode(error instanceof AudioBatchApiError ? error.code : 'BATCH_SUMMARY_STATUS_UNAVAILABLE');
        if (error instanceof AudioBatchApiError && [400, 403, 404].includes(error.status)) return;
        failureCount += 1;
        timer = window.setTimeout(() => void poll(), Math.min(15000, 2000 * (2 ** Math.min(failureCount, 3))));
      }
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [batchSummaryJob?.batch_id, batchSummaryJob?.summary_job_id, batchSummaryJob?.status]);

  const filteredCases = Array.isArray(cases) ? cases : [];

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
      setSearch('');
      setCasePage(1);
      await fetchCases(1, '');
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
      await fetchCases(casePage, search);

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
    if (pendingBatchTranscribeTaskIds.length > 0) {
      if (!activeBatch) {
        setSnackbar({ open: true, message: 'Batch không còn khả dụng.', severity: 'error' });
        return;
      }
      const orderedTaskIds = orderTaskIdsByBatch(activeBatch, pendingBatchTranscribeTaskIds);
      const eligibleTaskIds = new Set(
        activeBatch.items.filter(item => ['uploaded', 'failed'].includes(item.status)).map(item => item.task_id),
      );
      if (orderedTaskIds.length !== pendingBatchTranscribeTaskIds.length
        || orderedTaskIds.some(taskId => !eligibleTaskIds.has(taskId))) {
        setSnackbar({ open: true, message: 'Selection đã thay đổi. Hãy chọn lại các file có thể chuyển biên.', severity: 'warning' });
        setPendingBatchTranscribeTaskIds([]);
        return;
      }
      setBatchActionBusy(true);
      try {
        const accepted = await transcribeAudioBatch(activeBatch.id, {
          task_ids: orderedTaskIds,
          language: 'vi',
          enable_diarization: options.enable_diarization,
          diarization_method: options.diarization_method === 'simple_vad' ? 'simple' : options.diarization_method || 'pyannote',
          fast_mode: options.fast_mode,
        });
        const selected = new Set(orderedTaskIds);
        setActiveBatch(current => current ? {
          ...current,
          status: accepted.status,
          items: current.items.map(item => selected.has(item.task_id) ? { ...item, status: 'queued' } : item),
        } : current);
        setPendingBatchTranscribeTaskIds([]);
        setSnackbar({ open: true, message: `Đã xếp hàng chuyển biên ${orderedTaskIds.length} file.`, severity: 'info' });
      } catch (error) {
        const code = error instanceof AudioBatchApiError ? error.code : 'BATCH_TRANSCRIBE_FAILED';
        setSnackbar({ open: true, message: `Không thể chuyển biên batch (${code}).`, severity: 'error' });
      } finally {
        setBatchActionBusy(false);
      }
      return;
    }
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
      await response.json();
      setFiles(prev => prev.map(f => f.task_id === selectedTaskId ? { ...f, status: 'transcribing' } : f));
      setTranscribeDialogOpen(false);
      setSnackbar({ open: true, message: '🎙️ Transcription started! Please wait...', severity: 'info' });

      // Start polling for status updates
      startPolling(selectedTaskId, 'transcribing');
    } catch (error) {
      setSnackbar({ open: true, message: 'Failed to start', severity: 'error' });
    }
  };

  const handleSummarize = async (options: SummaryDialogOptions) => {
    if (!selectedTaskId) return;
    try {
      const userPrompt = normalizeSummaryUserPrompt(options.user_prompt);
      const response = await apiFetch(`${API_V2_BASE}/summarize/${selectedTaskId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: options.model_name === 'auto' ? null : options.model_name,
          summary_type: options.summary_type,
          ...(userPrompt ? { user_prompt: userPrompt } : {}),
          include_context: options.include_context_analysis !== false,
          async_mode: true,
          min_length: options.min_length,
          max_length: options.max_length,
          length_mode: options.length_mode,
          investigation_scenario: options.investigation_scenario,
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

  const handleBatchUploadComplete = (batch: AudioBatchResponse) => {
    if (!currentUser) return;
    const uploadedBatchStorageKey = audioBatchResumeStorageKey(
      currentUser.id ?? currentUser.username,
      batch.case_id,
    );
    window.localStorage.setItem(uploadedBatchStorageKey, JSON.stringify({
      batch_id: batch.id,
      selected_task_ids: [],
    }));
    if (!selectedCase || String(batch.case_id) !== String(selectedCase.id)) {
      return;
    }
    setActiveBatch(batch);
    setBatchSelectedTaskIds([]);
    setBatchSummaryJob(null);
    setBatchSummaryErrorCode(null);
    void fetchFiles();
    setSnackbar({ open: true, message: `Đã tạo batch ${batch.requested_count} file.`, severity: 'success' });
  };

  const handleBatchSelectionChange = (taskIds: string[]) => {
    if (!activeBatch) {
      setBatchSelectedTaskIds([]);
      return;
    }
    setBatchSelectedTaskIds(orderTaskIdsByBatch(activeBatch, taskIds));
  };

  const handleBulkTranscribe = (taskIds: string[]) => {
    if (!activeBatch || batchActionBusy) return;
    const orderedTaskIds = orderTaskIdsByBatch(activeBatch, taskIds);
    if (orderedTaskIds.length === 0 || orderedTaskIds.length !== taskIds.length) {
      setSnackbar({ open: true, message: 'Selection không hợp lệ cho batch hiện tại.', severity: 'warning' });
      return;
    }
    setBatchSelectedTaskIds(orderedTaskIds);
    setPendingBatchTranscribeTaskIds(orderedTaskIds);
    setTranscribeDialogOpen(true);
  };

  const handleBulkSummarize = (taskIds: string[]) => {
    if (!activeBatch || batchActionBusy) return;
    const orderedTaskIds = orderTaskIdsByBatch(activeBatch, taskIds);
    const fileByTaskId = new Map(files.map(file => [file.task_id, file]));
    if (orderedTaskIds.length === 0
      || orderedTaskIds.length !== taskIds.length
      || orderedTaskIds.some(taskId => !fileByTaskId.get(taskId)?.transcript)) {
      setSnackbar({ open: true, message: 'Merged summary yêu cầu mọi file đã chọn có transcript.', severity: 'warning' });
      return;
    }
    setBatchSelectedTaskIds(orderedTaskIds);
    setBatchSummaryDialogOpen(true);
  };

  const handleBatchSummarySubmitted = (job: AudioBatchSummaryJob) => {
    if (!activeBatch || job.batch_id !== activeBatch.id) {
      setBatchSummaryErrorCode('BATCH_SUMMARY_PARENT_MISMATCH');
      return;
    }
    setBatchSummaryJob(job);
    setBatchSummaryErrorCode(null);
    setBatchSummaryDialogOpen(false);
    if (batchStorageKey) {
      window.localStorage.setItem(batchStorageKey, JSON.stringify({
        batch_id: activeBatch.id,
        summary_job_id: job.summary_job_id,
        selected_task_ids: batchSelectedTaskIds,
      }));
    }
    setTab(3);
    setSnackbar({ open: true, message: 'Merged summary đã được xếp hàng.', severity: 'info' });
  };

  const handleCancelBatch = async () => {
    if (!activeBatch || isAudioBatchTerminal(activeBatch.status) || batchActionBusy) return;
    setBatchActionBusy(true);
    try {
      const accepted = await cancelAudioBatch(activeBatch.id);
      setActiveBatch(current => current ? { ...current, status: accepted.status } : current);
      setSnackbar({ open: true, message: 'Đã yêu cầu hủy batch.', severity: 'info' });
    } catch (error) {
      const code = error instanceof AudioBatchApiError ? error.code : 'BATCH_CANCEL_FAILED';
      setSnackbar({ open: true, message: `Không thể hủy batch (${code}).`, severity: 'error' });
    } finally {
      setBatchActionBusy(false);
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
      if (pollingRequestsRef.current.has(taskId)) return;
      pollingRequestsRef.current.add(taskId);
      try {
        const response = await apiFetch(`${API_V2_BASE}/tasks/${taskId}/status?include_result=false`);
        if (!response.ok) {
          clearInterval(pollInterval);
          pollingIntervalsRef.current.delete(taskId);
          return;
        }

        const statusData = await response.json();
        const currentStatus = statusData.status;

        setFiles(prev => {
          const target = prev.find(f => f.task_id === taskId);
          if (!target || target.status === currentStatus) return prev;
          return prev.map(f => f.task_id === taskId ? { ...f, status: currentStatus } : f);
        });

        // Stop polling if task is complete or failed
        if (currentStatus === 'transcribed' || currentStatus === 'summarized' || currentStatus === 'visualized' || currentStatus === 'failed') {
          clearInterval(pollInterval);
          pollingIntervalsRef.current.delete(taskId);

          if (currentStatus === 'transcribed') {
            setSnackbar({ open: true, message: '✅ Transcription completed!', severity: 'success' });
            void fetchFiles();
          } else if (currentStatus === 'summarized') {
            setSnackbar({
              open: true,
              message: '✅ Summarization completed!',
              severity: 'success',
            });
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
      } finally {
        pollingRequestsRef.current.delete(taskId);
      }
    }, 2000); // Poll every 2 seconds

    // Store interval for cleanup
    pollingIntervalsRef.current.set(taskId, pollInterval);
  };

  useEffect(() => {
    return () => {
      pollingIntervalsRef.current.forEach(interval => clearInterval(interval));
      pollingIntervalsRef.current.clear();
      pollingRequestsRef.current.clear();
    };
  }, []);

  function highlightSummary(summary: string) {
    if (!summary) return null;
    const keywordRegex = /(\b(?:người|địa điểm|thời gian|quyết định|hành động|cảm xúc|chủ đề|thông tin nhạy cảm|thực thể|mục tiêu|kết quả|liên hệ|mối quan hệ|tên|số điện thoại|email|địa chỉ|sự kiện|vai trò|tóm tắt|key points|entities|privacy)\b)/gi;
    const blocks = summary.split(/\n|\r|\u2022|-/).filter(Boolean);
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

  const selectedSummaryTranscriptLength = countTranscriptWords(
    files.find(file => file.task_id === selectedTaskId)?.transcript,
  );
  const batchFileByTaskId = new Map(files.map(file => [file.task_id, file]));
  const batchSummarySources = activeBatch
    ? orderTaskIdsByBatch(activeBatch, batchSelectedTaskIds).map(taskId => ({
      task_id: taskId,
      filename: batchFileByTaskId.get(taskId)?.filename
        ?? activeBatch.items.find(item => item.task_id === taskId)?.original_filename
        ?? 'Audio source',
      transcriptReady: Boolean(batchFileByTaskId.get(taskId)?.transcript),
    }))
    : [];
  const renderedMergedSources = batchSummaryJob?.source_manifest
    ?? batchSummarySources.map((source, position) => ({ position, task_id: source.task_id, filename: source.filename }));

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
        variant={isDesktopViewport ? 'persistent' : 'temporary'}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        ModalProps={{ keepMounted: true }}
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
                  onChange={e => { setSearch(e.target.value); setCasePage(1); }}
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
                    bgcolor: sortMenuAnchor ? 'rgba(0,0,0,0.05)' : 'transparent'
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
                  onClick={() => { setCaseSortBy('created_at'); setCaseOrder('desc'); setCasePage(1); setSortMenuAnchor(null); }}
              >
                Mới nhất
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'created_at' && caseOrder === 'asc'}
                  onClick={() => { setCaseSortBy('created_at'); setCaseOrder('asc'); setCasePage(1); setSortMenuAnchor(null); }}
              >
                Cũ nhất
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'title' && caseOrder === 'asc'}
                  onClick={() => { setCaseSortBy('title'); setCaseOrder('asc'); setCasePage(1); setSortMenuAnchor(null); }}
              >
                Tên (A-Z)
              </MenuItem>
              <MenuItem
                selected={caseSortBy === 'title' && caseOrder === 'desc'}
                  onClick={() => { setCaseSortBy('title'); setCaseOrder('desc'); setCasePage(1); setSortMenuAnchor(null); }}
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
                  onClick={() => {
                    setSelectedCase(c);
                    if (!isDesktopViewport) setSidebarOpen(false);
                  }}
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
                    secondary={(
                      <Box component="span" sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.25, minWidth: 0 }}>
                        {c.description && (
                          <Typography component="span" variant="caption" color="text.secondary" noWrap>
                            {c.description}
                          </Typography>
                        )}
                        <DateTimeText
                          value={c.created_at}
                          label="Ngày tạo"
                          showIcon={false}
                        />
                      </Box>
                    )}
                    secondaryTypographyProps={{ component: 'div' }}
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
          {caseTotal > CASE_PAGE_SIZE && (
            <Box sx={{ px: 1, pb: 2, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
              <Pagination
                count={Math.ceil(caseTotal / CASE_PAGE_SIZE)}
                page={casePage}
                onChange={(_, page) => setCasePage(page)}
                size="small"
                siblingCount={0}
              />
              <Typography variant="caption" color="text.secondary">
                {Math.min((casePage - 1) * CASE_PAGE_SIZE + 1, caseTotal)}-{Math.min(casePage * CASE_PAGE_SIZE, caseTotal)} / {caseTotal} cases
              </Typography>
            </Box>
          )}
        </Box>
      </Drawer>
      <Box sx={{ ml: isDesktopViewport && sidebarOpen ? `${drawerWidth}px` : 0, transition: 'margin 0.2s', p: { xs: 1.5, sm: 3 }, pt: 10, minHeight: '100vh', bgcolor: 'background.default' }}>
        {selectedCase ? (
          <Paper elevation={0} sx={{ p: { xs: 1.5, sm: 3 }, maxWidth: 960, mx: 'auto' }}>
            <Typography variant="h5" fontWeight={600} mb={1}>
              {selectedCase.title}
            </Typography>
            <DateTimeText
              value={selectedCase.created_at}
              label="Ngày tạo"
              sx={{ mb: selectedCase.description ? 0.75 : 2 }}
            />
            {selectedCase.description && (
              <Typography variant="body2" color="text.secondary" mb={3}>
                {selectedCase.description}
              </Typography>
            )}
            <Tabs
              value={tab}
              onChange={(_, v) => {
                setTab(v);
                if (v === 4) setAnalysisTaskId(null);
              }}
              variant="scrollable"
              scrollButtons="auto"
              allowScrollButtonsMobile
              sx={{ mb: 3, maxWidth: '100%' }}
            >
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
                  disabled={Boolean(activeBatch && !isAudioBatchTerminal(activeBatch.status))}
                  onUploadComplete={handleBatchUploadComplete}
                />

                {activeBatch && (
                  <BatchProgressRegion
                    batch={activeBatch}
                    errorCode={batchErrorCode}
                    cancelling={batchActionBusy}
                    onCancel={handleCancelBatch}
                  />
                )}

                {/* File Table */}
                <FileTable
                  files={files}
                  selectableTaskIds={activeBatch?.items.map(item => item.task_id)}
                  selectedTaskIds={activeBatch ? batchSelectedTaskIds : undefined}
                  onSelectionChange={activeBatch ? handleBatchSelectionChange : undefined}
                  onBulkTranscribe={activeBatch ? handleBulkTranscribe : undefined}
                  onBulkSummarize={activeBatch ? handleBulkSummarize : undefined}
                  bulkProcessing={batchActionBusy}
                  onTranscribe={(taskId) => {
                    setPendingBatchTranscribeTaskIds([]);
                    setSelectedTaskId(taskId);
                    setTranscribeDialogOpen(true);
                  }}
                  onSummarize={(taskId) => {
                    setSelectedTaskId(taskId);
                    setSummarizeDialogOpen(true);
                  }}
                  onAnalyze={(taskId) => {
                    const file = files.find(f => f.task_id === taskId);
                    if (!file?.transcript) {
                      setSnackbar({
                        open: true,
                        message: 'Cần transcript trước khi mở Analysis.',
                        severity: 'warning',
                      });
                      return;
                    }
                    setAnalysisTaskId(taskId);
                    setTab(4);
                  }}
                    onVisualize={(taskId) => {
                      const file = files.find(f => f.task_id === taskId);
                      if (!file) return;
                      if (!file.transcript) {
                        setSnackbar({
                          open: true,
                          message: 'Cần transcript trước khi mở visualization.',
                          severity: 'warning'
                        });
                        return;
                    }
                    setVisualizeTaskId(taskId);
                    setVisualizeDialogOpen(true);
                  }}
                  onDelete={async (taskId) => {
                    const file = files.find(f => f.task_id === taskId);
                    if (!file || !window.confirm(`Xóa file "${file.filename}"?`)) return;
                    if (activeBatch?.items.some(item => item.task_id === taskId) && !isAudioBatchTerminal(activeBatch.status)) {
                      setSnackbar({ open: true, message: 'Không thể xóa file khi batch đang xử lý.', severity: 'warning' });
                      return;
                    }
                    try {
                      const response = await apiFetch(`/api/v1/audio/${file.audio_id || taskId}`, { method: 'DELETE' });
                      if (!response.ok) throw new Error('DELETE_REJECTED');
                      void fetchFiles();
                      setSnackbar({ open: true, message: '✅ File deleted', severity: 'success' });
                    } catch {
                      setSnackbar({ open: true, message: `❌ Delete failed`, severity: 'error' });
                    }
                  }}
                />
              </Box>
            )}
            {tab === 1 ? (
              <Box>
                {activeBatch && (
                  <BatchProgressRegion
                    batch={activeBatch}
                    errorCode={batchErrorCode}
                    cancelling={batchActionBusy}
                    onCancel={handleCancelBatch}
                  />
                )}
                {files.filter(f => f.transcript).length > 0 ? (
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
                  <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '8px' }}>
                    <Typography color="text.secondary">Chưa có transcript nào. Hãy chạy Transcribe cho các file audio.</Typography>
                  </Paper>
                )}
              </Box>
            ) : null}
            {/* Diarization Tab (tab 2) */}
            {tab === 2 && (
              <DiarizationPanel
                fileGroups={files.map(file => ({
                  task_id: file.task_id,
                  filename: file.filename,
                  duration: file.duration,
                  segments: file.segments?.length ? file.segments : file.diarization?.segments,
                }))}
              />
            )}
            {/* Summary Tab (tab 3) */}
            {tab === 3 && (
              <Box>
                {batchSummaryJob && (
                  <Box sx={{ pb: 2, mb: 3, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.5}>
                      <Typography variant="h6" fontWeight={700}>Summary theo từng loại</Typography>
                      <Chip size="small" label={batchStatusLabel[batchSummaryJob.status] ?? batchSummaryJob.status} />
                      {batchSummaryJob.user_prompt_applied && (
                        <Chip size="small" variant="outlined" label="Prompt tùy chọn đã áp dụng" />
                      )}
                    </Box>
                    {!isAudioBatchSummaryTerminal(batchSummaryJob.status) && <LinearProgress sx={{ mb: 1.5 }} />}
                    {(batchSummaryErrorCode || batchSummaryJob.error) && (
                      <Alert severity="error" sx={{ mb: 1.5 }}>
                        Merged summary chưa thể hoàn tất ({batchSummaryErrorCode ?? batchSummaryJob.error?.code}).
                      </Alert>
                    )}
                    <Typography variant="subtitle2" fontWeight={700}>Nguồn theo thứ tự</Typography>
                    <Box component="ol" sx={{ mt: 0.5, mb: 1.5, pl: 3 }}>
                      {renderedMergedSources.map(source => (
                        <Typography component="li" variant="body2" key={`${source.position}-${source.task_id}`}>
                          {source.filename}
                        </Typography>
                      ))}
                    </Box>
                    <BatchSummaryResults job={batchSummaryJob} />
                  </Box>
                )}

                {files.filter(f => summaryDisplayText(f) || Object.keys(f.summary_variants || {}).length > 0).length > 0 && (
                  <Box>
                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={2} gap={1} flexWrap="wrap">
                      <Typography variant="h6" fontWeight={700}>Summary từng file</Typography>
                      <Chip label={`${files.filter(f => summaryDisplayText(f) || Object.keys(f.summary_variants || {}).length > 0).length} file`} size="small" />
                    </Box>
                    {files.filter(f => summaryDisplayText(f) || Object.keys(f.summary_variants || {}).length > 0).map((file, idx) => (
                      <Accordion key={file.task_id} defaultExpanded={!batchSummaryJob && idx === 0} sx={{ mb: 2, borderRadius: '8px !important', border: '1px solid', borderColor: 'divider', '&:before': { display: 'none' } }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography fontWeight={600} sx={{ overflowWrap: 'anywhere' }}>{file.filename}</Typography>
                        </AccordionSummary>
                        <AccordionDetails sx={{ pt: 1 }}>
                          <SummaryVariants
                            summary={file.summary}
                            summary_type={file.summary_type}
                            summary_variants={file.summary_variants}
                          />
                        </AccordionDetails>
                      </Accordion>
                    ))}
                  </Box>
                )}

                {!batchSummaryJob && files.filter(f => summaryDisplayText(f) || Object.keys(f.summary_variants || {}).length > 0).length === 0 && (
                  <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '8px' }}>
                    <Typography color="text.secondary">Chưa có summary nào. Hãy chọn các transcript đã hoàn tất để tạo summary.</Typography>
                  </Paper>
                )}
              </Box>
            )}
            {/* Analysis Tab (tab 4) */}
            {tab === 4 && (
              <AnalysisPanel
                files={files}
                caseId={selectedCase.id}
                mode={mode}
                onRefresh={fetchFiles}
                focusTaskId={analysisTaskId}
              />
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
        onClose={() => {
          setTranscribeDialogOpen(false);
          if (!batchActionBusy) setPendingBatchTranscribeTaskIds([]);
        }}
        onConfirm={handleTranscribe}
        filename={pendingBatchTranscribeTaskIds.length > 0
          ? `${pendingBatchTranscribeTaskIds.length} file đã chọn`
          : selectedTaskId || ''}
      />

      {/* V2 API - Summarize Dialog */}
      <SummarizeDialog
        open={summarizeDialogOpen}
        onClose={() => setSummarizeDialogOpen(false)}
        onConfirm={handleSummarize}
        transcriptLength={selectedSummaryTranscriptLength}
      />

      {activeBatch && (
        <BatchSummaryDialog
          open={batchSummaryDialogOpen}
          batchId={activeBatch.id}
          sources={batchSummarySources}
          onClose={() => setBatchSummaryDialogOpen(false)}
          onSubmitted={handleBatchSummarySubmitted}
        />
      )}

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
