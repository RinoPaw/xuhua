"""Host-side upgrade; credentials and authorization caches never leave the host."""
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

source = Path(sys.argv[1]).resolve()
base = Path('/opt/xfyun-wake')
sdk = base / 'vendor/Linux_ivw_e867a88f2_v1.0.11_v2.2.15-rc5'
backup = base / 'backups' / time.strftime('%Y%m%d%H%M%S')
backup.mkdir(parents=True, mode=0o700)
service = Path('/etc/systemd/system/xfyun-wake.service')
site = Path('/etc/nginx/sites-enabled/xuhua').resolve()
keywords = Path('/var/lib/xfyun-wake/keywords.txt')
for path in (base / 'wake-worker', base / 'server.py', service, site, keywords):
    shutil.copyfile(path, backup / path.name)
subprocess.run(['g++', '-O2', '-std=c++11', '-o', str(base / 'wake-worker.new'),
                str(source / 'wake_worker.cpp'), '-I' + str(sdk / 'include'),
                '-L' + str(sdk / 'libs'), '-laikit', '-lpthread', '-ldl',
                '-Wl,-rpath,' + str(sdk / 'libs')], check=True)
config = Path('/etc/xfyun-wake/service.env')
if not config.exists():
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, 'w') as file:
        file.write('WAKE_SERVICE_TOKEN=' + secrets.token_urlsafe(32) + '\n')
    os.chown(config, 0, pwd.getpwnam('xfwake').pw_gid)
private_token = dict(line.split('=', 1) for line in config.read_text().splitlines() if '=' in line)['WAKE_SERVICE_TOKEN']
app_env = Path('/etc/xuhua/xuhua.env')
current = app_env.read_text()
existing = dict(line.split('=', 1) for line in current.splitlines() if '=' in line and not line.startswith('#'))
updates = {'XF_WAKE_URL': 'ws://172.17.0.1:5052/api/wake', 'XF_WAKE_TOKEN': private_token,
           'XF_WAKE_TERMINAL_KEY': existing.get('XF_WAKE_TERMINAL_KEY') or secrets.token_urlsafe(24)}
lines = [line for line in current.splitlines() if line.split('=', 1)[0] not in updates]
app_env.write_text('\n'.join(lines) + '\n' + ''.join(f'{key}={value}\n' for key, value in updates.items()))
try:
    subprocess.run(['systemctl', 'stop', 'xfyun-wake'], check=True)
    os.replace(base / 'wake-worker.new', base / 'wake-worker')
    shutil.copyfile(source / 'wake_worker.cpp', base / 'wake_worker.cpp')
    shutil.copyfile(source / 'server.py', base / 'server.py')
    keywords.write_text('叙华;\n你好叙华;\n', encoding='utf-8')
    contents = service.read_text().replace('--host 127.0.0.1', '--host 172.17.0.1')
    if 'EnvironmentFile=/etc/xfyun-wake/service.env' not in contents:
        contents = contents.replace('[Service]\n', '[Service]\nEnvironmentFile=/etc/xfyun-wake/service.env\n')
    service.write_text(contents)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'start', 'xfyun-wake'], check=True)
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://172.17.0.1:5052/healthz', timeout=2) as response:
                health = json.load(response)
            if health['ready']:
                break
        except OSError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError('Wake service did not become ready')
    site.write_text(site.read_text().replace('http://127.0.0.1:5052/', 'http://172.17.0.1:5052/'))
    subprocess.run(['nginx', '-t'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    page = base / 'index.html'
    page_source = page.read_text().replace('小白小白', '叙华')
    if 'message.keyword ||' not in page_source:
        page_source = page_source.replace("message.result?.rlt?.[0]?.keyword", "message.keyword || message.result?.rlt?.[0]?.keyword")
    page.write_text(page_source)
    print(json.dumps({'ready': True, 'keywords': health['keywords'], 'backup': str(backup)}, ensure_ascii=False))
except Exception:
    subprocess.run(['systemctl', 'stop', 'xfyun-wake'])
    for path in (base / 'wake-worker', base / 'server.py', service, site, keywords):
        shutil.copyfile(backup / path.name, path)
    subprocess.run(['systemctl', 'daemon-reload'])
    subprocess.run(['systemctl', 'start', 'xfyun-wake'])
    subprocess.run(['systemctl', 'reload', 'nginx'])
    raise
