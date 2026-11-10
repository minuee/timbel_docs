const path = require('path');
const { app } = require('electron');
const { spawn } = require('child_process');
const { StringDecoder } = require('string_decoder');
const { v4: uuidv4 } = require('uuid');
const fs = require('fs');
const log = require('electron-log/main');
const { logInfo } = require('./logger');

class AudioHelperManager {
  constructor() {
    this.helperProcess = null;
    this.sessionId = uuidv4();
    this.isDevMode = process.argv.includes('--dev');
    this.getPath = null;
    this.onEvent = null;
  }

  setOnEvent(handler) {
    this.onEvent = typeof handler === 'function' ? handler : null;
  }

  _safeEmit(payload) {
    try {
      if (this.onEvent) this.onEvent(payload);
    } catch (_) {}
  }

  getHelperPath() {
    // 개발/프로덕션 모든 케이스를 포괄하는 후보 경로들을 순서대로 확인
    const fs = require('fs');
    if( process.platform === 'win32') {
      const candidates = [
        // 1) asar-unpacked (가장 안전: 실행 가능)
        path.join(process.resourcesPath, 'app.asar.unpacked', 'helpers', 'windows', 'AudioHelper.exe'),
        // 2) resources/helpers (extraFiles로 배치됨)
        path.join(process.resourcesPath, 'helpers', 'windows', 'AudioHelper.exe'),
        // 3) resources 상위 helpers (일부 배포자 구성)
        path.join(process.resourcesPath, '..', 'helpers', 'windows', 'AudioHelper.exe'),
        // 4) 개발 환경: 프로젝트 소스 트리
        path.join(__dirname, '../helpers/windows/AudioHelper.exe')
      ];
  
      for (const p of candidates) {
        // asar 내부에 있는 바이너리는 spawn 불가하므로 건너뜀 (app.asar.unpacked은 허용)
        if (p.includes('app.asar\\') || p.includes('app.asar/')) continue;
        try {
          if (fs.existsSync(p)) return p;
        } catch (_) { /* ignore */ }
      }
  
      // 마지막 후보(일반적인 배포 경로)를 반환하되, 존재 여부는 startHelper에서 다시 로깅
      return path.join(process.resourcesPath, 'helpers', 'windows', 'AudioHelper.exe');
      
    }else if( process.platform === 'darwin') {
      // 패키징 후보 경로들 (순서대로 확인)
      const candidates = [
        // 1) Contents/Resources/helpers (extraResources 사용 시)
        path.join(process.resourcesPath, 'helpers', 'macos', 'AudioHelper.app', 'Contents', 'MacOS', 'AudioHelper'),
        // 2) Contents/helpers (extraFiles 사용 시)
        path.join(process.resourcesPath, '..', 'helpers', 'macos', 'AudioHelper.app', 'Contents', 'MacOS', 'AudioHelper'),
        // 4) app.asar.unpacked
        path.join(process.resourcesPath, 'app.asar.unpacked', 'helpers', 'macos', 'AudioHelper.app', 'Contents', 'MacOS', 'AudioHelper'),
      ];
      try { require('./logger').logInfo('get path', { path:process.resourcesPath }); } catch (_) {}
      // 패키징된 경로 먼저 확인
      for (const p of candidates) {
        try {
          if (fs.existsSync(p)) {
            return p;
          }
        } catch (_) { /* ignore */ }
      }
      
      // 개발 모드 경로
      const devPath = path.join(process.cwd(), 'src', 'helpers', 'macos', 'AudioHelper.app', 'Contents', 'MacOS', 'AudioHelper');
      if (fs.existsSync(devPath)) {
        return devPath;
      }
      
      // 모두 실패 시 기본값 (로깅용)
      return candidates[1];
    }
  }

