import React, { useMemo } from 'react';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import { Box, Tooltip, Typography } from '@mui/material';
import type { SxProps, Theme } from '@mui/material/styles';
import { DISPLAY_TIME_ZONE, formatApiDateTime } from '../utils/dateTime';

interface DateTimeTextProps {
  value?: string | null;
  fallbackValue?: string | null;
  label?: string;
  fallbackLabel?: string;
  missingText?: string;
  showIcon?: boolean;
  sx?: SxProps<Theme>;
}

const DateTimeText: React.FC<DateTimeTextProps> = React.memo(({
  value,
  fallbackValue,
  label = 'Tạo',
  fallbackLabel = 'Cập nhật',
  missingText = 'Chưa có ngày giờ',
  showIcon = true,
  sx,
}) => {
  const resolved = useMemo(() => {
    const primary = formatApiDateTime(value);
    if (primary) {
      return { formatted: primary, label };
    }

    const fallback = formatApiDateTime(fallbackValue);
    return fallback ? { formatted: fallback, label: fallbackLabel } : null;
  }, [fallbackLabel, fallbackValue, label, value]);
  const displayLabel = resolved?.label ? `${resolved.label}: ` : '';
  const tooltip = resolved
    ? `ISO: ${resolved.formatted.iso} | Múi giờ hiển thị: ${DISPLAY_TIME_ZONE}`
    : 'Bản ghi cũ chưa có timestamp hợp lệ.';

  return (
    <Tooltip title={tooltip} arrow disableInteractive>
      <Box
        component="span"
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.5,
          minWidth: 0,
          maxWidth: '100%',
          color: 'text.secondary',
          ...sx,
        }}
      >
        {showIcon && <AccessTimeIcon aria-hidden sx={{ fontSize: 14, flexShrink: 0 }} />}
        <Typography
          component="span"
          variant="caption"
          color="inherit"
          sx={{ lineHeight: 1.35, overflowWrap: 'anywhere' }}
        >
          {resolved ? `${displayLabel}${resolved.formatted.display}` : missingText}
        </Typography>
      </Box>
    </Tooltip>
  );
});

DateTimeText.displayName = 'DateTimeText';

export default DateTimeText;
