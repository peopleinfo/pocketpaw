import { X, Video, FileAudio, Image as ImageIcon, Film, Clock, Maximize2, HardDrive, FileType } from 'lucide-react';
import type { MediaMetadata } from '@/types/storage';
import { getMediaType, formatDuration } from '../utils/validation';
import { formatBytes } from '@/utils/format-utils';

interface MediaInfoPanelProps {
  media: MediaMetadata;
  onClose: () => void;
}

export function MediaInfoPanel({ media, onClose }: MediaInfoPanelProps) {
  const mediaType = getMediaType(media.mimeType);

  const typeIcon = mediaType === 'video'
    ? <Video className="w-3.5 h-3.5 text-primary" />
    : mediaType === 'audio'
    ? <FileAudio className="w-3.5 h-3.5 text-green-500" />
    : <ImageIcon className="w-3.5 h-3.5 text-blue-500" />;

  const typeLabel = mediaType === 'video' ? 'Video' : mediaType === 'audio' ? 'Audio' : 'Image';

  const rows: Array<{ icon: React.ReactNode; label: string; value: string }> = [];

  // Type
  rows.push({ icon: <FileType className="w-3 h-3" />, label: 'Type', value: `${typeLabel} (${media.mimeType.split('/')[1]})` });

  // Duration (video/audio only)
  if ((mediaType === 'video' || mediaType === 'audio') && media.duration > 0) {
    rows.push({ icon: <Clock className="w-3 h-3" />, label: 'Duration', value: formatDuration(media.duration) });
  }

  // Dimensions (video/image only)
  if ((mediaType === 'video' || mediaType === 'image') && media.width > 0 && media.height > 0) {
    rows.push({ icon: <Maximize2 className="w-3 h-3" />, label: 'Dimensions', value: `${media.width} × ${media.height}` });
  }

  // Codec (video/audio)
  if (media.codec && media.codec !== 'importing...') {
    let codecStr = media.codec;
    if (media.audioCodec) codecStr += ` / ${media.audioCodec}`;
    rows.push({ icon: <Film className="w-3 h-3" />, label: 'Codec', value: codecStr });
  }

  // File size
  rows.push({ icon: <HardDrive className="w-3 h-3" />, label: 'Size', value: formatBytes(media.fileSize) });

  // FPS (video only)
  if (mediaType === 'video' && media.fps > 0) {
    rows.push({ icon: <Film className="w-3 h-3" />, label: 'Frame Rate', value: `${media.fps} fps` });
  }

  return (
    <div className="border-t border-border bg-panel-bg flex-shrink-0
      animate-in slide-in-from-bottom-4 duration-300 ease-out">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border/50">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          {typeIcon}
          <span className="text-[11px] font-medium text-foreground truncate">
            {media.fileName}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-0.5 rounded hover:bg-foreground/10 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
          title="Close info"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {/* Info rows */}
      <div className="p-3 space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2 text-[10px]">
            <span className="text-muted-foreground flex-shrink-0">{row.icon}</span>
            <span className="text-muted-foreground w-16 flex-shrink-0">{row.label}</span>
            <span className="text-foreground truncate">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
