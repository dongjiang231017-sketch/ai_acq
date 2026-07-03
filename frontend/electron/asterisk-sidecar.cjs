const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
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
  gatewayDiscoveryEnabled: true,
  gatewayDiscoveryHttpPort: 80,
  gatewayDiscoveryTimeoutMs: 420,
  gatewayDiscoveryConcurrency: 48,
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
    const voiceGatewayDiscovery = await this.reconcileVoiceGateway(layout, runtime);
    const running = this.isManagedRunning();
    const amiReachable = await isTcpOpen("127.0.0.1", layout.state.amiPort, 350);
    const audioSocketReachable = await isTcpOpen(layout.state.audioSocketHost, layout.state.audioSocketPort, 350);
    const checks = this.buildChecks({ layout, runtime, running, amiReachable, audioSocketReachable, voiceGatewayDiscovery });
    const customerDelivery = this.buildCustomerDelivery({ layout, runtime, running, amiReachable, audioSocketReachable, voiceGatewayDiscovery });
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
      voiceGatewayDiscovery,
      configDir: layout.configDir,
      stateDir: layout.stateDir,
      backendEnvPath: layout.backendEnvPath,
      backendEnvReady: fs.existsSync(layout.backendEnvPath),
      customerDelivery,
      checks,
      lastExit: this.lastExit,
      nextStep: this.nextStep({ runtime, running, amiReachable, audioSocketReachable, layout }),
    };
  }

  async start() {
    const layout = this.ensureLayout();
    const runtime = this.resolveRuntime();
    await this.reconcileVoiceGateway(layout, runtime);
    if (!runtime.found) {
      return this.status();
    }
    if (this.isManagedRunning() || (await isTcpOpen("127.0.0.1", layout.state.amiPort, 350))) {
      return this.status();
    }

    this.managedProcess = spawn(runtime.path, ["-f", "-C", layout.asteriskConfPath], {
      cwd: layout.baseDir,
      detached: false,
      env: { ...process.env, ...(runtime.env || {}), ASTERISK_CONSOLE: "no" },
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
    const runtime = this.resolveRuntime();
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
      runtime,
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
      gatewayDiscoveryEnabled: process.env.AI_ACQ_VOICE_GATEWAY_AUTO_DISCOVERY !== "false",
      gatewayDiscoveryHttpPort: Number(process.env.AI_ACQ_VOICE_GATEWAY_HTTP_PORT || DEFAULTS.gatewayDiscoveryHttpPort),
      gatewayDiscoveryTimeoutMs: Number(process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_TIMEOUT_MS || DEFAULTS.gatewayDiscoveryTimeoutMs),
      gatewayDiscoveryConcurrency: Number(process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_CONCURRENCY || DEFAULTS.gatewayDiscoveryConcurrency),
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
    if (Object.prototype.hasOwnProperty.call(process.env, "AI_ACQ_VOICE_GATEWAY_AUTO_DISCOVERY")) {
      state.gatewayDiscoveryEnabled = process.env.AI_ACQ_VOICE_GATEWAY_AUTO_DISCOVERY !== "false";
    }
    if (process.env.AI_ACQ_VOICE_GATEWAY_HTTP_PORT) state.gatewayDiscoveryHttpPort = Number(process.env.AI_ACQ_VOICE_GATEWAY_HTTP_PORT);
    if (process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_TIMEOUT_MS) state.gatewayDiscoveryTimeoutMs = Number(process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_TIMEOUT_MS);
    if (process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_CONCURRENCY) {
      state.gatewayDiscoveryConcurrency = Number(process.env.AI_ACQ_VOICE_GATEWAY_DISCOVERY_CONCURRENCY);
    }
    fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
    return state;
  }

  async reconcileVoiceGateway(layout, runtime) {
    const { state } = layout;
    if (state.gatewayDiscoveryEnabled === false) {
      return {
        status: "disabled",
        host: state.voiceGatewayHost,
        sipPort: state.voiceGatewaySipPort,
        message: "语音网关自动匹配已关闭。",
      };
    }

    const timeoutMs = positiveNumber(state.gatewayDiscoveryTimeoutMs, DEFAULTS.gatewayDiscoveryTimeoutMs);
    const currentHost = state.voiceGatewayHost;
    const sipPort = positiveNumber(state.voiceGatewaySipPort, DEFAULTS.voiceGatewaySipPort);
    const httpPort = positiveNumber(state.gatewayDiscoveryHttpPort, DEFAULTS.gatewayDiscoveryHttpPort);
    if (currentHost) {
      const currentReachable =
        (await isTcpOpen(currentHost, sipPort, Math.min(timeoutMs, 500))) ||
        (await isKnownVoiceGatewayHttp(currentHost, httpPort, Math.min(timeoutMs, 500)));
      if (currentReachable) {
        return {
          status: "current",
          host: currentHost,
          sipPort,
          message: `当前语音网关 ${currentHost}:${sipPort} 可达，无需重新匹配。`,
        };
      }
    }

    const discovery = await discoverVoiceGateway({
      currentHost,
      sipPort,
      httpPort,
      timeoutMs,
      concurrency: positiveNumber(state.gatewayDiscoveryConcurrency, DEFAULTS.gatewayDiscoveryConcurrency),
    });
    if (!discovery) {
      return {
        status: "not_found",
        host: currentHost,
        sipPort,
        message: currentHost
          ? `原语音网关 ${currentHost}:${sipPort} 不可达，当前局域网未发现可自动匹配的语音网关。`
          : "当前局域网未发现可自动匹配的语音网关。",
      };
    }

    if (discovery.host === currentHost && discovery.sipPort === sipPort) {
      return {
        status: "current",
        host: discovery.host,
        sipPort: discovery.sipPort,
        source: discovery.source,
        message: `当前语音网关 ${discovery.host}:${discovery.sipPort} 已重新确认可达。`,
      };
    }

    const previousHost = currentHost;
    const previousSipPort = sipPort;
    state.voiceGatewayHost = discovery.host;
    state.voiceGatewaySipPort = discovery.sipPort;
    state.uc100Host = discovery.host;
    state.uc100SipPort = discovery.sipPort;
    state.voiceGatewayDiscoveredAt = new Date().toISOString();
    state.voiceGatewayDiscoverySource = discovery.source;
    state.voiceGatewayPreviousHost = previousHost || "";
    state.voiceGatewayPreviousSipPort = previousSipPort;
    fs.writeFileSync(layout.statePath, JSON.stringify(state, null, 2));
    this.writeConfigs({ ...layout, runtime });

    const reload = this.reloadAsterisk(runtime, layout);
    return {
      status: "updated",
      host: discovery.host,
      sipPort: discovery.sipPort,
      previousHost,
      previousSipPort,
      source: discovery.source,
      reload,
      message: `已自动匹配语音网关：${previousHost || "未配置"} -> ${discovery.host}:${discovery.sipPort}。`,
    };
  }

  reloadAsterisk(runtime, layout) {
    if (!runtime.found) {
      return { attempted: false, ok: false, message: "Asterisk 未运行，已重写配置，启动时会使用新网关地址。" };
    }
    const commands = ["pjsip reload", "dialplan reload"];
    const results = commands.map((command) =>
      spawnSync(runtime.path, ["-C", layout.asteriskConfPath, "-rx", command], {
        cwd: layout.baseDir,
        encoding: "utf8",
        timeout: 3000,
      }),
    );
    const failed = results.find((result) => result.status !== 0);
    if (failed) {
      return {
        attempted: true,
        ok: false,
        message: String(failed.stderr || failed.stdout || "Asterisk 热重载失败").trim(),
      };
    }
    return { attempted: true, ok: true, message: "Asterisk 已热重载语音网关配置。" };
  }

  writeConfigs(paths) {
    const { state } = paths;
    const moduleDir = paths.runtime?.modulesDir
      ? `astmoddir => ${paths.runtime.modulesDir}
`
      : "";
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
${moduleDir}
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
      return runtimeFromPath("explicit", explicit);
    }

    const bundled = [
      path.join(process.resourcesPath || "", "asterisk", os.platform(), "bin", "asterisk"),
      path.join(process.resourcesPath || "", "asterisk", "bin", "asterisk"),
      path.join(__dirname, "asterisk", os.platform(), "bin", "asterisk"),
      path.join(__dirname, "asterisk", "bin", "asterisk"),
    ].find(fileExists);
    if (bundled) return runtimeFromPath("bundled", bundled);

    const system = commandPath("asterisk");
    if (system) return runtimeFromPath("system", system);

    return { mode: "bundled", found: false, path: "", safePath: "", modulesDir: "", modulesFound: false, ready: false };
  }

  isManagedRunning() {
    return Boolean(this.managedProcess && this.managedProcess.exitCode === null && !this.managedProcess.killed);
  }

  buildChecks({ layout, runtime, running, amiReachable, audioSocketReachable, voiceGatewayDiscovery }) {
    return [
      {
        key: "runtime",
        label: "Asterisk runtime",
        status: runtime.ready ? "pass" : "fail",
        detail: runtime.found
          ? `${runtime.mode}: ${runtime.safePath}${runtime.modulesFound ? ` · modules ${runtime.modulesDir}` : " · 缺少 modules"}`
          : "安装包还没有随带 Asterisk 可执行文件。",
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
        status: voiceGatewayDiscovery?.status === "not_found" ? "fail" : "pass",
        detail: `${layout.state.voiceGatewayLabel} · ${layout.state.voiceGatewayHost}:${layout.state.voiceGatewaySipPort}，当前配置 ${layout.state.maxChannels} 路。`,
      },
      {
        key: "voice_gateway_discovery",
        label: "自动匹配",
        status:
          voiceGatewayDiscovery?.status === "updated" || voiceGatewayDiscovery?.status === "current"
            ? "pass"
            : voiceGatewayDiscovery?.status === "disabled"
              ? "warn"
              : "fail",
        detail: voiceGatewayDiscovery?.message || "等待语音网关自动匹配。",
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

  buildCustomerDelivery({ layout, runtime, running, amiReachable, audioSocketReachable, voiceGatewayDiscovery }) {
    const gatewayAddress = `${layout.state.voiceGatewayHost}:${layout.state.voiceGatewaySipPort}`;
    const actionItems = [];
    let status = "pass";
    let title = "客户现场可单号试拨";
    let message = `客户端已绑定语音网关 ${gatewayAddress}，后端环境已生成，下一步做单号真实拨测。`;

    if (!runtime.ready) {
      status = "fail";
      title = "安装包缺少 Asterisk 运行时";
      message = runtime.found
        ? "客户端找到了 Asterisk binary，但没有找到可加载的 modules，不能保证 PJSIP/AudioSocket 可用。"
        : "客户电脑不能依赖开发机 Docker 或网页预览，必须由桌面客户端内置或指定 Asterisk。";
      actionItems.push("运行 npm run desktop:runtime:prepare 准备 runtime，再运行 npm run desktop:dist 打正式安装包。");
      actionItems.push("如果使用外部 Asterisk，设置 AI_ACQ_ASTERISK_BIN 和 AI_ACQ_ASTERISK_MODULE_DIR。");
    } else if (voiceGatewayDiscovery?.status === "not_found") {
      status = "fail";
      title = "没有在当前网络发现语音网关";
      message = voiceGatewayDiscovery.message || "旧网关地址不可达，当前局域网没有识别到可绑定的语音网关。";
      actionItems.push("确认客户电脑和语音网关接在同一个路由器或同一局域网。");
      actionItems.push("确认语音网关已通电、网线接入正确，后台页面能从客户电脑打开。");
      actionItems.push("如果客户现场有多个网段，先在系统设置里手动指定网关 IP，再重新预检。");
    } else if (!layout.state.voiceGatewaySipUsername || !layout.state.voiceGatewaySipPassword) {
      status = "warn";
      title = "已发现网关，但缺少 SIP 注册账号";
      message = `客户端可看到语音网关 ${gatewayAddress}，但还没有可注册到网关的 SIP 分机账号。`;
      actionItems.push("在网关后台创建/确认 SIP 分机账号，并把账号密码写入客户端网关配置。");
      actionItems.push("UC100 实测档案需要 SIP 分机作为路由来源，不能只配 SIP 中继名。");
    } else if (!running && !amiReachable) {
      status = "warn";
      title = "设备已绑定，Asterisk 还未启动";
      message = `语音网关地址已匹配到 ${gatewayAddress}，点击启动内置 Asterisk 后会自动注册 trunk。`;
      actionItems.push("点击「启动内置Asterisk」。");
    } else if (!amiReachable) {
      status = "warn";
      title = "Asterisk 启动中，等待 AMI";
      message = "Asterisk 进程已启动，但本机 AMI 端口还没有通过健康检查。";
      actionItems.push("等待 3-10 秒后刷新；若仍失败，查看客户端日志目录。");
    } else if (!audioSocketReachable) {
      status = "warn";
      title = "线路已准备，实时语音桥未启动";
      message = "电话可通过 Asterisk 发起，但接通后还不能进入 AI 实时听说。";
      actionItems.push("启动后端实时 AudioSocket bridge，再做单号试拨。");
    } else if (voiceGatewayDiscovery?.status === "updated") {
      title = "已自动重绑新网络下的语音网关";
      message = voiceGatewayDiscovery.message || `客户端已把语音网关更新为 ${gatewayAddress}。`;
      actionItems.push(voiceGatewayDiscovery.reload?.message || "已重写 Asterisk 和后端环境配置。");
      actionItems.push("现在做单号试拨，用蜂窝侧接通和 AudioSocket 事件确认真实通话。");
    } else {
      actionItems.push("点击「预检线路」，确认 AMI、Trunk、单号试拨开关全部通过。");
      actionItems.push("先做单号试拨，页面必须显示蜂窝侧确认和媒体链路确认后，才允许进入批量。");
    }

    return {
      status,
      title,
      message,
      gatewayAddress,
      previousGatewayAddress:
        voiceGatewayDiscovery?.previousHost && voiceGatewayDiscovery?.previousSipPort
          ? `${voiceGatewayDiscovery.previousHost}:${voiceGatewayDiscovery.previousSipPort}`
          : "",
      discoveryStatus: voiceGatewayDiscovery?.status || "unknown",
      discoverySource: voiceGatewayDiscovery?.source || "",
      actionItems,
    };
  }

  nextStep({ runtime, running, amiReachable, audioSocketReachable, layout }) {
    if (!runtime.ready) {
      return "先准备完整 Asterisk runtime（binary + modules），再启动桌面客户端 sidecar。";
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

function dirExists(filePath) {
  try {
    return Boolean(filePath) && fs.existsSync(filePath) && fs.statSync(filePath).isDirectory();
  } catch {
    return false;
  }
}

function runtimeFromPath(mode, binaryPath) {
  const root = runtimeRootFromBinary(binaryPath);
  const modulesDir = process.env.AI_ACQ_ASTERISK_MODULE_DIR || findFirstDir([
    path.join(root, "lib", "asterisk", "modules"),
    path.join(root, "lib64", "asterisk", "modules"),
    path.join(path.dirname(path.dirname(binaryPath)), "lib", "asterisk", "modules"),
    "/opt/homebrew/lib/asterisk/modules",
    "/usr/local/lib/asterisk/modules",
    "/usr/lib/asterisk/modules",
    "/usr/lib64/asterisk/modules",
  ]);
  const libDir = findFirstDir([path.join(root, "lib"), path.join(root, "lib64")]);
  const env = {};
  if (libDir) {
    env.DYLD_LIBRARY_PATH = [libDir, process.env.DYLD_LIBRARY_PATH].filter(Boolean).join(path.delimiter);
    env.LD_LIBRARY_PATH = [libDir, process.env.LD_LIBRARY_PATH].filter(Boolean).join(path.delimiter);
  }
  return {
    mode,
    found: true,
    path: binaryPath,
    safePath: binaryPath,
    root,
    modulesDir,
    modulesFound: dirExists(modulesDir),
    ready: dirExists(modulesDir),
    env,
  };
}

function runtimeRootFromBinary(binaryPath) {
  const parent = path.dirname(binaryPath);
  return path.basename(parent) === "bin" || path.basename(parent) === "sbin" ? path.dirname(parent) : parent;
}

function findFirstDir(candidates) {
  return candidates.find((candidate) => dirExists(candidate)) || "";
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

async function discoverVoiceGateway({ currentHost, sipPort, httpPort, timeoutMs, concurrency }) {
  const hosts = gatewayCandidateHosts(currentHost);
  const checks = hosts.map((host) => async () => {
    const [httpSignature, sipOpen] = await Promise.all([
      readVoiceGatewayHttpSignature(host, httpPort, timeoutMs),
      isTcpOpen(host, sipPort, timeoutMs),
    ]);
    if (!httpSignature.matched && !sipOpen) return null;
    if (httpSignature.matched) {
      return { host, sipPort, source: httpSignature.title ? `http:${httpSignature.title}` : "http:voice-gateway" };
    }
    return { host, sipPort, source: `sip:${sipPort}` };
  });
  const result = await runLimited(checks, Math.max(4, Math.min(positiveNumber(concurrency, DEFAULTS.gatewayDiscoveryConcurrency), 96)));
  return result.find(Boolean) || null;
}

function gatewayCandidateHosts(currentHost) {
  const hosts = new Set();
  if (currentHost) hosts.add(currentHost);
  for (const network of localIpv4Networks()) {
    for (let host = 1; host <= 254; host += 1) hosts.add(`${network}.${host}`);
  }
  return [...hosts];
}

function localIpv4Networks() {
  const networks = new Set();
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses || []) {
      if (address.family !== "IPv4" || address.internal) continue;
      const parts = String(address.address || "").split(".");
      if (parts.length !== 4) continue;
      if (parts[0] === "127" || parts[0] === "169") continue;
      networks.add(parts.slice(0, 3).join("."));
    }
  }
  return [...networks];
}

async function isKnownVoiceGatewayHttp(host, port, timeoutMs) {
  const signature = await readVoiceGatewayHttpSignature(host, port, timeoutMs);
  return signature.matched;
}

function readVoiceGatewayHttpSignature(host, port, timeoutMs) {
  return new Promise((resolve) => {
    const request = http.get({ host, port, path: "/", timeout: timeoutMs }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        if (body.length < 65536) body += chunk;
      });
      response.on("end", () => {
        const title = titleFromHtml(body);
        const server = String(response.headers.server || "");
        resolve({
          matched: isVoiceGatewaySignature(`${title}\n${server}\n${body.slice(0, 2048)}`),
          title,
        });
      });
    });
    request.setTimeout(timeoutMs, () => request.destroy());
    request.on("error", () => resolve({ matched: false, title: "" }));
  });
}

function isVoiceGatewaySignature(text) {
  return /UC100|UC100-ZYH|Dinstar|鼎信|语音网关|VoLTE/i.test(text);
}

function titleFromHtml(html) {
  const match = String(html || "").match(/<title[^>]*>([^<]+)<\/title>/i);
  return match ? match[1].trim() : "";
}

async function runLimited(tasks, limit) {
  const results = new Array(tasks.length);
  let index = 0;
  async function worker() {
    while (index < tasks.length) {
      const taskIndex = index;
      index += 1;
      results[taskIndex] = await tasks[taskIndex]();
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, () => worker()));
  return results;
}

function positiveNumber(value, fallback) {
  const next = Number(value);
  return Number.isFinite(next) && next > 0 ? next : fallback;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

module.exports = { createAsteriskSidecar };
