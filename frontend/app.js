/**
 * ThreadSift - Frontend Application Logic
 * Implements FTS5 BM25 search, Hermes RAG chat, Web Speech API live voice call, and Exporter runner.
 */

// Application Global State
const state = {
  currentTab: 'search',
  lastSearchResults: [],
  chatHistory: [],
  isCallActive: false,
  isMicMuted: false,
  isListening: false,
  isSpeaking: false,
  isThinking: false,
  recognition: null,
  audioPlayer: null,
  systemStatus: null,
};

// Initialize Application on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initSpeechRecognition();
  fetchStatus();
  executeSearch();
  // Poll status periodically (every 15s)
  setInterval(fetchStatus, 15000);
});

// --- Tab Switching Navigation ---
function switchTab(tabId) {
  state.currentTab = tabId;
  const views = document.querySelectorAll('.tab-view');
  views.forEach(v => v.classList.add('hidden'));

  const targetView = document.getElementById(`view-${tabId}`);
  if (targetView) targetView.classList.remove('hidden');

  const tabButtons = document.querySelectorAll('.tab-btn');
  tabButtons.forEach(btn => {
    btn.className = 'tab-btn px-3.5 py-1.5 rounded-lg flex items-center gap-2 text-slate-400 hover:text-white transition-all hover:bg-slate-800/60';
  });

  const activeBtn = document.getElementById(`tabBtn-${tabId}`);
  if (activeBtn) {
    activeBtn.className = 'tab-btn px-3.5 py-1.5 rounded-lg flex items-center gap-2 transition-all bg-indigo-600 text-white shadow-sm';
  }
}

// --- Status & Statistics Polling ---
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();
    state.systemStatus = data;

    // Update Header Status Pills
    const totalMsgsEl = document.getElementById('stat-total-msgs');
    if (totalMsgsEl && data.vault) {
      totalMsgsEl.textContent = `${data.vault.total_messages.toLocaleString()} msgs (${data.vault.messages_90_days} in 90d)`;
    }

    const llmDot = document.getElementById('stat-llm-dot');
    const llmText = document.getElementById('stat-llm-text');
    if (data.llm) {
      if (data.llm.online) {
        llmDot.className = 'w-2 h-2 rounded-full bg-emerald-400';
        llmText.textContent = data.llm.model;
      } else {
        llmDot.className = 'w-2 h-2 rounded-full bg-amber-500';
        llmText.textContent = 'local-offline';
      }
    }

    // Update Exporter Status
    const exportBadge = document.getElementById('export-status-badge');
    if (exportBadge && data.exporter) {
      if (data.exporter.cli_found) {
        exportBadge.className = 'text-xs px-2.5 py-0.5 rounded-full font-mono bg-emerald-950/60 text-emerald-400 border border-emerald-800/60';
        exportBadge.textContent = 'CLI Available';
      } else {
        exportBadge.className = 'text-xs px-2.5 py-0.5 rounded-full font-mono bg-amber-950/60 text-amber-400 border border-amber-800/60';
        exportBadge.textContent = 'CLI Not Found';
      }
    }

    // Populate Channel Filter Options
    const channelSelect = document.getElementById('channel-filter');
    if (channelSelect && data.vault && data.vault.channels) {
      const currentVal = channelSelect.value;
      let opts = '<option value="">All Channels (#)</option>';
      data.vault.channels.forEach(ch => {
        opts += `<option value="${escapeHtml(ch)}">#${escapeHtml(ch)}</option>`;
      });
      channelSelect.innerHTML = opts;
      channelSelect.value = currentVal;
    }

    // Populate Voices Select
    const voiceSelect = document.getElementById('voice-select');
    if (voiceSelect && data.elevenlabs && data.elevenlabs.popular_voices) {
      const currentVoice = voiceSelect.value || data.elevenlabs.default_voice_id;
      let vOpts = '';
      data.elevenlabs.popular_voices.forEach(v => {
        vOpts += `<option value="${v.id}">${v.name}</option>`;
      });
      voiceSelect.innerHTML = vOpts;
      if (currentVoice) voiceSelect.value = currentVoice;
    }
  } catch (err) {
    console.warn('Status poll error:', err);
  }
}

