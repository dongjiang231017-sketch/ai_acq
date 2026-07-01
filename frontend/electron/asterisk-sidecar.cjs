const crypto = require("crypto");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const DEFAULTS = {
  amiUsername: "ai_acq",
  amiPort: 5038,
  sipPort: 5060,
  rtpStart: 10000,
  rtpEnd: 10100,
  trunkName: "uc100",
  voiceGatewayProfile: "uc100_sip_volte",
  voiceGatewayLabel: "语音网关（UC100 测试档案）",
  voiceGatewayHost: "192.168.10.100",
  voiceGatewaySipPort: 5080,
  asteriskAdvertisedHost: "",
  asteriskLocalNet: "172.16.0.0/12",
  maxChannels: 1,
  audioSocketHost: "127.0.0.1",
  audioSocketPort: 9019,
};

function createAsteriskSidecar(options) {
  return new AsteriskSidecar(options);
}

class AsteriskSidecar {
  constructor(options = {}) {
    this.userDataDir = path.resolve(options.userDataDir || path.join(os.homedir(), ".ai-acq-client"));
    this.managedProcess = null;
    this.lastExit = null;
  }

  async status() {
    const layout = this.ensureLayout();
    const runtime = this.resolveRuntime();
    const running = this.isManagedRunning();
    const amiReachable = await isTcpOpen("127.0.0.1", layout.state.amiPort, 350);
    const audioSocketReachable = await isTcpOpen(layout.state.audioSocketHost, layout.state.audioSocketPort, 350);
    const checks = this.buildChecks({ layout, runtime, running, amiReachable, audioSocketReachable });
    return {
      deliveryMode: "client-sidecar",
      runtimeMode: runtime.mode,
      runtimeFound: runtime.found,
      runtimePath: runtime.safePath,
      status: amiReachable ? "running" : running ? "starting" : runtime.found ? "stopped" : "blocked",
      running: running || amiReachable,
      managedPid: this.managedProcess?.pid ?? null,
      amiHost: "127.0.0.1",
      amiPort: layout.state.amiPort,
      sipPort: layout.state.sipPort,
      trunkName: layout.state.trunkName,
      voiceGatewayProfile: layout.state.voiceGatewayProfile,
      voiceGatewayLabel: layout.state.voiceGatewayLabel,
      voiceGatewayHost: layout.state.voiceGatewayHost,
      voiceGatewaySipPort: layout.state.voiceGatewaySipPort,
      voiceGatewayRegisterEnabled: Boolean(layout.state.voiceGatewaySipUsername && layout.state.voiceGatewaySipPassword),
      uc100Host: layout.state.uc100Host,
      uc100SipPort: layout.state.uc100SipPort,
      uc100RegisterEnabled: Boolean(layout.state.voiceGatewaySipUsername && layout.state.voiceGatewaySipPassword),
      asteriskAdvertisedHost: layout.state.asteriskAdvertisedHost,
      asteriskLocalNet: layout.state.asteriskLocalNet,
      maxChannels: layout.state.maxChannels,
      audioSocketHost: layout.state.audioSocketHost,
      audioSocketPort: layout.state.audioSocketPort,
      audioSocketReachable,
      configDir: layout.configDir,
      stateDir: layout.stateDir,
      backendEnvPath: layout.backendEnvPath,
      backendEnvReady: fs.existsSync(layout.backendEnvPath),
      checks,
      lastExit: this.lastExit,
      nextStep: this.nextStep({ runtime, running, amiReachable, audioSocketReachable, layout }),
    };
  }

  async start() {
    const layout = this.ensureLayout();
    const runtime = this.resolveRuntime();
    if (!runtime.found) {
      return this.status();
    }
    if (this.isManagedRunning() || (await isTcpOpen("127.0.0.1", layout.state.amiPort, 350))) {
      return this.status();
    }

    this.managedProcess = spawn(runtime.path, ["-f", "-C", layout.asteriskConfPath], {
      cwd: layout.baseDir,
      detached: false,
      env: { ...process.env, ASTERISK_CONSOLE: "no" },
      stdio: "ignore",
    });
    this.managedProcess.once("exit", (code, signal) => {
      this.lastExit = { code, signal, at: new Date().toISOString() };
      this.managedProcess = null;
    });
    this.managedProcess.unref();
    await sleep(600);
    return this.status();
  }

  async stop() {
    if (this.isManagedRunning()) {
      this.managedProcess.kill("SIGTERM");
      await sleep(500);
      if (this.isManagedRunning()) this.managedProcess.kill("SIGKILL");
    }
    return this.status();
  }