  async startHelper() {
    if (this.helperProcess) {
      try { require('./logger').logWarn('helper_already_running'); } catch (_) {}
      return;
    }

    const helperPath = this.getHelperPath();
    this.getPath = helperPath;
    const fs = require('fs');
    const helperExists = fs.existsSync(helperPath);
    try { require('./logger').logInfo('helper_start', { helperPath, helperExists }); } catch (_) {}
    // 렌더러에도 상태 전달 (배포 모드에서 콘sole이 안 보일 수 있음)
    this._safeEmit({
      ev: 'helper_status',
      stage: 'pre_spawn',
      path: helperPath,
      exists: helperExists
    });

    try {
      this.helperProcess = spawn(helperPath, [], {
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
        cwd: path.dirname(helperPath)
      });

      // 스폰 직후 상태 알림
      this._safeEmit({
        ev: 'helper_status',
        stage: 'spawned',
        pid: this.helperProcess && this.helperProcess.pid
      });

      // UTF-8 스트리밍 디코더로 멀티바이트 경계 안전 처리
      this._stdoutDecoder = new StringDecoder('utf8');
      this._stdoutBuf = '';
      this.helperProcess.stdout.on('data', (data) => {
        const text = this._stdoutDecoder.write(data);
        this._stdoutBuf += text;
        let idx;
        while ((idx = this._stdoutBuf.indexOf('\n')) >= 0) {
          const rawLine = this._stdoutBuf.slice(0, idx);
          this._stdoutBuf = this._stdoutBuf.slice(idx + 1);
          const line = rawLine.trim();
          if (!line) continue;
          try {
            const event = JSON.parse(line);
            this.handleHelperEvent(event);
          } catch (e) {
            try { require('./logger').logDebug('helper_output', { line }); } catch (_) {}
          }
        }
      });

      this._stderrDecoder = new StringDecoder('utf8');
      this.helperProcess.stderr.on('data', (data) => {
        const text = this._stderrDecoder.write(data);
        try { require('./logger').logError('helper_error', { text }); } catch (_) {}
        // 렌더러로 에러 로그 전달
        this._safeEmit({
          ev: 'helper_log',
          level: 'error',
          message: text
        });
      });

      this.helperProcess.on('close', (code) => {
        try { require('./logger').logWarn('helper_closed', { code }); } catch (_) {}
        this.helperProcess = null;
        this._safeEmit({
          ev: 'helper_status',
          stage: 'closed',
          code
        });
      });

      this.helperProcess.on('error', (err) => {
        try { require('./logger').logError('helper_start_failed', { message: err && err.message }); } catch (_) {}
        this.helperProcess = null;
        this._safeEmit({
          ev: 'helper_status',
          stage: 'spawn_error',
          message: err && (err.message || String(err))
        });
      });

    } catch (error) {
      try { require('./logger').logError('helper_start_exception', { message: error && error.message }); } catch (_) {}
      throw error;
    }
  }

  handleHelperEvent(event) {
    // 과다 로그 방지: level/waveform 이벤트는 콘솔 출력 생략
    if (event && (event.ev === 'level' || event.ev === 'waveform' || event.ev === 'progress')) {
      // 필요 시 디버깅 샘플링 로깅: 1% 확률로만 출력
      if (Math.random() < 0.001) {
        if(event.ev === 'progress') {
          try { require('./logger').logDebug('helper_progress', { ev: event.ev, seconds: event.seconds, samples: event.samples, mic_samples: event.mic_samples, mic_seconds: event.mic_seconds }); } catch (_) {}
        }else{
          try { require('./logger').logDebug('helper_event_sampled', { ev: event.ev, source: event.source, t: event.t }); } catch (_) {}
        }
      }
    } else {
      try { require('./logger').logDebug('helper_event', event); } catch (_) {}
    }
    // Decode UTF-16LE base64 device names (to avoid mojibake in logs)
    try {
      if (event && event.ev === 'devices' && Array.isArray(event.devices)) {
        event.devices.forEach(d => {
          const decodedName = d && d.name_b64_utf16le
            ? Buffer.from(d.name_b64_utf16le, 'base64').toString('utf16le')
            : d?.name;
          try { require('./logger').logInfo('device_decoded', { decodedName, id: d?.id, isDefault: d?.isDefault }); } catch (_) {}
        });
      }
    } catch (e) {
      try { require('./logger').logWarn('device_decode_failed', { message: e?.message || String(e) }); } catch (_) {}
    }
    // UI로 이벤트 전달
    this._safeEmit(event);
  }

  sendCommand(command) {
    if (!this.helperProcess) {
      throw new Error('Helper not running');
    }
    
    const commandWithSession = {
      ...command,
      sessionId: this.sessionId
    };
    
    try { require('./logger').logDebug('helper_command_send', { command: commandWithSession && commandWithSession.cmd }); } catch (_) {}
    this.helperProcess.stdin.write(JSON.stringify(commandWithSession) + '\n');
  }

  stopHelper() {
    if (this.helperProcess) {
      this.helperProcess.kill();
      this.helperProcess = null;
    }
  }
}

module.exports = { 
  AudioHelperManager
};