// --- Vault Search (SQLite FTS5 + BM25) ---
async function executeSearch() {
  const queryInput = document.getElementById('search-input');
  const channelSelect = document.getElementById('channel-filter');
  const daysSelect = document.getElementById('days-filter');
  const resultsContainer = document.getElementById('search-results-list');
  const countEl = document.getElementById('results-count');
  const latencyEl = document.getElementById('search-latency');

  const query = queryInput ? queryInput.value.trim() : '';
  const channel = channelSelect ? channelSelect.value : '';
  const days = daysSelect ? daysSelect.value : '90';

  resultsContainer.innerHTML = `
    <div class="glass-card rounded-xl p-8 text-center text-slate-400 text-sm">
      <div class="inline-block animate-spin rounded-full h-6 w-6 border-2 border-indigo-500 border-t-transparent mb-2"></div>
      <div>Querying 90-day FTS5 virtual table...</div>
    </div>
  `;

  const startTime = performance.now();

  try {
    const url = new URL('/api/search', window.location.origin);
    if (query) url.searchParams.set('q', query);
    if (channel) url.searchParams.set('channel_id', channel);
    url.searchParams.set('days', days);
    url.searchParams.set('limit', '40');

    const res = await fetch(url.toString());
    const data = await res.json();
    const elapsed = (performance.now() - startTime).toFixed(1);

    state.lastSearchResults = data.results || [];

    if (latencyEl) {
      latencyEl.textContent = `Latency: ${elapsed}ms • BM25 Ranked`;
    }

    if (countEl) {
      countEl.textContent = `Found ${data.total_results || 0} messages matching query in last ${days} days`;
    }

    if (!data.results || data.results.length === 0) {
      resultsContainer.innerHTML = `
        <div class="glass-card rounded-2xl p-12 text-center text-slate-400 space-y-3">
          <svg class="w-10 h-10 mx-auto text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <div class="text-base font-semibold text-slate-300">No matching conversations found</div>
          <p class="text-xs text-slate-500 max-w-sm mx-auto">No messages found. If you haven't imported your Discord chats yet, go to the <button onclick="switchTab('export')" class="text-indigo-400 underline hover:text-indigo-300 font-semibold">Exporter tab</button> to upload your JSON file or export a channel.</p>
        </div>
      `;
      return;
    }

    let html = '';
    data.results.forEach(msg => {
      const formattedDate = formatDate(msg.timestamp);
      const authorInitial = (msg.author || '?')[0].toUpperCase();
      const rankBadge = msg.rank !== 0 ? `<span class="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20" title="FTS5 BM25 Score">BM25: ${msg.rank}</span>` : '';

      html += `
        <article class="glass-card hover:border-slate-700/80 transition-all rounded-xl p-4 sm:p-5 flex flex-col sm:flex-row items-start gap-4 group">
          <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-slate-800 to-slate-700 border border-slate-600/40 flex items-center justify-center text-slate-200 font-bold text-sm flex-shrink-0 shadow-sm">
            ${authorInitial}
          </div>
          
          <div class="flex-1 w-full space-y-2">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="font-semibold text-white text-sm">${escapeHtml(msg.author)}</span>
                <span class="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">#${escapeHtml(msg.channel_id)}</span>
                ${rankBadge}
              </div>
              <span class="text-xs font-mono text-slate-400">${formattedDate}</span>
            </div>

            <div class="text-slate-200 text-sm leading-relaxed font-sans bg-slate-900/50 p-3 rounded-lg border border-slate-800/60">
              ${msg.snippet || escapeHtml(msg.content)}
            </div>

            <div class="flex items-center justify-between pt-1 text-xs">
              <span class="text-slate-500 font-mono text-[11px]">ID: ${escapeHtml(msg.id)}</span>
              <button onclick="copyToClipboard('${escapeAttr(msg.content)}', this)" class="text-slate-400 hover:text-indigo-300 transition-colors flex items-center gap-1 font-mono text-[11px]">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                <span>Copy</span>
              </button>
            </div>
          </div>
        </article>
      `;
    });

    resultsContainer.innerHTML = html;
  } catch (err) {
    console.error('Search error:', err);
    resultsContainer.innerHTML = `
      <div class="glass-card rounded-xl p-6 text-center text-red-400 text-sm">
        Error executing search: ${escapeHtml(err.message)}
      </div>
    `;
  }
}

