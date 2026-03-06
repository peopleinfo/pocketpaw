/**
 * FreeCut API Client
 * Provides the same interface as window.opencut but uses HTTP to communicate with Python backend.
 * Works in both browser and Electron environments.
 */

const API_BASE = "/api";

// Type definitions matching the backend
export interface FFmpegCheckResult {
  available: boolean;
  version: string;
  path: string;
  hwAccel: { encoder: string; hwaccel: string; available: boolean };
}

export interface ProbeResult {
  duration: number;
  width: number;
  height: number;
  fps: number;
  codec: string;
  audioCodec: string | null;
  bitrate: number;
}

export interface ExportOptions {
  inputPath: string;
  outputPath: string;
  startTimeSeconds?: number;
  durationSeconds?: number;
  width?: number;
  height?: number;
  fps?: number;
  format: "mp4" | "webm" | "mov";
  quality: "low" | "medium" | "high" | "very_high";
  useHardwareAccel?: boolean;
}

// Helper function to make API requests
async function apiRequest<T>(
  endpoint: string,
  method: string = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }

  return response.json();
}

// FFmpeg API
export const ffmpeg = {
  check: (): Promise<FFmpegCheckResult> =>
    apiRequest<FFmpegCheckResult>("/ffmpeg/check", "GET"),

  probe: (filePath: string): Promise<ProbeResult> =>
    apiRequest<ProbeResult>("/ffmpeg/probe", "POST", { filePath }),

  thumbnail: (
    filePath: string,
    timeSeconds: number,
  ): Promise<{ thumbnail: string }> =>
    apiRequest("/ffmpeg/thumbnail", "POST", { filePath, timeSeconds }),

  export: async (
    options: ExportOptions,
    onProgress?: (progress: number) => void,
  ): Promise<void> => {
    // Set up progress polling
    let progressInterval: ReturnType<typeof setInterval> | null = null;

    if (onProgress) {
      progressInterval = setInterval(async () => {
        try {
          const result: { progress: number } = await apiRequest(
            "/ffmpeg/progress",
            "GET",
          );
          onProgress(result.progress || 0);
        } catch {
          // Ignore progress polling errors
        }
      }, 100);
    }

    try {
      await apiRequest("/ffmpeg/export", "POST", options);
      onProgress?.(1);
    } finally {
      if (progressInterval) {
        clearInterval(progressInterval);
      }
    }
  },

  cancelExport: (): Promise<{ success: boolean }> =>
    apiRequest("/ffmpeg/cancel-export", "POST"),

  onExportProgress: (_callback: (progress: number) => void): (() => void) => {  // eslint-disable-line @typescript-eslint/no-unused-vars
    // For HTTP-based implementation, polling is handled in export()
    // This is a no-op to maintain API compatibility
    return () => { };
  },
};

// File dialog API
// Note: In browser, we use the File System Access API or simple download
export const dialog = {
  openFile: async (options?: {
    title?: string;
    multiple?: boolean;
    filters?: { name: string; extensions: string[] }[];
  }): Promise<string | string[] | null> => {
    // Use browser File System Access API if available
    if ("showOpenFilePicker" in window) {
      try {
        const handles = await (window as any).showOpenFilePicker({
          multiple: options?.multiple || false,
          types: options?.filters?.map((f) => ({
            description: f.name,
            accept: { "*": f.extensions.map((e) => `.${e}`) },
          })) || [
              {
                description: "All Files",
                accept: { "*": ["*"] },
              },
            ],
        });

        // Get file paths from handles (Chromium only)
        if (options?.multiple) {
          return handles.map((h: any) => h.name || "");
        }
        return handles[0]?.name || "";
      } catch {
        return null;
      }
    }

    // Fallback: Use hidden file input
    return new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = options?.multiple || false;

      if (options?.filters?.length) {
        input.accept = options.filters
          .flatMap((f) => f.extensions.map((e) => `.${e}`))
          .join(",");
      }

      input.onchange = () => {
        if (input.files?.length) {
          if (options?.multiple) {
            resolve(Array.from(input.files).map((f) => f.name));
          } else {
            resolve(input.files?.[0]?.name ?? null);
          }
        } else {
          resolve(null);
        }
      };

      input.click();
    });
  },

  saveFile: async (options?: {
    title?: string;
    defaultPath?: string;
    filters?: { name: string; extensions: string[] }[];
  }): Promise<string | null> => {
    // Use browser File System Access API if available
    if ("showSaveFilePicker" in window) {
      try {
        const handle = await (window as any).showSaveFilePicker({
          suggestedName: options?.defaultPath,
          types: options?.filters?.map((f) => ({
            description: f.name,
            accept: { "*": f.extensions.map((e) => `.${e}`) },
          })) || [
              {
                description: "All Files",
                accept: { "*": ["*"] },
              },
            ],
        });

        return handle.name || "";
      } catch {
        return null;
      }
    }

    // For browsers without File System Access API,
    // the download will be handled by the export process
    return options?.defaultPath || null;
  },
};

// Shell API (limited in browser)
export const shell = {
  openExternal: async (url: string): Promise<void> => {
    window.open(url, "_blank");
  },

  showItemInFolder: async (fullPath: string): Promise<void> => {
    // Not available in browser - could show download prompt instead
    console.warn("showItemInFolder not available in browser:", fullPath);
  },
};

// File system API (limited in browser)
export const fs = {
  writeFile: async (filePath: string, data: ArrayBuffer): Promise<boolean> => {
    // In browser, use File System Access API or download
    if ("showSaveFilePicker" in window) {
      try {
        const handle = await (window as any).showSaveFilePicker({
          suggestedName: filePath.split(/[\\/]/).pop(),
        });
        const writable = await handle.createWritable();
        await writable.write(data);
        await writable.close();
        return true;
      } catch {
        return false;
      }
    }

    // Fallback: trigger download
    const blob = new Blob([data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filePath.split(/[\\/]/).pop() || "download";
    a.click();
    URL.revokeObjectURL(url);
    return true;
  },
};

// Export the complete API object matching window.opencut interface
export const opencut = {
  dialog,
  shell,
  ffmpeg,
  fs,
};

// Auto-detect and use the appropriate API
export function getApi() {
  // Check if we're in Electron (has opencut on window)
  if (typeof window !== "undefined" && window.opencut) {
    return window.opencut;
  }

  // Otherwise use HTTP API
  return opencut;
}

export default opencut;
