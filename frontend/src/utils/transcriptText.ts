export function countTranscriptWords(transcript: unknown): number {
  if (typeof transcript !== 'string') return 0;

  const normalized = transcript.trim();
  return normalized ? normalized.split(/\s+/u).length : 0;
}
