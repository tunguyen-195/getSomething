import React, { useState, useMemo } from 'react';
import {
    Box,
    Typography,
    Paper,
    Chip,
    Grid,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Accordion,
    AccordionSummary,
    AccordionDetails,
    Avatar,
    IconButton,
    LinearProgress,
} from '@mui/material';
import {
    Timeline as TimelineIcon,
    Person as PersonIcon,
    Place as PlaceIcon,
    Event as EventIcon,
    Hub as HubIcon,
    ExpandMore as ExpandMoreIcon,
    ContentCopy as ContentCopyIcon,
    Analytics as AnalyticsIcon,
    Description as SummaryIcon,
    Phone as PhoneIcon,
    Email as EmailIcon,
    Home as AddressIcon,
    AttachMoney as MoneyIcon,
    CalendarMonth as DateIcon,
    RecordVoiceOver as SpeakerIcon,
    Category as TopicIcon,
} from '@mui/icons-material';
import {
    ReleasedVisualizationArtifact,
    validateReleasedVisualizationArtifact,
} from '../utils/investigationProjection';

interface FileWithData {
    task_id: string;
    filename: string;
    summary?: string;
    status: string;
    num_speakers?: number;
    has_visualization?: boolean;
    visualization_data?: unknown;
    segments?: Array<{ speaker?: string; text: string }>;
}

interface AnalysisPanelProps {
    files: FileWithData[];
    caseId: string;
    mode?: 'light' | 'dark';
}

type FileWithReleasedVisualization = FileWithData & {
    visualization_data: ReleasedVisualizationArtifact;
};

// Extract key information from summary text
const extractKeyInfo = (summary: string) => {
    const info: { type: string; value: string; icon: React.ReactNode; color: string; context?: string }[] = [];

    // Phone numbers (Vietnamese format)
    const phones = summary.match(/(?:0\d{9,10}|\+84\d{9,10}|0\d{2,3}[\s.-]\d{3}[\s.-]\d{4})/g) || [];
    phones.forEach(p => info.push({ type: 'phone', value: p, icon: <PhoneIcon />, color: '#2196f3' }));

    // Emails
    const emails = summary.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) || [];
    emails.forEach(e => info.push({ type: 'email', value: e, icon: <EmailIcon />, color: '#4caf50' }));

    // Money (Vietnamese format)
    const money = summary.match(/(?:\d{1,3}(?:[.,]\d{3})*(?:\s*(?:đồng|vnđ|VNĐ|triệu|tr|nghìn|ngàn|k))?|\d+\s*(?:triệu|tr|nghìn|ngàn|k))/gi) || [];
    money.forEach(m => info.push({ type: 'money', value: m, icon: <MoneyIcon />, color: '#ff9800' }));

    // Dates (common Vietnamese formats)
    const dates = summary.match(/(?:\d{1,2}[\/\-]\d{1,2}(?:[\/\-]\d{2,4})?)/g) || [];
    dates.forEach(d => info.push({ type: 'date', value: d, icon: <DateIcon />, color: '#9c27b0' }));

    return info;
};

// Calculate speaker statistics
const calculateSpeakerStats = (files: FileWithData[]) => {
    const stats: { [key: string]: number } = {};
    let total = 0;

    files.forEach(f => {
        if (f.segments) {
            f.segments.forEach(seg => {
                const speaker = seg.speaker || 'Unknown';
                const wordCount = seg.text?.split(/\s+/).length || 0;
                stats[speaker] = (stats[speaker] || 0) + wordCount;
                total += wordCount;
            });
        } else if (f.num_speakers) {
            // Fallback: estimate from num_speakers
            for (let i = 1; i <= f.num_speakers; i++) {
                const speaker = `Speaker ${i}`;
                stats[speaker] = (stats[speaker] || 0) + Math.floor(100 / f.num_speakers);
            }
            total = 100;
        }
    });

    return Object.entries(stats).map(([speaker, count]) => ({
        speaker,
        count,
        percentage: total > 0 ? Math.round((count / total) * 100) : 0,
    })).sort((a, b) => b.percentage - a.percentage);
};

