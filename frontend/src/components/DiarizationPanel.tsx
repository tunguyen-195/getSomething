import React from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Avatar,
    Box,
    Chip,
    LinearProgress,
    Paper,
    Typography,
} from '@mui/material';
import {
    AudioFile as AudioFileIcon,
    ExpandMore as ExpandMoreIcon,
    GraphicEq as AudioIcon,
    Person as PersonIcon,
    Timeline as TimelineIcon,
} from '@mui/icons-material';

export interface DiarizationSegment {
    start: number;
    end: number;
    text: string;
    speaker: string;
}

export interface DiarizationFileGroup {
    task_id: string;
    filename: string;
    duration?: number;
    segments?: Array<Partial<DiarizationSegment> & {
        start_time?: number;
        end_time?: number;
        speaker?: string | null;
        text?: string | null;
    }>;
}

interface DiarizationPanelProps {
    /** Legacy single-conversation input. Prefer `fileGroups` for a case. */
    segments?: Array<Partial<DiarizationSegment> & {
        start_time?: number;
        end_time?: number;
        speaker?: string | null;
        text?: string | null;
    }>;
    duration?: number;
    /** Explicit file boundaries. Segments are never merged across groups. */
    fileGroups?: DiarizationFileGroup[];
}

const SPEAKER_COLORS = ['#e11d48', '#2563eb', '#16a34a', '#9333ea', '#ea580c', '#0891b2'];

const getSpeakerColor = (speaker: string): string => {
    const match = speaker.match(/(\d+)/);
    const idx = match ? parseInt(match[1], 10) : 0;
    return SPEAKER_COLORS[idx % SPEAKER_COLORS.length];
};

const formatTime = (seconds: number): string => {
    const safeSeconds = Number.isFinite(seconds) && seconds >= 0 ? seconds : 0;
    const mins = Math.floor(safeSeconds / 60);
    const secs = Math.floor(safeSeconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
};

function normalizeSegments(
    segments: DiarizationPanelProps['segments'] | DiarizationFileGroup['segments'],
): DiarizationSegment[] {
    if (!Array.isArray(segments)) return [];
    return segments
        .map(segment => {
            const start = typeof segment.start === 'number'
                ? segment.start
                : typeof segment.start_time === 'number' ? segment.start_time : NaN;
            const end = typeof segment.end === 'number'
                ? segment.end
                : typeof segment.end_time === 'number' ? segment.end_time : NaN;
            const text = typeof segment.text === 'string' ? segment.text.trim() : '';
            if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start || !text) return null;
            return {
                start,
                end,
                text,
                speaker: typeof segment.speaker === 'string' && segment.speaker.trim()
                    ? segment.speaker.trim()
                    : 'SPEAKER_00',
            };
        })
        .filter((segment): segment is DiarizationSegment => segment !== null)
        .sort((left, right) => left.start - right.start);
}

interface PreparedFileGroup {
    task_id: string;
    filename: string;
    duration: number;
    segments: DiarizationSegment[];
}

function prepareFileGroups(props: DiarizationPanelProps): PreparedFileGroup[] {
    if (Array.isArray(props.fileGroups)) {
        return props.fileGroups.map((group, index) => {
            const segments = normalizeSegments(group.segments);
            const maxEnd = segments.reduce((max, segment) => Math.max(max, segment.end), 0);
            const duration = typeof group.duration === 'number' && group.duration > 0
                ? group.duration
                : maxEnd;
            return {
                task_id: group.task_id || `file-${index}`,
                filename: group.filename || `File ${index + 1}`,
                duration,
                segments,
            };
        });
    }
    const segments = normalizeSegments(props.segments);
    if (segments.length === 0) return [];
    const maxEnd = segments.reduce((max, segment) => Math.max(max, segment.end), 0);
    return [{
        task_id: 'legacy-conversation',
        filename: 'Hội thoại',
        duration: typeof props.duration === 'number' && props.duration > 0 ? props.duration : maxEnd,
        segments,
    }];
}