function quickSearch(term) {
  const queryInput = document.getElementById('search-input');
  if (queryInput) {
    queryInput.value = term;
    executeSearch();
  }
}

function exportSearchResultsJSON() {
  if (!state.lastSearchResults || state.lastSearchResults.length === 0) {
    alert('No search results to export. Run a search first.');
    return;
  }
  const blob = new Blob([JSON.stringify(state.lastSearchResults, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `threadsift_export_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// --- Live Voice Call Engine (Web Speech STT -> Hermes -> ElevenLabs TTS) ---
function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn('Web Speech API is not supported in this browser. Live voice speech-to-text will fall back to manual text input.');
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onstart = () => {
    state.isListening = true;
    updateVoiceUIState('listening');
  };

  recognition.onresult = (event) => {
    let interimTranscript = '';
    let finalTranscript = '';

    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }

    const interimDisplay = document.getElementById('live-interim-text');
    if (interimDisplay) {
      interimDisplay.textContent = finalTranscript || interimTranscript || 'Listening...';
    }

    if (finalTranscript.trim().length > 1) {
      handleFinalVoiceTurn(finalTranscript.trim());
    }
  };

  recognition.onerror = (event) => {
    console.warn('Speech recognition event:', event.error);
    if (event.error === 'not-allowed') {
      alert('Microphone permission denied. Please allow microphone access in your browser settings.');
      stopVoiceCall();
    }
  };

  recognition.onend = () => {
    state.isListening = false;
    // Auto restart recognition if call is still active and agent is not speaking
    if (state.isCallActive && !state.isSpeaking && !state.isThinking) {
      try {
        recognition.start();
      } catch (e) {
        // Ignore already started error
      }
    }
  };

  state.recognition = recognition;
}

function toggleVoiceCall() {
  if (state.isCallActive) {
    stopVoiceCall();
  } else {
    startVoiceCall();
  }
}

function startVoiceCall() {
  if (!state.recognition) {
    alert('Web Speech API is not supported in this browser. Please use Chrome, Edge, or Safari.');
    return;
  }

  state.isCallActive = true;
  const btn = document.getElementById('btn-toggle-call');
  const muteBtn = document.getElementById('btn-mute-mic');
  if (btn) {
    btn.className = 'px-6 py-3.5 rounded-2xl bg-red-600 hover:bg-red-500 text-white font-bold text-sm transition-all shadow-lg shadow-red-600/30 flex items-center gap-2';
    btn.innerHTML = `
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M5 3a2 2 0 00-2 2v1c0 8.284 6.716 15 15 15h1a2 2 0 002-2v-3.28a1 1 0 00-.684-.948l-4.493-1.498a1 1 0 00-1.21.502l-1.13 2.257a11.042 11.042 0 01-5.516-5.516l2.257-1.13a1 1 0 00.502-1.21L9.228 3.684A1 1 0 008.28 3H5z"/></svg>
      <span>End Call</span>
    `;
  }
  if (muteBtn) muteBtn.disabled = false;

  try {
    state.recognition.start();
  } catch (err) {
    console.warn('Recognition start:', err);
  }

  updateVoiceUIState('listening');
  appendVoiceLog('system', 'Voice call session started. Hermes 3 is listening with 90-day vault context.');
}

function stopVoiceCall() {
  state.isCallActive = false;
  state.isSpeaking = false;
  state.isThinking = false;

  if (state.recognition) {
    try { state.recognition.stop(); } catch (e) {}
  }

  if (state.audioPlayer) {
    state.audioPlayer.pause();
    state.audioPlayer = null;
  }
  window.speechSynthesis.cancel();

  const btn = document.getElementById('btn-toggle-call');
  const muteBtn = document.getElementById('btn-mute-mic');
  if (btn) {
    btn.className = 'px-6 py-3.5 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-sm transition-all shadow-lg shadow-emerald-600/30 flex items-center gap-2';
    btn.innerHTML = `
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/></svg>
      <span>Start Voice Call</span>
    `;
  }
  if (muteBtn) muteBtn.disabled = true;

  updateVoiceUIState('idle');
  appendVoiceLog('system', 'Call ended.');
}

function toggleMute() {
  state.isMicMuted = !state.isMicMuted;
  const unmutedIcon = document.getElementById('mic-icon-unmuted');
  const mutedIcon = document.getElementById('mic-icon-muted');

  if (state.isMicMuted) {
    if (state.recognition) state.recognition.stop();
    unmutedIcon.classList.add('hidden');
    mutedIcon.classList.remove('hidden');
    appendVoiceLog('system', 'Microphone muted.');
  } else {
    if (state.isCallActive && state.recognition) {
      try { state.recognition.start(); } catch (e) {}
    }
    unmutedIcon.classList.remove('hidden');
    mutedIcon.classList.add('hidden');
    appendVoiceLog('system', 'Microphone unmuted.');
  }
}

async function handleFinalVoiceTurn(transcript) {
  if (state.isThinking || state.isSpeaking) return;
  state.isThinking = true;
  updateVoiceUIState('thinking');

  // Stop recognition while Hermes processes and speaks
  if (state.recognition) {
    try { state.recognition.stop(); } catch (e) {}
  }

  appendVoiceLog('user', transcript);

  const voiceSelect = document.getElementById('voice-select');
  const selectedVoiceId = voiceSelect ? voiceSelect.value : null;

  try {
    const res = await fetch('/api/voice/call-turn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: transcript,
        voice_id: selectedVoiceId,
      }),
    });

    const data = await res.json();
    state.isThinking = false;

    if (data.response_text) {
      appendVoiceLog('assistant', data.response_text, data.retrieved_context);
      await playVoiceResponse(data.response_text, data.audio_base64, data.used_elevenlabs);
    } else {
      updateVoiceUIState('listening');
      if (state.isCallActive && state.recognition) {
        try { state.recognition.start(); } catch (e) {}
      }
    }
  } catch (err) {
    console.error('Voice call error:', err);
    state.isThinking = false;
    appendVoiceLog('system', `Error processing turn: ${err.message}`);
    updateVoiceUIState('listening');
    if (state.isCallActive && state.recognition) {
      try { state.recognition.start(); } catch (e) {}
    }
  }
}

async function playVoiceResponse(text, audioBase64, usedElevenLabs) {
  state.isSpeaking = true;
  updateVoiceUIState('speaking');

  const engineBadge = document.getElementById('tts-engine-badge');
  if (engineBadge) {
    engineBadge.textContent = usedElevenLabs ? 'ElevenLabs Turbo TTS' : 'Web Speech Synthesis';
  }

  return new Promise((resolve) => {
    const onFinished = () => {
      state.isSpeaking = false;
      if (state.isCallActive) {
        updateVoiceUIState('listening');
        if (state.recognition && !state.isMicMuted) {
          try { state.recognition.start(); } catch (e) {}
        }
      } else {
        updateVoiceUIState('idle');
      }
      resolve();
    };

    if (usedElevenLabs && audioBase64) {
      try {
        const audio = new Audio(`data:audio/mpeg;base64,${audioBase64}`);
        state.audioPlayer = audio;
        audio.onended = onFinished;
        audio.onerror = (e) => {
          console.warn('Audio playback error, falling back to WebTTS:', e);
          fallbackWebTTS(text, onFinished);
        };
        audio.play().catch(() => fallbackWebTTS(text, onFinished));
      } catch (err) {
        fallbackWebTTS(text, onFinished);
      }
    } else {
      fallbackWebTTS(text, onFinished);
    }
  });
}

function fallbackWebTTS(text, onFinishedCallback) {
  if (!('speechSynthesis' in window)) {
    onFinishedCallback();
    return;
  }
  window.speechSynthesis.cancel();
  const clean = text.replace(/[*_#`]/g, '');
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  utterance.onend = onFinishedCallback;
  utterance.onerror = onFinishedCallback;
  window.speechSynthesis.speak(utterance);
}

function updateVoiceUIState(uiState) {
  const sphere = document.getElementById('voice-sphere');
  const pillDot = document.getElementById('voice-pill-dot');
  const pillText = document.getElementById('voice-status-text');
  const stateTitle = document.getElementById('voice-state-title');
  const stateSub = document.getElementById('voice-state-sub');
  const transcribingBadge = document.getElementById('transcribing-badge');

  if (!sphere) return;

  // Reset classes
  sphere.className = 'w-48 h-48 sm:w-56 sm:h-56 rounded-full transition-all duration-500 relative flex items-center justify-center';

  if (uiState === 'idle') {
    sphere.classList.add('visualizer-idle', 'bg-gradient-to-tr', 'from-indigo-950', 'via-slate-900', 'to-indigo-900', 'border', 'border-indigo-500/30');
    pillDot.className = 'w-2 h-2 rounded-full bg-slate-500 mr-2';
    pillText.textContent = 'Ready to Connect';
    stateTitle.textContent = 'Interactive Voice Call';
    stateSub.textContent = 'Tap Start Voice Call to begin hands-free conversation with Hermes 3.';
    if (transcribingBadge) transcribingBadge.classList.add('hidden');
  } else if (uiState === 'listening') {
    sphere.classList.add('visualizer-listening', 'bg-gradient-to-tr', 'from-emerald-950', 'via-slate-900', 'to-emerald-900', 'border', 'border-emerald-500/50');
    pillDot.className = 'w-2 h-2 rounded-full bg-emerald-400 mr-2 animate-ping';
    pillText.textContent = 'Listening (Speak now)';
    stateTitle.textContent = 'Hermes 3 is Listening...';
    stateSub.textContent = 'Speak naturally about any Discord conversation or decision.';
    if (transcribingBadge) transcribingBadge.classList.remove('hidden');
  } else if (uiState === 'thinking') {
    sphere.classList.add('visualizer-thinking', 'bg-gradient-to-tr', 'from-violet-950', 'via-slate-900', 'to-purple-900', 'border', 'border-violet-500/50');
    pillDot.className = 'w-2 h-2 rounded-full bg-violet-400 mr-2 animate-pulse';
    pillText.textContent = 'Hermes 3 Thinking & Grounding';
    stateTitle.textContent = 'Synthesizing Vault Context...';
    stateSub.textContent = 'Querying SQLite FTS5 90-day archive and preparing spoken synthesis.';
    if (transcribingBadge) transcribingBadge.classList.add('hidden');
  } else if (uiState === 'speaking') {
    sphere.classList.add('visualizer-speaking', 'bg-gradient-to-tr', 'from-blue-950', 'via-slate-900', 'to-indigo-900', 'border', 'border-blue-500/50');
    pillDot.className = 'w-2 h-2 rounded-full bg-blue-400 mr-2 animate-bounce';
    pillText.textContent = 'Hermes 3 Speaking';
    stateTitle.textContent = 'Speaking Answer';
    stateSub.textContent = 'Audio output streaming via ElevenLabs / Web Audio.';
    if (transcribingBadge) transcribingBadge.classList.add('hidden');
  }
}

function appendVoiceLog(role, text, sources = null) {
  const container = document.getElementById('voice-turn-log');
  if (!container) return;

  // Clear idle greeting if present
  if (container.children.length === 1 && container.children[0].textContent.includes('Session is idle')) {
    container.innerHTML = '';
  }

  const el = document.createElement('div');
  const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  if (role === 'user') {
    el.className = 'bg-slate-900/90 border border-slate-800 p-3.5 rounded-2xl ml-6 space-y-1';
    el.innerHTML = `
      <div class="flex items-center justify-between text-[11px] font-mono text-slate-400">
        <span class="text-indigo-400 font-semibold">You (Voice)</span>
        <span>${now}</span>
      </div>
      <p class="text-slate-200 text-sm">${escapeHtml(text)}</p>
    `;
  } else if (role === 'assistant') {
    let sourceHtml = '';
    if (sources && sources.length > 0) {
      sourceHtml = `
        <details class="text-xs text-slate-400 pt-1">
          <summary class="cursor-pointer hover:text-slate-300 font-mono text-[11px]">Grounded in ${sources.length} Discord messages</summary>
          <div class="mt-2 space-y-1 pl-2 border-l border-slate-700">
            ${sources.slice(0, 3).map(s => `
              <div class="text-[11px] font-mono text-slate-300">
                #${escapeHtml(s.channel_id)} | <span class="text-indigo-300">${escapeHtml(s.author)}</span>: ${escapeHtml(s.content.substring(0, 70))}...
              </div>
            `).join('')}
          </div>
        </details>
      `;
    }

    el.className = 'bg-indigo-950/30 border border-indigo-900/40 p-3.5 rounded-2xl mr-6 space-y-1';
    el.innerHTML = `
      <div class="flex items-center justify-between text-[11px] font-mono text-slate-400">
        <span class="text-emerald-400 font-semibold">Hermes 3</span>
        <span>${now}</span>
      </div>
      <p class="text-slate-100 text-sm leading-relaxed">${escapeHtml(text)}</p>
      ${sourceHtml}
    `;
  } else {
    el.className = 'text-center text-[11px] font-mono text-slate-500 py-1';
    el.textContent = `[${now}] ${text}`;
  }

  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

function clearVoiceLog() {
  const container = document.getElementById('voice-turn-log');
  if (container) {
    container.innerHTML = `
      <div class="text-center text-xs text-slate-500 py-12">
        Session log cleared. Ready for next voice turn.
      </div>
    `;
  }
}

// --- Chat with Hermes 3 (Grounded RAG) ---
async function handleChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('btn-send-chat');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  appendChatMessage('user', msg);

  btn.disabled = true;
  btn.classList.add('opacity-50');

  // Add thinking placeholder
  const placeholderId = appendChatPlaceholder();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        history: state.chatHistory,
      }),
    });

    const data = await res.json();
    removeChatPlaceholder(placeholderId);

    if (data.response) {
      appendChatMessage('assistant', data.response, data.retrieved_context);
      state.chatHistory.push({ role: 'user', content: msg });
      state.chatHistory.push({ role: 'assistant', content: data.response });
    }
  } catch (err) {
    removeChatPlaceholder(placeholderId);
    appendChatMessage('assistant', `Error connecting to Hermes: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-50');
  }
}

function appendChatMessage(role, text, sources = null) {
  const container = document.getElementById('chat-messages-container');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'flex items-start gap-3';

  if (role === 'user') {
    msgDiv.innerHTML = `
      <div class="h-8 w-8 rounded-lg bg-slate-700 flex items-center justify-center flex-shrink-0 text-white text-xs font-bold">U</div>
      <div class="max-w-2xl bg-indigo-600 text-white rounded-2xl rounded-tl-sm p-4 text-sm shadow-md">
        <p class="whitespace-pre-wrap">${escapeHtml(text)}</p>
      </div>
    `;
  } else {
    let sourcesBlock = '';
    if (sources && sources.length > 0) {
      sourcesBlock = `
        <div class="mt-3 pt-3 border-t border-slate-800">
          <details class="text-xs text-slate-400">
            <summary class="cursor-pointer hover:text-indigo-300 font-mono font-medium flex items-center gap-1.5">
              <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
              <span>View Grounded Vault Sources (${sources.length} matching messages)</span>
            </summary>
            <div class="mt-2 space-y-2 max-h-48 overflow-y-auto pr-1">
              ${sources.map(s => `
                <div class="p-2 rounded bg-slate-950/70 border border-slate-800 text-[11px] font-mono">
                  <div class="flex justify-between text-slate-400">
                    <span class="text-indigo-400 font-bold">#${escapeHtml(s.channel_id)}</span>
                    <span>${escapeHtml(s.author)}</span>
                    <span>${(s.timestamp || '').substring(0, 10)}</span>
                  </div>
                  <p class="text-slate-200 mt-1">${escapeHtml(s.content)}</p>
                </div>
              `).join('')}
            </div>
          </details>
        </div>
      `;
    }

    msgDiv.innerHTML = `
      <div class="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0 text-white text-xs font-bold">TS</div>
      <div class="max-w-2xl bg-slate-900/90 border border-slate-800 rounded-2xl rounded-tl-sm p-4 text-sm text-slate-200 shadow-md space-y-2">
        <div class="prose prose-invert max-w-none text-sm leading-relaxed">${renderSimpleMarkdown(text)}</div>
        ${sourcesBlock}
      </div>
    `;
  }

  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

function appendChatPlaceholder() {
  const container = document.getElementById('chat-messages-container');
  const id = `placeholder-${Date.now()}`;
  const div = document.createElement('div');
  div.id = id;
  div.className = 'flex items-start gap-3';
  div.innerHTML = `
    <div class="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0 text-white text-xs font-bold">TS</div>
    <div class="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 text-xs font-mono text-slate-400 flex items-center gap-2">
      <div class="inline-block animate-spin rounded-full h-3.5 w-3.5 border-2 border-indigo-500 border-t-transparent"></div>
      <span>Hermes 3 synthesizing RAG context...</span>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeChatPlaceholder(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function clearChatHistory() {
  state.chatHistory = [];
  const container = document.getElementById('chat-messages-container');
  if (container) {
    container.innerHTML = `
      <div class="flex items-start gap-3">
        <div class="h-8 w-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0 text-white text-xs font-bold">TS</div>
        <div class="max-w-2xl bg-slate-900/90 border border-slate-800 rounded-2xl rounded-tl-sm p-4 text-sm text-slate-200">
          <p>Chat cleared. Ask anything regarding your 90-day Discord conversations!</p>
        </div>
      </div>
    `;
  }
}

// --- Direct Discord JSON Upload & Drag & Drop (Zero Bot Method) ---
function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  const zone = document.getElementById('drop-zone');
  if (zone) zone.classList.add('border-indigo-500', 'bg-indigo-950/20');
}

function handleDragLeave(e) {
  e.preventDefault();
  e.stopPropagation();
  const zone = document.getElementById('drop-zone');
  if (zone) zone.classList.remove('border-indigo-500', 'bg-indigo-950/20');
}

function handleFileDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  const zone = document.getElementById('drop-zone');
  if (zone) zone.classList.remove('border-indigo-500', 'bg-indigo-950/20');

  const files = e.dataTransfer.files;
  if (files && files.length > 0) {
    uploadDiscordJsonFile(files[0]);
  }
}

function handleFileSelect(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    uploadDiscordJsonFile(files[0]);
  }
}