  ensureLayout() {
    const baseDir = path.join(this.userDataDir, "asterisk-sidecar");
    const configDir = path.join(baseDir, "etc");
    const stateDir = path.join(baseDir, "state");
    const spoolDir = path.join(baseDir, "spool");
    const logDir = path.join(baseDir, "log");
    const runDir = path.join(baseDir, "run");
    const dataDir = path.join(baseDir, "data");
    const keyDir = path.join(baseDir, "keys");
    for (const dir of [baseDir, configDir, stateDir, spoolDir, logDir, runDir, dataDir, keyDir]) {
      fs.mkdirSync(dir, { recursive: true });
    }

    const statePath = path.join(stateDir, "sidecar.json");
    const state = this.loadOrCreateState(statePath);
    const asteriskConfPath = path.join(configDir, "asterisk.conf");
    const backendEnvPath = path.join(stateDir, "backend-asterisk.env");
    this.writeConfigs({
      asteriskConfPath,
      backendEnvPath,
      baseDir,
      configDir,
      dataDir,
      keyDir,
      logDir,
      runDir,
      spoolDir,
      stateDir,
      state,
    });

    return {
      baseDir,
      configDir,
      stateDir,
      spoolDir,
      logDir,
      runDir,
      dataDir,
      keyDir,
      statePath,
      backendEnvPath,
      asteriskConfPath,
      state,
    };
  }

  loadOrCreateState(statePath) {
    const existing = readJson(statePath);
    const state = {
      amiUsername: DEFAULTS.amiUsername,
      amiPassword: crypto.randomBytes(18).toString("hex"),
      amiPort: DEFAULTS.amiPort,
      sipPort: DEFAULTS.sipPort,
      rtpStart: DEFAULTS.rtpStart,
      rtpEnd: DEFAULTS.rtpEnd,
      trunkName: process.env.AI_ACQ_VOICE_GATEWAY_TRUNK_NAME || DEFAULTS.trunkName,
      voiceGatewayProfile: process.env.AI_ACQ_VOICE_GATEWAY_PROFILE || DEFAULTS.voiceGatewayProfile,
      voiceGatewayLabel: process.env.AI_ACQ_VOICE_GATEWAY_LABEL || DEFAULTS.voiceGatewayLabel,
      voiceGatewayHost: process.env.AI_ACQ_VOICE_GATEWAY_HOST || process.env.AI_ACQ_UC100_HOST || DEFAULTS.voiceGatewayHost,
      voiceGatewaySipPort: Number(process.env.AI_ACQ_VOICE_GATEWAY_SIP_PORT || process.env.AI_ACQ_UC100_SIP_PORT || DEFAULTS.voiceGatewaySipPort),
      voiceGatewaySipUsername: process.env.AI_ACQ_VOICE_GATEWAY_SIP_USERNAME || process.env.AI_ACQ_UC100_SIP_USERNAME || "",
      voiceGatewaySipPassword: process.env.AI_ACQ_VOICE_GATEWAY_SIP_PASSWORD || process.env.AI_ACQ_UC100_SIP_PASSWORD || "",
      asteriskAdvertisedHost: process.env.AI_ACQ_ASTERISK_ADVERTISED_HOST || DEFAULTS.asteriskAdvertisedHost,
      asteriskLocalNet: process.env.AI_ACQ_ASTERISK_LOCAL_NET || DEFAULTS.asteriskLocalNet,
      maxChannels: Number(process.env.AI_ACQ_VOICE_GATEWAY_MAX_CHANNELS || process.env.AI_ACQ_ASTERISK_MAX_CHANNELS || DEFAULTS.maxChannels),
      audioSocketHost: process.env.AI_ACQ_AUDIOSOCKET_HOST || DEFAULTS.audioSocketHost,
      audioSocketPort: Number(process.env.AI_ACQ_AUDIOSOCKET_PORT || DEFAULTS.audioSocketPort),
      audioSocketUuid: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      ...(existing || {}),
    };
    if (!state.voiceGatewayHost && state.uc100Host) state.voiceGatewayHost = state.uc100Host;
    if (!state.voiceGatewaySipPort && state.uc100SipPort) state.voiceGatewaySipPort = state.uc100SipPort;
    if (!state.voiceGatewaySipUsername && state.uc100SipUsername) state.voiceGatewaySipUsername = state.uc100SipUsername;
    if (!state.voiceGatewaySipPassword && state.uc100SipPassword) state.voiceGatewaySipPassword = state.uc100SipPassword;
    if (process.env.AI_ACQ_VOICE_GATEWAY_PROFILE) state.voiceGatewayProfile = process.env.AI_ACQ_VOICE_GATEWAY_PROFILE;
    if (process.env.AI_ACQ_VOICE_GATEWAY_LABEL) state.voiceGatewayLabel = process.env.AI_ACQ_VOICE_GATEWAY_LABEL;
    if (process.env.AI_ACQ_VOICE_GATEWAY_TRUNK_NAME) state.trunkName = process.env.AI_ACQ_VOICE_GATEWAY_TRUNK_NAME;
    if (process.env.AI_ACQ_VOICE_GATEWAY_HOST || process.env.AI_ACQ_UC100_HOST) {
      state.voiceGatewayHost = process.env.AI_ACQ_VOICE_GATEWAY_HOST || process.env.AI_ACQ_UC100_HOST;
    }
    if (process.env.AI_ACQ_VOICE_GATEWAY_SIP_PORT || process.env.AI_ACQ_UC100_SIP_PORT) {
      state.voiceGatewaySipPort = Number(process.env.AI_ACQ_VOICE_GATEWAY_SIP_PORT || process.env.AI_ACQ_UC100_SIP_PORT);
    }
    if (
      Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_VOICE_GATEWAY_SIP_USERNAME") ||
      Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_UC100_SIP_USERNAME")
    ) {
      state.voiceGatewaySipUsername = process.env.AI_ACQ_VOICE_GATEWAY_SIP_USERNAME || process.env.AI_ACQ_UC100_SIP_USERNAME || "";
    }
    if (
      Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_VOICE_GATEWAY_SIP_PASSWORD") ||
      Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_UC100_SIP_PASSWORD")
    ) {
      state.voiceGatewaySipPassword = process.env.AI_ACQ_VOICE_GATEWAY_SIP_PASSWORD || process.env.AI_ACQ_UC100_SIP_PASSWORD || "";
    }
    state.uc100Host = state.voiceGatewayHost;
    state.uc100SipPort = state.voiceGatewaySipPort;
    state.uc100SipUsername = state.voiceGatewaySipUsername;
    state.uc100SipPassword = state.voiceGatewaySipPassword;
    if (Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_ASTERISK_ADVERTISED_HOST")) {
      state.asteriskAdvertisedHost = process.env.AI_ACQ_ASTERISK_ADVERTISED_HOST || "";
    }
    if (process.env.AI_ACQ_ASTERISK_LOCAL_NET) state.asteriskLocalNet = process.env.AI_ACQ_ASTERISK_LOCAL_NET;
    if (process.env.AI_ACQ_VOICE_GATEWAY_MAX_CHANNELS || process.env.AI_ACQ_ASTERISK_MAX_CHANNELS) {
      state.maxChannels = Number(process.env.AI_ACQ_VOICE_GATEWAY_MAX_CHANNELS || process.env.AI_ACQ_ASTERISK_MAX_CHANNELS);
    }
    if (process.env.AI_ACQ_AUDIOSOCKET_HOST) state.audioSocketHost = process.env.AI_ACQ_AUDIOSOCKET_HOST;
    if (process.env.AI_ACQ_AUDIOSOCKET_PORT) state.audioSocketPort = Number(process.env.AI_ACQ_AUDIOSOCKET_PORT);
    fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
    return state;
  }