function FileDiarizationView({ group }: { group: PreparedFileGroup }) {
    const speakerStats = React.useMemo(() => {
        const stats: Record<string, { totalTime: number; segments: number }> = {};
        group.segments.forEach(segment => {
            const current = stats[segment.speaker] ?? { totalTime: 0, segments: 0 };
            current.totalTime += Math.max(0, segment.end - segment.start);
            current.segments += 1;
            stats[segment.speaker] = current;
        });
        const denominator = group.duration > 0
            ? group.duration
            : Math.max(...group.segments.map(segment => segment.end), 0);
        return Object.entries(stats)
            .map(([speaker, data]) => ({
                speaker,
                totalTime: data.totalTime,
                segments: data.segments,
                percentage: denominator > 0 ? Math.min(100, (data.totalTime / denominator) * 100) : 0,
            }))
            .sort((left, right) => right.totalTime - left.totalTime);
    }, [group]);

    const groupedSegments = React.useMemo(() => {
        const groups: Array<{ speaker: string; start: number; end: number; texts: string[] }> = [];
        group.segments.forEach(segment => {
            const current = groups[groups.length - 1];
            if (current && current.speaker === segment.speaker && segment.start - current.end < 2) {
                current.end = Math.max(current.end, segment.end);
                current.texts.push(segment.text);
            } else {
                groups.push({ speaker: segment.speaker, start: segment.start, end: segment.end, texts: [segment.text] });
            }
        });
        return groups;
    }, [group.segments]);

    if (group.segments.length === 0) {
        return (
            <Box data-testid={`diarization-file-${group.task_id}`} sx={{ py: 1 }}>
                <Typography variant="body2" color="text.secondary">
                    Chưa có dữ liệu diarization cho file này.
                </Typography>
            </Box>
        );
    }

    return (
        <Box data-testid={`diarization-file-${group.task_id}`}>
            <Box display="flex" alignItems="center" gap={1} mb={1.5}>
                <TimelineIcon color="secondary" />
                <Typography variant="subtitle1" fontWeight={700}>Chi tiết hội thoại</Typography>
                <Chip size="small" label={`${group.segments.length} đoạn`} variant="outlined" />
                {group.duration > 0 && <Chip size="small" label={formatTime(group.duration)} variant="outlined" />}
            </Box>
            {speakerStats.length > 0 && (
                <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
                    <Box display="flex" alignItems="center" gap={1} mb={1.5}>
                        <PersonIcon color="primary" />
                        <Typography fontWeight={600}>Thống kê người nói</Typography>
                        <Chip label={`${speakerStats.length} speakers`} size="small" color="primary" variant="outlined" />
                    </Box>
                    <Box display="flex" flexDirection="column" gap={1.5}>
                        {speakerStats.map(stat => (
                            <Box key={stat.speaker}>
                                <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={0.5} flexWrap="wrap">
                                    <Box display="flex" alignItems="center" gap={1}>
                                        <Avatar sx={{ width: 28, height: 28, bgcolor: getSpeakerColor(stat.speaker), fontSize: 12 }}>
                                            {stat.speaker.replace(/\D/g, '') || '?'}
                                        </Avatar>
                                        <Typography fontWeight={500}>{stat.speaker}</Typography>
                                    </Box>
                                    <Box display="flex" alignItems="center" gap={1}>
                                        <Chip label={`${stat.percentage.toFixed(1)}%`} size="small" sx={{ bgcolor: getSpeakerColor(stat.speaker), color: '#fff' }} />
                                        <Typography variant="body2" color="text.secondary">
                                            {formatTime(stat.totalTime)} ({stat.segments} đoạn)
                                        </Typography>
                                    </Box>
                                </Box>
                                <LinearProgress variant="determinate" value={stat.percentage} sx={{ height: 8, borderRadius: 4, '& .MuiLinearProgress-bar': { bgcolor: getSpeakerColor(stat.speaker), borderRadius: 4 } }} />
                            </Box>
                        ))}
                    </Box>
                </Paper>
            )}
            <Box display="flex" flexDirection="column" gap={1.5}>
                {groupedSegments.map((segment, index) => {
                    const color = getSpeakerColor(segment.speaker);
                    return (
                        <Box key={`${segment.start}-${segment.end}-${index}`}>
                            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                                <Chip label={segment.speaker} size="small" sx={{ bgcolor: color, color: '#fff', height: 24 }} />
                                <Typography variant="caption" color="text.secondary">
                                    {formatTime(segment.start)} - {formatTime(segment.end)}
                                </Typography>
                            </Box>
                            <Paper variant="outlined" sx={{ p: 1.5, bgcolor: 'action.hover', overflowWrap: 'anywhere' }}>
                                <Typography sx={{ lineHeight: 1.6 }}>{segment.texts.join(' ')}</Typography>
                            </Paper>
                        </Box>
                    );
                })}
            </Box>
        </Box>
    );
}

const DiarizationPanel: React.FC<DiarizationPanelProps> = (props) => {
    const groups = React.useMemo(() => prepareFileGroups(props), [props.fileGroups, props.segments, props.duration]);
    if (groups.length === 0 || groups.every(group => group.segments.length === 0)) {
        return (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '8px' }}>
                <AudioIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
                <Typography color="text.secondary">
                    Chưa có dữ liệu diarization. Hãy chạy Transcribe với diarization enabled.
                </Typography>
            </Paper>
        );
    }
    return (
        <Box data-testid="diarization-case" aria-label="Diarization theo từng file">
            {groups.map((group, index) => (
                <Accordion key={group.task_id} defaultExpanded={index === 0} sx={{ mb: 1.5, borderRadius: '8px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Box display="flex" alignItems="center" gap={1} minWidth={0} width="100%">
                            <AudioFileIcon color="primary" fontSize="small" />
                            <Typography fontWeight={700} sx={{ overflowWrap: 'anywhere' }} flex={1}>{group.filename}</Typography>
                            <Chip size="small" label={group.segments.length > 0 ? `${group.segments.length} đoạn` : 'Chưa có dữ liệu'} color={group.segments.length > 0 ? 'default' : 'warning'} />
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails sx={{ pt: 1 }}>
                        <FileDiarizationView group={group} />
                    </AccordionDetails>
                </Accordion>
            ))}
        </Box>
    );
};

export default DiarizationPanel;
