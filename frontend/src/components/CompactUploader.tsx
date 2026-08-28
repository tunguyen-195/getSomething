import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Chip,
    Collapse,
    IconButton,
    LinearProgress,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Paper,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    AudioFile as AudioIcon,
    CheckCircle as AcceptedIcon,
    CloudUpload as UploadIcon,
    Delete as DeleteIcon,
    Error as RejectedIcon,
    ExpandLess as CollapseIcon,
    ExpandMore as ExpandIcon,
    HourglassEmpty as PendingIcon,
} from '@mui/icons-material';
import {
    AUDIO_BATCH_MAX_FILES,
    AUDIO_BATCH_MAX_FILE_BYTES,
    AUDIO_BATCH_MAX_TOTAL_BYTES,
    AudioBatchApiError,
    createAudioBatch,
    createAudioBatchIdempotencyKey,
} from '../api/client';
import type { AudioBatchResponse } from '../api/client';

interface CompactUploaderProps {
    caseId: string;
    onUploadComplete?: (batch: AudioBatchResponse) => void;
    disabled?: boolean;
}

type UploadItemStatus = 'pending' | 'uploading' | 'accepted' | 'rejected';

interface UploadItem {
    id: number;
    file: File;
    status: UploadItemStatus;
    taskId?: string;
    errorCode?: string;
}

