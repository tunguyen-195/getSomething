import React, { useState, useMemo } from 'react';
import {
    Box,
    Typography,
    Paper,
    Chip,
    Card,
    CardContent,
    Grid,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Tabs,
    Tab,
    IconButton,
    Tooltip,
    Divider,
    LinearProgress,
} from '@mui/material';
import {
    Timeline as TimelineIcon,
    Person as PersonIcon,
    Place as PlaceIcon,
    Event as EventIcon,
    Hub as HubIcon,
    AccessTime as TimeIcon,
    ArrowBack as ArrowBackIcon,
    Refresh as RefreshIcon,
    Business as OrgIcon,
    Lightbulb as InsightIcon,
    SentimentSatisfied as SentimentIcon,
    TrendingUp as TrendingIcon,
} from '@mui/icons-material';
import { getLegacyVisualizationData } from '../utils/visualization';

// Types
interface VisualizationNode {
    id: string;
    label: string;
    type?: string;
    importance?: number;
}

interface VisualizationEdge {
    from: string;
    to: string;
    label?: string;
    type?: string;
}

interface TimelineItem {
    time?: string;
    event: string;
    entities_involved?: string[];
}

interface VisualizationData {
    nodes?: VisualizationNode[];
    edges?: VisualizationEdge[];
    timeline?: TimelineItem[];
    main_events?: string[];
    entity_types?: string[];
    summary?: {
        topic?: string;
        key_entities?: string[];
        key_actions?: string[];
    };
    sentiment?: {
        overall?: string;
        confidence?: number;
        details?: string;
    };
    insights?: string[];
    legacy_view?: VisualizationData;
}

interface FileWithVisualization {
    task_id: string;
    filename: string;
    has_visualization?: boolean;
    visualization_data?: VisualizationData;
}

interface VisualizationDashboardProps {
    files: FileWithVisualization[];
    onBack: () => void;
    onRegenerate?: (taskId: string) => void;
}

// Utility functions
const getEntityIcon = (type?: string) => {
    switch (type?.toLowerCase()) {
        case 'person': return <PersonIcon sx={{ color: '#2196f3' }} />;
        case 'location':
        case 'place': return <PlaceIcon sx={{ color: '#4caf50' }} />;
        case 'organization':
        case 'org': return <OrgIcon sx={{ color: '#ff9800' }} />;
        case 'event': return <EventIcon sx={{ color: '#e91e63' }} />;
        case 'time': return <TimeIcon sx={{ color: '#9c27b0' }} />;
        default: return <HubIcon sx={{ color: '#607d8b' }} />;
    }
};

const getEntityColor = (type?: string) => {
    switch (type?.toLowerCase()) {
        case 'person': return '#2196f3';
        case 'location':
        case 'place': return '#4caf50';
        case 'organization':
        case 'org': return '#ff9800';
        case 'event': return '#e91e63';
        case 'time': return '#9c27b0';
        default: return '#607d8b';
    }
};

const getSentimentColor = (sentiment?: string) => {
    switch (sentiment?.toLowerCase()) {
        case 'positive': return '#4caf50';
        case 'negative': return '#f44336';
        case 'mixed': return '#ff9800';
        default: return '#9e9e9e';
    }
};

