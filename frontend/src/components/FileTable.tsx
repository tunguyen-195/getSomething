import React, { useEffect, useState, useMemo } from 'react';
import {
    Box,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper,
    Chip,
    IconButton,
    Collapse,
    Typography,
    Button,
    Checkbox,
    Tooltip,
    LinearProgress,
    TableSortLabel,
} from '@mui/material';
import {
    KeyboardArrowDown as ExpandIcon,
    KeyboardArrowUp as CollapseIcon,
    AudioFile as AudioIcon,
    Transcribe as TranscribeIcon,
    Summarize as SummarizeIcon,
    Analytics as VisualizeIcon,
    Insights as AnalysisIcon,
    PlayArrow as PlayIcon,
    Delete as DeleteIcon,
    CheckCircle as CheckIcon,
    HourglassEmpty as PendingIcon,
    Error as ErrorIcon,
} from '@mui/icons-material';
import DateTimeText from './DateTimeText';
import { apiDateTimeToEpoch } from '../utils/dateTime';

export interface FileData {
    task_id: string;
    audio_id?: string | number;
    filename: string;
    status: string;
    duration?: string;
    num_speakers?: number;
    has_visualization?: boolean;
    visualization_data?: unknown;
    transcript?: string;
    summary?: string;
    created_at?: string;
    updated_at?: string;
    uploaded_at?: string;
    download_url?: string;
    batch_id?: string;
}

export interface FileTableProps {
    files: FileData[];
    onTranscribe: (taskId: string) => void;
    onSummarize: (taskId: string) => void;
    onAnalyze: (taskId: string) => void;
    onVisualize: (taskId: string) => void;
    onDelete: (taskId: string) => void;
    onBulkTranscribe?: (taskIds: string[]) => void | Promise<void>;
    onBulkSummarize?: (taskIds: string[]) => void | Promise<void>;
    onSelectionChange?: (taskIds: string[]) => void;
    selectableTaskIds?: string[];
    selectedTaskIds?: string[];
    processingTaskId?: string;
    bulkProcessing?: boolean;
}

const getStatusChip = (status: string) => {
    switch (status) {
        case 'uploaded':
            return <Chip label="Uploaded" size="small" color="default" icon={<PendingIcon />} />;
        case 'transcribing':
        case 'summarizing':
        case 'processing':
        case 'queued':
            return <Chip label="Processing" size="small" color="warning" icon={<PendingIcon />} />;
        case 'transcribed':
            return <Chip label="Transcribed" size="small" color="info" icon={<CheckIcon />} />;
        case 'summarized':
            return <Chip label="Summarized" size="small" color="success" icon={<CheckIcon />} />;
        case 'visualized':
            return <Chip label="Analyzed" size="small" color="secondary" icon={<CheckIcon />} />;
        case 'error':
        case 'failed':
            return <Chip label="Error" size="small" color="error" icon={<ErrorIcon />} />;
        case 'cancel_requested':
            return <Chip label="Cancelling" size="small" color="warning" icon={<PendingIcon />} />;
        case 'cancelled':
            return <Chip label="Cancelled" size="small" color="default" />;
        default:
            return <Chip label={status} size="small" />;
    }
};

type Order = 'asc' | 'desc';

