#!/usr/bin/env python3
import os
import sys
import time
import subprocess

REG_KEY   = r'Software\Microsoft\Windows\CurrentVersion\Run'
REG_NAME  = 'WindowsSecurityHost'
INSTALL_DIR = os.path.join(os.environ.get('APPDATA',''), 'Microsoft', 'WindowsHost')
INSTALL_EXE = os.path.join(INSTALL_DIR, 'svchost32.exe')


def remove_startup():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, REG_NAME)
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def kill_agent():
    try:
        import psutil
        current = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['pid'] == current:
                    continue
                exe = (proc.info['exe'] or '').lower()
                if 'svchost32' in exe or 'windowshost' in exe:
                    proc.kill()
            except Exception:
                pass
    except Exception:
        pass


def remove_files():
    bat = os.path.join(os.environ.get('TEMP', ''), '_rd_clean.bat')
    with open(bat, 'w') as f:
        f.write(
            f'@echo off\ntimeout /t 2 /nobreak >nul\n'
            f'del /f /q "{INSTALL_EXE}" >nul 2>&1\n'
            f'rmdir /q "{INSTALL_DIR}" >nul 2>&1\n'
            f'del /f /q "%~f0"\n'
        )
    subprocess.Popen(['cmd.exe', '/c', bat], creationflags=0x08000008)


def main():
    remove_startup()
    kill_agent()
    time.sleep(1)
    remove_files()


if __name__ == '__main__':
    main()
