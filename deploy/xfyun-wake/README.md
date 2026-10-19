# Persona 云端唤醒部署

此目录保存独立宿主机服务的源码，不包含供应商 SDK、凭据或授权文件。
服务器已有经 MD5 核验的 AIKit Linux SDK，安装器复用 `/opt/xfyun-wake/vendor/`。

## 升级现有服务

把本目录文件传到服务器的临时目录，然后以 root 执行：

```sh
python3 /home/ubuntu/wake-deploy/install.py /home/ubuntu/wake-deploy
```

安装器备份程序、关键词、systemd 和 Nginx 配置，保留设备授权缓存。
健康检查失败则恢复旧文件。服务只监听宿主机 Docker bridge 地址 `172.17.0.1:5052`。
叙华 Docker 容器通过 `XF_WAKE_URL` 连接它；公网由叙华的 `/api/wake` 代理。

私有配置：

- `/etc/xfyun-wake/credentials.env`：讯飞应用凭据。
- `/etc/xfyun-wake/service.env`：内部认证 `WAKE_SERVICE_TOKEN`；可选 `WAKE_THRESHOLDS`。
- `/etc/xuhua/xuhua.env`：安装器写入 `XF_WAKE_URL`、`XF_WAKE_TOKEN`、`XF_WAKE_TERMINAL_KEY`。

`XF_WAKE_TERMINAL_KEY` 通过 `/persona#wake=...` 交给指定展示终端一次。
页面将其兑换为 HttpOnly、SameSite=Strict 的 30 天终端 Cookie，并清除地址片段。
普通访客不会自动采音或占用引擎。需要轮换访问时更换终端 key 并重启叙华容器，旧 Cookie 随即失效。
同一时间只支持一个终端；对话期间通过暂停检测和心跳继续持有该终端的引擎租约。
独立测试页依然有 120 秒限制，正式入口通过内部凭据获得长连接，二者不能同时占用。

## 检查

```sh
systemctl status xfyun-wake
curl --noproxy '*' -fsS http://172.17.0.1:5052/healthz
journalctl -u xfyun-wake -n 30 --no-pager
```

`smoke.py` 使用 `/home/ubuntu/wake-deploy/` 下的私有合成测试 PCM：
`short.pcm`、`long.pcm`、`question.pcm`、`negative.pcm`。
它检查两种唤醒词、连说问题、负样本、占用拒绝、暂停/恢复和超过 120 秒的心跳。
测试时会占用引擎。合成测试不能替代真人识别率测试。

授权后的 `GET /api/wake/metrics` 返回自进程启动起最近 24 小时、最多 2000 次尝试的均值和 P50/P95。
唤醒回应与普通问答分开统计；未播放的失败/取消不记为 0 毫秒，并单独计数。
不保存音频，指标缓存随服务重启清空。

回滚前端检测方式：移除叙华环境中的 `XF_WAKE_URL` 并重建/重启容器，即恢复原 Sherpa 路径。
