import React, { useState } from 'react';
import { Card, CardContent, Typography, Box, Button, Collapse, Alert, List, ListItem, Checkbox, Divider, Tabs, Tab, Tooltip, Chip, Avatar, CardHeader, Grid, ListItemIcon, ListItemText } from '@mui/material';
import { Timeline, TimelineItem, TimelineSeparator, TimelineConnector, TimelineContent, TimelineDot } from '@mui/lab';
import ReactFlow, { Background, Controls, MiniMap } from 'react-flow-renderer';
import InfoIcon from '@mui/icons-material/Info';
import SecurityIcon from '@mui/icons-material/Security';
import EmojiEmotionsIcon from '@mui/icons-material/EmojiEmotions';
import InsightsIcon from '@mui/icons-material/Insights';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import EventIcon from '@mui/icons-material/Event';
import PlaceIcon from '@mui/icons-material/Place';
import LabelIcon from '@mui/icons-material/Label';
import { formatAnalysisValue, formatSlangDetected } from '../utils/analysisRender';
import type { InvestigationVerificationStatus } from '../utils/investigationProjection';
import {
  selectKeyPoints,
  selectReleasedInsightStatements,
} from '../utils/investigationProjection';

// Kiểu dữ liệu cho props
interface InvestigationSummaryCardProps {
  summary: string | object | null;
  contextAnalysis?: object | string | null;
  taskId?: string;
}

function verificationPresentation(status: InvestigationVerificationStatus): {
  checked: boolean;
  color: 'success' | 'warning' | 'error';
  label: string;
} {
  if (status === 'human_verified') {
    return { checked: true, color: 'success', label: 'Đã xác minh' };
  }
  if (status === 'rejected') {
    return { checked: false, color: 'error', label: 'Đã bác bỏ' };
  }
  return { checked: false, color: 'warning', label: 'Chưa xác minh' };
}

// Helper: parse JSON nếu có, fallback text, tự động cắt ```json ... ``` hoặc ``` ... ```
function parseJsonOrText(data: any) {
  if (!data) return null;
  if (typeof data === 'object') return data;
  if (typeof data === 'string') {
    // Cắt markdown code block nếu có
    let s = data.trim();
    if (s.startsWith('```json')) s = s.replace(/^```json/, '').replace(/```$/, '').trim();
    else if (s.startsWith('```')) s = s.replace(/^```/, '').replace(/```$/, '').trim();
    try {
      return JSON.parse(s);
    } catch {
      return null;
    }
  }
  return null;
}

