import React, { useEffect, useMemo, useState } from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Avatar,
    Box,
    Chip,
    Divider,
    Grid,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Paper,
    Tab,
    Tabs,
    Typography,
} from '@mui/material';
import {
    AttachMoney as MoneyIcon,
    CalendarMonth as DateIcon,
    Category as TopicIcon,
    Email as EmailIcon,
    Event as EventIcon,
    ExpandMore as ExpandMoreIcon,
    Hub as HubIcon,
    Person as PersonIcon,
    Phone as PhoneIcon,
    Place as PlaceIcon,
    Timeline as TimelineIcon,
    Analytics as AnalyticsIcon,
} from '@mui/icons-material';
import VisualizationPanel from './VisualizationPanel';
import {
    AnalysisGraphV2,
    EvidenceItem,
    EvidenceRef,
    LegacyVisualizationData,
    getCanonicalAnalysisGraph,
    getKeyEntities,
    getLegacyVisualizationData,
    stringifyAnalysisValue,
} from '../utils/visualization';
import HallucinationAnalysisView from './HallucinationAnalysisView';

type AnalysisView = 'overview' | 'visualization' | 'evidence' | 'hallucination';

interface FileWithData {
    task_id: string;
    filename: string;
    summary?: string;
    status: string;
    num_speakers?: number;
    has_visualization?: boolean;
    visualization_data?: AnalysisGraphV2 | LegacyVisualizationData | null;
    segments?: Array<{ speaker?: string; text: string }>;
}

interface AnalysisPanelProps {
    files: FileWithData[];
    caseId: string;
    mode?: 'light' | 'dark';
    focusTaskId?: string | null;
    activeView?: AnalysisView;
    onActiveViewChange?: (view: AnalysisView) => void;
}

type KeyInfo = {
    type: string;
    value: string;
    icon: React.ReactNode;
    color: string;
    context?: string;
};

const iconForKeyType = (type: string): React.ReactNode => {
    switch (type.toLowerCase()) {
        case 'phone': return <PhoneIcon />;
        case 'email': return <EmailIcon />;
        case 'person':
        case 'person_name': return <PersonIcon />;
        case 'organization': return <TopicIcon />;
        case 'location':
        case 'address': return <PlaceIcon />;
        case 'money': return <MoneyIcon />;
        case 'date':
        case 'date_time':
        case 'time': return <DateIcon />;
        default: return <TopicIcon />;
    }
};

const colorForKeyType = (type: string): string => {
    switch (type.toLowerCase()) {
        case 'phone': return '#2196f3';
        case 'email': return '#4caf50';
        case 'person':
        case 'person_name': return '#1976d2';
        case 'organization': return '#607d8b';
        case 'location':
        case 'address': return '#2e7d32';
        case 'money': return '#ff9800';
        case 'date':
        case 'date_time':
        case 'time': return '#9c27b0';
        default: return '#757575';
    }
};

const confidenceLabel = (confidence?: number): string => (
    typeof confidence === 'number' ? `${Math.round(confidence * 100)}%` : 'n/a'
);

const formatTime = (value?: number | null): string | null => (
    typeof value === 'number' ? `${value.toFixed(2)}s` : null
);

const formatEvidenceTime = (ref: EvidenceRef): string => {
    const start = formatTime(ref.start_time);
    const end = formatTime(ref.end_time);
    if (start && end) return `${start} - ${end}`;
    if (start) return start;
    return 'Không có timestamp';
};

const formatSemanticTimelineTime = (semanticTime?: any): string | undefined => {
    if (!semanticTime || typeof semanticTime !== 'object') return undefined;
    if (semanticTime.kind === 'compound' && Array.isArray(semanticTime.items)) {
        const labels = semanticTime.items
            .map((item: any) => formatSemanticTimelineTime(item))
            .filter(Boolean);
        const unique = Array.from(new Set(labels));
        if (unique.length > 0) return unique.join(', ');
    }
    if (semanticTime.kind === 'date_range') {
        const start = stringifyAnalysisValue(semanticTime.start);
        const end = stringifyAnalysisValue(semanticTime.end);
        if (start && end) return `${start} - ${end}`;
    }
    if (semanticTime.kind === 'date') {
        const value = stringifyAnalysisValue(semanticTime.value);
        if (value) return value;
    }
    if (semanticTime.kind === 'time' && semanticTime.value) {
        return String(semanticTime.value);
    }
    return undefined;
};