async function uploadDiscordJsonFile(file) {
  if (!file.name.endsWith('.json')) {
    alert('Please select a valid JSON file exported from DiscordChatExporter.');
    return;
  }

  const logOutput = document.getElementById('export-log-output');
  const badge = document.getElementById('export-status-badge');
  if (badge) {
    badge.className = 'text-xs px-2.5 py-0.5 rounded-full font-mono bg-indigo-950/60 text-indigo-400 border border-indigo-800/60';
    badge.textContent = 'Importing...';
  }

  logOutput.textContent = `[${new Date().toISOString()}] Uploading and parsing "${file.name}" (${(file.size / 1024).toFixed(1)} KB)...\n`;
  logOutput.textContent += `Zero bot method active: Parsing exported conversation archive into SQLite FTS5...\n`;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload-json', {
      method: 'POST',
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Upload failed');
    }

    logOutput.textContent += `[+] Import successful!\n`;
    logOutput.textContent += `File: ${data.filename}\n`;
    logOutput.textContent += `Channel: #${data.channel}\n`;
    logOutput.textContent += `Parsed Messages: ${data.parsed_messages}\n`;
    logOutput.textContent += `New Records Ingested: ${data.inserted_messages}\n`;
    logOutput.textContent += `Total Vault Archive: ${data.vault.total_messages} messages (${data.vault.messages_90_days} in 90d window)\n`;

    if (badge) {
      badge.className = 'text-xs px-2.5 py-0.5 rounded-full font-mono bg-emerald-950/60 text-emerald-400 border border-emerald-800/60';
      badge.textContent = 'Imported';
    }

    fetchStatus();
    executeSearch();
    alert(`Successfully imported ${data.inserted_messages} messages from "${file.name}"!`);
  } catch (err) {
    logOutput.textContent += `[-] ERROR: ${err.message}\n`;
    if (badge) {
      badge.className = 'text-xs px-2.5 py-0.5 rounded-full font-mono bg-red-950/60 text-red-400 border border-red-800/60';
      badge.textContent = 'Failed';
    }
    alert(`Failed to import JSON: ${err.message}`);
  }
}

