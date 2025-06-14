import React, { useState } from 'react';
import { Card, CardContent, Typography, Box, Button, Collapse, Alert, List, ListItem, Checkbox, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, Divider, Tabs, Tab, Tooltip, Chip, Avatar } from '@mui/material';
import { Timeline, TimelineItem, TimelineSeparator, TimelineConnector, TimelineContent, TimelineDot } from '@mui/lab';
import ReactFlow, { Background, Controls, MiniMap } from 'react-flow-renderer';
import InfoIcon from '@mui/icons-material/Info';
import SecurityIcon from '@mui/icons-material/Security';
import EmojiEmotionsIcon from '@mui/icons-material/EmojiEmotions';
import InsightsIcon from '@mui/icons-material/Insights';

// Kiểu dữ liệu cho props
interface InvestigationSummaryCardProps {
  summary: string | object | null;
  contextAnalysis?: object | string | null;
}

// Helper: parse JSON nếu có, fallback text
function parseJsonOrText(data: any) {
  if (!data) return null;
  if (typeof data === 'object') return data;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

const InvestigationSummaryCard: React.FC<InvestigationSummaryCardProps> = ({ summary, contextAnalysis }) => {
  // Ưu tiên contextAnalysis, fallback summary
  const parsed = parseJsonOrText(contextAnalysis) || parseJsonOrText(summary);
  const [showSensitive, setShowSensitive] = useState(false);
  const [tab, setTab] = useState(0);

  // Extract fields (ép kiểu về mảng an toàn)
  const overview = parsed?.overview || {};
  const entities = Array.isArray(parsed?.entities) ? parsed.entities : (Array.isArray(parsed?.entities?.people) ? parsed.entities.people : []);
  const relationships = Array.isArray(parsed?.relationships) ? parsed.relationships : [];
  const events = Array.isArray(parsed?.events) ? parsed.events : [];
  const sensitive = Array.isArray(parsed?.sensitive_info) ? parsed.sensitive_info : [];
  const keypoints = Array.isArray(parsed?.key_points) ? parsed.key_points : [];
  const actions = Array.isArray(parsed?.actions) ? parsed.actions : [];
  const offers = Array.isArray(parsed?.offers) ? parsed.offers : [];
  const decisions = Array.isArray(parsed?.decisions) ? parsed.decisions : [];
  const sentiment = parsed?.sentiment || '';
  const risk = Array.isArray(parsed?.risk) ? parsed.risk : (parsed?.risk ? [parsed.risk] : []);
  const notes = parsed?.notes || '';
  const insight = Array.isArray(parsed?.insight) ? parsed.insight : (parsed?.insight ? [parsed.insight] : []);
  const slang = parsed?.slang_detected || '';
  const hiddenRelationships = Array.isArray(parsed?.hidden_relationships) ? parsed.hidden_relationships : (parsed?.hidden_relationships ? [parsed.hidden_relationships] : []);

  if (!parsed) {
    console.warn('InvestigationSummaryCard: parsed data is null or invalid', { summary, contextAnalysis });
  }

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

  return (
    <Card sx={{ mb: 3, borderRadius: 4, boxShadow: 6, background: '#f5faff' }}>
      <CardContent>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Tổng quan" />
          <Tab label="Sơ đồ quan hệ" />
          <Tab label="Timeline" />
          <Tab label="Insight" />
          <Tab label="Nhạy cảm" />
          <Tab label="Cảm xúc" />
        </Tabs>
        {tab === 0 && (
          <Box>
            <Typography variant="h6" color="primary" fontWeight={700} mb={2}>Tổng quan</Typography>
            <Box mb={2}>
              <Typography><b>Tiêu đề:</b> {overview.title || 'Không rõ'}</Typography>
              <Typography><b>Thời gian:</b> {overview.time || 'Không rõ'}</Typography>
              <Typography><b>Địa điểm:</b> {overview.location || 'Không rõ'}</Typography>
              <Typography><b>Trạng thái:</b> {overview.status || 'Không rõ'}</Typography>
              <Typography><b>Chủ đề:</b> {overview.topic || 'Không rõ'}</Typography>
            </Box>
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
        {tab === 2 && events.length > 0 && (
          <Box>
            <Typography variant="h6" color="secondary" fontWeight={700} mb={1}>Timeline sự kiện</Typography>
            <Timeline position="right">
              {events.map((ev: any, idx: number) => (
                <TimelineItem key={idx}>
                  <TimelineSeparator>
                    <TimelineDot color="primary" />
                    {idx < events.length - 1 && <TimelineConnector />}
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
                {sensitive.length === 0 && <Typography>Không có thông tin nhạy cảm.</Typography>}
                {sensitive.map((info: any, idx: number) => (
                  <Box key={idx} mb={1}>{typeof info === 'string' ? info : JSON.stringify(info)}</Box>
                ))}
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
        {/* Nếu dữ liệu trống */}
        {!parsed && (
          <Box mt={2}>
            <Typography variant="body1" color="text.primary" sx={{ whiteSpace: 'pre-wrap' }}>
              Không có thông tin.
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default InvestigationSummaryCard; 