const formatTimelineTime = (item: Record<string, any>): string | undefined => {
    const semantic = formatSemanticTimelineTime(item.semantic_time);
    if (semantic) return semantic;
    return item.time !== undefined ? String(item.time) : undefined;
};

const reviewColor = (status?: string): 'default' | 'success' | 'warning' | 'error' | 'info' => {
    switch (status) {
        case 'confirmed': return 'success';
        case 'rejected': return 'error';
        case 'needs_review': return 'warning';
        case 'machine_suggested': return 'info';
        default: return 'default';
    }
};

const isEffectivelyVisibleEvidenceItem = (item: EvidenceItem, graph?: AnalysisGraphV2 | null): boolean => {
    if (item.review_status === 'rejected') return false;
    const blockedIds = graph?.visibility?.blocked_item_ids || [];
    return !blockedIds.includes(item.id);
};

const isPlaceKeyInfo = (item: { type: string; value: string; context?: string }): boolean => {
    const type = item.type.toLowerCase();
    if (['place', 'location', 'address'].includes(type)) return true;
    if (type !== 'organization') return false;
    const text = `${item.value} ${item.context || ''}`.toLowerCase();
    return /khách\s*sạn|hotel|bệnh\s*viện|trường|venue|địa điểm/.test(text);
};

const EmptyState: React.FC<{ message: string }> = ({ message }) => (
    <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '12px' }}>
        <AnalyticsIcon sx={{ fontSize: 48, color: '#bdbdbd', mb: 2 }} />
        <Typography color="text.secondary">{message}</Typography>
    </Paper>
);

const EvidenceRefs: React.FC<{ refs?: EvidenceRef[] }> = ({ refs = [] }) => {
    if (refs.length === 0) {
        return <Typography variant="body2" color="text.secondary">Chưa có evidence refs.</Typography>;
    }

    return (
        <List dense disablePadding>
            {refs.map((ref, idx) => (
                <ListItem key={`${ref.segment_id || ref.source_text_sha256 || 'ref'}-${idx}`} sx={{ alignItems: 'flex-start', px: 0 }}>
                    <ListItemIcon sx={{ minWidth: 34 }}>
                        <Chip label={idx + 1} size="small" sx={{ height: 22, minWidth: 22 }} />
                    </ListItemIcon>
                    <ListItemText
                        primary={
                            <Box display="flex" flexWrap="wrap" gap={0.75} mb={0.5}>
                                <Chip label={ref.speaker_id || 'Không rõ speaker'} size="small" variant="outlined" />
                                <Chip label={formatEvidenceTime(ref)} size="small" variant="outlined" />
                                {ref.source_kind && <Chip label={ref.source_kind} size="small" variant="outlined" />}
                            </Box>
                        }
                        secondary={ref.text_span || 'No transcript span available'}
                        secondaryTypographyProps={{ sx: { whiteSpace: 'pre-wrap' } }}
                    />
                </ListItem>
            ))}
        </List>
    );
};

