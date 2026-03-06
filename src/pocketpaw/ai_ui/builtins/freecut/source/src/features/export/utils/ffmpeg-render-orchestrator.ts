/**
 * FFmpeg Render Orchestrator
 *
 * Renders frames using the existing canvas renderer, but instead of encoding
 * with mediabunny WebCodecs, pipes raw RGBA frames to the Python backend
 * where FFmpeg uses NVENC (or other HW accelerators) for encoding.
 *
 * This gives 10-50x speedup over browser-based encoding by leveraging the GPU.
 */

import type { CompositionInputProps } from "@/types/export";
import type {
  ClientExportSettings,
  RenderProgress,
  ClientRenderResult,
} from "./client-renderer";
import { getMimeType } from "./client-renderer";
import { createLogger } from "@/shared/logging/logger";
import { createCompositionRenderer } from "./client-render-engine";
import {
  processAudio,
  hasAudioContent,
  clearAudioDecodeCache,
  createAudioBuffer,
} from "./canvas-audio";
import {
  createExportJob,
  finalizeExport,
  downloadExport,
  cancelExportJob,
  sendAudioData,
  type FFmpegJobSettings,
} from "./ffmpeg-export-client";

const log = createLogger("FFmpegRenderOrchestrator");

const BACKEND_URL = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FFmpegRenderOptions {
  settings: ClientExportSettings;
  composition: CompositionInputProps;
  onProgress: (progress: RenderProgress) => void;
  signal?: AbortSignal;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Convert AudioBuffer to WAV Blob for sending to backend
 */
function audioBufferToWavBlob(audioBuffer: AudioBuffer): Blob {
  const numChannels = audioBuffer.numberOfChannels;
  const sampleRate = audioBuffer.sampleRate;
  const length = audioBuffer.length;

  // Interleave channels
  const interleaved = new Float32Array(length * numChannels);
  for (let ch = 0; ch < numChannels; ch++) {
    const channelData = audioBuffer.getChannelData(ch);
    for (let i = 0; i < length; i++) {
      interleaved[i * numChannels + ch] = channelData[i]!;
    }
  }

  // Convert to 16-bit PCM
  const pcmData = new Int16Array(interleaved.length);
  for (let i = 0; i < interleaved.length; i++) {
    const s = Math.max(-1, Math.min(1, interleaved[i]!));
    pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }

  // Build WAV header
  const dataSize = pcmData.length * 2;
  const headerSize = 44;
  const buffer = new ArrayBuffer(headerSize + dataSize);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");

  // fmt chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true); // chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numChannels * 2, true); // byte rate
  view.setUint16(32, numChannels * 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample

  // data chunk
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  // Write PCM data
  const bytesView = new Uint8Array(buffer);
  bytesView.set(new Uint8Array(pcmData.buffer), headerSize);

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view: DataView, offset: number, string: string): void {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

// ---------------------------------------------------------------------------
// Main Export Function
// ---------------------------------------------------------------------------

/**
 * Render a composition using the backend FFmpeg pipeline with GPU acceleration.
 *
 * Flow:
 * 1. Create export job on backend (starts FFmpeg process)
 * 2. Render each frame on canvas (same as before)
 * 3. Extract raw RGBA pixels and POST to backend
 * 4. Backend pipes frames to FFmpeg stdin
 * 5. Process audio and send as WAV
 * 6. Finalize → download result blob
 */
export async function renderCompositionViaFFmpeg(
  options: FFmpegRenderOptions,
): Promise<ClientRenderResult> {
  const { settings, composition, onProgress, signal } = options;
  const { fps, durationInFrames = 0 } = composition;
  const totalFrames = durationInFrames;
  const durationSeconds = totalFrames / fps;

  log.info("Starting FFmpeg GPU-accelerated render", {
    fps,
    totalFrames,
    durationSeconds,
    width: settings.resolution.width,
    height: settings.resolution.height,
    codec: settings.codec,
    container: settings.container,
  });

  if (totalFrames <= 0) {
    throw new Error("Composition has no duration");
  }

  if (signal?.aborted) {
    throw new DOMException("Render cancelled", "AbortError");
  }

  // --- Step 1: Create export job on backend ---
  onProgress({
    phase: "preparing",
    progress: 0,
    totalFrames,
    message: "Starting GPU encoder...",
  });

  const jobSettings: FFmpegJobSettings = {
    width: settings.resolution.width,
    height: settings.resolution.height,
    fps,
    totalFrames,
    codec: settings.codec,
    quality: settings.quality,
    container: settings.container,
    videoBitrate: settings.videoBitrate,
    audioBitrate: settings.audioBitrate,
  };

  const job = await createExportJob(jobSettings);
  const { jobId } = job;

  log.info("Export job created", { jobId });

  // Setup cancel handler
  const handleAbort = () => {
    cancelExportJob(jobId).catch(() => {});
  };
  signal?.addEventListener("abort", handleAbort, { once: true });

  try {
    // --- Step 2: Process audio in parallel ---
    onProgress({
      phase: "preparing",
      progress: 5,
      totalFrames,
      message: "Processing audio...",
    });

    let audioBlob: Blob | null = null;
    if (await hasAudioContent(composition)) {
      try {
        const audioData = await processAudio(composition, signal);
        if (audioData) {
          const audioBuffer = createAudioBuffer(audioData);
          audioBlob = audioBufferToWavBlob(audioBuffer);
          log.info("Audio processed", { size: audioBlob.size });
        }
      } catch (error) {
        log.error("Audio processing failed, continuing without audio", {
          error,
        });
      }
    }

    // --- Step 3: Setup canvas renderer ---
    onProgress({
      phase: "preparing",
      progress: 10,
      totalFrames,
      message: "Loading media...",
    });

    const compositionWidth = composition.width ?? settings.resolution.width;
    const compositionHeight = composition.height ?? settings.resolution.height;
    const exportWidth = settings.resolution.width;
    const exportHeight = settings.resolution.height;
    const needsScaling =
      exportWidth !== compositionWidth || exportHeight !== compositionHeight;

    const renderCanvas = new OffscreenCanvas(
      compositionWidth,
      compositionHeight,
    );
    const ctx = renderCanvas.getContext("2d");
    if (!ctx) {
      throw new Error("Failed to create OffscreenCanvas 2D context");
    }

    const outputCanvas = needsScaling
      ? new OffscreenCanvas(exportWidth, exportHeight)
      : renderCanvas;
    const outputCtx = needsScaling ? outputCanvas.getContext("2d")! : ctx;

    // Create composition renderer (same as existing export)
    const frameRenderer = await createCompositionRenderer(
      composition,
      renderCanvas,
      ctx,
    );
    await frameRenderer.preload();

    onProgress({
      phase: "preparing",
      progress: 15,
      totalFrames,
      message: "Media loaded, starting render...",
    });

    // --- Step 4: Render and send frames ---
    // We send frames one at a time via individual POST requests.
    // The backend buffers them and writes to FFmpeg stdin in order.

    const CONCURRENCY = 3; // Max in-flight frame uploads
    let inFlight = 0;
    const pendingUploads: Promise<void>[] = [];

    for (let frame = 0; frame < totalFrames; frame++) {
      if (signal?.aborted) {
        throw new DOMException("Render cancelled", "AbortError");
      }

      // Render frame to canvas
      await frameRenderer.renderFrame(frame);

      // Scale if needed
      if (needsScaling) {
        outputCtx.clearRect(0, 0, exportWidth, exportHeight);
        outputCtx.drawImage(renderCanvas, 0, 0, exportWidth, exportHeight);
      }

      // Extract raw RGBA pixels
      const imageData = outputCtx.getImageData(0, 0, exportWidth, exportHeight);
      const rgbaBuffer = imageData.data.buffer.slice(0); // Copy to avoid detach issues

      // Send frame to backend (with concurrency limiting)
      const uploadPromise = sendFrameToBackend(jobId, frame, rgbaBuffer);
      pendingUploads.push(uploadPromise);
      inFlight++;

      // Wait if we have too many in-flight
      if (inFlight >= CONCURRENCY) {
        await Promise.race(pendingUploads);
        // Remove completed promises by filtering for still-pending ones
        const checked = pendingUploads.map((p) => {
          let resolved = false;
          p.then(
            () => {
              resolved = true;
            },
            () => {
              resolved = true;
            },
          );
          return { p, resolved: () => resolved };
        });
        // Give microtask queue a tick to settle
        await new Promise((resolve) => setTimeout(resolve, 0));
        const stillPending = checked
          .filter((c) => !c.resolved())
          .map((c) => c.p);
        pendingUploads.length = 0;
        pendingUploads.push(...stillPending);
        inFlight = stillPending.length;
      }

      // Report progress
      const progress = Math.round((frame / totalFrames) * 85) + 10; // 10-95%
      onProgress({
        phase: "rendering",
        progress,
        currentFrame: frame,
        totalFrames,
        message: `Rendering frame ${frame + 1}/${totalFrames}`,
      });
    }

    // Wait for all remaining uploads
    await Promise.all(pendingUploads);

    // --- Step 5: Send audio data ---
    if (audioBlob) {
      onProgress({
        phase: "encoding",
        progress: 92,
        currentFrame: totalFrames,
        totalFrames,
        message: "Sending audio to encoder...",
      });

      await sendAudioData(jobId, audioBlob);
    }

    // --- Step 6: Finalize ---
    onProgress({
      phase: "finalizing",
      progress: 95,
      currentFrame: totalFrames,
      totalFrames,
      message: "Finalizing video...",
    });

    const finalResult = await finalizeExport(jobId);
    log.info("Export finalized", { fileSize: finalResult.fileSize });

    // --- Step 7: Download result ---
    onProgress({
      phase: "finalizing",
      progress: 97,
      currentFrame: totalFrames,
      totalFrames,
      message: "Downloading result...",
    });

    const blob = await downloadExport(jobId);

    onProgress({
      phase: "finalizing",
      progress: 100,
      currentFrame: totalFrames,
      totalFrames,
      message: "Complete!",
    });

    // Cleanup
    frameRenderer.dispose();
    clearAudioDecodeCache();

    return {
      blob,
      mimeType: getMimeType(settings.container, settings.codec),
      duration: durationSeconds,
      fileSize: blob.size,
    };
  } catch (error) {
    // Try to cancel the backend job on error
    cancelExportJob(jobId).catch(() => {});
    clearAudioDecodeCache();
    throw error;
  } finally {
    signal?.removeEventListener("abort", handleAbort);
  }
}

/**
 * Send a single frame to the backend using a simple JSON+base64 approach.
 * While not the most bandwidth-efficient, it's simple and reliable.
 */
async function sendFrameToBackend(
  jobId: string,
  frameIndex: number,
  rgbaData: ArrayBuffer,
): Promise<void> {
  // Convert to base64 for JSON transport
  const bytes = new Uint8Array(rgbaData);
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  const base64 = btoa(binary);

  const response = await fetch(`${BACKEND_URL}/api/ffmpeg/export-frame`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jobId,
      frameIndex,
      data: base64,
    }),
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(
      `Failed to send frame ${frameIndex}: ${error.error ?? error}`,
    );
  }
}