// --- Discord Exporter Execution ---
async function runDiscordExport() {
  const channelInput = document.getElementById('export-channel-id');
  const tokenInput = document.getElementById('export-token');
  const daysInput = document.getElementById('export-days');
  const isBotInput = document.getElementById('export-is-bot');
  const logOutput = document.getElementById('export-log-output');
  const btn = document.getElementById('btn-run-export');

  const channelId = channelInput.value.trim();
  const token = tokenInput.value.trim();
  const days = parseInt(daysInput.value, 10) || 90;
  const isBot = isBotInput.checked;

  if (!channelId || !token) {
    alert('Please enter both Discord Channel ID and Authentication Token.');
    return;
  }

  btn.disabled = true;
  btn.classList.add('opacity-50');
  logOutput.textContent = `[${new Date().toISOString()}] Launching DiscordChatExporter subprocess...\n`;
  logOutput.textContent += `Channel: ${channelId} | History Window: ${days} days | Bot Token: ${isBot}\n`;

  try {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_id: channelId,
        token: token,
        days: days,
        bot_token: isBot,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Export failed');
    }

    logOutput.textContent += `[+] Export completed successfully!\n`;
    logOutput.textContent += `Exported: ${data.exported_messages} messages\n`;
    logOutput.textContent += `Ingested/Deduplicated into SQLite: ${data.inserted_messages} records\n`;
    logOutput.textContent += `File stored: ${data.file_path}\n`;

    fetchStatus();
    executeSearch();
  } catch (err) {
    logOutput.textContent += `[-] ERROR: ${err.message}\n`;
  } finally {
    btn.disabled = false;
    btn.classList.remove('opacity-50');
  }
}

