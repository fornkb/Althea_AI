import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from .errors import ComponentError, require


def beneath(data_dir, relative):
    root = Path(data_dir).resolve()
    path = (root / relative).resolve()
    require(not Path(relative).is_absolute() and path.is_relative_to(root), 'Audio path escapes data_dir.')
    return path


def run_tool(args, *, timeout=30):
    try:
        return subprocess.run(args, capture_output=True, check=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComponentError('INVALID_INPUT', 'Audio could not be decoded or inspected within the time limit.') from exc


def prepare_audio(local_path, settings):
    path = Path(local_path).resolve()
    require(path.is_file() and path.suffix.lower() in ('.mp3', '.wav'), 'Choose an existing MP3 or WAV file.', 'INVALID_INPUT')
    original_stat = path.stat()
    require(0 < path.stat().st_size <= min(settings.get('max_upload_bytes', 20*1024*1024),20*1024*1024), 'Audio must be nonempty and at most 20 MiB.', 'INVALID_INPUT')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    require(bool(ffmpeg and ffprobe), 'Install FFmpeg and add ffmpeg.exe and ffprobe.exe to PATH.', 'MISSING_AUDIO_TOOLS')
    result = run_tool([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(path)])
    try:
        info = json.loads(result.stdout)
        streams = info['streams']
        audio = [s for s in streams if s.get('codec_type') == 'audio']
        require(len(audio) == 1 and not any(s.get('codec_type') == 'video' and not s.get('disposition',{}).get('attached_pic') for s in streams), 'Require a single decodable audio stream.', 'INVALID_INPUT')
        stream = audio[0]
        require(isinstance(stream.get('channels'),int) and 1 <= stream['channels'] <= 8, 'Unsupported audio channel count; use one to eight channels.', 'INVALID_INPUT')
        duration = float(info.get('format',{}).get('duration', stream.get('duration',0)))
        require(math.isfinite(duration) and duration > 0, 'Invalid audio duration.', 'INVALID_INPUT')
        require(duration <= min(settings.get('max_audio_seconds',300),300), 'Audio exceeds the five-minute limit; shorten it before uploading.', 'AUDIO_TOO_LONG')
        format_names = set(info.get('format',{}).get('format_name','').split(','))
        require(bool(format_names & ({'wav'} if path.suffix.lower() == '.wav' else {'mp3'})), 'Audio extension does not match the decoded format.', 'INVALID_INPUT')
    except (KeyError, TypeError, ValueError) as exc:
        raise ComponentError('INVALID_INPUT', 'Malformed media probe result.') from exc
    # Decode each channel without downmixing; detect complete digital silence only.
    decoded = run_tool([ffmpeg,'-v','error','-i',str(path),'-map','0:a:0','-ar','16000','-f','s16le','-acodec','pcm_s16le','-'], timeout=settings.get('request_timeout_s',90))
    require(bool(decoded.stdout) and any(decoded.stdout), 'Audio is empty or digitally silent.', 'INVALID_INPUT')
    raw = path.read_bytes()
    final_stat = path.stat()
    require((original_stat.st_size,original_stat.st_mtime_ns)==(final_stat.st_size,final_stat.st_mtime_ns), 'Audio changed during validation; upload it again.', 'INVALID_INPUT')
    require(len(raw) <= 20*1024*1024, 'Audio changed during validation.', 'INVALID_INPUT')
    sha = hashlib.sha256(raw).hexdigest()
    root = Path(settings['data_dir']).resolve()
    destination = beneath(root, f'media/{sha}/original{path.suffix.lower()}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as handle:
            handle.write(raw)
    except FileExistsError:
        require(destination.read_bytes() == raw, 'Existing media content differs from its hash.', 'STORAGE_ERROR')
    codec = stream.get('codec_name','')
    derivative = destination
    # Keep all channels. Convert unusual WAV encodings only; MP3 and PCM WAV pass through.
    if path.suffix.lower() == '.wav' and codec != 'pcm_s16le':
        derivative = destination.with_name('api.wav')
        if not derivative.exists():
            run_tool([ffmpeg,'-v','error','-n','-i',str(destination),'-map','0:a:0','-c:a','pcm_s16le',str(derivative)], timeout=90)
    return dict(path=str(derivative), duration_s=round(duration,3), content_sha256=sha,
                audio_relpath=destination.relative_to(root).as_posix(), original_filename=path.name)
