# 牡丹非遗知识库

这是从 `panda_mudan` 中拆出的全新项目。旧项目只作为数据来源，本项目不依赖语音识别、TTS、PySide 或桌面端窗口逻辑。

## 数据结构

新数据集位于：

```text
data/processed/heritage_items.json
```

每条记录统一为：

```json
{
  "id": "h_xxxxxxxxxx",
  "title": "太极拳（陈氏太极拳）",
  "category": "传统体育、游艺与杂技",
  "summary": "摘要文本",
  "content": "资料原文",
  "aliases": [],
  "search_text": "用于检索的合并文本",
  "source": {
    "legacy_order": 1,
    "files": []
  }
}
```

这比旧格式更适合维护：标题、分类、摘要、正文、别名和来源都在同一条记录里。

## 启动

```powershell
cd D:\Projects\mudan_heritage_explorer
python -m pip install -r requirements.txt
python .\scripts\build_dataset.py
python .\app.py
```

默认本机地址：

```text
http://127.0.0.1:5050
```

默认会监听 `0.0.0.0:5050`，同一局域网设备可以访问：

```text
http://你的电脑内网IP:5050
```

例如本机 Wi-Fi IP 是 `192.168.1.2` 时，手机或另一台电脑访问：

```text
http://192.168.1.2:5050
```

如果无法访问，通常是 Windows 防火墙拦截了 Python，需要允许 Python 通过专用网络，或开放 `5050` 端口。

## AI 问答

默认不配置 API Key 也能使用本地依据式回答。要接入大模型，在 `.env` 中配置 OpenAI 兼容接口：

```text
AI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AI_MODEL=glm-4-flash
AI_TIMEOUT=60
AI_API_KEY=你的密钥
```

问答接口会先从本地数据集召回相关条目，再把资料交给模型生成回答。

## 数字人

页面内置轻量数字人面板，复用旧项目中的 `idle/greet/speak` 三段 MP4：

```text
static/media/mudan-idle.mp4
static/media/mudan-greet.mp4
static/media/mudan-speak.mp4
```

提问时自动切到检索状态，回答生成后切到说话状态。页面还提供浏览器语音播报开关，
可用系统自带中文语音朗读回答内容。

## 开发检查

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check src tests scripts app.py
python -m pytest -q
```

## 旧数据来源

默认从同级目录读取：

```text
D:\Projects\panda_mudan
```

可手动指定：

```powershell
python .\scripts\build_dataset.py --source-root D:\Projects\panda_mudan
```