// --- Sample Data Seeding & Vault Management ---
async function seedSampleData() {
  const logOutput = document.getElementById('export-log-output');
  if (logOutput) {
    logOutput.textContent = `[*] Seeding realistic 90-day Discord conversation archive into chat vault...\n`;
  }

  try {
    const res = await fetch('/api/ingest-sample', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      if (logOutput) {
        logOutput.textContent += `[+] Successfully seeded ${data.seeded_messages} messages across channels (#dev-core, #research-hermes, #operations, #product, #general).\n`;
      }
      await fetchStatus();
      await executeSearch();
      alert(`Successfully seeded ${data.seeded_messages} messages into the 90-day chat vault!`);
    }
  } catch (err) {
    alert(`Failed to seed data: ${err.message}`);
  }
}

async function confirmClearVault() {
  if (!confirm('Are you sure you want to clear all messages from the SQLite chat vault? This cannot be undone.')) {
    return;
  }

  try {
    const res = await fetch('/api/clear-vault', { method: 'POST' });
    if (res.ok) {
      fetchStatus();
      executeSearch();
      alert('Chat vault has been cleared.');
    }
  } catch (err) {
    alert(`Error clearing vault: ${err.message}`);
  }
}

// --- System Configuration & Settings ---
async function saveSettings() {
  const llmUrl = document.getElementById('cfg-llm-url').value.trim();
  const llmModel = document.getElementById('cfg-llm-model').value.trim();
  const llmKey = document.getElementById('cfg-llm-key').value.trim();
  const elevenKey = document.getElementById('cfg-eleven-key').value.trim();
  const elevenVoice = document.getElementById('cfg-eleven-voice').value.trim();

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        llm_base_url: llmUrl || undefined,
        llm_model: llmModel || undefined,
        llm_api_key: llmKey || undefined,
        elevenlabs_api_key: elevenKey || undefined,
        elevenlabs_voice_id: elevenVoice || undefined,
      }),
    });

    const data = await res.json();
    if (res.ok) {
      fetchStatus();
      alert('Settings saved successfully!');
    }
  } catch (err) {
    alert(`Failed to save settings: ${err.message}`);
  }
}

// --- Utility Functions ---
function formatDate(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoStr;
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeAttr(text) {
  if (!text) return '';
  return String(text).replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\n/g, ' ');
}

function renderSimpleMarkdown(text) {
  if (!text) return '';
  let out = escapeHtml(text);
  // Bold
  out = out.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic
  out = out.replace(/\*(.*?)\*/g, '<em>$1</em>');
  // Inline code
  out = out.replace(/`(.*?)`/g, '<code class="bg-slate-800 text-indigo-300 px-1 py-0.5 rounded text-xs font-mono">$1</code>');
  // Linebreaks
  out = out.replace(/\n/g, '<br/>');
  return out;
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const originalText = btn.innerHTML;
    btn.innerHTML = `<span class="text-emerald-400">Copied!</span>`;
    setTimeout(() => { btn.innerHTML = originalText; }, 1500);
  });
}
