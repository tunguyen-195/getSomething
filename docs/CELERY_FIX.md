# Celery Worker Crash Fix - Comprehensive Solution

## Problem
Celery worker exits immediately after completing 1 task, especially heavy transcription tasks.

## Solutions Applied

### Fix 1: Enhanced Celery Config (worker.py)
- Extended timeouts: 3600s → 7200s (2 hours)
- Added soft time limit: 7000s
- Broker connection retry enabled
- Extended socket timeouts: 10s → 30s
- Socket keepalive enabled
- Worker pool auto-restart enabled

### Fix 2: Optimized Worker Flags
`ash
--without-heartbeat --without-gossip --without-mingle
`

### Expected Results
- Worker stays alive after task completion
- Processes multiple tasks sequentially
- Stable memory usage
- No connection timeouts

See full docs for details.
