"""
Summarization Service Module
Handles all summarization operations with LLM
"""
# Import from v2 service (current implementation)
from .summary_service_v2 import (
    summarize_transcript_v2,
    summarize_multi_transcripts_v2
)

# Backward compatibility aliases
# Map old function names to v2 functions for compatibility
summarize_transcript = summarize_transcript_v2
summarize_multi_transcripts = summarize_multi_transcripts_v2

__all__ = [
    'summarize_transcript',
    'summarize_multi_transcripts',
    'summarize_transcript_v2',
    'summarize_multi_transcripts_v2'
]
