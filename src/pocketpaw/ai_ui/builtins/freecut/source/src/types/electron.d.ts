export interface OpencutFfmpeg {
  check: () => Promise<{
    available: boolean;
    version: string;
    path: string;
    hwAccel: { encoder: string; hwaccel: string; available: boolean };
  }>;
  probe: (filePath: string) => Promise<{
    duration: number;
    width: number;
    height: number;
    fps: number;
    codec: string;
    audioCodec: string | null;
    bitrate: number;
  }>;
  thumbnail: (filePath: string, timeSeconds: number) => Promise<string>;
  export: (options: {
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
  }) => Promise<void>;
  cancelExport: () => Promise<boolean>;
  onExportProgress: (callback: (progress: number) => void) => () => void;
}

export interface OpencutDialog {
  openFile: (options?: {
    title?: string;
    multiple?: boolean;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<string | string[] | null>;
  saveFile: (options?: {
    title?: string;
    defaultPath?: string;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<string | null>;
}

export interface OpencutShell {
  openExternal: (url: string) => Promise<void>;
  showItemInFolder: (fullPath: string) => Promise<void>;
}

export interface OpencutFs {
  writeFile: (filePath: string, data: ArrayBuffer) => Promise<boolean>;
}

declare global {
  interface Window {
    opencut?: {
      dialog: OpencutDialog;
      shell: OpencutShell;
      ffmpeg: OpencutFfmpeg;
      fs: OpencutFs;
    };
  }
}