const FileTable: React.FC<FileTableProps> = ({
    files,
    onTranscribe,
    onSummarize,
    onAnalyze,
    onVisualize,
    onDelete,
    onBulkTranscribe,
    onBulkSummarize,
    onSelectionChange,
    selectableTaskIds,
    selectedTaskIds: controlledSelectedTaskIds,
    processingTaskId,
    bulkProcessing = false,
}) => {
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
    const [order, setOrder] = useState<Order>('desc');
    const [orderBy, setOrderBy] = useState<keyof FileData>('created_at');
    const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>(controlledSelectedTaskIds ?? []);
    const [localBulkAction, setLocalBulkAction] = useState<'transcribe' | 'summary' | null>(null);

    const handleRequestSort = (property: keyof FileData) => {
        const isAsc = orderBy === property && order === 'asc';
        setOrder(isAsc ? 'desc' : 'asc');
        setOrderBy(property);
    };

    const toggleRow = (taskId: string) => {
        setExpandedRows(prev => {
            const newSet = new Set(prev);
            if (newSet.has(taskId)) {
                newSet.delete(taskId);
            } else {
                newSet.add(taskId);
            }
            return newSet;
        });
    };

    const sortedFiles = useMemo(() => {
        return [...files].sort((a, b) => {
            const aValue = orderBy === 'created_at'
                ? apiDateTimeToEpoch(a.uploaded_at || a.created_at)
                : a[orderBy] || '';
            const bValue = orderBy === 'created_at'
                ? apiDateTimeToEpoch(b.uploaded_at || b.created_at)
                : b[orderBy] || '';

            if (bValue < aValue) {
                return order === 'asc' ? 1 : -1;
            }
            if (bValue > aValue) {
                return order === 'asc' ? -1 : 1;
            }
            return 0;
        });
    }, [files, order, orderBy]);

    useEffect(() => {
        const fileIds = new Set(files.map(file => file.task_id));
        const currentIds = new Set((selectableTaskIds ?? Array.from(fileIds)).filter(taskId => fileIds.has(taskId)));
        setSelectedTaskIds(current => {
            const next = current.filter(taskId => currentIds.has(taskId));
            if (next.length === current.length) return current;
            onSelectionChange?.(next);
            return next;
        });
    }, [files, selectableTaskIds?.join('\u0000')]);

    useEffect(() => {
        if (!controlledSelectedTaskIds) return;
        const allowed = new Set(selectableTaskIds ?? files.map(file => file.task_id));
        const next = controlledSelectedTaskIds.filter(taskId => allowed.has(taskId));
        setSelectedTaskIds(current => (
            current.length === next.length && current.every((taskId, index) => taskId === next[index])
                ? current
                : next
        ));
    }, [controlledSelectedTaskIds?.join('\u0000'), files, selectableTaskIds?.join('\u0000')]);

    const fileByTaskId = new Map(files.map(file => [file.task_id, file]));
    const canonicalFiles = (selectableTaskIds ?? sortedFiles.map(file => file.task_id))
        .map(taskId => fileByTaskId.get(taskId))
        .filter((file): file is FileData => Boolean(file));
    const selectableFiles = canonicalFiles.filter(file => ![
        'queued',
        'transcribing',
        'summarizing',
        'processing',
        'cancel_requested',
        'cancelled',
    ].includes(file.status));
    const selectedSet = new Set(selectedTaskIds);
    const orderedSelectedFiles = canonicalFiles.filter(file => selectedSet.has(file.task_id));
    const orderedSelectedTaskIds = orderedSelectedFiles.map(file => file.task_id);
    const transcribableTaskIds = orderedSelectedFiles
        .filter(file => !file.transcript && ['uploaded', 'failed'].includes(file.status))
        .map(file => file.task_id);
    const incompleteSummaryCount = orderedSelectedFiles.filter(file => !file.transcript).length;
    const bulkEnabled = Boolean(onBulkTranscribe || onBulkSummarize || onSelectionChange);
    const allSelectableSelected = selectableFiles.length > 0
        && selectableFiles.every(file => selectedSet.has(file.task_id));
    const someSelectableSelected = selectableFiles.some(file => selectedSet.has(file.task_id));
    const isBulkBusy = bulkProcessing || localBulkAction !== null;

    const commitSelection = (taskIds: string[]) => {
        setSelectedTaskIds(taskIds);
        onSelectionChange?.(taskIds);
    };

    const toggleSelection = (taskId: string) => {
        const requested = selectedSet.has(taskId)
            ? new Set(selectedTaskIds.filter(id => id !== taskId))
            : new Set([...selectedTaskIds, taskId]);
        const next = canonicalFiles
            .filter(file => requested.has(file.task_id))
            .map(file => file.task_id);
        commitSelection(next);
    };

    const toggleAll = () => {
        commitSelection(allSelectableSelected ? [] : selectableFiles.map(file => file.task_id));
    };

    const runBulkAction = async (
        action: 'transcribe' | 'summary',
        callback: ((taskIds: string[]) => void | Promise<void>) | undefined,
        taskIds: string[],
    ) => {
        if (!callback || taskIds.length === 0 || isBulkBusy) return;
        setLocalBulkAction(action);
        try {
            await callback(taskIds);
        } finally {
            setLocalBulkAction(null);
        }
    };

    if (files.length === 0) {
        return (
            <Paper sx={{ p: 3, textAlign: 'center', borderRadius: '12px' }}>
                <Typography color="text.secondary">
                    Chưa có files. Upload files để bắt đầu.
                </Typography>
            </Paper>
        );
    }

    return (
        <Box>
            {bulkEnabled && (
                <Paper
                    variant="outlined"
                    sx={{
                        minHeight: 52,
                        px: 1.5,
                        py: 1,
                        mb: 1,
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1,
                        flexWrap: 'wrap',
                    }}
                >
                    <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }}>
                        Đã chọn {orderedSelectedTaskIds.length}
                    </Typography>
                    <Button
                        size="small"
                        onClick={() => commitSelection([])}
                        disabled={orderedSelectedTaskIds.length === 0 || isBulkBusy}
                    >
                        Bỏ chọn
                    </Button>
                    <Box sx={{ flex: { xs: '0 0 100%', sm: 1 }, height: { xs: 0, sm: 'auto' } }} />
                    {incompleteSummaryCount > 0 && orderedSelectedTaskIds.length > 0 && (
                        <Typography variant="caption" color="warning.main">
                            {incompleteSummaryCount} file chưa có transcript
                        </Typography>
                    )}
                    {onBulkTranscribe && (
                        <Button
                            size="small"
                            variant="outlined"
                            startIcon={<TranscribeIcon />}
                            disabled={transcribableTaskIds.length === 0 || isBulkBusy}
                            onClick={() => runBulkAction('transcribe', onBulkTranscribe, transcribableTaskIds)}
                            sx={{ textTransform: 'none', flex: { xs: '1 1 100%', sm: '0 0 auto' } }}
                        >
                            {localBulkAction === 'transcribe' ? 'Đang gửi...' : `Transcribe (${transcribableTaskIds.length})`}
                        </Button>
                    )}
                    {onBulkSummarize && (
                        <Tooltip title={incompleteSummaryCount > 0 ? 'Tất cả file đã chọn phải có transcript' : ''}>
                            <span>
                                <Button
                                    size="small"
                                    variant="contained"
                                    startIcon={<SummarizeIcon />}
                                    disabled={orderedSelectedTaskIds.length === 0 || incompleteSummaryCount > 0 || isBulkBusy}
                                    onClick={() => runBulkAction('summary', onBulkSummarize, orderedSelectedTaskIds)}
                                    sx={{ textTransform: 'none', width: { xs: '100%', sm: 'auto' } }}
                                >
                                    {localBulkAction === 'summary' ? 'Đang mở...' : `Merged summary (${orderedSelectedTaskIds.length})`}
                                </Button>
                            </span>
                        </Tooltip>
                    )}
                </Paper>
            )}
            <TableContainer component={Paper} sx={{ borderRadius: '8px', overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 720 }}>
                <TableHead>
                    <TableRow sx={{ bgcolor: 'rgba(0,0,0,0.02)' }}>
                        {bulkEnabled && (
                            <TableCell padding="checkbox">
                                <Checkbox
                                    size="small"
                                    checked={allSelectableSelected}
                                    indeterminate={!allSelectableSelected && someSelectableSelected}
                                    onChange={toggleAll}
                                    inputProps={{ 'aria-label': 'Chọn tất cả file khả dụng' }}
                                />
                            </TableCell>
                        )}
                        <TableCell width={40}></TableCell>
                        <TableCell>
                            <TableSortLabel
                                active={orderBy === 'filename'}
                                direction={orderBy === 'filename' ? order : 'asc'}
                                onClick={() => handleRequestSort('filename')}
                            >
                                <strong>File</strong>
                            </TableSortLabel>
                        </TableCell>
                        <TableCell width={180}>
                            <TableSortLabel
                                active={orderBy === 'created_at'}
                                direction={orderBy === 'created_at' ? order : 'asc'}
                                onClick={() => handleRequestSort('created_at')}
                            >
                                <strong>Tải lên</strong>
                            </TableSortLabel>
                        </TableCell>
                        <TableCell width={100}><strong>Speakers</strong></TableCell>
                        <TableCell width={120}>
                            <TableSortLabel
                                active={orderBy === 'status'}
                                direction={orderBy === 'status' ? order : 'asc'}
                                onClick={() => handleRequestSort('status')}
                            >
                                <strong>Status</strong>
                            </TableSortLabel>
                        </TableCell>
                        <TableCell width={60} align="center"></TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {sortedFiles.map((file) => {
                        const isExpanded = expandedRows.has(file.task_id);
                        const isProcessing = processingTaskId === file.task_id;

                        return (
                            <React.Fragment key={file.task_id}>
                                {/* Main Row */}
                                <TableRow
                                    hover
                                    sx={{
                                        cursor: 'pointer',
                                        '& > *': { borderBottom: isExpanded ? 'none' : undefined },
                                        bgcolor: isExpanded ? 'rgba(225, 29, 72, 0.02)' : undefined,
                                    }}
                                    onClick={() => toggleRow(file.task_id)}
                                >
                                    {bulkEnabled && (
                                        <TableCell padding="checkbox" onClick={(event) => event.stopPropagation()}>
                                            <Checkbox
                                                size="small"
                                                checked={selectedSet.has(file.task_id)}
                                                disabled={!selectableFiles.some(item => item.task_id === file.task_id)}
                                                onChange={() => toggleSelection(file.task_id)}
                                                inputProps={{ 'aria-label': `Chọn ${file.filename}` }}
                                            />
                                        </TableCell>
                                    )}
                                    <TableCell>
                                        <IconButton size="small">
                                            {isExpanded ? <CollapseIcon /> : <ExpandIcon />}
                                        </IconButton>
                                    </TableCell>
                                    <TableCell>
                                        <Box display="flex" alignItems="center" gap={1}>
                                            <AudioIcon sx={{ color: '#e11d48', fontSize: 20 }} />
                                            <Typography variant="body2" fontWeight={500} noWrap sx={{ maxWidth: 300 }}>
                                                {file.filename}
                                            </Typography>
                                        </Box>
                                    </TableCell>
                                    <TableCell>
                                        <DateTimeText
                                            value={file.uploaded_at || file.created_at}
                                            label=""
                                            showIcon={false}
                                            sx={{ whiteSpace: 'nowrap' }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        {file.num_speakers ? (
                                            <Chip label={`${file.num_speakers} speakers`} size="small" variant="outlined" />
                                        ) : '-'}
                                    </TableCell>
                                    <TableCell>{getStatusChip(file.status)}</TableCell>
                                    <TableCell align="center">
                                        <Tooltip title="Delete">
                                            <IconButton
                                                size="small"
                                                onClick={(e) => { e.stopPropagation(); onDelete(file.task_id); }}
                                                color="error"
                                            >
                                                <DeleteIcon fontSize="small" />
                                            </IconButton>
                                        </Tooltip>
                                    </TableCell>
                                </TableRow>

                                {/* Expanded Row */}
                                <TableRow>
                                    <TableCell colSpan={bulkEnabled ? 7 : 6} sx={{ p: 0 }}>
                                        <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                            <Box sx={{ p: 2, bgcolor: 'rgba(0,0,0,0.01)' }}>
                                                {isProcessing && (
                                                    <LinearProgress sx={{ mb: 2 }} />
                                                )}

                                                {/* Audio Player */}
                                                <Box mb={2}>
                                                    <Typography variant="caption" color="text.secondary" fontWeight={600} display="block" mb={0.5}>
                                                        🎵 Nghe file:
                                                    </Typography>
                                                    <audio
                                                        controls
                                                        style={{ width: '100%', height: 32 }}
                                                        src={file.download_url || `/api/v1/audio/${file.audio_id}/download`}
                                                    />
                                                </Box>

                                                <Box display="flex" gap={1} flexWrap="wrap">
                                                    <Button
                                                        variant="outlined"
                                                        size="small"
                                                        startIcon={<TranscribeIcon />}
                                                        onClick={(e) => { e.stopPropagation(); onTranscribe(file.task_id); }}
                                                        disabled={isProcessing || file.status === 'transcribing'}
                                                        sx={{ textTransform: 'none' }}
                                                    >
                                                        Transcribe
                                                    </Button>

                                                    <Button
                                                        variant="outlined"
                                                        size="small"
                                                        startIcon={<SummarizeIcon />}
                                                        onClick={(e) => { e.stopPropagation(); onSummarize(file.task_id); }}
                                                        disabled={isProcessing || !file.transcript || file.status === 'summarizing'}
                                                        sx={{ textTransform: 'none' }}
                                                    >
                                                        Summarize
                                                    </Button>

                                                    <Button
                                                        variant="outlined"
                                                        size="small"
                                                        startIcon={<AnalysisIcon />}
                                                        onClick={(e) => { e.stopPropagation(); onAnalyze(file.task_id); }}
                                                        disabled={isProcessing || !file.transcript}
                                                        sx={{ textTransform: 'none' }}
                                                        color="primary"
                                                    >
                                                        Analysis
                                                    </Button>

                                                    <Button
                                                        variant="outlined"
                                                        size="small"
                                                        startIcon={<VisualizeIcon />}
                                                        onClick={(e) => { e.stopPropagation(); onVisualize(file.task_id); }}
                                                        disabled={isProcessing || !file.transcript}
                                                        sx={{ textTransform: 'none' }}
                                                        color="secondary"
                                                    >
                                                        Visualization
                                                    </Button>
                                                </Box>
                                            </Box>
                                        </Collapse>
                                    </TableCell>
                                </TableRow>
                            </React.Fragment>
                        );
                    })}
                </TableBody>
            </Table>
            </TableContainer>
        </Box>
    );
};

export default FileTable;