  writeConfigs(paths) {
    const { state } = paths;
    const gatewayRegisterEnabled = Boolean(state.voiceGatewaySipUsername && state.voiceGatewaySipPassword);
    const advertisedTransport = state.asteriskAdvertisedHost
      ? `external_signaling_address = ${state.asteriskAdvertisedHost}
external_media_address = ${state.asteriskAdvertisedHost}
local_net = ${state.asteriskLocalNet}
`
      : "";
    const gatewayAuth = gatewayRegisterEnabled
      ? `
[${state.trunkName}-auth]
type = auth
auth_type = userpass
username = ${state.voiceGatewaySipUsername}
password = ${state.voiceGatewaySipPassword}
`
      : "";
    const gatewayEndpointAuth = gatewayRegisterEnabled
      ? `outbound_auth = ${state.trunkName}-auth
from_user = ${state.voiceGatewaySipUsername}
from_domain = ${state.voiceGatewayHost}
callerid = ${state.voiceGatewaySipUsername}
contact_user = ${state.voiceGatewaySipUsername}
`
      : "";
    const gatewayRegistration = gatewayRegisterEnabled
      ? `
[${state.trunkName}-registration]
type = registration
transport = transport-udp
outbound_auth = ${state.trunkName}-auth
server_uri = sip:${state.voiceGatewayHost}:${state.voiceGatewaySipPort}
client_uri = sip:${state.voiceGatewaySipUsername}@${state.voiceGatewayHost}:${state.voiceGatewaySipPort}
contact_user = ${state.voiceGatewaySipUsername}
retry_interval = 30
forbidden_retry_interval = 30
expiration = 300
`
      : "";
    writeFileIfChanged(
      paths.asteriskConfPath,
      `[directories]
astetcdir => ${paths.configDir}
astvarlibdir => ${paths.dataDir}
astdbdir => ${paths.stateDir}
astkeydir => ${paths.keyDir}
astdatadir => ${paths.dataDir}
astagidir => ${path.join(paths.dataDir, "agi-bin")}
astspooldir => ${paths.spoolDir}
astrundir => ${paths.runDir}
astlogdir => ${paths.logDir}
`,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "modules.conf"),
      `[modules]
autoload = yes
`,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "logger.conf"),
      `[general]
dateformat = %F %T

[logfiles]
console => notice,warning,error
messages => notice,warning,error
`,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "manager.conf"),
      `[general]
enabled = yes
webenabled = no
port = ${state.amiPort}
bindaddr = 127.0.0.1

[${state.amiUsername}]
secret = ${state.amiPassword}
read = system,call,command,agent,user,originate
write = system,call,command,agent,user,originate
permit = 127.0.0.1/255.255.255.255
`,
      0o600,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "pjsip.conf"),
      `[global]
type = global
user_agent = AI_ACQ_Client_Asterisk

[transport-udp]
type = transport
protocol = udp
bind = 0.0.0.0:${state.sipPort}
${advertisedTransport}${gatewayAuth}

[${state.trunkName}]
type = endpoint
transport = transport-udp
context = from-voice-gateway
disallow = all
allow = alaw,ulaw
aors = ${state.trunkName}-aor
${gatewayEndpointAuth}direct_media = no
rtp_symmetric = yes
force_rport = yes
rewrite_contact = yes
timers = no

[${state.trunkName}-aor]
type = aor
contact = sip:${state.voiceGatewayHost}:${state.voiceGatewaySipPort}
qualify_frequency = 30
${gatewayRegistration}

[${state.trunkName}-identify]
type = identify
endpoint = ${state.trunkName}
match = ${state.voiceGatewayHost}
`,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "extensions.conf"),
      `[from-ai-acq]
exten => s,1,NoOp(AI ACQ realtime outbound call answered)
 same => n,Answer()
 same => n,Set(AI_ACQ_CALL_UUID=\${UUID()})
 same => n,AudioSocket(\${AI_ACQ_CALL_UUID},${state.audioSocketHost}:${state.audioSocketPort})
 same => n,Hangup()

[from-voice-gateway]
exten => _X.,1,NoOp(Inbound call from voice gateway: \${CALLERID(all)})
 same => n,Hangup()
`,
    );
    writeFileIfChanged(
      path.join(paths.configDir, "rtp.conf"),
      `[general]
rtpstart = ${state.rtpStart}
rtpend = ${state.rtpEnd}
`,
    );
    writeFileIfChanged(
      paths.backendEnvPath,
      `# Generated by the AI ACQ desktop client. Do not commit this file.
TELEPHONY_GATEWAY_MODE=asterisk
VOICE_GATEWAY_PROFILE=${state.voiceGatewayProfile}
VOICE_GATEWAY_LABEL=${state.voiceGatewayLabel}
VOICE_GATEWAY_HOST=${state.voiceGatewayHost}
VOICE_GATEWAY_SIP_PORT=${state.voiceGatewaySipPort}
VOICE_GATEWAY_TRUNK_NAME=${state.trunkName}
VOICE_GATEWAY_MAX_CHANNELS=${state.maxChannels}
ASTERISK_HOST=127.0.0.1
ASTERISK_AMI_PORT=${state.amiPort}
ASTERISK_AMI_USERNAME=${state.amiUsername}
ASTERISK_AMI_PASSWORD=${state.amiPassword}
ASTERISK_ORIGINATE_CONTEXT=from-ai-acq
ASTERISK_ORIGINATE_EXTENSION=s
ASTERISK_ORIGINATE_CHANNEL_TEMPLATE=PJSIP/{phone}@{trunk}
ASTERISK_TRUNK_NAME=${state.trunkName}
ASTERISK_MAX_CHANNELS=${state.maxChannels}
ASTERISK_LIVE_CALL_ENABLED=false
ASTERISK_BULK_CALL_ENABLED=false
ASTERISK_AUDIO_SOCKET_BIND_HOST=${state.audioSocketHost}
ASTERISK_AUDIO_SOCKET_HOST=${state.audioSocketHost}
ASTERISK_AUDIO_SOCKET_PORT=${state.audioSocketPort}
`,
      0o600,
    );
  }

  resolveRuntime() {
    const explicit = process.env.AI_ACQ_ASTERISK_BIN;
    if (explicit && fileExists(explicit)) {
      return { mode: "explicit", found: true, path: explicit, safePath: explicit };
    }

    const bundled = [
      path.join(process.resourcesPath || "", "asterisk", "bin", "asterisk"),
      path.join(__dirname, "asterisk", os.platform(), "bin", "asterisk"),
      path.join(__dirname, "asterisk", "bin", "asterisk"),
    ].find(fileExists);
    if (bundled) return { mode: "bundled", found: true, path: bundled, safePath: bundled };

    const system = commandPath("asterisk");
    if (system) return { mode: "system", found: true, path: system, safePath: system };

    return { mode: "bundled", found: false, path: "", safePath: "" };
  }

  isManagedRunning() {
    return Boolean(this.managedProcess && this.managedProcess.exitCode === null && !this.managedProcess.killed);
  }

  buildChecks({ layout, runtime, running, amiReachable, audioSocketReachable }) {
    return [
      {
        key: "runtime",
        label: "Asterisk runtime",
        status: runtime.found ? "pass" : "fail",
        detail: runtime.found ? `${runtime.mode}: ${runtime.safePath}` : "安装包还没有随带 Asterisk 可执行文件。",
      },
      {
        key: "config",
        label: "客户端配置",
        status: "pass",
        detail: `配置目录已生成：${layout.configDir}`,
      },
      {
        key: "backend_env",
        label: "后端环境",
        status: fs.existsSync(layout.backendEnvPath) ? "pass" : "fail",
        detail: `已生成客户本机专用 AMI 环境文件：${layout.backendEnvPath}`,
      },
      {
        key: "process",
        label: "进程",
        status: amiReachable ? "pass" : running ? "warn" : "warn",
        detail: amiReachable ? `AMI 监听在 127.0.0.1:${layout.state.amiPort}` : running ? "Asterisk 已启动，等待 AMI 端口打开。" : "Asterisk sidecar 尚未启动。",
      },
      {
        key: "voice_gateway_target",
        label: "语音网关目标",
        status: "warn",
        detail: `${layout.state.voiceGatewayLabel} · ${layout.state.voiceGatewayHost}:${layout.state.voiceGatewaySipPort}，当前配置 ${layout.state.maxChannels} 路。`,
      },
      {
        key: "audio_socket",
        label: "实时媒体桥",
        status: audioSocketReachable ? "pass" : "warn",
        detail: audioSocketReachable
          ? `AudioSocket bridge 已监听：${layout.state.audioSocketHost}:${layout.state.audioSocketPort}。`
          : `Asterisk 接通后会连接 AudioSocket：${layout.state.audioSocketHost}:${layout.state.audioSocketPort}，请先启动实时音频桥。`,
      },
    ];
  }

  nextStep({ runtime, running, amiReachable, audioSocketReachable, layout }) {
    if (!runtime.found) {
      return "把 Asterisk runtime 打进桌面客户端安装包，或在开发机用 AI_ACQ_ASTERISK_BIN 指向可执行文件后再启动。";
    }
    if (!running && !amiReachable) {
      return "点击启动内置 Asterisk；客户端会使用本机专用配置和 AMI 密钥。";
    }
    if (!amiReachable) {
      return "Asterisk 进程已启动，等待 AMI 端口打开；若持续失败，查看客户端日志目录。";
    }
    if (!audioSocketReachable) {
      return "内置 Asterisk 已运行；启动实时 AudioSocket bridge 后，再做语音网关 trunk 预检和单号试拨。";
    }
    return `内置 Asterisk 和实时媒体桥已运行。后端应读取 ${layout.backendEnvPath}，再做语音网关 trunk 预检。`;
  }
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function writeFileIfChanged(filePath, content, mode) {
  const normalized = content.trimStart();
  if (fs.existsSync(filePath) && fs.readFileSync(filePath, "utf8") === normalized) return;
  fs.writeFileSync(filePath, normalized, { mode });
}

function fileExists(filePath) {
  try {
    return Boolean(filePath) && fs.existsSync(filePath) && fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function commandPath(command) {
  const result = spawnSync("sh", ["-lc", `command -v ${command}`], { encoding: "utf8" });
  if (result.status !== 0) return "";
  return String(result.stdout || "").trim().split("\n")[0] || "";
}

function isTcpOpen(host, port, timeoutMs) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const finish = (value) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
    socket.connect(port, host);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

module.exports = { createAsteriskSidecar };