const CompactUploader: React.FC<CompactUploaderProps> = ({ caseId, onUploadComplete, disabled = false }) => {
    const [expanded, setExpanded] = useState(false);
    const [items, setItems] = useState<UploadItem[]>([]);
    const [uploading, setUploading] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [batch, setBatch] = useState<AudioBatchResponse | null>(null);
    const [requestError, setRequestError] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const inputId = useId();
    const nextItemIdRef = useRef(1);
    const requestSequenceRef = useRef(0);
    const idempotencyKeyRef = useRef(createAudioBatchIdempotencyKey());

    const resetRequestIdentity = useCallback(() => {
        requestSequenceRef.current += 1;
        idempotencyKeyRef.current = createAudioBatchIdempotencyKey();
        setBatch(null);
        setRequestError(null);
    }, []);

    useEffect(() => {
        setItems([]);
        setBatch(null);
        setRequestError(null);
        setUploading(false);
        setExpanded(false);
        requestSequenceRef.current += 1;
        idempotencyKeyRef.current = createAudioBatchIdempotencyKey();
        if (inputRef.current) inputRef.current.value = '';
    }, [caseId]);

    const addFiles = useCallback((nextFiles: File[]) => {
        if (disabled || uploading || nextFiles.length === 0) return;
        resetRequestIdentity();
        setItems(current => {
            const shouldReplace = current.some(item => item.status !== 'pending');
            return [
            ...(shouldReplace ? [] : current),
            ...nextFiles.map(file => ({
                id: nextItemIdRef.current++,
                file,
                status: 'pending' as const,
            })),
        ];
        });
        setExpanded(true);
    }, [disabled, resetRequestIdentity, uploading]);

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        addFiles(Array.from(event.target.files ?? []));
        event.target.value = '';
    };

    const handleDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        setIsDragging(false);
        addFiles(Array.from(event.dataTransfer.files));
    }, [addFiles]);

    const removeFile = (id: number) => {
        resetRequestIdentity();
        setItems(current => current.filter(item => item.id !== id));
    };

    const clearQueue = () => {
        setItems([]);
        setExpanded(false);
        resetRequestIdentity();
        if (inputRef.current) inputRef.current.value = '';
    };

    const totalBytes = items.reduce((total, item) => total + item.file.size, 0);
    const exceedsFileLimit = items.length > AUDIO_BATCH_MAX_FILES;
    const exceedsTotalLimit = totalBytes > AUDIO_BATCH_MAX_TOTAL_BYTES;
    const invalidSizeCount = items.filter(item => item.file.size === 0 || item.file.size > AUDIO_BATCH_MAX_FILE_BYTES).length;
    const normalizedNames = items.map(item => item.file.name.normalize('NFKC').toLocaleLowerCase());
    const duplicateNameCount = normalizedNames.length - new Set(normalizedNames).size;
    const invalidNameCount = items.filter(item => {
        const normalized = item.file.name.normalize('NFC').trim();
        const hasControl = Array.from(normalized).some(character => {
            const codePoint = character.codePointAt(0) ?? 0;
            return codePoint <= 0x1f
                || (codePoint >= 0x7f && codePoint <= 0x9f)
                || (codePoint >= 0x200b && codePoint <= 0x200f)
                || (codePoint >= 0x202a && codePoint <= 0x202e)
                || (codePoint >= 0x2060 && codePoint <= 0x206f);
        });
        return !normalized
            || normalized === '.'
            || normalized === '..'
            || normalized.length > 255
            || /[\\/:]/.test(normalized)
            || hasControl;
    }).length;
    const queueInvalid = exceedsFileLimit
        || exceedsTotalLimit
        || invalidSizeCount > 0
        || duplicateNameCount > 0
        || invalidNameCount > 0;
    const canUpload = items.length > 0
        && items.every(item => item.status === 'pending')
        && !queueInvalid
        && !uploading
        && !disabled;

    const handleUpload = async () => {
        if (!canUpload || !caseId) return;
        setUploading(true);
        setRequestError(null);
        setItems(current => current.map(item => ({ ...item, status: 'uploading' })));
        const requestSequence = requestSequenceRef.current;

        try {
            const response = await createAudioBatch({
                files: items.map(item => item.file),
                caseId,
                idempotencyKey: idempotencyKeyRef.current,
            });
            if (requestSequenceRef.current !== requestSequence) return;
            onUploadComplete?.(response);
            setBatch(response);
            setItems(current => current.map((queuedItem, index) => {
                const result = response.items.find(item => item.position === index) ?? response.items[index];
                const accepted = Boolean(result?.task_id) && result?.status !== 'failed';
                return {
                    ...queuedItem,
                    status: accepted ? 'accepted' : 'rejected',
                    taskId: result?.task_id,
                    errorCode: accepted ? undefined : result?.error_code ?? 'UPLOAD_REJECTED',
                };
            }));
        } catch (error) {
            if (requestSequenceRef.current === requestSequence) {
                setItems(current => current.map(item => ({ ...item, status: 'pending' })));
                const safeCode = error instanceof AudioBatchApiError ? ` (${error.code})` : '';
                setRequestError(`Không thể gửi batch${safeCode}. Kiểm tra kết nối rồi thử lại; lần thử lại dùng cùng mã chống trùng lặp.`);
            }
        } finally {
            if (requestSequenceRef.current === requestSequence) setUploading(false);
        }
    };

    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
        return `${(bytes / (1000 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
    };

    const statusIcon = (status: UploadItemStatus) => {
        if (status === 'accepted') return <AcceptedIcon color="success" fontSize="small" />;
        if (status === 'rejected') return <RejectedIcon color="error" fontSize="small" />;
        return <PendingIcon color={status === 'uploading' ? 'warning' : 'disabled'} fontSize="small" />;
    };

    const statusText = (item: UploadItem) => {
        if (item.status === 'accepted') return item.taskId ? `Đã nhận · ${item.taskId}` : 'Đã nhận';
        if (item.status === 'rejected') return `Bị từ chối · ${item.errorCode}`;
        if (item.status === 'uploading') return 'Đang gửi';
        return formatBytes(item.file.size);
    };

    return (
        <Box>
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    p: 1,
                    borderRadius: '8px',
                    bgcolor: expanded ? 'transparent' : 'rgba(225, 29, 72, 0.05)',
                    border: '1px solid',
                    borderColor: expanded ? 'primary.main' : 'divider',
                }}
            >
                <input
                    ref={inputRef}
                    type="file"
                    accept="audio/*"
                    multiple
                    onChange={handleFileChange}
                    style={{ display: 'none' }}
                    id={inputId}
                />
                <label htmlFor={inputId}>
                    <Button
                        component="span"
                        variant={expanded ? 'outlined' : 'contained'}
                        size="small"
                        startIcon={<UploadIcon />}
                        disabled={uploading || disabled || !caseId}
                        sx={{ textTransform: 'none', fontWeight: 600, borderRadius: '8px', px: 2 }}
                    >
                        Upload audio
                    </Button>
                </label>
                {items.length > 0 && <Chip label={`${items.length} file`} size="small" color="primary" />}
                {batch && <Chip label={`Batch ${batch.id}`} size="small" variant="outlined" />}
                <Box flex={1} />
                <Tooltip title={expanded ? 'Thu gọn' : 'Mở danh sách'}>
                    <IconButton size="small" onClick={() => setExpanded(current => !current)}>
                        {expanded ? <CollapseIcon /> : <ExpandIcon />}
                    </IconButton>
                </Tooltip>
            </Box>

            <Collapse in={expanded}>
                <Paper
                    sx={{
                        mt: 1,
                        p: 2,
                        borderRadius: '8px',
                        border: isDragging ? '2px dashed' : '1px solid',
                        borderColor: isDragging ? 'primary.main' : 'divider',
                        bgcolor: isDragging ? 'rgba(225, 29, 72, 0.05)' : 'background.paper',
                    }}
                    onDrop={handleDrop}
                    onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }}
                    onDragLeave={() => setIsDragging(false)}
                >
                    {items.length === 0 ? (
                        <Box textAlign="center" py={2}>
                            <Typography color="text.secondary" fontSize="0.9rem">
                                Kéo thả tối đa {AUDIO_BATCH_MAX_FILES} file vào đây
                            </Typography>
                        </Box>
                    ) : (
                        <>
                            {exceedsFileLimit && (
                                <Alert severity="error" sx={{ mb: 1 }}>
                                    Mỗi batch tối đa {AUDIO_BATCH_MAX_FILES} file.
                                </Alert>
                            )}
                            {exceedsTotalLimit && (
                                <Alert severity="error" sx={{ mb: 1 }}>
                                    Tổng dung lượng batch vượt quá {formatBytes(AUDIO_BATCH_MAX_TOTAL_BYTES)}.
                                </Alert>
                            )}
                            {invalidSizeCount > 0 && (
                                <Alert severity="error" sx={{ mb: 1 }}>
                                    {invalidSizeCount} file rỗng hoặc vượt quá {formatBytes(AUDIO_BATCH_MAX_FILE_BYTES)}.
                                </Alert>
                            )}
                            {duplicateNameCount > 0 && (
                                <Alert severity="error" sx={{ mb: 1 }}>
                                    Tên file trong cùng batch không được trùng nhau.
                                </Alert>
                            )}
                            {invalidNameCount > 0 && (
                                <Alert severity="error" sx={{ mb: 1 }}>
                                    {invalidNameCount} tên file không hợp lệ.
                                </Alert>
                            )}
                            {requestError && <Alert severity="error" sx={{ mb: 1 }}>{requestError}</Alert>}
                            <List dense disablePadding aria-label="Danh sách file trong batch">
                                {items.map(item => (
                                    <ListItem
                                        key={item.id}
                                        secondaryAction={item.status === 'pending' ? (
                                            <IconButton size="small" disabled={disabled} onClick={() => removeFile(item.id)} aria-label={`Xóa ${item.file.name}`}>
                                                <DeleteIcon fontSize="small" />
                                            </IconButton>
                                        ) : undefined}
                                        sx={{ py: 0.5 }}
                                    >
                                        <ListItemIcon sx={{ minWidth: 32 }}><AudioIcon color="primary" fontSize="small" /></ListItemIcon>
                                        <ListItemText
                                            primary={item.file.name}
                                            secondary={statusText(item)}
                                            primaryTypographyProps={{ fontSize: '0.85rem', fontWeight: 500 }}
                                            secondaryTypographyProps={{ fontSize: '0.72rem' }}
                                        />
                                        <Box sx={{ mr: item.status === 'pending' ? 4 : 0 }}>{statusIcon(item.status)}</Box>
                                    </ListItem>
                                ))}
                            </List>
                            {uploading && <LinearProgress sx={{ mt: 1 }} />}
                            <Box display="flex" justifyContent="space-between" alignItems="center" mt={2} gap={1} flexWrap="wrap">
                                <Typography variant="caption" color="text.secondary">
                                    {items.length} file · {formatBytes(totalBytes)}
                                </Typography>
                                <Box display="flex" gap={1}>
                                    <Button size="small" onClick={clearQueue} disabled={uploading || disabled}>Xóa danh sách</Button>
                                    <Button
                                        variant="contained"
                                        size="small"
                                        onClick={handleUpload}
                                        disabled={!canUpload}
                                        sx={{ textTransform: 'none', fontWeight: 600 }}
                                    >
                                        {uploading ? 'Đang gửi batch...' : `Upload ${items.length} file`}
                                    </Button>
                                </Box>
                            </Box>
                        </>
                    )}
                </Paper>
            </Collapse>
        </Box>
    );
};

export default CompactUploader;
