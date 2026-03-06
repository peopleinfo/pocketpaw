/**
 * FFmpeg Export Client
 *
 * HTTP client for communicating with the Python backend's FFmpeg export endpoints.
 * Handles job lifecycle: create → send frames → send audio → finalize → download.
 */

import { createLogger } from "@/shared/logging/logger";

const log = createLogger("FFmpegExportClient");

const BACKEND_URL = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FFmpegCapabilities {
  available: boolean;
  version: string;
  path: string;
  hwAccel: {
    encoder: string;
    hwaccel: string;
    available: boolean;
  };
}

export interface FFmpegJobSettings {
  width: number;
  height: number;
  fps: number;
  totalFrames: number;
  codec: string;
  quality: string;
  container: string;
  videoBitrate?: number;
  audioBitrate?: number;
}

export interface FFmpegJobInfo {
  jobId: string;
  status: string;
  outputPath: string;
}

export interface FFmpegExportProgress {
  jobId: string;
  phase: string;
  progress: number;
  framesReceived: number;
  totalFrames: number;
  encoderFps: number;
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

/**
 * Check FFmpeg availability and GPU acceleration support.
 */
export async function checkFFmpegCapabilities(): Promise<FFmpegCapabilities> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/ffmpeg/check`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      return {
        available: false,
        version: "",
        path: "",
        hwAccel: { encoder: "libx264", hwaccel: "", available: false },
      };
    }
    return await response.json();
  } catch {
    log.debug("Backend not available for FFmpeg check");
    return {
      available: false,
      version: "",
      path: "",
      hwAccel: { encoder: "libx264", hwaccel: "", available: false },
    };
  }
}

/**
 * Create a new FFmpeg export job.
 */
export async function createExportJob(
  settings: FFmpegJobSettings,
): Promise<FFmpegJobInfo> {
  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-compose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Failed to create export job: ${error.error}`);
  }

  return await response.json();
}

/**
 * Send a rendered frame (raw RGBA pixels) to the backend.
 * Uses ImageData directly from canvas for efficiency.
 */
export async function sendFrame(
  jobId: string,
  frameIndex: number,
  rgbaData: ArrayBuffer,
): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-frame`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: new Blob([
      // Header: jobId (36 bytes UUID) + frameIndex (4 bytes uint32) + data
      new TextEncoder().encode(jobId.padEnd(36, "\0")),
      new Uint32Array([frameIndex]).buffer,
      rgbaData,
    ]),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Failed to send frame ${frameIndex}: ${error.error}`);
  }
}

/**
 * Send a batch of frames more efficiently using chunked transfer.
 * Each frame is a raw RGBA buffer.
 */
export async function sendFrameBatch(
  jobId: string,
  startFrameIndex: number,
  frames: ArrayBuffer[],
): Promise<void> {
  // Build a single payload: [frameCount(4)] + for each: [frameIndex(4) + dataLength(4) + data]
  const headerSize = 4; // frameCount
  let totalSize = headerSize;
  for (const frame of frames) {
    totalSize += 4 + 4 + frame.byteLength; // frameIndex + dataLength + data
  }

  const buffer = new ArrayBuffer(totalSize);
  const view = new DataView(buffer);
  let offset = 0;

  // Frame count
  view.setUint32(offset, frames.length, true);
  offset += 4;

  for (let i = 0; i < frames.length; i++) {
    const frameIndex = startFrameIndex + i;
    const frameData = frames[i]!;

    view.setUint32(offset, frameIndex, true);
    offset += 4;
    view.setUint32(offset, frameData.byteLength, true);
    offset += 4;

    new Uint8Array(buffer, offset, frameData.byteLength).set(
      new Uint8Array(frameData),
    );
    offset += frameData.byteLength;
  }

  const response = await fetch(
    `${BACKEND_URL}/api/ffmpeg/export-frames-batch`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Job-Id": jobId,
      },
      body: buffer,
    },
  );

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Failed to send frame batch: ${error.error}`);
  }
}

/**
 * Send audio data (WAV blob) to be muxed into the final output.
 */
export async function sendAudioData(
  jobId: string,
  audioBlob: Blob,
): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-audio`, {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Job-Id": jobId,
    },
    body: audioBlob,
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Failed to send audio: ${error.error}`);
  }
}

/**
 * Finalize the export — tells backend to close FFmpeg stdin and wait for completion.
 */
export async function finalizeExport(
  jobId: string,
): Promise<{ success: boolean; fileSize: number; outputPath: string }> {
  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jobId }),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Failed to finalize export: ${error.error}`);
  }

  return await response.json();
}

/**
 * Get export job progress.
 */
