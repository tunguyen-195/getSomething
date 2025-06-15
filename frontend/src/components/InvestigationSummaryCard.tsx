import React, { useState, useEffect } from 'react';
import { Card, CardContent, Typography, Box, Button, Collapse, Alert, List, ListItem, Checkbox, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, Divider, Tabs, Tab, Tooltip, Chip, Avatar, CircularProgress, Dialog, DialogTitle, DialogContent, DialogActions, Snackbar, CardHeader, Grid, ListItemIcon, ListItemText } from '@mui/material';
import { Timeline, TimelineItem, TimelineSeparator, TimelineConnector, TimelineContent, TimelineDot } from '@mui/lab';
import ReactFlow, { Background, Controls, MiniMap } from 'react-flow-renderer';
import InfoIcon from '@mui/icons-material/Info';
import SecurityIcon from '@mui/icons-material/Security';
import EmojiEmotionsIcon from '@mui/icons-material/EmojiEmotions';
import InsightsIcon from '@mui/icons-material/Insights';
import { CopyToClipboard } from 'react-copy-to-clipboard';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import EventIcon from '@mui/icons-material/Event';
import PlaceIcon from '@mui/icons-material/Place';
import LabelIcon from '@mui/icons-material/Label';

// Kiểu dữ liệu cho props
interface InvestigationSummaryCardProps {
  summary: string | object | null;
  contextAnalysis?: object | string | null;
  taskId?: string;
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

function highlightSummary(text: string) {
  // Highlight số điện thoại, email, CCCD, tên riêng (giả lập)
  let t = text.replace(/(0\d{9,10})/g, '<mark title="Số điện thoại">$1</mark>');
  t = t.replace(/([\w\.-]+@[\w\.-]+)/g, '<mark title="Email">$1</mark>');
  t = t.replace(/(\b\d{9,12}\b)/g, '<mark title="CCCD/Số giấy tờ">$1</mark>');
  t = t.replace(/(Quyên|Marriott|Hà Nội)/g, '<mark title="Tên riêng/Địa danh">$1</mark>');
  return t;
}

// Sửa lỗi linter: ép kiểu cho CopyToClipboard
const CopyToClipboardAny = CopyToClipboard as any;

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';
const ANALYZE_ENDPOINT = API_BASE_URL + '/api/v1/summaries/analyze';

// Helper gọi API với model fallback
async function analyzeSummaryWithFallback(summary: string, taskId?: string) {
  let res = await fetch(ANALYZE_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ summary, task_id: taskId })
  });
  let data = await res.json();
  if (data.context_analysis) return data.context_analysis;
  throw new Error('Phân tích thất bại');
}

