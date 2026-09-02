import React, { useMemo, useState } from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Grid,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Paper,
    Typography,
} from '@mui/material';
import {
    Analytics as AnalyticsIcon,
    AssignmentTurnedIn as ActionIcon,
    Badge as ParticipantIcon,
    Event as EventIcon,
    ExpandMore as ExpandMoreIcon,
    HelpOutline as QuestionIcon,
    Hub as HubIcon,
    Link as RelationshipIcon,
    Numbers as NumbersIcon,
    Person as PersonIcon,
    Refresh as RefreshIcon,
    ReportProblem as ReportProblemIcon,
} from '@mui/icons-material';
import { apiFetch } from '../api/client';
import { sanitizeSummaryDisplayText } from '../utils/summaryDisplay';
import { AnalysisAction, projectInvestigationAnalysis } from '../utils/investigationAnalysis';

interface FileWithData {
    task_id: string;
    filename: string;
    transcript?: string;
    summary?: string;
    status: string;
    duration?: number;
    context_analysis?: unknown;
    segments?: Array<{ speaker?: string; text: string }>;
}

interface AnalysisPanelProps {
    files: FileWithData[];
    caseId: string;
    mode?: 'light' | 'dark';
    onRefresh?: () => Promise<void> | void;
    focusTaskId?: string | null;
}

function responseError(payload: unknown, fallback: string): string {
    if (!payload || typeof payload !== 'object') return fallback;
    const detail = (payload as Record<string, unknown>).detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') {
        const record = detail as Record<string, unknown>;
        if (typeof record.message === 'string') return record.message;
        if (typeof record.code === 'string') return record.code;
    }
    return fallback;
}

function AnalysisItemList({ items }: { items: AnalysisAction[] }) {
    return (
        <List dense disablePadding>
            {items.map(item => (
                <ListItem key={item.id} alignItems="flex-start">
                    <ListItemIcon sx={{ minWidth: 34 }}><ActionIcon color="action" /></ListItemIcon>
                    <ListItemText
                        primary={item.description}
                        secondary={[
                            item.actor && `Chủ thể: ${item.actor}`,
                            item.target && `Đối tượng: ${item.target}`,
                            item.assignee && `Phụ trách: ${item.assignee}`,
                            item.deadline && `Hạn: ${item.deadline}`,
                            item.priority && `Ưu tiên: ${item.priority}`,
                            item.reason && `Lý do: ${item.reason}`,
                            item.status && `Trạng thái: ${item.status}`,
                        ].filter(Boolean).join(' • ')}
                    />
                </ListItem>
            ))}
        </List>
    );
}

