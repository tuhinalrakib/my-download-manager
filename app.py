import os
import re
import uuid
import threading
import time
import shutil
import urllib.parse
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory download task tracking
tasks = {}

def init_cookies():
    """Generates and formats cookies.txt from YOUTUBE_COOKIES env variable if provided."""
    cookie_env = os.environ.get('YOUTUBE_COOKIES')
    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    if cookie_env:
        try:
            lines = cookie_env.strip().splitlines()
            formatted = ["# Netscape HTTP Cookie File"]
            for line in lines:
                l_str = line.strip()
                if not l_str or l_str.startswith('#') or 'Include Subdomains' in l_str:
                    continue
                parts = re.split(r'\t+|\s{2,}', l_str)
                if len(parts) >= 6:
                    if len(parts) == 6:
                        parts.append('')
                    formatted.append('\t'.join(parts[:7]))
                elif '\t' in l_str:
                    formatted.append(l_str)
            with open(cookie_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(formatted))
            print("Successfully initialized formatted cookies.txt from YOUTUBE_COOKIES env var!")
        except Exception as e:
            print(f"Failed to write YOUTUBE_COOKIES: {e}")

init_cookies()

def get_ffmpeg_path():
    # 1. Check if ffmpeg is in PATH
    if shutil.which('ffmpeg'):
        return None  # yt-dlp will automatically find it in PATH
    # 2. Check if ffmpeg.exe exists in app root folder or ffmpeg/bin
    local_ffmpeg = os.path.join(BASE_DIR, 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    local_ffmpeg_bin = os.path.join(BASE_DIR, 'ffmpeg', 'bin', 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg_bin):
        return local_ffmpeg_bin
    return False # Not installed

def clear_old_downloads(max_age_seconds=0):
    """Deletes downloaded files older than max_age_seconds (default 0 for instant cleanup), preserving active task files."""
    if os.path.exists(DOWNLOAD_DIR):
        now = time.time()
        # Protect files belonging to active running tasks
        active_task_ids = [t_id[:6] for t_id, task in tasks.items() if task.get('status') in ['starting', 'downloading', 'processing']]
        
        for filename in os.listdir(DOWNLOAD_DIR):
            if any(t_id in filename for t_id in active_task_ids):
                continue
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            try:
                if now - os.path.getmtime(file_path) >= max_age_seconds:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

def clean_filename(title):
    # Strip URL-unsafe and OS-unsafe characters including # % & + | \ / * ? : " < >
    cleaned = re.sub(r'[\\/*?:"<>|#%&+\n\r]', '', title)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or 'video'

def clean_error_message(err):
    err_str = str(err)
    # Strip ANSI color escape codes
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', err_str)
    # Remove repetitive ERROR: or [download] prefixes
    clean = re.sub(r'^ERROR:\s*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^\[download\]\s*Got error:\s*', '', clean, flags=re.IGNORECASE)
    if 'Unsupported URL' in clean:
        clean += ' | Tip: MovieBox / 123movienow links load dynamically with JS. Try inspecting F12 -> Network tab for direct .m3u8 stream links and paste that URL instead.'
    elif 'Sign in to confirm' in clean:
        clean += ' | Tip: Export valid YouTube cookies (with SID & LOGIN_INFO while logged in) and set YOUTUBE_COOKIES env var on Render.'
    return clean.strip()

@app.route('/')
def index():
    clear_old_downloads()
    return render_template('index.html')

@app.route('/api/clear', methods=['POST'])
def clear_downloads_api():
    clear_old_downloads(max_age_seconds=0)
    tasks.clear()
    return jsonify({'status': 'cleared', 'message': 'All download history and files cleared.'})

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'YouTube URL is required'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'no_color': True,
        'skip_download': True,
        'extract_flat': False,
        'socket_timeout': 30,
        'retries': 10,
        'nocheckcertificate': True,
        'js_runtimes': {'node': {}, 'deno': {}},
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'android', 'ios', 'mweb', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    }

    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Handle playlist vs single video
            if '_type' in info and info['_type'] == 'playlist':
                entries = info.get('entries', [])
                if not entries:
                    return jsonify({'error': 'Empty playlist'}), 400
                info = entries[0]

            formats = info.get('formats', [])
            
            # Collect video formats with audio or video-only
            video_options = []
            seen_res = set()
            
            # Top option: Maximum Available Quality
            video_options.append({
                'format_id': 'best',
                'resolution': 'best',
                'label': '⭐ Best Quality (Ultra HD 4K / 2K / 1080p Max)',
                'height': 9999,
                'ext': 'mp4',
                'size': 'Highest Quality'
            })

            for f in formats:
                height = f.get('height')
                fps = f.get('fps')
                format_note = str(f.get('format_note', '')).lower()
                
                # Fallback height from format_note for sites like Facebook
                if not height:
                    if 'hd' in format_note or 'high' in format_note or '1080' in format_note:
                        height = 1080
                    elif '720' in format_note:
                        height = 720
                    elif 'sd' in format_note or '480' in format_note:
                        height = 480
                    elif '360' in format_note:
                        height = 360

                fps_str = f"{int(fps)}fps " if (fps and isinstance(fps, (int, float)) and int(fps) > 30) else ""

                if height:
                    if height >= 2160:
                        label = f"🔥 2160p {fps_str}(4K Ultra HD)"
                    elif height >= 1440:
                        label = f"✨ 1440p {fps_str}(2K Quad HD)"
                    elif height >= 1080:
                        label = f"🌟 1080p {fps_str}(Full HD)"
                    elif height >= 720:
                        label = f"🎬 720p {fps_str}(HD)"
                    elif height >= 480:
                        label = f"📱 480p (Standard)"
                    else:
                        label = f"⚡ {height}p"

                    res_key = f"{height}p_{fps_str}"
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    
                    if res_key not in seen_res:
                        seen_res.add(res_key)
                        size_mb = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "Variable"
                        video_options.append({
                            'format_id': f.get('format_id'),
                            'resolution': f"{height}p",
                            'label': f"{label} - {size_mb}",
                            'height': height,
                            'ext': 'mp4',
                            'size': size_mb
                        })

            # Sort formats descending by height
            video_options = sorted(video_options, key=lambda x: x['height'], reverse=True)
            
            # Audio options
            audio_options = [
                {'format_id': 'bestaudio/best', 'label': 'MP3 High Quality (320kbps)', 'ext': 'mp3'},
                {'format_id': 'm4a', 'label': 'M4A Audio', 'ext': 'm4a'},
                {'format_id': 'wav', 'label': 'WAV Lossless Audio', 'ext': 'wav'}
            ]

            thumbnail = info.get('thumbnail') or (info.get('thumbnails')[-1]['url'] if info.get('thumbnails') else '')
            
            # Safe duration formatting
            duration_sec = info.get('duration')
            if duration_sec is not None:
                try:
                    duration_sec = int(duration_sec)
                    minutes, seconds = divmod(duration_sec, 60)
                    hours, minutes = divmod(minutes, 60)
                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
                except (ValueError, TypeError):
                    duration_str = "Video / Reel"
            else:
                duration_str = "Video / Reel"

            # Safe view count formatting
            view_cnt = info.get('view_count')
            if view_cnt is not None:
                try:
                    views_str = f"{int(view_cnt):,} views"
                except (ValueError, TypeError):
                    views_str = "Available"
            else:
                views_str = "Available"

            ffmpeg_status = get_ffmpeg_path() is not False

            response_data = {
                'title': info.get('title') or info.get('description') or 'Facebook Video / Reel',
                'channel': info.get('uploader') or info.get('channel') or info.get('extractor_key') or 'Facebook',
                'thumbnail': thumbnail,
                'duration': duration_str,
                'views': views_str,
                'video_options': video_options,
                'audio_options': audio_options,
                'ffmpeg_installed': ffmpeg_status,
                'url': url
            }
            return jsonify(response_data)
            
    except Exception as e:
        return jsonify({'error': f'Failed to fetch video info: {clean_error_message(e)}'}), 500


