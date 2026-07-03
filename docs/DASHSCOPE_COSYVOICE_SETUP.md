# DashScope / CosyVoice 声音复刻接入

声音档案支持接入 DashScope CosyVoice 作为真实复刻服务。密钥只通过环境变量读取，不写入 Git。

## 配置

在 `backend/.env` 中配置：

```env
VOICE_CLONE_TRAINING_ENABLED=true
VOICE_CLONE_PROVIDER=dashscope
VOICE_CLONE_ENGINE_NAME=DashScope CosyVoice
DASHSCOPE_API_KEY=your-dashscope-api-key
DASHSCOPE_VOICE_CLONE_MODEL=cosyvoice-v2
DASHSCOPE_TTS_MODEL=cosyvoice-v2
DASHSCOPE_SYSTEM_TTS_MODEL=qwen3-tts-flash
DASHSCOPE_SYSTEM_TTS_LANGUAGE_TYPE=Chinese
DASHSCOPE_VOICE_PREFIX=aiacq
DASHSCOPE_VOICE_LANGUAGE_HINTS=zh
VOICE_SAMPLE_PUBLIC_BASE_URL=https://your-public-api-host
```

`VOICE_SAMPLE_PUBLIC_BASE_URL` 必须是 DashScope 能访问到的 API 域名。DashScope 创建音色时需要一个可公网访问的录音 URL，本地 `127.0.0.1` 或 `localhost` 不能被阿里云访问。本地内测可用 ngrok、cloudflared 或部署测试 API 域名指向后端。

## 验证

不打印 API Key 的连通性检查：

```bash
curl "http://127.0.0.1:8017/api/voice/provider/status?probe=true"
```

正常时会返回 `ready=true` 或明确提示缺少 Key、公网样本地址、连接失败原因。

## 复刻流程

1. 在声音档案上传客户/员工授权录音。
2. 授权审核通过。
3. 打开 `音色复刻`，点击 `生成复刻`。
4. 后端调用 DashScope `VoiceEnrollmentService.create_voice` 获取 `voice_id`。
5. 后端调用 CosyVoice TTS 生成一段试听音频，写入克隆语音记录。

试听音频保存在 `.voice_outputs/`，录音样本保存在 `.voice_samples/`，二者都被 `.gitignore` 忽略。

系统内置音色试听使用 Qwen-TTS 预置音色，点击试听时会调用 `DASHSCOPE_SYSTEM_TTS_MODEL` 配置的模型并使用该音色的官方 `voice` 参数生成音频 URL；默认按中文文本传入 `DASHSCOPE_SYSTEM_TTS_LANGUAGE_TYPE=Chinese`。
