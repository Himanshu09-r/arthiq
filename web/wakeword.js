/* ARTHIQ hands-free wake listener.
 * The user must explicitly enable it once per page load. Audio is analysed in-browser;
 * only completed speech clips are sent to the server for STT.
 */
(() => {
  'use strict';
  if (!navigator.mediaDevices?.getUserMedia) return;

  const $ = (s) => document.querySelector(s);
  const state = {
    enabled: false, mode: 'off', stream: null, context: null, processor: null,
    vad: { floor: 0.008, active: false, attack: 0, silence: 0, elapsed: 0, voiced: 0 },
    pre: [], frames: [], busy: false, followupDeadline: 0, timer: null,
  };
  const CONFIG = { frameMs: 2048 / 48000 * 1000, preFrames: 8,
    wakeSilenceMs: 750, commandSilenceMs: 1050, wakeMaxMs: 7000, commandMaxMs: 14000,
    followupWaitMs: 9000, minimumVoicedMs: 300 };

  function status(text) {
    const node = $('#voice-status-text');
    if (node) node.textContent = text;
    const tabStatus = $('#voice-tab-status');
    if (tabStatus) tabStatus.textContent = text;
    const mic = $('#btn-master-mic');
    if (mic) mic.dataset.handsfree = state.mode;
    const dot = $('#wake-dot');
    if (dot) dot.classList.toggle('active', state.enabled && (state.mode === 'armed' || state.mode === 'followup'));
    const button = $('#handsfreeBtn');
    if (button) button.setAttribute('aria-pressed', state.enabled ? 'true' : 'false');
  }

  function resetVad() {
    state.vad.active = false;
    state.vad.attack = 0;
    state.vad.silence = 0;
    state.vad.elapsed = 0;
    state.vad.voiced = 0;
  }

  function detectFrame(rms, durationMs) {
    const vad = state.vad;
    const threshold = Math.max(0.010, vad.floor * 2.8);
    if (!vad.active) {
      if (rms > threshold) {
        vad.attack += 1;
        if (vad.attack >= 2) {
          vad.active = true;
          vad.elapsed = durationMs * vad.attack;
          vad.voiced = vad.elapsed;
          vad.silence = 0;
          return 'start';
        }
      } else {
        vad.attack = 0;
        vad.floor = vad.floor * 0.96 + rms * 0.04;
      }
      return null;
    }
    vad.elapsed += durationMs;
    if (rms > threshold * 0.58) {
      vad.silence = 0;
      vad.voiced += durationMs;
    } else {
      vad.silence += durationMs;
    }
    const isFollowup = state.mode === 'followup';
    if (vad.silence >= (isFollowup ? CONFIG.commandSilenceMs : CONFIG.wakeSilenceMs)) return 'end';
    if (vad.elapsed >= (isFollowup ? CONFIG.commandMaxMs : CONFIG.wakeMaxMs)) return 'end';
    return null;
  }

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const write = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
    write(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); write(8, 'WAVEfmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const sample = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return new Blob([buffer], { type: 'audio/wav' });
  }

  function wavFromFrames(frames, sampleRate) {
    const total = frames.reduce((n, frame) => n + frame.length, 0);
    const input = new Float32Array(total);
    let offset = 0;
    for (const frame of frames) { input.set(frame, offset); offset += frame.length; }
    const ratio = sampleRate / 16000;
    const out = new Float32Array(Math.max(1, Math.floor(total / ratio)));
    for (let i = 0; i < out.length; i++) {
      const pos = i * ratio, left = Math.floor(pos), right = Math.min(left + 1, input.length - 1);
      out[i] = input[left] + (input[right] - input[left]) * (pos - left);
    }
    return encodeWav(out, 16000);
  }

  async function postClip(path, wav) {
    const form = new FormData();
    form.append('audio', wav, 'speech.wav');
    form.append('shop_id', String(SHOP_ID));
    const response = await fetch(path, { method: 'POST', body: form });
    if (!response.ok) {
      let message = await response.text();
      try { message = JSON.parse(message).detail || message; } catch (_) {}
      throw new Error(`HTTP ${response.status}: ${message}`);
    }
    return response.json();
  }

  function playAudio(audioB64) {
    if (!audioB64) return Promise.resolve();
    return new Promise((resolve) => {
      const audio = new Audio('data:audio/wav;base64,' + audioB64);
      let finished = false;
      const done = () => { if (!finished) { finished = true; resolve(); } };
      audio.addEventListener('ended', done, { once: true });
      audio.addEventListener('error', done, { once: true });
      setTimeout(done, 30000);
      audio.play().catch(done);
    });
  }

  function chime() {
    if (!state.context || state.context.state !== 'running') return;
    const now = state.context.currentTime;
    [[660, 0], [880, 0.12]].forEach(([frequency, delay]) => {
      const oscillator = state.context.createOscillator();
      const gain = state.context.createGain();
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, now + delay);
      gain.gain.exponentialRampToValueAtTime(0.11, now + delay + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.13);
      oscillator.connect(gain); gain.connect(state.context.destination);
      oscillator.start(now + delay); oscillator.stop(now + delay + 0.14);
    });
  }

  function manualRecording() {
    try { return typeof isCommandRecording !== 'undefined' && Boolean(isCommandRecording); }
    catch (_) { return false; }
  }

  function enterArmed(note) {
    state.mode = 'armed';
    state.followupDeadline = 0;
    resetVad(); state.frames = []; state.pre = [];
    status(note || 'Hands-free is on — say “Suno ARTHIQ” or “ARTHIQ SUNO”.');
  }

  function enterFollowup(note) {
    state.mode = 'followup';
    state.followupDeadline = performance.now() + CONFIG.followupWaitMs;
    resetVad(); state.frames = []; state.pre = [];
    status(note || 'ARTHIQ is listening — speak your command or confirmation.');
  }

  async function handleTurn(result) {
    state.busy = true;
    state.mode = 'processing';
    status('Understanding…');
    if (typeof window.handleTurnResponse === 'function') {
      await window.handleTurnResponse(result);
    } else {
      if (result.transcript && typeof window.appendChatBubble === 'function') window.appendChatBubble('user', result.transcript);
      if (result.reply && typeof window.appendChatBubble === 'function') window.appendChatBubble('assistant', result.reply);
      if (result.audio_b64) await playAudio(result.audio_b64);
    }
    state.busy = false;
    const needsReply = Boolean(result && (result.listen || result.state === 'confirm' || result.state === 'ask'));
    if (state.enabled) {
      if (needsReply) enterFollowup();
      else enterArmed();
    }
  }

  async function finishUtterance() {
    const frames = state.frames;
    const voicedMs = state.vad.voiced;
    const capturedMode = state.mode;
    state.frames = [];
    resetVad();
    if (voicedMs < CONFIG.minimumVoicedMs) return;
    state.busy = true;
    state.mode = 'processing';
    status('Understanding…');
    const wav = wavFromFrames(frames, state.context.sampleRate);
    try {
      if (capturedMode === 'armed') {
        const result = await postClip('/voice/wake', wav);
        if (!result.wake) {
          state.busy = false;
          enterArmed();
          return;
        }
        chime();
        if (result.turn) {
          await handleTurn(result.turn);
          return;
        }
        if (result.ack_reply && typeof window.appendChatBubble === 'function') window.appendChatBubble('assistant', result.ack_reply);
        await playAudio(result.ack_audio_b64);
        state.busy = false;
        enterFollowup();
        return;
      }

      const result = await postClip('/voice/command', wav);
      await handleTurn(result);
    } catch (error) {
      state.busy = false;
      if (state.enabled) enterArmed('Hands-free error: ' + String(error.message || error).slice(0, 180));
    }
  }

  function onAudioFrame(event) {
    if (!state.enabled || !state.context || state.context.state !== 'running') return;
    if (document.hidden || manualRecording() || state.busy || state.mode === 'off' || state.mode === 'processing') {
      resetVad(); state.frames = []; state.pre = [];
      return;
    }
    const channel = event.inputBuffer.getChannelData(0);
    let squares = 0;
    for (let i = 0; i < channel.length; i++) squares += channel[i] * channel[i];
    const rms = Math.sqrt(squares / channel.length);
    const durationMs = channel.length / state.context.sampleRate * 1000;
    const frame = new Float32Array(channel);

    if (state.mode === 'followup' && !state.vad.active && performance.now() > state.followupDeadline) {
      enterArmed();
      return;
    }
    const eventType = detectFrame(rms, durationMs);
    if (state.vad.active) {
      if (eventType === 'start') {
        state.frames = state.pre.splice(0);
        status(state.mode === 'armed' ? 'Listening for wake phrase…' : 'Listening for your command…');
      }
      state.frames.push(frame);
    } else {
      state.pre.push(frame);
      if (state.pre.length > CONFIG.preFrames) state.pre.shift();
    }
    if (eventType === 'end') finishUtterance();
  }

  async function enable() {
    if (state.enabled) return;
    const button = $('#handsfreeBtn');
    if (button) button.disabled = true;
    try {
      // Create/resume the audio context directly from the button gesture before the
      // microphone permission prompt can consume the browser's transient activation.
      state.context = new (window.AudioContext || window.webkitAudioContext)();
      await state.context.resume();
      state.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }
      });
      if (state.context.state !== 'running') await state.context.resume();
      const source = state.context.createMediaStreamSource(state.stream);
      const highPass = state.context.createBiquadFilter();
      highPass.type = 'highpass'; highPass.frequency.value = 100;
      const lowPass = state.context.createBiquadFilter();
      lowPass.type = 'lowpass'; lowPass.frequency.value = 7200;
      state.processor = state.context.createScriptProcessor(2048, 1, 1);
      const mute = state.context.createGain(); mute.gain.value = 0;
      source.connect(highPass); highPass.connect(lowPass); lowPass.connect(state.processor);
      state.processor.connect(mute); mute.connect(state.context.destination);
      state.processor.onaudioprocess = onAudioFrame;
      state.enabled = true;
      state.vad.floor = 0.008;
      state.mode = 'armed';
      const track = state.stream.getAudioTracks()[0];
      track.addEventListener('ended', () => disable('Microphone disconnected. Enable Hands-Free again.'), { once: true });
      if (button) { button.disabled = false; button.textContent = 'Disable Hands-Free'; button.setAttribute('aria-pressed', 'true'); }
      enterArmed('Calibrating microphone… then say “Suno ARTHIQ”.');
      setTimeout(() => { if (state.enabled && state.mode === 'armed') enterArmed(); }, 1200);
    } catch (error) {
      if (button) button.disabled = false;
      disable('Could not enable microphone: ' + String(error.message || error));
    }
  }

  function disable(note) {
    state.enabled = false;
    state.mode = 'off'; state.busy = false;
    clearTimeout(state.timer);
    if (state.processor) { state.processor.onaudioprocess = null; try { state.processor.disconnect(); } catch (_) {} }
    if (state.stream) state.stream.getTracks().forEach(track => track.stop());
    if (state.context) state.context.close().catch(() => {});
    state.processor = state.stream = state.context = null;
    resetVad(); state.frames = []; state.pre = [];
    const button = $('#handsfreeBtn');
    if (button) { button.disabled = false; button.textContent = 'Enable Hands-Free'; button.setAttribute('aria-pressed', 'false'); }
    status(note || 'Hands-free is off. Use the mic button or enable hands-free.');
  }

  function beginSpeaking() {
    if (!state.enabled) return;
    state.busy = true;
    state.mode = 'speaking';
    resetVad(); state.frames = []; state.pre = [];
    status('ARTHIQ is speaking…');
  }

  function afterTurn(result) {
    if (!state.enabled) return;
    state.busy = false;
    const needsReply = Boolean(result && (result.listen || result.state === 'confirm' || result.state === 'ask'));
    if (needsReply) enterFollowup(); else enterArmed();
  }

  const button = $('#handsfreeBtn');
  if (button) button.addEventListener('click', () => state.enabled ? disable() : enable());
  document.addEventListener('visibilitychange', () => {
    if (state.enabled && document.hidden) status('Hands-free paused while this tab is in the background.');
    else if (state.enabled) {
      if (state.context && state.context.state !== 'running') state.context.resume().catch(() => {});
      if (state.mode === 'followup') enterFollowup(); else enterArmed();
    }
  });
  window.ArthiqWake = { enable, disable, beginSpeaking, afterTurn, isEnabled: () => state.enabled };
})();