const VisualizationDashboard: React.FC<VisualizationDashboardProps> = ({
    files,
    onBack,
    onRegenerate,
}) => {
    const [activeTab, setActiveTab] = useState(0);
    const [selectedFileId, setSelectedFileId] = useState<string | null>(
        files.find(f => f.has_visualization)?.task_id || null
    );

    const filesWithViz = useMemo(
        () => files.filter(f => f.has_visualization && f.visualization_data),
        [files]
    );

    const selectedFile = useMemo(
        () => filesWithViz.find(f => f.task_id === selectedFileId),
        [filesWithViz, selectedFileId]
    );

    const data = getLegacyVisualizationData(selectedFile?.visualization_data);

    // Stats
    const stats = useMemo(() => ({
        entities: data.nodes?.length || 0,
        relationships: data.edges?.length || 0,
        events: data.main_events?.length || 0,
        timeline: data.timeline?.length || 0,
    }), [data]);

    // Empty state
    if (filesWithViz.length === 0) {
        return (
            <Box sx={{ p: 4, textAlign: 'center' }}>
                <TimelineIcon sx={{ fontSize: 80, color: '#bdbdbd', mb: 2 }} />
                <Typography variant="h5" color="text.secondary" gutterBottom>
                    No visualization data
                </Typography>
                <Typography variant="body1" color="text.secondary">
                    Generate visualization from transcribed files first.
                </Typography>
            </Box>
        );
    }

    return (
        <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column', bgcolor: '#0a0a0f' }}>
            {/* Header */}
            <Box sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                p: 2,
                borderBottom: '1px solid rgba(255,255,255,0.1)',
                background: 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.05))',
            }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <IconButton onClick={onBack} sx={{ color: '#fff' }}>
                        <ArrowBackIcon />
                    </IconButton>
                    <Typography variant="h5" fontWeight={700} sx={{
                        background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                        WebkitBackgroundClip: 'text',
                        WebkitTextFillColor: 'transparent',
                    }}>
                        Visualization Dashboard
                    </Typography>
                    <Chip
                        label={`${filesWithViz.length} file(s)`}
                        size="small"
                        sx={{ bgcolor: 'rgba(99,102,241,0.2)', color: '#a5b4fc' }}
                    />
                </Box>
                {selectedFile && onRegenerate && (
                    <Tooltip title="Re-generate visualization">
                        <IconButton
                            onClick={() => onRegenerate(selectedFile.task_id)}
                            sx={{ color: '#a5b4fc' }}
                        >
                            <RefreshIcon />
                        </IconButton>
                    </Tooltip>
                )}
            </Box>

            {/* Main Content */}
            <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
                {/* Left Panel - File List */}
                <Box sx={{
                    width: 280,
                    borderRight: '1px solid rgba(255,255,255,0.1)',
                    p: 2,
                    overflow: 'auto',
                }}>
                    <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2 }}>
                        SELECT FILE
                    </Typography>
                    {filesWithViz.map(file => (
                        <Paper
                            key={file.task_id}
                            onClick={() => setSelectedFileId(file.task_id)}
                            sx={{
                                p: 1.5,
                                mb: 1,
                                cursor: 'pointer',
                                bgcolor: file.task_id === selectedFileId
                                    ? 'rgba(99,102,241,0.2)'
                                    : 'rgba(255,255,255,0.03)',
                                border: file.task_id === selectedFileId
                                    ? '1px solid rgba(99,102,241,0.5)'
                                    : '1px solid rgba(255,255,255,0.05)',
                                borderRadius: 2,
                                transition: 'all 0.2s',
                                '&:hover': {
                                    bgcolor: 'rgba(99,102,241,0.1)',
                                    borderColor: 'rgba(99,102,241,0.3)',
                                },
                            }}
                        >
                            <Typography variant="body2" fontWeight={600} noWrap>
                                {file.filename}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {getLegacyVisualizationData(file.visualization_data).nodes?.length || 0} entities
                            </Typography>
                        </Paper>
                    ))}
                </Box>

                {/* Right Panel - Content */}
                <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    {/* Stats Bar */}
                    <Box sx={{
                        display: 'flex',
                        gap: 2,
                        p: 2,
                        borderBottom: '1px solid rgba(255,255,255,0.1)',
                    }}>
                        <StatCard icon={<HubIcon />} label="Entities" value={stats.entities} color="#6366f1" />
                        <StatCard icon={<TrendingIcon />} label="Relations" value={stats.relationships} color="#8b5cf6" />
                        <StatCard icon={<EventIcon />} label="Events" value={stats.events} color="#ec4899" />
                        <StatCard icon={<TimelineIcon />} label="Timeline" value={stats.timeline} color="#10b981" />
                    </Box>

                    {/* Tabs */}
                    <Tabs
                        value={activeTab}
                        onChange={(_, v) => setActiveTab(v)}
                        sx={{
                            px: 2,
                            borderBottom: '1px solid rgba(255,255,255,0.1)',
                            '& .MuiTab-root': { color: '#9ca3af', minHeight: 48 },
                            '& .Mui-selected': { color: '#a5b4fc' },
                            '& .MuiTabs-indicator': { bgcolor: '#6366f1' },
                        }}
                    >
                        <Tab label="Overview" />
                        <Tab label="Timeline" />
                        <Tab label="Entities" />
                        <Tab label="Relations" />
                        <Tab label="Insights" />
                    </Tabs>

                    {/* Tab Content */}
                    <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
                        {activeTab === 0 && <OverviewTab data={data} />}
                        {activeTab === 1 && <TimelineTab timeline={data.timeline || []} />}
                        {activeTab === 2 && <EntitiesTab nodes={data.nodes || []} />}
                        {activeTab === 3 && <RelationsTab nodes={data.nodes || []} edges={data.edges || []} />}
                        {activeTab === 4 && <InsightsTab data={data} />}
                    </Box>
                </Box>
            </Box>
        </Box>
    );
};