def run_download(task_id, url, format_type, quality_id):
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent_raw = d.get('_percent_str', '0%')
            clean_percent = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', percent_raw).strip()
            speed_raw = d.get('_speed_str', '0 B/s')
            clean_speed = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', speed_raw).strip()
            eta_raw = d.get('_eta_str', '0s')
            clean_eta = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', eta_raw).strip()

            tasks[task_id].update({
                'status': 'downloading',
                'progress': clean_percent,
                'speed': clean_speed,
                'eta': clean_eta
            })
        elif d['status'] == 'finished':
            tasks[task_id].update({
                'status': 'processing',
                'progress': '100%',
                'message': 'Finalizing file...'
            })

    output_template = os.path.join(DOWNLOAD_DIR, f'%(title)s_{task_id[:6]}.%(ext)s')
    ffmpeg_loc = get_ffmpeg_path()

    # Enhanced network resilience & retry configurations for yt-dlp
    network_opts = {
        'quiet': True,
        'no_color': True,
        'socket_timeout': 45,
        'retries': 20,
        'fragment_retries': 20,
        'skip_unavailable_fragments': True,
        'nocheckcertificate': True,
        'js_runtimes': {'node': {}, 'deno': {}},
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'android', 'ios', 'mweb', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    }

    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    if os.path.exists(cookie_path):
        network_opts['cookiefile'] = cookie_path

    if format_type == 'audio':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'progress_hooks': [progress_hook],
            **network_opts
        }
        if ffmpeg_loc is not False:
            if ffmpeg_loc:
                ydl_opts['ffmpeg_location'] = ffmpeg_loc
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': quality_id if quality_id in ['mp3', 'm4a', 'wav'] else 'mp3',
                'preferredquality': '192',
            }]
    else:
        # Check if FFmpeg is available
        if ffmpeg_loc is not False:
            # Full FFmpeg mode: can merge separate high quality video & audio streams
            if ffmpeg_loc:
                ydl_opts_ffmpeg = {'ffmpeg_location': ffmpeg_loc}
            else:
                ydl_opts_ffmpeg = {}
                
            if quality_id and quality_id != 'best':
                height = quality_id.replace('p', '')
                format_str = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
            else:
                format_str = 'bestvideo+bestaudio/best'

            ydl_opts = {
                'format': format_str,
                'outtmpl': output_template,
                'progress_hooks': [progress_hook],
                'merge_output_format': 'mp4',
                **network_opts,
                **ydl_opts_ffmpeg
            }
        else:
            # No FFmpeg mode: download single combined video+audio format (no merging needed!)
            if quality_id and quality_id != 'best':
                height = quality_id.replace('p', '')
                format_str = f"best[height<={height}][ext=mp4]/best[ext=mp4]/best"
            else:
                format_str = "best[ext=mp4]/best"

            ydl_opts = {
                'format': format_str,
                'outtmpl': output_template,
                'progress_hooks': [progress_hook],
                **network_opts
            }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Handle postprocessed audio extension change if ffmpeg used
            if format_type == 'audio' and ffmpeg_loc is not False:
                base, _ = os.path.splitext(filename)
                filename = f"{base}.{quality_id if quality_id in ['mp3', 'm4a', 'wav'] else 'mp3'}"
            else:
                base, ext = os.path.splitext(filename)
                if os.path.exists(f"{base}.mp4"):
                    filename = f"{base}.mp4"

            final_basename = os.path.basename(filename)
            safe_basename = clean_filename(final_basename)
            
            if safe_basename != final_basename:
                new_path = os.path.join(DOWNLOAD_DIR, safe_basename)
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(os.path.join(DOWNLOAD_DIR, final_basename), new_path)
                    final_basename = safe_basename
                except Exception as rename_err:
                    print(f"Rename error: {rename_err}")

            encoded_basename = urllib.parse.quote(final_basename)

            tasks[task_id].update({
                'status': 'completed',
                'progress': '100%',
                'filename': final_basename,
                'download_url': f'/api/file/{encoded_basename}'
            })
    except Exception as e:
        tasks[task_id].update({
            'status': 'failed',
            'error': clean_error_message(e)
        })