const EvidenceItemList: React.FC<{ title: string; items?: EvidenceItem[] }> = ({ title, items = [] }) => (
    <Accordion sx={{ mb: 1, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(33, 150, 243, 0.05)' }}>
            <Box display="flex" alignItems="center" gap={1}>
                <HubIcon sx={{ color: '#1976d2' }} />
                <Typography fontWeight={600}>{title}</Typography>
                <Chip label={items.length} size="small" />
            </Box>
        </AccordionSummary>
        <AccordionDetails>
            {items.length === 0 ? (
                <Typography color="text.secondary">Chưa có {title.toLowerCase()}.</Typography>
            ) : (
                <List disablePadding>
                    {items.map(item => (
                        <ListItem key={item.id} sx={{ display: 'block', px: 0, py: 1.25 }}>
                            <Box display="flex" flexWrap="wrap" alignItems="center" gap={1} mb={1}>
                                <Typography fontWeight={700}>{item.title_vi || item.label_vi || item.label || item.type}</Typography>
                                <Chip label={item.slot_type || item.type} size="small" variant="outlined" />
                                <Chip label={confidenceLabel(item.confidence)} size="small" color="info" variant="outlined" />
                                <Chip label={item.review_status || 'unknown'} size="small" color={reviewColor(item.review_status)} />
                                {item.source_method && <Chip label="GPT OSS 120" size="small" variant="outlined" />}
                                <Chip label={`${item.evidence_refs?.length || 0} evidence`} size="small" variant="outlined" />
                            </Box>
                            {item.confidence_reason && (
                                <Typography variant="body2" color="text.secondary" mb={1}>
                                    {item.confidence_reason}
                                </Typography>
                            )}
                            {item.description_vi && (
                                <Typography variant="body2" color="text.secondary" mb={1}>
                                    {item.description_vi}
                                </Typography>
                            )}
                            <EvidenceRefs refs={item.evidence_refs} />
                            <Divider sx={{ mt: 1.25 }} />
                        </ListItem>
                    ))}
                </List>
            )}
        </AccordionDetails>
    </Accordion>
);

const EvidenceView: React.FC<{ file?: FileWithData }> = ({ file }) => {
    const graph = getCanonicalAnalysisGraph(file?.visualization_data);

    if (!file) {
        return <EmptyState message="Chọn file đã có analysis để xem evidence." />;
    }

    if (!graph) {
        return <EmptyState message="File này chỉ có visualization legacy, chưa có V2 evidence." />;
    }

    const activeEntities = (graph.entities || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeRelations = (graph.relations || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeEvents = (graph.events || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeClaims = (graph.claims || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeFacts = (graph.facts || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeSlots = (graph.slots || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeRisks = (graph.risk_flags || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));
    const activeInsights = (graph.insight_items || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph));

    return (
        <Box>
            <Paper sx={{ p: 2, mb: 2, borderRadius: '12px', bgcolor: 'rgba(25, 118, 210, 0.04)' }}>
                <Typography variant="subtitle1" fontWeight={700}>{file.filename}</Typography>
                <Typography variant="body2" color="text.secondary">
                    Phân tích do máy gợi ý, chưa được xác minh. Cần kiểm tra evidence và trạng thái review trước khi dùng như kết luận.
                </Typography>
                <Box display="flex" flexWrap="wrap" gap={1} mt={1}>
                    <Chip label={`schema ${graph.schema_version}`} size="small" />
                    <Chip label={`revision ${graph.graph_revision || 1}`} size="small" />
                    <Chip label={`${graph.segments?.length || 0} segments`} size="small" />
                </Box>
            </Paper>
            <EvidenceItemList title="Thông tin trích xuất" items={activeFacts} />
            <EvidenceItemList title="Slots" items={activeSlots} />
            <EvidenceItemList title="Insights" items={activeInsights} />
            <EvidenceItemList title="Cờ rủi ro" items={activeRisks} />
            <EvidenceItemList title="Thực thể" items={activeEntities} />
            <EvidenceItemList title="Quan hệ" items={activeRelations} />
            <EvidenceItemList title="Sự kiện" items={activeEvents} />
            <EvidenceItemList title="Claims" items={activeClaims} />
        </Box>
    );
};

const DisplaySections: React.FC<{ files: FileWithData[] }> = ({ files }) => {
    const sections = files.flatMap(file => {
        const graph = getCanonicalAnalysisGraph(file.visualization_data);
        return (graph?.display_sections_vi || []).map(section => ({ ...section, filename: file.filename, task_id: file.task_id }));
    });

    if (sections.length === 0) return null;

    return (
        <Accordion defaultExpanded sx={{ mb: 1, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: 'rgba(67, 160, 71, 0.06)' }}>
                <Box display="flex" alignItems="center" gap={1}>
                    <AnalyticsIcon sx={{ color: '#2e7d32' }} />
                    <Typography fontWeight={600}>Phân tích tiếng Việt</Typography>
                    <Chip label={sections.reduce((sum, section) => sum + (section.items?.length || 0), 0)} size="small" color="success" />
                </Box>
            </AccordionSummary>
            <AccordionDetails>
                <Grid container spacing={1.5}>
                    {sections.map(section => (
                        <Grid item xs={12} md={6} key={`${section.task_id}-${section.id}`}>
                            <Paper sx={{ p: 1.5, borderRadius: '8px', border: '1px solid rgba(46, 125, 50, 0.18)' }}>
                                <Typography variant="subtitle2" fontWeight={700}>{section.title_vi}</Typography>
                                <Typography variant="caption" color="text.secondary">{section.filename}</Typography>
                                <List dense disablePadding sx={{ mt: 1 }}>
                                    {(section.items || []).slice(0, 12).map((item: any) => (
                                        <ListItem key={item.id} sx={{ px: 0, alignItems: 'flex-start' }}>
                                            <ListItemText
                                                primary={
                                                    <Box display="flex" flexWrap="wrap" gap={0.75} alignItems="center">
                                                        <Typography variant="body2" fontWeight={600}>{item.label_vi || item.type}</Typography>
                                                        <Chip label={confidenceLabel(item.confidence)} size="small" variant="outlined" />
                                                        {item.requires_review && <Chip label="cần kiểm tra" size="small" color="warning" />}
                                                    </Box>
                                                }
                                                secondary={stringifyAnalysisValue(item.value || item.normalized_value)}
                                            />
                                        </ListItem>
                                    ))}
                                </List>
                            </Paper>
                        </Grid>
                    ))}
                </Grid>
            </AccordionDetails>
        </Accordion>
    );
};

const AnalysisPanel: React.FC<AnalysisPanelProps> = ({
    files,
    focusTaskId = null,
    activeView,
    onActiveViewChange,
}) => {
    const [copiedId, setCopiedId] = useState<string | null>(null);
    const [localView, setLocalView] = useState<AnalysisView>('overview');
    const [selectedAnalysisTaskId, setSelectedAnalysisTaskId] = useState<string | null>(focusTaskId);

    const currentView = activeView || localView;
    const setCurrentView = (view: AnalysisView) => {
        if (onActiveViewChange) {
            onActiveViewChange(view);
        } else {
            setLocalView(view);
        }
    };

    const filesWithViz = useMemo(
        () => files.filter(f => f.has_visualization && f.visualization_data),
        [files],
    );

    const filesWithData = useMemo(
        () => files.filter(f => f.summary || (f.has_visualization && f.visualization_data)),
        [files],
    );

    useEffect(() => {
        if (focusTaskId && filesWithViz.some(f => f.task_id === focusTaskId)) {
            setSelectedAnalysisTaskId(focusTaskId);
            return;
        }

        setSelectedAnalysisTaskId(prev => {
            if (prev && filesWithViz.some(f => f.task_id === prev)) {
                return prev;
            }
            return filesWithViz[0]?.task_id || null;
        });
    }, [focusTaskId, filesWithViz]);

    const selectedFile = useMemo(
        () => filesWithViz.find(f => f.task_id === selectedAnalysisTaskId) || filesWithViz[0],
        [filesWithViz, selectedAnalysisTaskId],
    );
    const selectedGraph = getCanonicalAnalysisGraph(selectedFile?.visualization_data);
    const hallucinationAnalysis = selectedGraph?.hallucination_analysis || null;

    const stats = useMemo(() => {
        const people = new Set<string>();
        const places = new Set<string>();
        const phones = new Set<string>();
        const events: string[] = [];
        const timeline: Array<{ time?: string; event: string; file: string }> = [];
        const allKeyInfo: KeyInfo[] = [];

        filesWithData.forEach(f => {
            const graph = getCanonicalAnalysisGraph(f.visualization_data);
            const viz = getLegacyVisualizationData(f.visualization_data as LegacyVisualizationData | null);
            const keyEntities = getKeyEntities(f.visualization_data);

            if (graph || keyEntities.length > 0) {
                keyEntities.forEach(item => {
                    if (item.type === 'person' || item.type === 'person_name') people.add(item.value);
                    if (isPlaceKeyInfo(item)) places.add(item.value);
                    if (item.type === 'phone') phones.add(item.value);
                });
            } else if (!graph) {
                viz.nodes?.forEach(n => {
                    const type = String(n.type || '').toLowerCase();
                    if (type === 'person') people.add(String(n.label || ''));
                    if (['place', 'location', 'address'].includes(type)) places.add(String(n.label || ''));
                    if (type === 'phone') phones.add(String(n.label || ''));
                });
            }

            viz.main_events?.forEach(e => events.push(String(e)));
            viz.timeline?.forEach(t => {
                const eventText = String(t.event || t.label || '');
                if (eventText) {
                    timeline.push({
                        time: formatTimelineTime(t),
                        event: eventText,
                        file: f.filename,
                    });
                }
            });

            keyEntities.forEach(entity => {
                allKeyInfo.push({
                    type: entity.type,
                    value: entity.value,
                    context: entity.context,
                    icon: iconForKeyType(entity.type),
                    color: colorForKeyType(entity.type),
                });
            });
        });

        const uniqueKeyInfo = allKeyInfo.filter((item, idx, arr) =>
            arr.findIndex(i => i.value === item.value && i.type === item.type) === idx
        );

        return {
            peopleCount: people.size,
            placesCount: places.size,
            eventsCount: events.length,
            timelineCount: timeline.length,
            people: Array.from(people).filter(Boolean),
            places: Array.from(places).filter(Boolean),
            phones: Array.from(phones).filter(Boolean),
            events,
            timeline,
            keyInfo: uniqueKeyInfo,
        };
    }, [filesWithData]);

    const handleCopy = (id: string, text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedId(id);
        setTimeout(() => setCopiedId(null), 2000);
    };

    if (files.length === 0) {
        return <EmptyState message="Chưa có files để phân tích" />;
    }

    if (filesWithData.length === 0) {
        return <EmptyState message='Chạy "Summarize" hoặc "Generate Analysis" để xem phân tích' />;
    }

    return (
        <Box>
            <Tabs
                value={currentView}
                onChange={(_, value) => setCurrentView(value)}
                sx={{ mb: 2 }}
            >
                <Tab value="overview" label="Tổng quan" />
                <Tab value="visualization" label="Graph" />
                <Tab value="evidence" label="Evidence" />
                <Tab value="hallucination" label="Ảo giác" />
            </Tabs>

            {currentView !== 'overview' && filesWithViz.length === 0 && (
                <EmptyState message="Chưa có file nào có analysis. Hãy chạy Generate Analysis trước." />
            )}

            {currentView !== 'overview' && filesWithViz.length > 0 && (
                <Box mb={2}>
                    <Typography variant="subtitle2" mb={1}>File phân tích:</Typography>
                    <Box display="flex" flexWrap="wrap" gap={1}>
                        {filesWithViz.map(file => (
                            <Chip
                                key={file.task_id}
                                label={file.filename}
                                variant={selectedFile?.task_id === file.task_id ? 'filled' : 'outlined'}
                                color={selectedFile?.task_id === file.task_id ? 'secondary' : 'default'}
                                onClick={() => setSelectedAnalysisTaskId(file.task_id)}
                            />
                        ))}
                    </Box>
                </Box>
            )}

            {currentView === 'overview' && (
                <Box>
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

                    <DisplaySections files={filesWithData} />

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
                                        <Grid item xs={6} sm={4} md={3} key={`${info.type}-${info.value}-${idx}`}>
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
                                                    <Typography variant="caption" color={copiedId === `info-${idx}` ? 'success.main' : 'text.secondary'} textTransform="capitalize">
                                                        {copiedId === `info-${idx}` ? 'Copied' : (info.context || info.type)}
                                                    </Typography>
                                                </Box>
                                            </Paper>
                                        </Grid>
                                    ))}
                                </Grid>
                            </AccordionDetails>
                        </Accordion>
                    )}

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
                                            <Typography variant="subtitle2" fontWeight={600} mb={1}>Người ({stats.peopleCount})</Typography>
                                            <Box display="flex" flexWrap="wrap" gap={0.5}>
                                                {stats.people.map((p, i) => <Chip key={i} label={p} size="small" sx={{ bgcolor: '#e3f2fd' }} />)}
                                            </Box>
                                        </Grid>
                                    )}
                                    {stats.places.length > 0 && (
                                        <Grid item xs={12} md={6}>
                                            <Typography variant="subtitle2" fontWeight={600} mb={1}>Địa điểm ({stats.placesCount})</Typography>
                                            <Box display="flex" flexWrap="wrap" gap={0.5}>
                                                {stats.places.map((p, i) => <Chip key={i} label={p} size="small" sx={{ bgcolor: '#e8f5e9' }} />)}
                                            </Box>
                                        </Grid>
                                    )}
                                </Grid>
                            </AccordionDetails>
                        </Accordion>
                    ) : null}

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
                                                <Typography variant="caption" color="text.secondary">{item.file}</Typography>
                                            </Paper>
                                        </Box>
                                    ))}
                                </Box>
                            </AccordionDetails>
                        </Accordion>
                    )}
                </Box>
            )}

            {currentView === 'visualization' && filesWithViz.length > 0 && (
                <VisualizationPanel files={filesWithViz} focusTaskId={selectedFile?.task_id || null} showFileSelector={false} />
            )}

            {currentView === 'evidence' && filesWithViz.length > 0 && (
                <EvidenceView file={selectedFile} />
            )}

            {currentView === 'hallucination' && filesWithViz.length > 0 && (
                <HallucinationAnalysisView analysis={hallucinationAnalysis} />
            )}
        </Box>
    );
};

export default AnalysisPanel;