// Sub-components
const StatCard: React.FC<{ icon: React.ReactNode; label: string; value: number; color: string }> = ({
    icon, label, value, color,
}) => (
    <Paper sx={{
        p: 2,
        flex: 1,
        bgcolor: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 2,
        display: 'flex',
        alignItems: 'center',
        gap: 2,
    }}>
        <Box sx={{ color, opacity: 0.8 }}>{icon}</Box>
        <Box>
            <Typography variant="h5" fontWeight={700} sx={{ color }}>{value}</Typography>
            <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Box>
    </Paper>
);

const OverviewTab: React.FC<{ data: VisualizationData }> = ({ data }) => (
    <Grid container spacing={3}>
        {/* Summary */}
        <Grid item xs={12} md={6}>
            <Card sx={{ bgcolor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <CardContent>
                    <Typography variant="h6" fontWeight={600} gutterBottom sx={{ color: '#a5b4fc' }}>
                        📝 Summary
                    </Typography>
                    <Typography variant="body1" sx={{ mb: 2 }}>
                        <strong>Topic:</strong> {data.summary?.topic || 'Not identified'}
                    </Typography>
                    {data.summary?.key_entities && data.summary.key_entities.length > 0 && (
                        <Box sx={{ mb: 2 }}>
                            <Typography variant="subtitle2" color="text.secondary">Key Entities:</Typography>
                            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
                                {data.summary.key_entities.map((e, i) => (
                                    <Chip key={i} label={e} size="small" variant="outlined" />
                                ))}
                            </Box>
                        </Box>
                    )}
                    {data.summary?.key_actions && data.summary.key_actions.length > 0 && (
                        <Box>
                            <Typography variant="subtitle2" color="text.secondary">Key Actions:</Typography>
                            <List dense>
                                {data.summary.key_actions.map((a, i) => (
                                    <ListItem key={i} sx={{ py: 0.5 }}>
                                        <ListItemText primary={`• ${a}`} />
                                    </ListItem>
                                ))}
                            </List>
                        </Box>
                    )}
                </CardContent>
            </Card>
        </Grid>

        {/* Sentiment */}
        <Grid item xs={12} md={6}>
            <Card sx={{ bgcolor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <CardContent>
                    <Typography variant="h6" fontWeight={600} gutterBottom sx={{ color: '#a5b4fc' }}>
                        <SentimentIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
                        Sentiment Analysis
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                        <Chip
                            label={data.sentiment?.overall || 'Neutral'}
                            sx={{
                                bgcolor: getSentimentColor(data.sentiment?.overall),
                                color: '#fff',
                                fontWeight: 600,
                                textTransform: 'capitalize',
                            }}
                        />
                        <Typography variant="body2" color="text.secondary">
                            Confidence: {((data.sentiment?.confidence || 0.5) * 100).toFixed(0)}%
                        </Typography>
                    </Box>
                    <LinearProgress
                        variant="determinate"
                        value={(data.sentiment?.confidence || 0.5) * 100}
                        sx={{
                            height: 8,
                            borderRadius: 4,
                            bgcolor: 'rgba(255,255,255,0.1)',
                            '& .MuiLinearProgress-bar': {
                                bgcolor: getSentimentColor(data.sentiment?.overall),
                            },
                        }}
                    />
                    {data.sentiment?.details && (
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                            {data.sentiment.details}
                        </Typography>
                    )}
                </CardContent>
            </Card>
        </Grid>

        {/* Main Events */}
        <Grid item xs={12}>
            <Card sx={{ bgcolor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <CardContent>
                    <Typography variant="h6" fontWeight={600} gutterBottom sx={{ color: '#a5b4fc' }}>
                        🎯 Main Events
                    </Typography>
                    {data.main_events && data.main_events.length > 0 ? (
                        <List>
                            {data.main_events.map((event, i) => (
                                <ListItem key={i} sx={{
                                    bgcolor: 'rgba(99,102,241,0.05)',
                                    borderRadius: 2,
                                    mb: 1,
                                }}>
                                    <ListItemIcon>
                                        <Chip label={i + 1} size="small" sx={{ bgcolor: '#6366f1', color: '#fff' }} />
                                    </ListItemIcon>
                                    <ListItemText primary={event} />
                                </ListItem>
                            ))}
                        </List>
                    ) : (
                        <Typography color="text.secondary">No main events identified</Typography>
                    )}
                </CardContent>
            </Card>
        </Grid>
    </Grid>
);

const TimelineTab: React.FC<{ timeline: TimelineItem[] }> = ({ timeline }) => (
    <Box sx={{ position: 'relative', pl: 4 }}>
        {/* Vertical line */}
        <Box sx={{
            position: 'absolute',
            left: 16,
            top: 0,
            bottom: 0,
            width: 3,
            background: 'linear-gradient(180deg, #6366f1, #8b5cf6, #ec4899)',
            borderRadius: 2,
        }} />

        {timeline.length > 0 ? timeline.map((item, i) => (
            <Box key={i} sx={{ display: 'flex', mb: 3, position: 'relative' }}>
                {/* Dot */}
                <Box sx={{
                    position: 'absolute',
                    left: -24,
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    bgcolor: '#6366f1',
                    border: '3px solid #1a1a2e',
                    zIndex: 1,
                }} />

                <Paper sx={{
                    p: 2,
                    ml: 2,
                    flex: 1,
                    bgcolor: 'rgba(99,102,241,0.05)',
                    border: '1px solid rgba(99,102,241,0.2)',
                    borderRadius: 2,
                }}>
                    {item.time && (
                        <Chip
                            label={item.time}
                            size="small"
                            sx={{ mb: 1, bgcolor: '#6366f1', color: '#fff' }}
                        />
                    )}
                    <Typography variant="body1">{item.event}</Typography>
                    {item.entities_involved && item.entities_involved.length > 0 && (
                        <Box sx={{ mt: 1, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                            {item.entities_involved.map((e, j) => (
                                <Chip key={j} label={e} size="small" variant="outlined" />
                            ))}
                        </Box>
                    )}
                </Paper>
            </Box>
        )) : (
            <Typography color="text.secondary">No timeline data available</Typography>
        )}
    </Box>
);

const EntitiesTab: React.FC<{ nodes: VisualizationNode[] }> = ({ nodes }) => (
    <Grid container spacing={2}>
        {nodes.length > 0 ? nodes.map((node, i) => (
            <Grid item xs={12} sm={6} md={4} key={i}>
                <Paper sx={{
                    p: 2,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 2,
                    bgcolor: 'rgba(255,255,255,0.03)',
                    border: `1px solid ${getEntityColor(node.type)}30`,
                    borderRadius: 2,
                    transition: 'all 0.2s',
                    '&:hover': {
                        transform: 'translateY(-4px)',
                        boxShadow: `0 8px 24px ${getEntityColor(node.type)}20`,
                    },
                }}>
                    {getEntityIcon(node.type)}
                    <Box sx={{ flex: 1 }}>
                        <Typography fontWeight={600}>{node.label}</Typography>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            {node.type && (
                                <Chip
                                    label={node.type}
                                    size="small"
                                    sx={{
                                        bgcolor: `${getEntityColor(node.type)}20`,
                                        color: getEntityColor(node.type),
                                        fontSize: 11,
                                    }}
                                />
                            )}
                            {node.importance && (
                                <Chip
                                    label={`★ ${node.importance}`}
                                    size="small"
                                    sx={{ fontSize: 11 }}
                                />
                            )}
                        </Box>
                    </Box>
                </Paper>
            </Grid>
        )) : (
            <Grid item xs={12}>
                <Typography color="text.secondary">No entities found</Typography>
            </Grid>
        )}
    </Grid>
);

const RelationsTab: React.FC<{ nodes: VisualizationNode[]; edges: VisualizationEdge[] }> = ({ nodes, edges }) => {
    const nodeMap = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes]);

    return (
        <Box>
            {edges.length > 0 ? (
                <List>
                    {edges.map((edge, i) => {
                        const fromNode = nodeMap.get(edge.from);
                        const toNode = nodeMap.get(edge.to);
                        return (
                            <ListItem key={i} sx={{
                                bgcolor: 'rgba(255,255,255,0.03)',
                                borderRadius: 2,
                                mb: 1,
                                border: '1px solid rgba(255,255,255,0.08)',
                            }}>
                                <ListItemIcon>{getEntityIcon(fromNode?.type)}</ListItemIcon>
                                <ListItemText
                                    primary={
                                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                            <Typography fontWeight={600}>{fromNode?.label || edge.from}</Typography>
                                            <Typography color="text.secondary">→</Typography>
                                            <Chip label={edge.label || 'relates to'} size="small" sx={{ bgcolor: 'rgba(99,102,241,0.2)' }} />
                                            <Typography color="text.secondary">→</Typography>
                                            <Typography fontWeight={600}>{toNode?.label || edge.to}</Typography>
                                        </Box>
                                    }
                                />
                            </ListItem>
                        );
                    })}
                </List>
            ) : (
                <Typography color="text.secondary">No relationships found</Typography>
            )}
        </Box>
    );
};

const InsightsTab: React.FC<{ data: VisualizationData }> = ({ data }) => (
    <Box>
        <Card sx={{ bgcolor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <CardContent>
                <Typography variant="h6" fontWeight={600} gutterBottom sx={{ color: '#fbbf24' }}>
                    <InsightIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
                    AI Insights
                </Typography>
                {data.insights && data.insights.length > 0 ? (
                    <List>
                        {data.insights.map((insight, i) => (
                            <ListItem key={i} sx={{
                                bgcolor: 'rgba(251,191,36,0.05)',
                                borderRadius: 2,
                                mb: 1,
                                border: '1px solid rgba(251,191,36,0.2)',
                            }}>
                                <ListItemIcon>
                                    <Chip label={i + 1} size="small" sx={{ bgcolor: '#fbbf24', color: '#000' }} />
                                </ListItemIcon>
                                <ListItemText primary={insight} />
                            </ListItem>
                        ))}
                    </List>
                ) : (
                    <Typography color="text.secondary">No insights generated</Typography>
                )}
            </CardContent>
        </Card>
    </Box>
);

export default VisualizationDashboard;