@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    format_type = data.get('format_type', 'video') # 'video' or 'audio'
    quality_id = data.get('quality', 'best')

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'status': 'starting',
        'progress': '0%',
        'speed': '0 B/s',
        'eta': 'Calculating...'
    }

    thread = threading.Thread(target=run_download, args=(task_id, url, format_type, quality_id))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id})


@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)


@app.route('/api/file/<path:filename>', methods=['GET'])
def download_file(filename):
    decoded_filename = urllib.parse.unquote(filename)
    file_path = os.path.join(DOWNLOAD_DIR, decoded_filename)

    if not os.path.exists(file_path):
        for item in os.listdir(DOWNLOAD_DIR):
            if item == decoded_filename or urllib.parse.unquote(item) == decoded_filename:
                decoded_filename = item
                file_path = os.path.join(DOWNLOAD_DIR, item)
                break
        else:
            return jsonify({'error': 'File not found or expired.'}), 404

    response = send_from_directory(DOWNLOAD_DIR, decoded_filename, as_attachment=True)

    @response.call_on_close
    def remove_file():
        def delayed_delete():
            time.sleep(3) # Wait 3s for browser download stream to complete
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Cleaned server temp file after device download: {file_path}")
            except Exception as e:
                print(f"Error removing temp file {file_path}: {e}")

        threading.Thread(target=delayed_delete, daemon=True).start()

    return response


if __name__ == '__main__':
    clear_old_downloads(max_age_seconds=0)
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print(f" YouTube Video Downloader Server Running on Port {port}!")
    print(f" Local URL: http://localhost:{port}")
    print("=" * 60)
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port)
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=False)

