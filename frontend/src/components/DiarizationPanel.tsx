import React from 'react';
import {
    Box,
    Paper,
    Typography,
    Accordion,
    AccordionSummary,
    AccordionDetails,
    Chip,
    LinearProgress,
    Avatar,
} from '@mui/material';
import {
    ExpandMore as ExpandMoreIcon,
    Person as PersonIcon,
    Timeline as TimelineIcon,
    GraphicEq as AudioIcon,
} from '@mui/icons-material';

interface Segment {
    start: number;
    end: number;
    text: string;
    speaker: string;
}

interface DiarizationPanelProps {
    segments: Segment[];
    duration: number;
}

// Speaker colors for visualization
const SPEAKER_COLORS = [
    '#e11d48', // Red
    '#2563eb', // Blue
    '#16a34a', // Green
    '#9333ea', // Purple
    '#ea580c', // Orange
    '#0891b2', // Cyan
];

const getSpeakerColor = (speaker: string): string => {
    // Extract number from speaker label (e.g., "SPEAKER_00" -> 0)
    const match = speaker.match(/(\d+)/);
    const idx = match ? parseInt(match[1], 10) : 0;
    return SPEAKER_COLORS[idx % SPEAKER_COLORS.length];
};

const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
};

const DiarizationPanel: React.FC<DiarizationPanelProps> = ({ segments, duration }) => {
    // Calculate speaker statistics
    const speakerStats = React.useMemo(() => {
        const stats: Record<string, { totalTime: number; segments: number }> = {};

        segments.forEach((seg) => {
            const speaker = seg.speaker || 'SPEAKER_00';
            if (!stats[speaker]) {
                stats[speaker] = { totalTime: 0, segments: 0 };
            }
            stats[speaker].totalTime += seg.end - seg.start;
            stats[speaker].segments += 1;
        });

        return Object.entries(stats).map(([speaker, data]) => ({
            speaker,
            totalTime: data.totalTime,
            segments: data.segments,
            percentage: duration > 0 ? (data.totalTime / duration) * 100 : 0,
        })).sort((a, b) => b.totalTime - a.totalTime);
    }, [segments, duration]);

    // Group consecutive segments by speaker for timeline
    const groupedSegments = React.useMemo(() => {
        const groups: { speaker: string; start: number; end: number; texts: string[] }[] = [];
        let current: typeof groups[0] | null = null;

        segments.forEach((seg) => {
            const speaker = seg.speaker || 'SPEAKER_00';
            if (current && current.speaker === speaker && seg.start - current.end < 2) {
                current.end = seg.end;
                current.texts.push(seg.text);
            } else {
                if (current) groups.push(current);
                current = { speaker, start: seg.start, end: seg.end, texts: [seg.text] };
            }
        });
        if (current) groups.push(current);

        return groups;
    }, [segments]);

    if (!segments || segments.length === 0) {
        return (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
                <AudioIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
                <Typography color="text.secondary">
                    Chưa có dữ liệu diarization. Hãy chạy Transcribe với diarization enabled.
                </Typography>
            </Paper>
        );
    }

    return (
        <Box>
            {/* Speaker Statistics */}
            <Accordion defaultExpanded sx={{ mb: 2, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box display="flex" alignItems="center" gap={1}>
                        <PersonIcon color="primary" />
                        <Typography fontWeight={600}>Thống kê người nói</Typography>
                        <Chip label={`${speakerStats.length} speakers`} size="small" color="primary" variant="outlined" sx={{ ml: 1 }} />
                    </Box>
                </AccordionSummary>
                <AccordionDetails>
                    <Box display="flex" flexDirection="column" gap={2}>
                        {speakerStats.map((stat) => (
                            <Box key={stat.speaker}>
                                <Box display="flex" justifyContent="space-between" alignItems="center" mb={0.5}>
                                    <Box display="flex" alignItems="center" gap={1}>
                                        <Avatar sx={{ width: 28, height: 28, bgcolor: getSpeakerColor(stat.speaker), fontSize: 12 }}>
                                            {stat.speaker.replace(/\D/g, '')}
                                        </Avatar>
                                        <Typography fontWeight={500}>{stat.speaker}</Typography>
                                    </Box>
                                    <Box display="flex" alignItems="center" gap={1}>
                                        <Chip
                                            label={`${stat.percentage.toFixed(1)}%`}
                                            size="small"
                                            sx={{ bgcolor: getSpeakerColor(stat.speaker), color: '#fff' }}
                                        />
                                        <Typography variant="body2" color="text.secondary">
                                            {formatTime(stat.totalTime)} ({stat.segments} segments)
                                        </Typography>
                                    </Box>
                                </Box>
                                <LinearProgress
                                    variant="determinate"
                                    value={stat.percentage}
                                    sx={{
                                        height: 8,
                                        borderRadius: 4,
                                        bgcolor: 'rgba(0,0,0,0.08)',
                                        '& .MuiLinearProgress-bar': {
                                            bgcolor: getSpeakerColor(stat.speaker),
                                            borderRadius: 4,
                                        },
                                    }}
                                />
                            </Box>
                        ))}
                    </Box>
                </AccordionDetails>
            </Accordion>

            {/* Conversation Chat View */}
            <Paper elevation={0} sx={{ p: 0, bgcolor: 'transparent' }}>
                <Box display="flex" alignItems="center" gap={1} mb={2}>
                    <TimelineIcon color="secondary" />
                    <Typography variant="h6" fontWeight={600}>Chi tiết hội thoại</Typography>
                </Box>

                <Box display="flex" flexDirection="column" gap={2}>
                    {groupedSegments.map((group, idx) => {
                        const isSpeaker0 = group.speaker === 'SPEAKER_00';
                        const color = getSpeakerColor(group.speaker);

                        return (
                            <Box key={idx} display="flex" flexDirection="column" alignItems="flex-start">
                                {/* Speaker Info */}
                                <Box display="flex" alignItems="center" gap={1} mb={0.5} ml={1}>
                                    <Chip
                                        label={group.speaker}
                                        size="small"
                                        sx={{
                                            bgcolor: color,
                                            color: '#fff',
                                            fontSize: '0.75rem',
                                            height: 24
                                        }}
                                    />
                                    <Typography variant="caption" color="text.secondary">
                                        {formatTime(group.start)} - {formatTime(group.end)}
                                    </Typography>
                                </Box>

                                {/* Chat Bubble */}
                                <Paper
                                    elevation={1}
                                    sx={{
                                        p: 2,
                                        borderRadius: '4px 16px 16px 16px',
                                        bgcolor: isSpeaker0 ? '#e3f2fd' : '#f5f5f5',
                                        border: '1px solid',
                                        borderColor: isSpeaker0 ? '#bbdefb' : '#e0e0e0',
                                        maxWidth: '100%',
                                        width: '100%'
                                    }}
                                >
                                    <Typography variant="body1" sx={{ lineHeight: 1.6 }}>
                                        {group.texts.join(' ')}
                                    </Typography>
                                </Paper>
                            </Box>
                        );
                    })}
                </Box>
            </Paper>
        </Box>
    );
};

export default DiarizationPanel;
