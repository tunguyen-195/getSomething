import React, { useState, useMemo } from 'react';
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

interface FileData {
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
}

interface FileTableProps {
    files: FileData[];
    onTranscribe: (taskId: string) => void;
    onSummarize: (taskId: string) => void;
    onAnalyze: (taskId: string) => void;
    onVisualize: (taskId: string) => void;
    onDelete: (taskId: string) => void;
    processingTaskId?: string;
}

const getStatusChip = (status: string) => {
    switch (status) {
        case 'uploaded':
            return <Chip label="Uploaded" size="small" color="default" icon={<PendingIcon />} />;
        case 'transcribing':
        case 'summarizing':
        case 'processing':
            return <Chip label="Processing" size="small" color="warning" icon={<PendingIcon />} />;
        case 'transcribed':
            return <Chip label="Transcribed" size="small" color="info" icon={<CheckIcon />} />;
        case 'summarized':
            return <Chip label="Summarized" size="small" color="success" icon={<CheckIcon />} />;
        case 'visualized':
            return <Chip label="Analyzed" size="small" color="secondary" icon={<CheckIcon />} />;
        case 'error':
            return <Chip label="Error" size="small" color="error" icon={<ErrorIcon />} />;
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
    processingTaskId,
}) => {
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
    const [order, setOrder] = useState<Order>('desc');
    const [orderBy, setOrderBy] = useState<keyof FileData>('created_at');

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
        <TableContainer component={Paper} sx={{ borderRadius: '12px', overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 720 }}>
                <TableHead>
                    <TableRow sx={{ bgcolor: 'rgba(0,0,0,0.02)' }}>
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
                                    <TableCell colSpan={6} sx={{ p: 0 }}>
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
    );
};

export default FileTable;