const AnalysisPanel: React.FC<AnalysisPanelProps> = ({ files, caseId, onRefresh, focusTaskId }) => {
    const [analyzingTaskId, setAnalyzingTaskId] = useState<string | null>(null);
    const [requestError, setRequestError] = useState<string | null>(null);
    const [requestSuccess, setRequestSuccess] = useState<string | null>(null);
    const analysisRows = useMemo(() => files.map(file => ({
        file,
        preview: projectInvestigationAnalysis(file.context_analysis),
    })), [files]);

    const analyzedFileCount = analysisRows.filter(row => row.preview.state === 'source_preview').length;
    const participantCount = analysisRows.reduce((sum, row) => sum + row.preview.participants.length, 0);
    const entityCount = analysisRows.reduce(
        (sum, row) => sum + row.preview.entities.length + row.preview.exact_values.length,
        0,
    );
    const eventCount = analysisRows.reduce((sum, row) => sum + row.preview.events.length, 0);
    const actionCount = analysisRows.reduce(
        (sum, row) => sum + row.preview.actions.length + row.preview.decisions.length
            + row.preview.commitments.length + row.preview.follow_ups.length,
        0,
    );

    const runAnalysis = async (file: FileWithData) => {
        if (!file.transcript || analyzingTaskId) return;
        setAnalyzingTaskId(file.task_id);
        setRequestError(null);
        setRequestSuccess(null);
        try {
            const response = await apiFetch('/api/v1/summaries/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    summary: sanitizeSummaryDisplayText(file.summary || ''),
                    task_id: file.task_id,
                }),
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok) throw new Error(responseError(payload, `HTTP ${response.status}`));
            setRequestSuccess(`Đã cập nhật Analysis cho ${file.filename}.`);
            await onRefresh?.();
        } catch (error) {
            setRequestError(error instanceof Error ? error.message : 'Không thể chạy Analysis.');
        } finally {
            setAnalyzingTaskId(null);
        }
    };

    if (files.length === 0) {
        return (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: 3 }}>
                <AnalyticsIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
                <Typography color="text.secondary">Chưa có file để phân tích.</Typography>
            </Paper>
        );
    }

    return (
        <Box>
            <Alert severity="info" sx={{ mb: 2 }}>
                Analysis dùng LLM để đọc toàn bộ hội thoại và trình bày các insight hữu ích. Các mục không có dữ liệu sẽ tự động được ẩn.
            </Alert>
            {requestError && <Alert severity="error" sx={{ mb: 2 }}>{requestError}</Alert>}
            {requestSuccess && <Alert severity="success" sx={{ mb: 2 }}>{requestSuccess}</Alert>}

            <Box display="flex" alignItems="center" justifyContent="space-between" gap={2} mb={2}>
                <Typography variant="h6" fontWeight={800}>Phân tích nội dung điều tra</Typography>
                <Chip label={`Case ${caseId}`} size="small" variant="outlined" />
            </Box>

            <Grid container spacing={1.25} sx={{ mb: 2 }}>
                {[
                    { label: 'File có Analysis', value: `${analyzedFileCount}/${files.length}`, icon: <AnalyticsIcon />, color: '#1565c0' },
                    { label: 'Người tham gia', value: participantCount, icon: <ParticipantIcon />, color: '#00796b' },
                    { label: 'Thực thể / giá trị', value: entityCount, icon: <HubIcon />, color: '#ef6c00' },
                    { label: 'Sự kiện / công việc', value: `${eventCount}/${actionCount}`, icon: <EventIcon />, color: '#ad1457' },
                ].map(stat => (
                    <Grid item xs={6} md={3} key={stat.label}>
                        <Paper sx={{ p: 1.5, height: '100%', borderRadius: 2.5, border: `1px solid ${stat.color}35` }}>
                            <Box display="flex" alignItems="center" gap={1} color={stat.color}>
                                {stat.icon}
                                <Typography variant="h6" fontWeight={800}>{stat.value}</Typography>
                            </Box>
                            <Typography variant="caption" color="text.secondary">{stat.label}</Typography>
                        </Paper>
                    </Grid>
                ))}
            </Grid>

            {analysisRows.map(row => {
                const preview = row.preview;
                const actionGroups = [
                    { title: 'Hành động', items: preview.actions },
                    { title: 'Quyết định', items: preview.decisions },
                    { title: 'Cam kết', items: preview.commitments },
                ].filter(group => group.items.length > 0);
                return (
                    <Accordion
                        key={row.file.task_id}
                        defaultExpanded={files.length === 1 || row.file.task_id === focusTaskId}
                        sx={{ mb: 1.25, borderRadius: '12px !important', '&:before': { display: 'none' } }}
                    >
                        <AccordionSummary
                            expandIcon={<ExpandMoreIcon />}
                            sx={{ '& .MuiAccordionSummary-content': { minWidth: 0 } }}
                        >
                            <Box
                                display="flex"
                                flexDirection={{ xs: 'column', sm: 'row' }}
                                alignItems={{ xs: 'flex-start', sm: 'center' }}
                                gap={1}
                                width="100%"
                                pr={1}
                                minWidth={0}
                            >
                                <Typography fontWeight={700} width={{ xs: '100%', sm: 'auto' }} minWidth={0} flex={1} noWrap>
                                    {row.file.filename}
                                </Typography>
                                <Chip
                                    label={preview.state_label}
                                    size="small"
                                    color={preview.state === 'failed' ? 'error' : preview.state === 'source_preview' ? 'warning' : 'default'}
                                    sx={{ maxWidth: '100%' }}
                                />
                            </Box>
                        </AccordionSummary>
                        <AccordionDetails>
                            {preview.state === 'failed' && (
                                <Alert severity="error" sx={{ mb: 2 }}>
                                    {preview.error_message || 'LLM chưa thể trả về kết quả Analysis sử dụng được.'}
                                </Alert>
                            )}
                            {preview.state === 'source_preview' && (
                                <Alert severity="warning" sx={{ mb: 2 }}>
                                    Kết quả do AI tạo từ nội dung hội thoại; điều tra viên cần đối chiếu transcript trước khi sử dụng nghiệp vụ.
                                </Alert>
                            )}
                            {!row.file.transcript && <Alert severity="info" sx={{ mb: 2 }}>Cần transcript trước khi chạy Analysis.</Alert>}
                            {row.file.transcript && (
                                <Button
                                    variant="outlined"
                                    size="small"
                                    startIcon={analyzingTaskId === row.file.task_id ? <CircularProgress size={16} /> : <RefreshIcon />}
                                    disabled={Boolean(analyzingTaskId)}
                                    onClick={() => runAnalysis(row.file)}
                                    sx={{ mb: 2, textTransform: 'none' }}
                                >
                                    {preview.state === 'missing' ? 'Chạy Analysis' : 'Phân tích lại'}
                                </Button>
                            )}

                            {preview.overview && (
                                <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'action.hover' }}>
                                    <Typography variant="subtitle1" fontWeight={800} mb={0.5}>Tổng quan</Typography>
                                    <Typography sx={{ whiteSpace: 'pre-wrap' }}>{preview.overview}</Typography>
                                </Paper>
                            )}
                            {preview.key_points.length > 0 && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800}>Điểm chính</Typography>
                                    <List dense disablePadding>
                                        {preview.key_points.map((point, index) => (
                                            <ListItem key={`${point}-${index}`}>
                                                <ListItemIcon sx={{ minWidth: 34 }}><Chip label={index + 1} size="small" /></ListItemIcon>
                                                <ListItemText primary={point} />
                                            </ListItem>
                                        ))}
                                    </List>
                                </Box>
                            )}
                            {preview.participants.length > 0 && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800} mb={1}>Người tham gia và vai trò</Typography>
                                    <Grid container spacing={1}>
                                        {preview.participants.map(item => (
                                            <Grid item xs={12} md={6} key={item.id}>
                                                <Paper variant="outlined" sx={{ p: 1.25, height: '100%' }}>
                                                    <Box display="flex" gap={0.75} alignItems="center" flexWrap="wrap">
                                                        <Chip icon={<PersonIcon />} label={item.name} size="small" />
                                                        {item.role && <Chip label={item.role} size="small" variant="outlined" />}
                                                    </Box>
                                                    {item.description && <Typography variant="body2" mt={0.75}>{item.description}</Typography>}
                                                </Paper>
                                            </Grid>
                                        ))}
                                    </Grid>
                                </Box>
                            )}
                            {(preview.entities.length > 0 || preview.exact_values.length > 0) && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800} mb={1}>Thực thể và giá trị chính xác</Typography>
                                    <Box display="flex" gap={0.75} flexWrap="wrap">
                                        {preview.entities.map(item => (
                                            <Chip key={item.id} label={`${item.value}${item.role ? ` - ${item.role}` : ''}`} variant="outlined" />
                                        ))}
                                        {preview.exact_values.map(item => (
                                            <Chip key={item.id} icon={<NumbersIcon />} label={item.value} color="warning" variant="outlined" />
                                        ))}
                                    </Box>
                                </Box>
                            )}
                            {preview.events.length > 0 && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800}>Timeline sự kiện</Typography>
                                    <List dense disablePadding>
                                        {preview.events.map(event => (
                                            <ListItem key={event.id} alignItems="flex-start">
                                                <ListItemIcon sx={{ minWidth: 36 }}><EventIcon color="action" /></ListItemIcon>
                                                <ListItemText
                                                    primary={event.description}
                                                    secondary={[
                                                        event.described_time && `Thời gian: ${event.described_time}`,
                                                        event.location && `Địa điểm: ${event.location}`,
                                                        event.actors.length > 0 && `Liên quan: ${event.actors.join(', ')}`,
                                                        event.status && `Trạng thái: ${event.status}`,
                                                    ].filter(Boolean).join(' • ')}
                                                />
                                            </ListItem>
                                        ))}
                                    </List>
                                </Box>
                            )}
                            {actionGroups.map(group => (
                                <Box mb={2} key={group.title}>
                                    <Typography variant="subtitle1" fontWeight={800}>{group.title}</Typography>
                                    <AnalysisItemList items={group.items} />
                                </Box>
                            ))}
                            {preview.relationships.length > 0 && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800}>Mối quan hệ được nêu</Typography>
                                    <List dense disablePadding>
                                        {preview.relationships.map(item => (
                                            <ListItem key={item.id}>
                                                <ListItemIcon sx={{ minWidth: 36 }}><RelationshipIcon color="action" /></ListItemIcon>
                                                <ListItemText primary={`${item.source} — ${item.label} — ${item.target}`} secondary={item.status} />
                                            </ListItem>
                                        ))}
                                    </List>
                                </Box>
                            )}
                            {preview.contradictions.length > 0 && (
                                <Alert severity="warning" icon={<ReportProblemIcon />} sx={{ mb: 2 }}>
                                    <Typography fontWeight={800}>Mâu thuẫn cần đối chiếu</Typography>
                                    {preview.contradictions.map(item => (
                                        <Box key={item.id} mt={0.5}>
                                            <Typography variant="body2">• {item.statement}</Typography>
                                            {item.details.map(detail => <Typography key={detail} variant="caption" display="block">— {detail}</Typography>)}
                                        </Box>
                                    ))}
                                </Alert>
                            )}
                            {preview.uncertainties.length > 0 && (
                                <Alert severity="info" icon={<QuestionIcon />} sx={{ mb: 2 }}>
                                    <Typography fontWeight={800}>Điểm chưa rõ</Typography>
                                    {preview.uncertainties.map(item => <Typography key={item.id} variant="body2">• {item.statement}</Typography>)}
                                </Alert>
                            )}
                            {preview.follow_ups.length > 0 && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800}>Câu hỏi và việc cần làm tiếp</Typography>
                                    <AnalysisItemList items={preview.follow_ups} />
                                </Box>
                            )}
                            {preview.gaps.length > 0 && (
                                <Alert severity="warning" sx={{ mb: 2 }}>
                                    <Typography fontWeight={800}>Khoảng trống cần kiểm tra</Typography>
                                    {preview.gaps.map(item => <Typography key={item} variant="body2">• {item}</Typography>)}
                                </Alert>
                            )}
                            {preview.analysis_text && (
                                <Box mb={2}>
                                    <Typography variant="subtitle1" fontWeight={800}>Nội dung phân tích</Typography>
                                    <Typography sx={{ whiteSpace: 'pre-wrap' }}>{preview.analysis_text}</Typography>
                                </Box>
                            )}
                            {preview.state !== 'failed'
                                && !preview.overview
                                && !preview.analysis_text
                                && preview.key_points.length === 0
                                && preview.participants.length === 0
                                && preview.entities.length === 0
                                && preview.events.length === 0
                                && preview.actions.length === 0
                                && preview.relationships.length === 0 && (
                                <Typography color="text.secondary">Chưa có nội dung Analysis để hiển thị.</Typography>
                            )}
                        </AccordionDetails>
                    </Accordion>
                );
            })}
        </Box>
    );
};

export default AnalysisPanel;
