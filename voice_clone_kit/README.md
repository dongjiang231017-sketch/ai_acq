# voice_clone_kit · 百炼声音克隆 + 话术批量试听

用授权录音克隆音色，把视频号团购电销话术批量合成 MP3 试听。当前包含 78 条已确认台词和 7 条待业务口径确认台词。

## 运行（一条命令）

```bash
cd ai_acq
python3 voice_clone_kit/clone_and_tts.py --lines lines.json
python3 voice_clone_kit/clone_and_tts.py --voice <已有音色ID> --lines lines_part2.json --no-compare
python3 voice_clone_kit/clone_and_tts.py --voice <已有音色ID> --lines lines_part3.json --no-compare
```

前置（多半已具备）：`pip install dashscope`、`brew install cloudflared`。API key 自动读 `backend/.env`。

## 话术批次

- `lines.json`：16 条开场白和主流程。
- `lines_part2.json`：32 条高频问答、收尾和特殊场景。
- `lines_part3.json`：30 条平台、价格、决策、信任、AI 兜底和回拨话术。
- `lines_part3_pending.json`：7 条待确认业务承诺，默认不合成。

## 产出

- `output/*.mp3` — 已合成的试听音频
- `output/voices.json` — 音色ID（v3.5-flash 与 v2 各一个，克隆免费）
- `output/manifest_*.json` — 文件↔台词对照

`output/`、授权声音样本和 Word 文档均是本地产物，不提交到源码 Git。

## 试听满意后接入外呼系统

`voice_id` 与模型绑定。用 v3.5-flash 的音色，需把 `backend/.env` 改为：

```
DASHSCOPE_VOICE_CLONE_MODEL=cosyvoice-v3.5-flash
DASHSCOPE_TTS_MODEL=cosyvoice-v3.5-flash
```

若不想动系统配置，直接用 v2 音色（系统现有配置即可用）。

## 其他

- 重跑只合成不重新克隆：`--voice <音色ID>`
- 换模型：`--model cosyvoice-v2`
- 费用：克隆本身免费；合成费用按实际模型和字符数计算
- 授权样本 `sample_for_clone.wav`：单声道 24kHz，做响度归一，仅本地使用