export async function getExportProgress(
  jobId: string,
): Promise<FFmpegExportProgress> {
  const response = await fetch(
    `${BACKEND_URL}/api/ffmpeg/export-progress/${jobId}`,
  );
  if (!response.ok) {
    throw new Error("Failed to get progress");
  }
  return await response.json();
}

/**
 * Download the finished export as a Blob.
 */
export async function downloadExport(jobId: string): Promise<Blob> {
  const response = await fetch(
    `${BACKEND_URL}/api/ffmpeg/export-download/${jobId}`,
  );
  if (!response.ok) {
    throw new Error("Failed to download export");
  }
  return await response.blob();
}

/**
 * Cancel an active export job.
 */
export async function cancelExportJob(jobId: string): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}/api/ffmpeg/export-cancel/${jobId}`, {
      method: "POST",
    });
  } catch {
    // Best effort cancel
    log.warn("Failed to send cancel request");
  }
}

// ---------------------------------------------------------------------------
// Direct File Export (Fast Path)
// ---------------------------------------------------------------------------

export interface DirectExportSettings {
  inputPath: string;
  codec: string;
  quality: string;
  container: string;
  width?: number;
  height?: number;
  fps?: number;
  startTime?: number;
  duration?: number;
  videoBitrate?: number;
  audioBitrate?: number;
  useHardwareAccel?: boolean;
}

export interface DirectExportResult {
  success: boolean;
  jobId: string;
  fileSize: number;
  outputPath: string;
  elapsed: number;
  encoder: string;
  hwAccel: boolean;
}

/**
 * Direct file-to-file export using FFmpeg on the backend.
 *
 * FAST PATH: Sends the source file path directly to FFmpeg for re-encoding.
 * This skips per-frame canvas rendering and HTTP transfer entirely,
 * giving 10-50x speedup over the frame-by-frame approach.
 *
 * Use this when the composition is a simple video clip without complex overlays/effects.
 */
export async function directExport(
  settings: DirectExportSettings,
): Promise<DirectExportResult> {
  log.info("Starting direct export", {
    inputPath: settings.inputPath,
    codec: settings.codec,
    container: settings.container,
    useHardwareAccel: settings.useHardwareAccel,
  });

  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-direct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Direct export failed: ${error.error}`);
  }

  const result: DirectExportResult = await response.json();
  log.info("Direct export completed", {
    elapsed: result.elapsed,
    fileSize: result.fileSize,
    encoder: result.encoder,
    hwAccel: result.hwAccel,
  });
  return result;
}

// ---------------------------------------------------------------------------
// Composition-Level Export (Backend-First Pipeline)
// ---------------------------------------------------------------------------

/**
 * Upload a media file to the backend for FFmpeg processing.
 * The backend stores it in a temp directory and returns the file path.
 */
export async function uploadMediaFile(
  mediaId: string,
  blob: Blob,
  filename: string,
): Promise<{ mediaId: string; path: string; cached: boolean }> {
  log.info("Uploading media to backend", {
    mediaId,
    filename,
    size: blob.size,
  });

  const response = await fetch(`${BACKEND_URL}/api/media/upload`, {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Media-Id": mediaId,
      "X-Filename": filename,
    },
    body: blob,
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Media upload failed: ${error.error}`);
  }

  return await response.json();
}

export interface CompositionExportRequest {
  composition: Record<string, unknown>;
  mediaMap: Record<string, string>; // mediaId -> backend file path
  settings: {
    codec: string;
    quality: string;
    container: string;
    width: number;
    height: number;
    videoBitrate?: number;
    audioBitrate?: number;
  };
  useHardwareAccel?: boolean;
}

export interface CompositionExportResult {
  success: boolean;
  jobId: string;
  fileSize: number;
  elapsed: number;
  encoder: string;
  hwAccel: boolean;
}

/**
 * Export a full composition via the backend FFmpeg pipeline.
 *
 * This is the FASTEST path — FFmpeg handles decode→filter→encode
 * entirely on the GPU. No canvas rendering, no frame-by-frame HTTP transfer.
 *
 * Flow:
 * 1. Upload media files to backend (cached, only uploaded once)
 * 2. Send composition JSON + media path mappings
 * 3. Backend builds FFmpeg filter_complex command
 * 4. FFmpeg processes everything natively with NVENC
 * 5. Download result blob
 */
export async function exportComposition(
  request: CompositionExportRequest,
): Promise<CompositionExportResult> {
  log.info("Starting composition export", {
    mediaCount: Object.keys(request.mediaMap).length,
    settings: request.settings,
  });

  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-composition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(`Composition export failed: ${error.error}`);
  }

  const result: CompositionExportResult = await response.json();
  log.info("Composition export completed", {
    elapsed: result.elapsed,
    fileSize: result.fileSize,
    encoder: result.encoder,
    hwAccel: result.hwAccel,
  });
  return result;
}