const InvestigationSummaryCard: React.FC<InvestigationSummaryCardProps> = ({ summary, contextAnalysis }) => {
  const [showSensitive, setShowSensitive] = useState(false);
  const [tab, setTab] = useState(0);
  const [copied, setCopied] = useState<string | false>(false);

  // Parse lại analysis nếu là chuỗi JSON hoặc object có field summary là chuỗi JSON
  let parsedAnalysis = parseJsonOrText(contextAnalysis ?? summary);
  if (parsedAnalysis && typeof parsedAnalysis.summary === 'string') {
    const inner = parseJsonOrText(parsedAnalysis.summary);
    if (inner && typeof inner === 'object') {
      parsedAnalysis = { ...parsedAnalysis, ...inner };
    }
  }
  const knowledge = parsedAnalysis?.investigation_knowledge;
  const evidenceSpans = Array.isArray(knowledge?.evidence_spans) ? knowledge.evidence_spans : [];
  const evidenceById = new Map(evidenceSpans.map((item: any) => [item.evidence_id, item]));
  const evidenceLabel = (evidenceIds: string[] = []) => evidenceIds
    .map((id: string) => evidenceById.get(id))
    .filter(Boolean)
    .map((item: any) => {
      const time = item.start_seconds != null ? `${Number(item.start_seconds).toFixed(2)}s` : 'text';
      const speaker = formatAnalysisValue(item.speaker_id);
      return `${time}${speaker ? ` · ${speaker}` : ''}: “${formatAnalysisValue(item.quote)}”`;
    })
    .join('\n');
  const summaryText = formatAnalysisValue(parsedAnalysis?.summary)
    || (typeof summary === 'string' ? summary.trim() : '');
  // Mapping lại các trường tổng quan từ parsedAnalysis
  const mappedOverview = {
    title: summaryText || formatAnalysisValue(parsedAnalysis?.context?.topic) || formatAnalysisValue(parsedAnalysis?.context?.purpose),
    time: formatAnalysisValue(parsedAnalysis?.entities?.time?.[0]?.value || parsedAnalysis?.details?.time),
    location: formatAnalysisValue(parsedAnalysis?.entities?.locations?.[0]?.name),
    status: formatAnalysisValue(parsedAnalysis?.context?.status),
    topic: formatAnalysisValue(parsedAnalysis?.context?.topic),
  };
  // Extract fields từ parsedAnalysis
  const entities = Array.isArray(knowledge?.entities)
    ? knowledge.entities
    : (Array.isArray(parsedAnalysis?.entities) ? parsedAnalysis.entities : (Array.isArray(parsedAnalysis?.entities?.people) ? parsedAnalysis.entities.people : []));
  const relationships = Array.isArray(knowledge?.relationships) ? knowledge.relationships : [];
  const keypoints = selectKeyPoints(parsedAnalysis);
  const sentiment = formatAnalysisValue(
    typeof parsedAnalysis?.sentiment === 'string' ? parsedAnalysis.sentiment : parsedAnalysis?.sentiment?.overall,
  );
  const notes = knowledge ? '' : formatAnalysisValue(parsedAnalysis?.notes);
  const insight = selectReleasedInsightStatements(parsedAnalysis);
  const slang = formatSlangDetected(parsedAnalysis?.slang_detected);
  const hiddenRelationships = knowledge ? [] : (Array.isArray(parsedAnalysis?.hidden_relationships) ? parsedAnalysis.hidden_relationships : (parsedAnalysis?.hidden_relationships ? [parsedAnalysis.hidden_relationships] : []));

  // Timeline: lấy từ events, nếu không có thì từ entities.time hoặc timeline
  const timelineEvents = Array.isArray(knowledge?.timeline) && knowledge.timeline.length > 0
    ? knowledge.timeline
    : (Array.isArray(parsedAnalysis?.timeline) ? parsedAnalysis.timeline : (Array.isArray(parsedAnalysis?.entities?.time) ? parsedAnalysis.entities.time.map((t: any) => ({ time: t.value, description: t.context || '' })) : []));

  // Nhạy cảm: lấy từ sensitive_info, đồng thời gom các entity có is_sensitive=true
  const sensitiveEntities = [
    ...(Array.isArray(parsedAnalysis?.entities?.people) ? parsedAnalysis.entities.people.filter((e: any) => e.is_sensitive) : []),
    ...(Array.isArray(parsedAnalysis?.entities?.locations) ? parsedAnalysis.entities.locations.filter((e: any) => e.is_sensitive) : []),
    ...(Array.isArray(parsedAnalysis?.entities?.time) ? parsedAnalysis.entities.time.filter((e: any) => e.is_sensitive) : []),
    ...(parsedAnalysis?.entities?.contact?.phone?.is_sensitive ? [parsedAnalysis.entities.contact.phone] : []),
    ...(parsedAnalysis?.entities?.contact?.email?.is_sensitive ? [parsedAnalysis.entities.contact.email] : []),
    ...(parsedAnalysis?.entities?.contact?.id?.is_sensitive ? [parsedAnalysis.entities.contact.id] : []),
  ];
  const allSensitive = [
    ...(Array.isArray(parsedAnalysis?.sensitive_info) ? parsedAnalysis.sensitive_info : []),
    ...sensitiveEntities
  ];

  // React Flow nodes/edges
  const entityNodeId = new Map(entities.map((e: any, idx: number) => [
    formatAnalysisValue(e.value || e.name || e.label),
    formatAnalysisValue(e.entity_id || e.id) || String(idx),
  ]));
  const nodes = entities.map((e: any, idx: number) => ({
    id: formatAnalysisValue(e.entity_id || e.id) || String(idx),
    data: {
      label: formatAnalysisValue(e.value || e.label || e.name || e.entity_type || e.type),
      isSensitive: e.is_sensitive,
      tooltip: evidenceLabel(e.evidence_ids) || formatAnalysisValue(e.context),
    },
    position: { x: 100 + idx * 120, y: 100 },
  }));
  const edges = relationships
    .filter((r: any) => entityNodeId.has(formatAnalysisValue(r.source)) && entityNodeId.has(formatAnalysisValue(r.target)))
    .map((r: any, idx: number) => ({
      id: formatAnalysisValue(r.relationship_id || r.id) || String(idx),
      source: entityNodeId.get(formatAnalysisValue(r.source)),
      target: entityNodeId.get(formatAnalysisValue(r.target)),
      label: formatAnalysisValue(r.label || r.type),
      tooltip: evidenceLabel(r.evidence_ids) || formatAnalysisValue(r.context),
    }));

  // Helper: biểu tượng cảm xúc
  const sentimentIcon = (sentiment: string) => {
    if (!sentiment) return null;
    if (sentiment.toLowerCase().includes('positive') || sentiment.includes('hài lòng')) return <EmojiEmotionsIcon color="success" sx={{ mr: 1 }} />;
    if (sentiment.toLowerCase().includes('negative')) return <EmojiEmotionsIcon color="error" sx={{ mr: 1 }} />;
    return <EmojiEmotionsIcon color="warning" sx={{ mr: 1 }} />;
  };

  const insightChecklist = insight.map((statement) => ({
    label: statement,
    icon: <InsightsIcon color="primary" />,
  }));
  const activeTab = tab === 3 && insight.length === 0 ? 0 : tab;

  return (
    <Card sx={{ mb: 3, borderRadius: 2, boxShadow: '0 2px 8px #b388ff11', background: '#fff', border: '1px solid #e0e7ef' }}>
      <CardContent>
        <Tabs value={activeTab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab value={0} label="Tổng quan" />
          <Tab value={1} label="Sơ đồ quan hệ" />
          <Tab value={2} label="Timeline" />
          {insight.length > 0 && <Tab value={3} label="Insight" />}
          <Tab value={4} label="Nhạy cảm" />
          <Tab value={5} label="Cảm xúc" />
        </Tabs>
        {activeTab === 0 && (
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', background: '#f6fafd', borderRadius: 2, p: 2, mb: 2 }}>
              <Typography variant="subtitle1" fontWeight={500} color="#333" sx={{ flex: 1, lineHeight: 1.7 }}>
                {mappedOverview.title || 'Không có tóm tắt hội thoại.'}
              </Typography>
              <Tooltip title={copied === 'summary' ? 'Đã copy!' : 'Copy'}>
                <Button size="small" variant="text" color={copied === 'summary' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.title); setCopied('summary'); setTimeout(()=>setCopied(false), 1500);}} disabled={!mappedOverview.title}><ContentCopyIcon fontSize="small" /></Button>
              </Tooltip>
            </Box>
            <Box sx={{ background: '#f8fafc', borderRadius: 3, p: 2, mb: 2, border: '1px solid #e3e8ee' }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6} md={3}>
                  <Box display="flex" alignItems="center">
                    <EventIcon color="primary" sx={{ mr: 1 }} />
                    <Typography fontWeight={600}>Thời gian:</Typography>
                    <Tooltip title={mappedOverview.time ? (copied === 'time' ? 'Đã copy!' : 'Copy') : 'Không rõ thời gian'}>
                      <Button size="small" variant="text" color={copied === 'time' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.time || ''); setCopied('time'); setTimeout(()=>setCopied(false), 1500);}} disabled={!mappedOverview.time}><ContentCopyIcon fontSize="small" /></Button>
                    </Tooltip>
                  </Box>
                  <Typography color={mappedOverview.time ? 'text.primary' : 'text.disabled'} sx={{ ml: 4 }}>{mappedOverview.time || 'Không rõ'}</Typography>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Box display="flex" alignItems="center">
                    <PlaceIcon color="primary" sx={{ mr: 1 }} />
                    <Typography fontWeight={600}>Địa điểm:</Typography>
                    <Tooltip title={mappedOverview.location ? (copied === 'location' ? 'Đã copy!' : 'Copy') : 'Không rõ địa điểm'}>
                      <Button size="small" variant="text" color={copied === 'location' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.location || ''); setCopied('location'); setTimeout(()=>setCopied(false), 1500);}} disabled={!mappedOverview.location}><ContentCopyIcon fontSize="small" /></Button>
                    </Tooltip>
                  </Box>
                  <Typography color={mappedOverview.location ? 'text.primary' : 'text.disabled'} sx={{ ml: 4 }}>{mappedOverview.location || 'Không rõ'}</Typography>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Box display="flex" alignItems="center">
                    <InfoIcon color="primary" sx={{ mr: 1 }} />
                    <Typography fontWeight={600}>Trạng thái:</Typography>
                    <Tooltip title={mappedOverview.status ? (copied === 'status' ? 'Đã copy!' : 'Copy') : 'Không rõ trạng thái'}>
                      <Button size="small" variant="text" color={copied === 'status' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.status || ''); setCopied('status'); setTimeout(()=>setCopied(false), 1500);}} disabled={!mappedOverview.status}><ContentCopyIcon fontSize="small" /></Button>
                    </Tooltip>
                  </Box>
                  <Typography color={mappedOverview.status ? 'text.primary' : 'text.disabled'} sx={{ ml: 4 }}>{mappedOverview.status || 'Không rõ'}</Typography>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Box display="flex" alignItems="center">
                    <LabelIcon color="primary" sx={{ mr: 1 }} />
                    <Typography fontWeight={600}>Chủ đề:</Typography>
                    <Tooltip title={mappedOverview.topic ? (copied === 'topic' ? 'Đã copy!' : 'Copy') : 'Không rõ chủ đề'}>
                      <Button size="small" variant="text" color={copied === 'topic' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.topic || ''); setCopied('topic'); setTimeout(()=>setCopied(false), 1500);}} disabled={!mappedOverview.topic}><ContentCopyIcon fontSize="small" /></Button>
                    </Tooltip>
                  </Box>
                  <Typography color={mappedOverview.topic ? 'text.primary' : 'text.disabled'} sx={{ ml: 4 }}>{mappedOverview.topic || 'Không rõ'}</Typography>
                </Grid>
              </Grid>
            </Box>
            <CardHeader
              avatar={<Avatar sx={{ bgcolor: '#1976d2' }}>{mappedOverview.topic ? mappedOverview.topic[0] : <HelpOutlineIcon />}</Avatar>}
              title={mappedOverview.topic || <span style={{ color: '#b0b0b0' }} title="Không rõ chủ đề">Không rõ</span>}
              subheader={null}
              sx={{ mb: 2 }}
            />
            <Grid container spacing={2} mb={2}>
              <Grid item xs={12} sm={6} md={4}>
                <Tooltip title={mappedOverview.time ? '' : 'Không rõ thời gian'}><Typography><b>Thời gian:</b> {mappedOverview.time || <span style={{ color: '#b0b0b0' }}>Không rõ</span>}</Typography></Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={4}>
                <Tooltip title={mappedOverview.location ? '' : 'Không rõ địa điểm'}><Typography><b>Địa điểm:</b> {mappedOverview.location || <span style={{ color: '#b0b0b0' }}>Không rõ</span>}</Typography></Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={4}>
                <Tooltip title={mappedOverview.status ? '' : 'Không rõ trạng thái'}><Typography><b>Trạng thái:</b> {mappedOverview.status || <span style={{ color: '#b0b0b0' }}>Không rõ</span>}</Typography></Tooltip>
              </Grid>
            </Grid>
            <Divider sx={{ my: 2 }} />
            {keypoints.length > 0 && (
              <Box mb={2}>
                <Typography variant="subtitle1" fontWeight={700}>Các điểm mấu chốt</Typography>
                <List>
                  {keypoints.map((item, idx) => {
                    const verification = verificationPresentation(item.verification_status);
                    return (
                      <ListItem key={`${item.statement}-${idx}`} sx={{ gap: 1, alignItems: 'flex-start' }}>
                        <Checkbox checked={verification.checked} disabled />
                        <Box sx={{ flex: 1 }}>
                          <Typography>{item.statement}</Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                            <Tooltip title={item.evidence_ids.length > 0 ? `Evidence: ${item.evidence_ids.join(', ')}` : 'Chưa có evidence reference'}>
                              <Chip
                                size="small"
                                variant="outlined"
                                color={verification.color}
                                label={verification.label}
                              />
                            </Tooltip>
                            {item.model_generated && (
                              <Chip size="small" variant="outlined" label="AI trích xuất" />
                            )}
                          </Box>
                        </Box>
                      </ListItem>
                    );
                  })}
                </List>
              </Box>
            )}
          </Box>
        )}
        {activeTab === 1 && (
          <Box>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={1}>Sơ đồ quan hệ</Typography>
            <Box sx={{ height: 300, background: '#e3f2fd', borderRadius: 2, mb: 2 }}>
              <ReactFlow nodes={nodes} edges={edges} fitView>
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </Box>
            <Box>
              <Typography variant="subtitle2" fontWeight={700}>Thực thể:</Typography>
              <List>
                {entities.map((e: any, idx: number) => (
                  <Tooltip key={idx} title={formatAnalysisValue(e.context)} arrow>
                    <ListItem>
                      <Chip label={formatAnalysisValue(e.label || e.name || e.value || e.type) || 'Không rõ'} color={e.is_sensitive ? 'error' : 'primary'} icon={e.is_sensitive ? <SecurityIcon /> : <InfoIcon />} />
                    </ListItem>
                  </Tooltip>
                ))}
              </List>
              <Typography variant="subtitle2" fontWeight={700}>Mối quan hệ:</Typography>
              <List>
                {relationships.map((r: any, idx: number) => (
                  <Tooltip key={idx} title={formatAnalysisValue(r.context)} arrow>
                    <ListItem>
                      <Chip label={formatAnalysisValue(r.label || r.type) || 'Không rõ'} color="secondary" icon={<InfoIcon />} />
                    </ListItem>
                  </Tooltip>
                ))}
              </List>
            </Box>
          </Box>
        )}
        {activeTab === 2 && timelineEvents.length > 0 && (
          <Box>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={1}>Timeline sự kiện</Typography>
            <Timeline position="right">
              {timelineEvents.map((ev: any, idx: number) => (
                <TimelineItem key={idx}>
                  <TimelineSeparator>
                    <TimelineDot color="primary" />
                    {idx < timelineEvents.length - 1 && <TimelineConnector />}
                  </TimelineSeparator>
                  <TimelineContent>
                    <Typography fontWeight={600}>{formatAnalysisValue(ev.time) || `Sự kiện ${idx + 1}`}</Typography>
                    <Typography>{formatAnalysisValue(ev.description || ev.action || ev.event)}</Typography>
                  </TimelineContent>
                </TimelineItem>
              ))}
            </Timeline>
          </Box>
        )}
        {activeTab === 3 && insight.length > 0 && (
          <Box>
            <Typography variant="h6" color="primary" fontWeight={700} mb={1}>Insight & Checklist</Typography>
            <List>
              {insightChecklist.map((ins, idx) => (
                <ListItem key={idx}>
                  <Avatar sx={{ bgcolor: 'white', color: 'primary.main', mr: 1 }}>{ins.icon}</Avatar>
                  <Typography>{ins.label}</Typography>
                </ListItem>
              ))}
            </List>
          </Box>
        )}
        {activeTab === 4 && (
          <Box>
            <Button variant="contained" color="error" onClick={() => setShowSensitive(v => !v)} sx={{ mb: 1 }}>
              {showSensitive ? 'Ẩn thông tin nhạy cảm' : 'Hiện thông tin nhạy cảm'}
            </Button>
            <Collapse in={showSensitive}>
              <Alert severity="error" sx={{ fontWeight: 700, fontSize: 16 }}>
                {allSensitive.length === 0 && <Typography>Không có thông tin nhạy cảm.</Typography>}
                <List>
                  {allSensitive.map((info: any, idx: number) => (
                    <ListItem key={idx} alignItems="flex-start" sx={{ mb: 1 }}>
                      <ListItemIcon><SecurityIcon color="error" /></ListItemIcon>
                      <ListItemText
                        primary={<span>
                          <b>{formatAnalysisValue(info.name || info.value) || 'Thông tin nhạy cảm'}</b>
                          {info.type && <Chip label={formatAnalysisValue(info.type)} size="small" sx={{ ml: 1 }} />}
                          {info.is_sensitive && <Chip label="Nhạy cảm" color="error" size="small" sx={{ ml: 1 }} />}
                          {['phone','email','id'].includes(formatAnalysisValue(info.type)) && info.value && (
                            <Button size="small" variant="outlined" color="primary" sx={{ ml: 1 }} onClick={() => navigator.clipboard.writeText(formatAnalysisValue(info.value))}>Copy</Button>
                          )}
                        </span>}
                        secondary={<>
                          {info.sensitivity_reason && <Typography color="error">Lý do: {formatAnalysisValue(info.sensitivity_reason)}</Typography>}
                          {info.context && <Typography color="text.secondary">{formatAnalysisValue(info.context)}</Typography>}
                        </>}
                      />
                    </ListItem>
                  ))}
                </List>
              </Alert>
            </Collapse>
            <Alert severity="warning" sx={{ mt: 2 }}>
              <SecurityIcon sx={{ mr: 1 }} /> Thông tin nhạy cảm cần được bảo mật nghiêm ngặt.
            </Alert>
          </Box>
        )}
        {activeTab === 5 && (
          <Box>
            <Typography variant="h6" color="primary" fontWeight={700} mb={2}>Cảm xúc hội thoại</Typography>
            <Box display="flex" alignItems="center" mb={2}>
              {sentimentIcon(sentiment)}
              <Typography fontWeight={600}>{sentiment || 'Không rõ'}</Typography>
            </Box>
          </Box>
        )}
        {/* Legacy notes remain informational; hypotheses are never promoted to risk. */}
        {(notes || slang || hiddenRelationships.length > 0) && (
          <Box mb={2}>
            {slang && (
              <Alert severity="warning" sx={{ mb: 1 }}>
                <b>Phát hiện tiếng lóng/mật ngữ:</b> {slang}
              </Alert>
            )}
            {hiddenRelationships.length > 0 && (
              <Alert severity="info" sx={{ mb: 1 }}>
                <b>Mối quan hệ ẩn/nghi vấn:</b> {hiddenRelationships.map((h: any, idx: number) => <span key={idx}>{formatAnalysisValue(h)}<br/></span>)}
              </Alert>
            )}
            {notes && (
              <Alert severity="info"><b>Ghi chú nghiệp vụ:</b> {notes}</Alert>
            )}
          </Box>
        )}
        {/* Nếu dữ liệu trống hoặc không parse được */}
        {!parsedAnalysis && (
          <Box mt={2}>
            <Alert severity="warning">Không có dữ liệu phân tích hoặc dữ liệu trả về không hợp lệ từ backend.</Alert>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default InvestigationSummaryCard;
