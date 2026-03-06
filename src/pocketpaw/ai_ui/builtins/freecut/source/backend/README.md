# FreeCut Python Backend

This directory contains the Python backend for the FreeCut video editor. The backend handles:

- FFmpeg operations (probe, thumbnail generation, video export)
- Hardware acceleration detection and usage
- File system operations

## Requirements

- Python 3.11+
- FFmpeg (must be installed on the system)

## Setup with uv

1. Install uv if not already installed:

   ```bash
   pip install uv
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

   Or using requirements.txt:

   ```bash
   uv pip install -r requirements.txt
   ```

## Running the Backend

### Development

```bash
uv run python main.py
```

The backend will start on `http://127.0.0.1:4848` by default.

### Environment Variables

Create a `.env` file (copy from `.env.example`) to customize:

- `PYTHON_HOST` - Server host (default: 127.0.0.1)
- `PYTHON_PORT` - Server port (default: 4848)

## API Endpoints

| Endpoint                     | Method | Description                                         |
| ---------------------------- | ------ | --------------------------------------------------- |
| `/`                          | GET    | Health check                                        |
| `/ffmpeg/check`              | POST   | Check FFmpeg availability and hardware acceleration |
| `/ffmpeg/probe`              | POST   | Probe media file for properties                     |
| `/ffmpeg/thumbnail`          | POST   | Generate thumbnail from video                       |
| `/ffmpeg/export`             | POST   | Export video with options                           |
| `/ffmpeg/cancel-export`      | POST   | Cancel active export                                |
| `/ffmpeg/progress`           | GET    | Get export progress                                 |
| `/dialog/open-file`          | POST   | Open file dialog (handled by Electron)              |
| `/dialog/save-file`          | POST   | Save file dialog (handled by Electron)              |
| `/shell/open-external`       | POST   | Open URL in browser                                 |
| `/shell/show-item-in-folder` | POST   | Show file in explorer                               |
| `/fs/write-file`             | POST   | Write file to disk                                  |

## FFmpeg Requirements

The backend requires FFmpeg to be installed on the system:

- **Windows**: Download from https://ffmpeg.org/download.html or use package managers
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg` or equivalent

The backend will automatically detect FFmpeg in:

1. Local `bin/` directory (for bundled FFmpeg)
2. System PATH

## Hardware Acceleration

The backend automatically detects and uses hardware acceleration when available:

- **Windows**: NVIDIA NVENC, AMD AMF, Intel QuickSync
- **macOS**: VideoToolbox
- **Linux**: NVIDIA NVENC, VAAPI