const AnalysisPanel: React.FC<AnalysisPanelProps> = ({ files, caseId }) => {
    const [copiedId, setCopiedId] = useState<string | null>(null);

    const filesWithData = useMemo<FileWithReleasedVisualization[]>(() => (
        files.flatMap(file => {
            if (!file.has_visualization) return [];
            const validation = validateReleasedVisualizationArtifact(file.visualization_data);
            return validation.ok
                ? [{ ...file, visualization_data: validation.value }]
                : [];
        })
    ), [files]);

    // Aggregate stats
    const stats = useMemo(() => {
        let people = new Set<string>();
        let places = new Set<string>();
        let phones = new Set<string>();
        let events: string[] = [];
        let timeline: Array<{ time?: string; event: string; file: string }> = [];
        let allKeyInfo: { type: string; value: string; icon: React.ReactNode; color: string; context?: string }[] = [];

        filesWithData.forEach(f => {
            if (f.visualization_data) {
                f.visualization_data.nodes.forEach(n => {
                    if (n.type?.toLowerCase() === 'person') people.add(n.label);
                    if (['place', 'location'].includes(n.type?.toLowerCase() || '')) places.add(n.label);
                    if (n.type?.toLowerCase() === 'phone') phones.add(n.label);
                });
                f.visualization_data.main_events.forEach(e => events.push(e.event));
                f.visualization_data.timeline.forEach(t => timeline.push({ ...t, file: f.filename }));

                if (f.visualization_data.extracted_entities.length > 0) {
                    f.visualization_data.extracted_entities.forEach(e => {
                        let icon = <TopicIcon />;
                        let color = '#757575';

                        switch (e.type.toLowerCase()) {
                            case 'phone': icon = <PhoneIcon />; color = '#2196f3'; break;
                            case 'email': icon = <EmailIcon />; color = '#4caf50'; break;
                            case 'money': icon = <MoneyIcon />; color = '#ff9800'; break;
                            case 'date': icon = <DateIcon />; color = '#9c27b0'; break;
                        }

                        allKeyInfo.push({
                            type: e.type,
                            value: e.value,
                            icon,
                            color,
                            context: e.context // Add context if available
                        });
                    });
                }
            }

        });

        // Dedupe key info
        const uniqueKeyInfo = allKeyInfo.filter((item, idx, arr) =>
            arr.findIndex(i => i.value === item.value) === idx
        );

        return {
            peopleCount: people.size,
            placesCount: places.size,
            eventsCount: events.length,
            timelineCount: timeline.length,
            people: Array.from(people),
            places: Array.from(places),
            phones: Array.from(phones),
            events,
            timeline,
            keyInfo: uniqueKeyInfo,
        };
    }, [filesWithData]);

    const speakerStats = useMemo(() => calculateSpeakerStats(files), [files]);

    const handleCopy = (id: string, text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedId(id);
        setTimeout(() => setCopiedId(null), 2000);
    };

    if (files.length === 0) {
        return (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '12px' }}>
                <AnalyticsIcon sx={{ fontSize: 48, color: '#bdbdbd', mb: 2 }} />
                <Typography color="text.secondary">Chưa có files để phân tích</Typography>
            </Paper>
        );
    }

    if (filesWithData.length === 0) {
        return (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '12px' }}>
                <AnalyticsIcon sx={{ fontSize: 48, color: '#9c27b0', mb: 2 }} />
                <Typography color="text.secondary">
                    Chưa có released analysis artifact đủ bằng chứng để hiển thị.
                </Typography>
            </Paper>
        );
    }

    return (
        <Box>
            {/* Quick Stats Row */}
            <Grid container spacing={1} sx={{ mb: 2 }}>
                {[
                    { icon: <PersonIcon />, label: 'Người', value: stats.peopleCount, color: '#1976d2' },
                    { icon: <PlaceIcon />, label: 'Địa điểm', value: stats.placesCount, color: '#43a047' },
                    { icon: <EventIcon />, label: 'Sự kiện', value: stats.eventsCount, color: '#ff9800' },
                    { icon: <TimelineIcon />, label: 'Timeline', value: stats.timelineCount, color: '#9c27b0' },
                ].map((stat, i) => (
                    <Grid item xs={3} key={i}>
                        <Paper sx={{ p: 1, textAlign: 'center', borderRadius: '8px', border: `1px solid ${stat.color}30` }}>
                            <Avatar sx={{ bgcolor: `${stat.color}15`, color: stat.color, mx: 'auto', width: 32, height: 32, mb: 0.5 }}>
                                {stat.icon}
                            </Avatar>
                            <Typography variant="h6" fontWeight={700} color={stat.color}>{stat.value}</Typography>
                            <Typography variant="caption" color="text.secondary">{stat.label}</Typography>
                        </Paper>
                    </Grid>
                ))}
            </Grid>

            {/* Key Information Cards - NEW */}
            {stats.keyInfo.length > 0 && (
                <Accordion defaultExpanded sx={{ mb: 1, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(33, 150, 243, 0.05)' }}>
                        <Box display="flex" alignItems="center" gap={1}>
                            <PhoneIcon sx={{ color: '#2196f3' }} />
                            <Typography fontWeight={600}>Thông tin quan trọng</Typography>
                            <Chip label={stats.keyInfo.length} size="small" color="info" />
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                        <Grid container spacing={1}>
                            {stats.keyInfo.map((info, idx) => (
                                <Grid item xs={6} sm={4} md={3} key={idx}>
                                    <Paper
                                        sx={{
                                            p: 1.5,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 1,
                                            borderRadius: '8px',
                                            border: `1px solid ${info.color}30`,
                                            cursor: 'pointer',
                                            '&:hover': { bgcolor: `${info.color}08` },
                                        }}
                                        onClick={() => handleCopy(`info-${idx}`, info.value)}
                                    >
                                        <Avatar sx={{ bgcolor: `${info.color}15`, color: info.color, width: 28, height: 28 }}>
                                            {info.icon}
                                        </Avatar>
                                        <Box flex={1} overflow="hidden">
                                            <Typography variant="body2" fontWeight={600} noWrap>{info.value}</Typography>
                                            <Typography variant="caption" color="text.secondary" textTransform="capitalize">
                                                {/* @ts-ignore */}
                                                {info.context || info.type}
                                            </Typography>
                                        </Box>
                                    </Paper>
                                </Grid>
                            ))}
                        </Grid>
                    </AccordionDetails>
                </Accordion>
            )}

            {/* Speaker stats REMOVED - now in dedicated Diarization tab */}

            {/* Summary section REMOVED - now in dedicated Summary tab */}

            {/* Entities Section */}
            {stats.people.length > 0 || stats.places.length > 0 ? (
                <Accordion sx={{ mb: 1, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(33, 150, 243, 0.05)' }}>
                        <Box display="flex" alignItems="center" gap={1}>
                            <HubIcon sx={{ color: '#2196f3' }} />
                            <Typography fontWeight={600}>Thực thể</Typography>
                            <Chip label={stats.peopleCount + stats.placesCount} size="small" />
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                        <Grid container spacing={2}>
                            {stats.people.length > 0 && (
                                <Grid item xs={12} md={6}>
                                    <Typography variant="subtitle2" fontWeight={600} mb={1}>👤 Người ({stats.peopleCount})</Typography>
                                    <Box display="flex" flexWrap="wrap" gap={0.5}>
                                        {stats.people.map((p, i) => <Chip key={i} label={p} size="small" sx={{ bgcolor: '#e3f2fd' }} />)}
                                    </Box>
                                </Grid>
                            )}
                            {stats.places.length > 0 && (
                                <Grid item xs={12} md={6}>
                                    <Typography variant="subtitle2" fontWeight={600} mb={1}>📍 Địa điểm ({stats.placesCount})</Typography>
                                    <Box display="flex" flexWrap="wrap" gap={0.5}>
                                        {stats.places.map((p, i) => <Chip key={i} label={p} size="small" sx={{ bgcolor: '#e8f5e9' }} />)}
                                    </Box>
                                </Grid>
                            )}
                        </Grid>
                    </AccordionDetails>
                </Accordion>
            ) : null}

            {/* Events Section */}
            {stats.events.length > 0 && (
                <Accordion sx={{ mb: 1, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(255, 152, 0, 0.05)' }}>
                        <Box display="flex" alignItems="center" gap={1}>
                            <EventIcon sx={{ color: '#ff9800' }} />
                            <Typography fontWeight={600}>Sự kiện chính</Typography>
                            <Chip label={stats.eventsCount} size="small" />
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                        <List dense disablePadding>
                            {stats.events.slice(0, 10).map((event, idx) => (
                                <ListItem key={idx} sx={{ py: 0.5 }}>
                                    <ListItemIcon sx={{ minWidth: 28 }}>
                                        <Chip label={idx + 1} size="small" sx={{ width: 22, height: 22, fontSize: '0.7rem' }} />
                                    </ListItemIcon>
                                    <ListItemText primary={event} primaryTypographyProps={{ fontSize: '0.85rem' }} />
                                </ListItem>
                            ))}
                        </List>
                    </AccordionDetails>
                </Accordion>
            )}

            {/* Timeline Section */}
            {stats.timeline.length > 0 && (
                <Accordion sx={{ borderRadius: '12px !important', '&:before': { display: 'none' } }}>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(156, 39, 176, 0.05)' }}>
                        <Box display="flex" alignItems="center" gap={1}>
                            <TimelineIcon sx={{ color: '#9c27b0' }} />
                            <Typography fontWeight={600}>Timeline</Typography>
                            <Chip label={stats.timelineCount} size="small" />
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                        <Box sx={{ position: 'relative', pl: 3, maxHeight: 300, overflow: 'auto' }}>
                            <Box sx={{ position: 'absolute', left: 8, top: 0, bottom: 0, width: 2, bgcolor: '#9c27b0' }} />
                            {stats.timeline.slice(0, 15).map((item, idx) => (
                                <Box key={idx} sx={{ display: 'flex', mb: 1, position: 'relative' }}>
                                    <Box sx={{ position: 'absolute', left: -19, width: 10, height: 10, borderRadius: '50%', bgcolor: '#9c27b0' }} />
                                    <Paper sx={{ p: 1, ml: 1, flex: 1, bgcolor: 'rgba(156, 39, 176, 0.03)', borderRadius: '6px' }}>
                                        {item.time && <Chip label={item.time} size="small" sx={{ mb: 0.5, bgcolor: '#9c27b0', color: '#fff', height: 18, fontSize: '0.65rem' }} />}
                                        <Typography variant="body2" fontSize="0.85rem">{item.event}</Typography>
                                    </Paper>
                                </Box>
                            ))}
                        </Box>
                    </AccordionDetails>
                </Accordion>
            )}
        </Box>
    );
};

export default AnalysisPanel;
