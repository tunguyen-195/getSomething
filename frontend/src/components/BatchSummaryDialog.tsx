import React, { useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    MenuItem,
    Select,
    TextField,
    Typography,
    useMediaQuery,
} from '@mui/material';
import { Close, Summarize } from '@mui/icons-material';
import {
    DEFAULT_BATCH_SUMMARY_TYPE,
    DEFAULT_MULTI_SUMMARY_MAX_LENGTH,
    DEFAULT_MULTI_SUMMARY_MIN_LENGTH,
    AUDIO_BATCH_MAX_FILES,
    AudioBatchApiError,
    normalizeSummaryUserPrompt,
    submitAudioBatchSummary,
    SUMMARY_USER_PROMPT_MAX_LENGTH,
} from '../api/client';
import type { AudioBatchSummaryJob, AudioBatchSummaryType } from '../api/client';

export interface BatchSummarySource {
    task_id: string;
    filename: string;
    transcriptReady: boolean;
}

interface BatchSummaryDialogProps {
    open: boolean;
    batchId: string;
    sources: BatchSummarySource[];
    onClose: () => void;
    onSubmitted: (job: AudioBatchSummaryJob) => void;
}

const BatchSummaryDialog: React.FC<BatchSummaryDialogProps> = ({
    open,
    batchId,
    sources,
    onClose,
    onSubmitted,
}) => {
    const fullScreen = useMediaQuery('(max-width:600px)');
    const [summaryType, setSummaryType] = useState<AudioBatchSummaryType>(DEFAULT_BATCH_SUMMARY_TYPE);
    const [userPrompt, setUserPrompt] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [requestErrorCode, setRequestErrorCode] = useState<string | null>(null);
    const promptLength = Array.from(userPrompt.trim()).length;
    const promptTooLong = promptLength > SUMMARY_USER_PROMPT_MAX_LENGTH;
    const incompleteCount = sources.filter(source => !source.transcriptReady).length;
    const duplicateSourceCount = sources.length - new Set(sources.map(source => source.task_id)).size;
    const canSubmit = sources.length > 0
        && sources.length <= AUDIO_BATCH_MAX_FILES
        && duplicateSourceCount === 0
        && incompleteCount === 0
        && !promptTooLong
        && !submitting;

    useEffect(() => {
        if (open) setRequestErrorCode(null);
    }, [open, batchId, sources]);

    const handleClose = () => {
        if (submitting) return;
        setSummaryType(DEFAULT_BATCH_SUMMARY_TYPE);
        setUserPrompt('');
        setRequestErrorCode(null);
        onClose();
    };

    const handleSubmit = async () => {
        if (!canSubmit) return;
        setSubmitting(true);
        setRequestErrorCode(null);
        try {
            const job = await submitAudioBatchSummary(batchId, {
                task_ids: sources.map(source => source.task_id),
                summary_type: summaryType,
                min_length: DEFAULT_MULTI_SUMMARY_MIN_LENGTH,
                max_length: DEFAULT_MULTI_SUMMARY_MAX_LENGTH,
                length_mode: 'auto',
                user_prompt: normalizeSummaryUserPrompt(userPrompt),
            });
            onSubmitted(job);
            setUserPrompt('');
        } catch (error) {
            setRequestErrorCode(error instanceof AudioBatchApiError ? error.code : 'BATCH_SUMMARY_REQUEST_FAILED');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth fullScreen={fullScreen}>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Summarize /> Merged summary
            </DialogTitle>
            <DialogContent>
                <Typography variant="body2" color="text.secondary" mb={2}>
                    {sources.length} nguồn theo đúng thứ tự đã chọn
                </Typography>
                {incompleteCount > 0 && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        {incompleteCount} file chưa có transcript. Merged summary chỉ chạy khi tất cả nguồn đã sẵn sàng.
                    </Alert>
                )}
                {(duplicateSourceCount > 0 || sources.length > AUDIO_BATCH_MAX_FILES) && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        Danh sách nguồn không hợp lệ. Hãy đóng hộp thoại và chọn lại.
                    </Alert>
                )}
                {requestErrorCode && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        Không thể tạo merged summary ({requestErrorCode}). Kiểm tra trạng thái batch rồi thử lại.
                    </Alert>
                )}
                <Box component="ol" sx={{ mt: 0, mb: 2, pl: 3, maxHeight: 120, overflow: 'auto' }}>
                    {sources.map(source => (
                        <Typography component="li" variant="body2" key={source.task_id} sx={{ overflowWrap: 'anywhere' }}>
                            {source.filename}
                        </Typography>
                    ))}
                </Box>
                <Typography variant="subtitle2" fontWeight={700} mb={1}>LOẠI TÓM TẮT</Typography>
                <FormControl fullWidth sx={{ mb: 2 }}>
                    <Select
                        size="small"
                        value={summaryType}
                        onChange={event => setSummaryType(event.target.value as AudioBatchSummaryType)}
                    >
                        <MenuItem value="brief">Brief</MenuItem>
                        <MenuItem value="detailed">Detailed</MenuItem>
                    </Select>
                </FormControl>
                <Typography variant="subtitle2" fontWeight={700} mb={1}>YÊU CẦU TÓM TẮT (TÙY CHỌN)</Typography>
                <TextField
                    value={userPrompt}
                    onChange={event => setUserPrompt(event.target.value)}
                    multiline
                    minRows={3}
                    maxRows={7}
                    fullWidth
                    error={promptTooLong}
                    placeholder="Ví dụ: So sánh các mốc thời gian giữa các file"
                    helperText={promptTooLong
                        ? `Tối đa ${SUMMARY_USER_PROMPT_MAX_LENGTH.toLocaleString('vi-VN')} ký tự`
                        : `${promptLength.toLocaleString('vi-VN')}/${SUMMARY_USER_PROMPT_MAX_LENGTH.toLocaleString('vi-VN')}`}
                    inputProps={{ 'aria-label': 'Yêu cầu merged summary tùy chọn' }}
                />
            </DialogContent>
            <DialogActions sx={{ px: { xs: 2, sm: 3 }, pb: { xs: 2, sm: 3 }, flexWrap: 'wrap' }}>
                <Button onClick={handleClose} disabled={submitting} startIcon={<Close />}>Hủy</Button>
                <Button
                    variant="contained"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    startIcon={<Summarize />}
                    sx={{ width: { xs: '100%', sm: 'auto' } }}
                >
                    {submitting ? 'Đang gửi...' : `Tóm tắt ${sources.length} file`}
                </Button>
            </DialogActions>
        </Dialog>
    );
};

export default BatchSummaryDialog;