const InvestigationSummaryCard: React.FC<InvestigationSummaryCardProps> = ({ summary, contextAnalysis, taskId }) => {
  const [showSensitive, setShowSensitive] = useState(false);
  const [tab, setTab] = useState(0);
  const [copied, setCopied] = useState(false);
  const [analysis, setAnalysis] = useState<any>(contextAnalysis || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingTab, setPendingTab] = useState<number | null>(null);
  const [snackbar, setSnackbar] = useState<{open: boolean, message: string, severity: 'success'|'error'}>({open: false, message: '', severity: 'success'});

  // Tự động gọi AI khi lần đầu vào tab visualize mà chưa có contextAnalysis
  useEffect(() => {
    if ([1,2,3,4,5].includes(tab) && !analysis && summary) {
      setLoading(true);
      setError(null);
      analyzeSummaryWithFallback(typeof summary === 'string' ? summary : JSON.stringify(summary), taskId)
        .then(setAnalysis)
        .catch(e => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [tab, analysis, summary, taskId]);

  // Đảm bảo tab luôn hợp lệ
  useEffect(() => {
    if (tab == null || isNaN(tab) || tab < 0 || tab > 5) setTab(0);
  }, [tab]);

  // Khi có lỗi backend hoặc context_analysis không hợp lệ, hiển thị lỗi rõ ràng và reset tab về 0
  useEffect(() => {
    if (error || (analysis && typeof analysis !== 'object')) {
      setTab(0);
    }
  }, [error, analysis]);

  // Parse lại analysis nếu là chuỗi JSON hoặc object có field summary là chuỗi JSON
  let parsedAnalysis = parseJsonOrText(analysis);
  if (parsedAnalysis && typeof parsedAnalysis.summary === 'string') {
    const inner = parseJsonOrText(parsedAnalysis.summary);
    if (inner && typeof inner === 'object') {
      parsedAnalysis = { ...parsedAnalysis, ...inner };
    }
  }
  // Mapping lại các trường tổng quan từ parsedAnalysis
  const mappedOverview = {
    title: parsedAnalysis?.summary || parsedAnalysis?.context?.topic || parsedAnalysis?.context?.purpose || '',
    time: parsedAnalysis?.entities?.time?.[0]?.value || parsedAnalysis?.details?.time || '',
    location: parsedAnalysis?.entities?.locations?.[0]?.name || '',
    status: parsedAnalysis?.context?.status || '',
    topic: parsedAnalysis?.context?.topic || '',
  };
  // Extract fields từ parsedAnalysis
  const entities = Array.isArray(parsedAnalysis?.entities) ? parsedAnalysis.entities : (Array.isArray(parsedAnalysis?.entities?.people) ? parsedAnalysis.entities.people : []);
  const relationships = Array.isArray(parsedAnalysis?.relationships) ? parsedAnalysis.relationships : [];
  const events = Array.isArray(parsedAnalysis?.events) ? parsedAnalysis.events : [];
  const sensitive = Array.isArray(parsedAnalysis?.sensitive_info) ? parsedAnalysis.sensitive_info : [];
  const keypoints = Array.isArray(parsedAnalysis?.key_points) ? parsedAnalysis.key_points : [];
  const actions = Array.isArray(parsedAnalysis?.actions) ? parsedAnalysis.actions : [];
  const offers = Array.isArray(parsedAnalysis?.offers) ? parsedAnalysis.offers : [];
  const decisions = Array.isArray(parsedAnalysis?.decisions) ? parsedAnalysis.decisions : [];
  const sentiment = parsedAnalysis?.sentiment || '';
  const risk = Array.isArray(parsedAnalysis?.risk) ? parsedAnalysis.risk : (parsedAnalysis?.risk ? [parsedAnalysis.risk] : []);
  const notes = parsedAnalysis?.notes || '';
  const insight = Array.isArray(parsedAnalysis?.insight) ? parsedAnalysis.insight : (parsedAnalysis?.insight ? [parsedAnalysis.insight] : []);
  const slang = parsedAnalysis?.slang_detected || '';
  const hiddenRelationships = Array.isArray(parsedAnalysis?.hidden_relationships) ? parsedAnalysis.hidden_relationships : (parsedAnalysis?.hidden_relationships ? [parsedAnalysis.hidden_relationships] : []);

  // Timeline: lấy từ events, nếu không có thì từ entities.time hoặc timeline
  const timelineEvents = Array.isArray(parsedAnalysis?.events) && parsedAnalysis.events.length > 0
    ? parsedAnalysis.events
    : (Array.isArray(parsedAnalysis?.timeline) ? parsedAnalysis.timeline : (Array.isArray(parsedAnalysis?.entities?.time) ? parsedAnalysis.entities.time.map((t: any) => ({ time: t.value, description: t.context || '' })) : []));

  // Nhạy cảm: lấy từ sensitive_info, đồng thời gom các entity có is_sensitive=true
  const sensitiveEntities = [
    ...(Array.isArray(parsedAnalysis?.entities?.people) ? parsedAnalysis.entities.people.filter(e => e.is_sensitive) : []),
    ...(Array.isArray(parsedAnalysis?.entities?.locations) ? parsedAnalysis.entities.locations.filter(e => e.is_sensitive) : []),
    ...(Array.isArray(parsedAnalysis?.entities?.time) ? parsedAnalysis.entities.time.filter(e => e.is_sensitive) : []),
    ...(parsedAnalysis?.entities?.contact?.phone?.is_sensitive ? [parsedAnalysis.entities.contact.phone] : []),
    ...(parsedAnalysis?.entities?.contact?.email?.is_sensitive ? [parsedAnalysis.entities.contact.email] : []),
    ...(parsedAnalysis?.entities?.contact?.id?.is_sensitive ? [parsedAnalysis.entities.contact.id] : []),
  ];
  const allSensitive = [
    ...(Array.isArray(parsedAnalysis?.sensitive_info) ? parsedAnalysis.sensitive_info : []),
    ...sensitiveEntities
  ];

  // React Flow nodes/edges
  const nodes = entities.map((e: any, idx: number) => ({ id: e.id || String(idx), data: { label: e.label || e.name || e.type, isSensitive: e.is_sensitive, tooltip: e.context }, position: { x: 100 + idx * 120, y: 100 } }));
  const edges = relationships.map((r: any, idx: number) => ({ id: r.id || String(idx), source: r.source, target: r.target, label: r.label || r.type, tooltip: r.context }));

  // Helper: biểu tượng cảm xúc
  const sentimentIcon = (sentiment: string) => {
    if (!sentiment) return null;
    if (sentiment.toLowerCase().includes('positive') || sentiment.includes('hài lòng')) return <EmojiEmotionsIcon color="success" sx={{ mr: 1 }} />;
    if (sentiment.toLowerCase().includes('negative')) return <EmojiEmotionsIcon color="error" sx={{ mr: 1 }} />;
    return <EmojiEmotionsIcon color="warning" sx={{ mr: 1 }} />;
  };

  // Helper: insight checklist
  const insightChecklist = [
    ...(offers.length ? offers.map((o: any) => ({ label: `Ưu đãi: ${o.content || o}`, icon: <InsightsIcon color="primary" /> })) : []),
    ...(decisions.length ? decisions.map((d: any) => ({ label: `Quyết định: ${d.content || d}`, icon: <InfoIcon color="info" /> })) : []),
    ...(actions.length ? actions.map((a: any) => ({ label: `Hành động: ${a.content || a}`, icon: <InfoIcon color="secondary" /> })) : []),
    ...(sentiment ? [{ label: `Cảm xúc: ${sentiment}`, icon: sentimentIcon(sentiment) }] : []),
  ];

  const handleTabChange = (_: any, v: number) => {
    // Nếu chuyển sang tab visualize (1-5) và đã có analysis, hỏi xác nhận
    if ([1,2,3,4,5].includes(v) && analysis) {
      setPendingTab(v);
      setConfirmOpen(true);
    } else {
      setTab(v);
    }
  };

  return (
    <Card sx={{ mb: 3, borderRadius: 4, boxShadow: 6, background: '#f5faff' }}>
      <CardContent>
        <Tabs value={typeof tab === 'number' && tab >= 0 && tab <= 5 ? tab : 0} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Tổng quan" />
          <Tab label="Sơ đồ quan hệ" />
          <Tab label="Timeline" />
          <Tab label="Insight" />
          <Tab label="Nhạy cảm" />
          <Tab label="Cảm xúc" />
        </Tabs>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        {tab === 0 && (
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', background: '#f6fafd', borderRadius: 2, p: 2, mb: 2 }}>
              <Typography variant="subtitle1" fontWeight={500} color="#333" sx={{ flex: 1, lineHeight: 1.7 }}>
                {mappedOverview.title || parsedAnalysis?.summary || 'Không có tóm tắt hội thoại.'}
              </Typography>
              <Tooltip title={copied === 'summary' ? 'Đã copy!' : 'Copy'}>
                <Button size="small" variant="text" color={copied === 'summary' ? 'success' : 'primary'} sx={{ minWidth: 0, ml: 1 }} onClick={() => {navigator.clipboard.writeText(mappedOverview.title || parsedAnalysis?.summary || ''); setCopied('summary'); setTimeout(()=>setCopied(false), 1500);}} disabled={!(mappedOverview.title || parsedAnalysis?.summary)}><ContentCopyIcon fontSize="small" /></Button>
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
                  {keypoints.map((kp: any, idx: number) => (
                    <ListItem key={idx}>
                      <Checkbox checked disabled />
                      <Typography>{typeof kp === 'string' ? kp : JSON.stringify(kp)}</Typography>
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        )}
        {tab === 1 && (
          <Box>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={1}>Sơ đồ quan hệ</Typography>
            <Box sx={{ height: 300, background: '#e3f2fd', borderRadius: 2, mb: 2 }}>
              {loading ? (
                <Box display="flex" alignItems="center" justifyContent="center" minHeight={180}>
                  <CircularProgress />
                  <Typography ml={2}>Đang phân tích dữ liệu bằng AI...</Typography>
                </Box>
              ) : error ? (
                <Alert severity="error">{error}</Alert>
              ) : (
                <ReactFlow nodes={nodes} edges={edges} fitView>
                  <MiniMap />
                  <Controls />
                  <Background />
                </ReactFlow>
              )}
            </Box>
            <Box>
              <Typography variant="subtitle2" fontWeight={700}>Thực thể:</Typography>
              <List>
                {entities.map((e: any, idx: number) => (
                  <Tooltip key={idx} title={e.context || ''} arrow>
                    <ListItem>
                      <Chip label={e.label || e.name || e.type} color={e.is_sensitive ? 'error' : 'primary'} icon={e.is_sensitive ? <SecurityIcon /> : <InfoIcon />} />
                    </ListItem>
                  </Tooltip>
                ))}
              </List>
              <Typography variant="subtitle2" fontWeight={700}>Mối quan hệ:</Typography>
              <List>
                {relationships.map((r: any, idx: number) => (
                  <Tooltip key={idx} title={r.context || ''} arrow>
                    <ListItem>
                      <Chip label={r.label || r.type} color="secondary" icon={<InfoIcon />} />
                    </ListItem>
                  </Tooltip>
                ))}
              </List>
            </Box>
          </Box>
        )}
        {tab === 2 && timelineEvents.length > 0 && (
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
                    <Typography fontWeight={600}>{ev.time || `Sự kiện ${idx + 1}`}</Typography>
                    <Typography>{ev.description || ev.action || ev.event || ''}</Typography>
                  </TimelineContent>
                </TimelineItem>
              ))}
            </Timeline>
          </Box>
        )}
        {tab === 3 && (
          <Box>
            <Typography variant="h6" color="primary" fontWeight={700} mb={1}>Insight & Checklist</Typography>
            <List>
              {insightChecklist.length === 0 && <ListItem><Typography>Không có insight nổi bật.</Typography></ListItem>}
              {insightChecklist.map((ins, idx) => (
                <ListItem key={idx}>
                  <Avatar sx={{ bgcolor: 'white', color: 'primary.main', mr: 1 }}>{ins.icon}</Avatar>
                  <Typography>{ins.label}</Typography>
                </ListItem>
              ))}
            </List>
          </Box>
        )}
        {tab === 4 && (
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
                          <b>{info.name || info.value || 'Thông tin nhạy cảm'}</b>
                          {info.type && <Chip label={info.type} size="small" sx={{ ml: 1 }} />}
                          {info.is_sensitive && <Chip label="Nhạy cảm" color="error" size="small" sx={{ ml: 1 }} />}
                          {['phone','email','id'].includes(info.type || '') && info.value && (
                            <Button size="small" variant="outlined" color="primary" sx={{ ml: 1 }} onClick={() => navigator.clipboard.writeText(info.value)}>Copy</Button>
                          )}
                        </span>}
                        secondary={<>
                          {info.sensitivity_reason && <Typography color="error">Lý do: {info.sensitivity_reason}</Typography>}
                          {info.context && <Typography color="text.secondary">{info.context}</Typography>}
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
        {tab === 5 && (
          <Box>
            <Typography variant="h6" color="primary" fontWeight={700} mb={2}>Cảm xúc hội thoại</Typography>
            <Box display="flex" alignItems="center" mb={2}>
              {sentimentIcon(sentiment)}
              <Typography fontWeight={600}>{sentiment || 'Không rõ'}</Typography>
            </Box>
          </Box>
        )}
        {/* Cảnh báo risk, notes, slang, hidden_relationships */}
        {(risk.length > 0 || notes || slang || hiddenRelationships.length > 0) && (
          <Box mb={2}>
            {risk.length > 0 && (
              <Alert severity="error" sx={{ mb: 1 }}>
                <b>Nguy cơ/rủi ro:</b> {risk.map((r: any, idx: number) => <span key={idx}>{typeof r === 'string' ? r : JSON.stringify(r)}<br/></span>)}
              </Alert>
            )}
            {slang && (
              <Alert severity="warning" sx={{ mb: 1 }}>
                <b>Phát hiện tiếng lóng/mật ngữ:</b> {slang}
              </Alert>
            )}
            {hiddenRelationships.length > 0 && (
              <Alert severity="info" sx={{ mb: 1 }}>
                <b>Mối quan hệ ẩn/nghi vấn:</b> {hiddenRelationships.map((h: any, idx: number) => <span key={idx}>{typeof h === 'string' ? h : JSON.stringify(h)}<br/></span>)}
              </Alert>
            )}
            {notes && (
              <Alert severity="info"><b>Ghi chú nghiệp vụ:</b> {notes}</Alert>
            )}
          </Box>
        )}
        {/* Checklist insight riêng */}
        {insight.length > 0 && (
          <Box mb={2}>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={1}>Insight nghiệp vụ</Typography>
            <List>
              {insight.map((ins: any, idx: number) => (
                <Tooltip key={idx} title="Insight nghiệp vụ, dấu hiệu bất thường, nguy cơ, hành vi nghi vấn, mối liên hệ ẩn..." arrow>
                  <ListItem>
                    <Checkbox checked disabled />
                    <Typography>{typeof ins === 'string' ? ins : JSON.stringify(ins)}</Typography>
                  </ListItem>
                </Tooltip>
              ))}
            </List>
          </Box>
        )}
        {/* Nếu dữ liệu trống hoặc không parse được */}
        {!parsedAnalysis && (
          <Box mt={2}>
            <Alert severity="warning">Không có dữ liệu phân tích hoặc dữ liệu trả về không hợp lệ từ backend.</Alert>
          </Box>
        )}
        {/* Dialog xác nhận visualize lại */}
        <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
          <DialogTitle>Xác nhận phân tích lại bằng AI?</DialogTitle>
          <DialogContent>Bạn đã có dữ liệu phân tích. Bạn có muốn gửi lại summary cho AI để phân tích lại và cập nhật visualize không?</DialogContent>
          <DialogActions>
            <Button onClick={() => { setConfirmOpen(false); setTab(pendingTab!); }}>Không, dùng dữ liệu cũ</Button>
            <Button onClick={async () => {
              setConfirmOpen(false);
              setLoading(true);
              setError(null);
              try {
                const result = await analyzeSummaryWithFallback(typeof summary === 'string' ? summary : JSON.stringify(summary), taskId);
                setAnalysis(result);
                setSnackbar({open: true, message: 'Phân tích lại thành công!', severity: 'success'});
                setTab(pendingTab!);
              } catch (e: any) {
                setError(e.message);
                setSnackbar({open: true, message: e.message, severity: 'error'});
              } finally {
                setLoading(false);
              }
            }} color="primary" variant="contained">Có, phân tích lại</Button>
          </DialogActions>
        </Dialog>
        {/* Thêm nút "Phân tích lại" (Visualize lại) chỉ hiển thị khi đã có analysis và đang ở tab visualize (1-5) */}
        {[1,2,3,4,5].includes(tab) && analysis && (
          <Box mb={2} display="flex" justifyContent="flex-end">
            <Button variant="outlined" color="primary" onClick={() => setConfirmOpen(true)}>
              Phân tích lại bằng AI
            </Button>
          </Box>
        )}
        <Snackbar open={snackbar.open} autoHideDuration={3000} onClose={() => setSnackbar({...snackbar, open: false})} anchorOrigin={{vertical:'top',horizontal:'center'}}>
          <Alert severity={snackbar.severity} sx={{ fontSize: 16 }}>{snackbar.message}</Alert>
        </Snackbar>
      </CardContent>
    </Card>
  );
};

export default InvestigationSummaryCard; 