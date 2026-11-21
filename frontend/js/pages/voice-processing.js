import { navigate, goBack } from '../router.js';
import { getState, setState, getUserLevelForRequest } from '../state.js';
import { renderHeader } from '../components/header.js';
import { startLoading, endLoading } from '../loading-guard.js';
import { speak, stopSpeaking } from '../tts.js';
import { mountWaitQuiz, showReadyPopup } from '../components/wait-quiz.js';

const GUIDE_VOICE = '마이크 버튼을 누르고 질문해 주세요. 말씀이 끝나면 버튼을 한 번 더 눌러 주세요.';

const DEBUG_STEPS = ['ready', 'recording', 'waiting', 'error'];
const API_BASE = 'https://yahak-backend-815747505478.asia-northeast3.run.app';
// Whisper STT 서버 (whisper/ 폴더를 Cloud Run에 따로 배포한 서비스)
// 배포 후 나온 서비스 URL로 바꿔 넣기. 로컬에서 열면 로컬 백엔드(main.py)의 /transcribe 사용
const STT_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  ? 'http://localhost:8000'
  : 'https://yahak-stt-815747505478.asia-northeast3.run.app';
const STT_URL = STT_BASE + '/transcribe';
// 음성 인식 비교 표시: 주소에 ?sttdebug=1 을 붙이면 힌트 있을 때/없을 때 결과와 시간을 대기 화면에 보여줌
// (서버가 두 번 돌리므로 그만큼 느려짐 - 측정할 때만)
const STT_DEBUG = new URLSearchParams(window.location.search).get('sttdebug') === '1';
const HINT_POLL_MS = 800; // 녹음하는 동안 힌트(시험지 낱말)를 받아 오는 간격
// 마이크 진단 표시: 주소에 ?micdebug=1 을 붙이면 마이크 상태(트랙 muted, 소리 크기, 자막 오류, 녹음 크기)를 화면 아래에 띄움
// (아이폰에서 두 번째 질문부터 마이크가 소리를 못 받는 문제 원인 확인용)
const MIC_DEBUG = new URLSearchParams(window.location.search).get('micdebug') === '1';
// 아이폰/아이패드(iOS는 크롬도 사파리 엔진): 실시간 자막(음성인식)이 녹음기와 마이크를 동시에 쓰면
// 가끔 자막 쪽이 마이크를 가져가 녹음이 0 bytes가 됨 (2026-11-21 ?micdebug=1로 확인: 마이크 정상 열림 +
// 자막 시작됨 + 녹음 0조각). 그래서 iOS에서는 녹음 중 실시간 자막을 끈다. 비교용으로 ?caption=1이면 강제로 켬
const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const LIVE_CAPTION = !IS_IOS || new URLSearchParams(window.location.search).get('caption') === '1';

function micDebug(line) {
  console.log('🎤 ' + line);
  if (!MIC_DEBUG) return;
  let panel = document.getElementById('mic-debug-panel');
  if (!panel) {
    panel = document.createElement('pre');
    panel.id = 'mic-debug-panel';
    panel.style.cssText = 'position:fixed;left:0;right:0;bottom:0;max-height:40vh;overflow:auto;margin:0;'
      + 'padding:8px;background:rgba(0,0,0,.8);color:#0f0;font:12px/1.4 monospace;white-space:pre-wrap;z-index:99999;';
    panel.addEventListener('click', () => panel.remove()); // 누르면 닫힘
    document.body.appendChild(panel);
  }
  const t = new Date().toTimeString().slice(0, 8);
  panel.textContent += `[${t}] ${line}\n`;
  panel.scrollTop = panel.scrollHeight;
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// 로딩 중 "나가기"를 눌렀을 때: 사진/질문 상태를 비우고 메뉴로
const LEAVE = () => goBack();

function getDebugStep() {
  const query = window.location.hash.split('?')[1];
  const step = new URLSearchParams(query).get('step');
  return DEBUG_STEPS.includes(step) ? step : null;
}

export function renderVoiceProcessing(container) {
  let step = getDebugStep() || 'ready';
  // 브라우저 뒤로가기 등으로 화면을 떠나면 안내 음성 중지
  window.addEventListener('hashchange', stopSpeaking, { once: true });

  let stream = null;
  let mediaRecorder = null;
  let audioChunks = [];
  let audioContext = null;
  let analyser = null;
  let animationFrameId = null;
  let leftPage = false;

  // 실시간 자막(크롬 Web Speech API) - 말하는 동안 화면에 보여주기만 함.
  // 최종 질문 텍스트는 항상 Whisper 결과를 씀 (자막 텍스트는 서버로 안 보냄)
  let recognition = null;
  let recognizedText = '';
  let quiz = null; // 기다리는 동안 퀴즈 - 해설이 나왔을 때 퀴즈를 했는지 확인용
  let retakeMessage = ''; // 해설 요청이 retake(사진 다시 찍기)로 끝났을 때 보여줄 서버 안내 문구
  // 음성 인식 힌트: 사진을 미리 처리한 서버 세션에서 문항 낱말을 받아 Whisper에 같이 보낸다.
  // 녹음하는 동안만 받아 오고, 녹음이 끝났을 때 아직 없으면 기다리지 않고 힌트 없이 보낸다.
  let hintText = '';
  let hintTimer = null;
  let sttDebug = null; // STT_DEBUG일 때 서버가 준 비교 결과
  let peakLevel = 0; // 녹음 중 들어온 가장 큰 소리 (0이면 마이크가 소리를 못 받은 것)

  function render() {
    if (step === 'ready') renderReady();
    else if (step === 'recording') renderRecording();
    else if (step === 'waiting') renderWaiting();
    else renderError();
  }

  function stopLiveCaption() {
    if (recognition) {
      try {
        recognition.onend = null;
        recognition.onresult = null;
        recognition.onerror = null;
        // stop()은 마지막 결과를 기다리느라 마이크를 바로 안 놓는 경우가 있어(아이폰) abort()로 즉시 해제.
        // 자막은 화면 표시용이라 마지막 결과를 버려도 됨
        recognition.abort();
      } catch (e) {
        // ignore
      }
      recognition = null;
    }
  }

  function startLiveCaption() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return; // 지원 안 하는 브라우저면 자막 없이 녹음만

    recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let text = '';
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript + (event.results[i].isFinal ? ' ' : '');
      }
      const box = container.querySelector('#live-caption');
      if (box && text.trim()) {
        box.textContent = '"' + text.trim() + '"';
        box.style.color = 'var(--color-text)';
      }
    };
    recognition.onerror = (e) => micDebug('자막 오류: ' + e.error);
    recognition.onstart = () => micDebug('자막 시작됨');

    try {
      recognition.start();
    } catch (e) {
      micDebug('자막 시작 실패: ' + e);
    }
  }

  function stopAudioStream() {
    leftPage = true;
    stopHintFetch();
    stopSpeaking();
    stopLiveCaption();
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    mediaRecorder = null;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    analyser = null;
  }

  function renderReady() {
    showHeader();
    container.innerHTML = `
      <section class="voice-screen">
        <p>준비가 되시면<br />녹음 버튼을 눌러주세요.</p>
        <button class="mic-btn" id="mic-btn" type="button" aria-label="녹음 시작">
          <img src="image/mic_btn.svg" alt="" aria-hidden="true" class="mic-icon" />
          <span class="ripple"></span>
        </button>
        <button class="link-btn" id="skip-voice-btn" type="button">사진으로만 질문하기</button>
      </section>
    `;
    container.querySelector('#mic-btn').addEventListener('click', startRecording);
    // 안내 음성 (녹음 시작하면 바로 끊음 - 안내 음성이 녹음에 섞이지 않게)
    speak(GUIDE_VOICE);
    container.querySelector('#skip-voice-btn').addEventListener('click', async () => {
      stopSpeaking();
      setState({ voiceQuestionText: null });
      // 이미 사진 단계에서 해설이 준비되어 있으면 바로 이동, 아니면 기본 질문으로 분석 호출
      if (getState().question) {
        navigate('/solve');
      } else {
        await requestAnalyzeWithImageAndVoice('이 문제 좀 알려줘');
      }
    });
  }

  function startHintFetch() {
    stopHintFetch();
    hintText = '';
    const sessionId = getState().photo?.sessionId;
    if (!sessionId) return;
    let tries = 0;
    const poll = async () => {
      hintTimer = null;
      tries += 1;
      try {
        const res = await fetch(`${API_BASE}/api/session/${encodeURIComponent(sessionId)}/hint`);
        if (res.ok) {
          const data = await res.json();
          if (data.ready) {
            hintText = data.hint || '';
            return; // 끝 (힌트가 없으면 없는 대로)
          }
        } else {
          return; // 세션 없음(404) 등 - 힌트 없이
        }
      } catch (e) {
        // 네트워크 오류 - 다음에 다시
      }
      if (tries < 40 && step === 'recording') hintTimer = setTimeout(poll, HINT_POLL_MS);
    };
    poll();
  }

  function stopHintFetch() {
    if (hintTimer) clearTimeout(hintTimer);
    hintTimer = null;
  }

  // 마이크를 연다. 아이폰은 바로 전에 TTS(해설 읽기·안내 음성)가 재생 중이었으면 오디오가 "재생 모드"에서
  // "녹음 모드"로 넘어가는 동안 소리 없는(muted) 마이크를 주는 경우가 있어, 재생을 끊고 잠깐 기다린 뒤 열고,
  // 그래도 muted면 한 번 닫았다가 다시 연다.
  async function openMic() {
    const wasSpeaking = 'speechSynthesis' in window
      && (window.speechSynthesis.speaking || window.speechSynthesis.pending);
    stopSpeaking();
    if (wasSpeaking) await wait(300);

    for (let attempt = 1; attempt <= 2; attempt++) {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      const track = s.getAudioTracks()[0];
      micDebug(`마이크 열림(${attempt}번째): ${track && track.label} muted=${track && track.muted} `
        + `state=${track && track.readyState} TTS재생중이었음=${!!wasSpeaking}`);
      if (track && !track.muted && track.readyState === 'live') return s;
      s.getTracks().forEach((t) => t.stop());
      await wait(400);
    }
    throw new Error('마이크가 소리를 받지 못함(muted)');
  }

  async function startRecording() {
    stopSpeaking();
    // 소리 막대용 AudioContext는 버튼을 누른 그 순간(await 전)에 만들어야 아이폰에서 멈춤(suspended) 상태가 안 됨
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      audioContext.resume().catch(() => {});
    } catch (e) {
      audioContext = null;
    }
    try {
      stream = await openMic();
    } catch (err) {
      if (audioContext) { audioContext.close(); audioContext = null; }
      micDebug('마이크 접근 실패: ' + err);
      step = 'error';
      render();
      return;
    }
    const track = stream.getAudioTracks()[0];
    if (track) {
      track.addEventListener('mute', () => micDebug('⚠ 녹음 중 마이크 muted 됨'));
      track.addEventListener('ended', () => micDebug('⚠ 녹음 중 마이크 끊김(ended)'));
    }

    audioChunks = [];
    recognizedText = '';
    const recStream = stream; // 녹음이 완전히 끝난 뒤 이 스트림을 닫는다
    const rec = new MediaRecorder(recStream);
    mediaRecorder = rec;
    micDebug('녹음 형식: ' + rec.mimeType);

    peakLevel = 0;
    rec.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) {
        if (!audioChunks.length) micDebug(`첫 녹음 조각 받음 (${e.data.size} bytes, ${e.data.type})`);
        audioChunks.push(e.data);
      }
    });

    rec.addEventListener('stop', () => {
      // 마이크는 녹음기가 마지막 데이터를 다 내보낸 다음에 끈다
      // (예전엔 stop() 직후 바로 꺼서 아이폰에서 마지막 조각이 빠질 수 있었음)
      recStream.getTracks().forEach((t) => t.stop());
      if (leftPage) return;
      const size = audioChunks.reduce((n, c) => n + c.size, 0);
      micDebug(`녹음 끝: ${audioChunks.length}조각 ${size} bytes`);
      micDebug(`녹음 중 최대 소리 크기: ${peakLevel.toFixed(2)} (0이면 마이크가 소리를 못 받은 것)`);
      const blob = new Blob(audioChunks, { type: rec.mimeType || audioChunks[0]?.type || 'audio/webm' });
      uploadVoice(blob);
    });

    // 0.5초마다 조각으로 받아 둔다 - 끝날 때 한 번에만 받으면 그 한 번이 비었을 때 전체가 비어 버림
    rec.start(500);

    step = 'recording';
    render();
    startHintFetch();
    startVolumeMeter();
    if (LIVE_CAPTION) startLiveCaption();
    else micDebug('실시간 자막 끔 (iOS - 녹음과 마이크 충돌 방지)');
  }

  function startVolumeMeter() {
    if (!audioContext) return; // AudioContext를 못 만든 기기 - 막대 없이 녹음만
    micDebug('소리 막대 AudioContext: ' + audioContext.state);
    const source = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const bars = container.querySelectorAll('.wave-bar');

    function tick() {
      analyser.getByteFrequencyData(dataArray);
      const average = dataArray.reduce((sum, v) => sum + v, 0) / dataArray.length;
      const level = Math.min(average / 128, 1);
      if (level > peakLevel) peakLevel = level;

      bars.forEach((bar, i) => {
        const variance = 0.7 + (i % 3) * 0.15;
        const height = 12 + level * 32 * variance;
        bar.style.height = height + 'px';
      });

      animationFrameId = requestAnimationFrame(tick);
    }
    tick();
  }

  function renderRecording() {
    showHeader();
    const barsHtml = Array.from({ length: 5 }).map(() => '<span class="wave-bar"></span>').join('');
    container.innerHTML = `
      <section class="voice-screen recording-screen">
        <p>말씀이 끝나시면<br />버튼을 눌러주세요</p>
        <div class="wave-bars" aria-hidden="true">
          ${barsHtml}
        </div>
        <p id="live-caption" style="min-height: 48px; margin: 12px 24px; padding: 10px 14px; background: #F5F5F5; border-radius: 10px; font-size: 0.85rem; color: var(--color-text-muted); text-align: center; word-break: keep-all;">
          ${LIVE_CAPTION ? '말씀하시는 내용이 여기에 실시간으로 표시됩니다...' : '듣고 있어요. 편하게 말씀해 주세요.'}
        </p>
        <button class="stop-btn" id="stop-btn" type="button" aria-label="녹음 종료">
          <img src="image/stop_btn.svg" alt="" aria-hidden="true" class="stop-icon" />
        </button>
      </section>
    `;
    container.querySelector('#stop-btn').addEventListener('click', () => {
      stopLiveCaption();
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop(); // 마이크는 녹음기 'stop' 이벤트에서 끈다
      } else if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      stream = null;
      if (audioContext) {
        audioContext.close();
        audioContext = null;
      }
      // 음성 인식 + 해설 생성(약 13~16초) 동안 퀴즈를 보여준다
      step = 'waiting';
      render();
    });
  }

  function hideHeader() {
    const headerRoot = document.getElementById('header-root');
    if (headerRoot) headerRoot.innerHTML = '';
  }

  function showHeader() {
    const headerRoot = document.getElementById('header-root');
    if (headerRoot) {
      headerRoot.innerHTML = '';
      headerRoot.appendChild(renderHeader({
        onBack: () => {
          stopAudioStream();
          goBack();
        },
      }));
    }
  }

  async function uploadVoice(blob) {
    const signal = startLoading(LEAVE); // 녹음이 끝나고 처리 시작할 때 1번

    stopHintFetch();
    // 소리가 하나도 안 담긴 녹음(아이폰에서 마이크가 소리를 못 받은 경우 ~수백 bytes)은 서버에 보내지 않는다
    if (blob.size < 1000) {
      micDebug(`녹음이 비어 있어 전송 안 함 (${blob.size} bytes)`);
      endLoading(() => {
        step = 'error';
        render();
      });
      return;
    }
    const formData = new FormData();
    formData.append('audio_file', blob, 'record.webm');
    if (hintText) formData.append('prompt', hintText);
    if (STT_DEBUG) formData.append('compare', '1');

    let finalText = '';

    try {
      const res = await fetch(STT_URL, {
        method: 'POST',
        body: formData,
        signal,
      });
      if (res.ok) {
        const result = await res.json();
        finalText = (result.text || '').trim();
        console.log('🎯 Whisper 변환 텍스트:', finalText, result.hint_used ? '(힌트 사용)' : '(힌트 없음)', result.ms + 'ms');
        if (STT_DEBUG) sttDebug = result;
      } else {
        console.error('Whisper 서버 오류:', res.status);
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('Whisper 서버 연결 실패:', err);
    }

    if (!finalText) {
      endLoading(() => {
        step = 'error';
        render();
      });
      return;
    }

    recognizedText = finalText;
    setState({ voiceQuestionText: finalText });

    // 따로 "인식 성공" 화면을 띄우지 않고, 퀴즈 화면 위쪽에 인식한 질문만 보여주고 바로 해설 요청
    showRecognizedQuestion();
    requestAnalyzeWithImageAndVoice(finalText, signal); // 같은 로딩으로 이어가기 위해 signal 전달
  }

  // ★ 9번 핵심: 사진(image)과 음성 질문(userQuestion)을 동시에 백엔드(/api/analyze)로 전달 ★
  async function requestAnalyzeWithImageAndVoice(questionText, existingSignal) {
    const signal = existingSignal || startLoading(LEAVE);
    if (signal.aborted) return;

    if (step !== 'waiting') { // "사진으로만 질문하기"로 바로 온 경우
      step = 'waiting';
      render();
    }

    const photoState = getState().photo;
    if (!photoState || !photoState.dataUri) {
      // 만약 사진 없이 음성 페이지로만 테스트 들어온 경우
      endLoading(() => navigate('/solve'));
      return;
    }

    // sessionId가 있으면 사진을 다시 보내지 않는다 - 서버가 녹음하는 동안 미리 처리해둔 결과로 바로 해설.
    // 없으면(구버전 서버 등) 예전처럼 사진 + 촬영 검사 결과를 보낸다.
    // sessionId(미리 처리 결과)와 사진을 같이 보낸다. 서버는 세션이 있으면 사진은 안 쓰고 바로 해설,
    // 세션이 없으면(시간 초과·서버 재시작·다른 서버로 요청이 감) 같이 온 사진으로 처음부터 처리한다
    // - 예전엔 sessionId만 보내서, 세션이 없으면 "사진 다시 찍기"가 떴음
    const body = {
      sessionId: photoState.sessionId || undefined,
      image: photoState.dataUri,
      userQuestion: questionText,
      userLevel: getUserLevelForRequest(),
      checkResult: photoState.check || undefined, // 촬영 검사 결과 (없으면 서버가 다시 검사)
    };

    try {
      const res = await fetch(API_BASE + '/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      });

      if (!res.ok) {
        console.error('Analyze API 오류:', res.status);
        endLoading(() => {
          step = 'error';
          render();
        });
        return;
      }

      const data = await res.json();
      if (data.status === 'success') {
        setState({ question: data });
        // 퀴즈를 안 건드렸으면 바로 해설로, 풀고 있었으면 팝업으로 알리고 본인이 누르게 함
        endLoading(() => {
          if (quiz && quiz.touched()) showReadyPopup(() => navigate('/solve'));
          else navigate('/solve');
        });
      } else if (data.status === 'retake') {
        // 사진 쪽 문제(사진 정보 만료, 문제 위치/글자를 못 찾음 등) - 다시 녹음해도 해결 안 되므로
        // "다시 말씀해주세요" 대신 서버 안내 문구와 사진 다시 찍기 버튼을 보여준다
        endLoading(() => {
          retakeMessage = data.message || '사진을 인식하지 못했어요.\n다시 찍어주세요';
          step = 'error';
          render();
        });
      } else {
        endLoading(() => {
          step = 'error';
          render();
        });
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('제미나이 연동 네트워크 오류:', err);
      endLoading(() => {
        step = 'error';
        render();
      });
    }
  }

  // 기다리는 화면: 위에는 진행 상태 + 인식한 질문, 아래는 퀴즈
  function renderWaiting() {
    hideHeader();
    container.innerHTML = `
      <section class="voice-screen wait-screen">
        <div class="wait-status">
          <div class="spinner wait-spinner" aria-hidden="true"></div>
          <p>해설을 만들고 있어요<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
        </div>
        <p class="wait-question" id="wait-question" hidden></p>
        <p class="wait-quiz-title">기다리는 동안 풀어보세요</p>
        <div id="wait-quiz"></div>
      </section>
    `;
    quiz = mountWaitQuiz(container.querySelector('#wait-quiz'));
    showRecognizedQuestion();
  }

  function showRecognizedQuestion() {
    const el = container.querySelector('#wait-question');
    if (!el || !recognizedText) return;
    el.textContent = '질문: "' + recognizedText + '"';
    el.hidden = false;
    if (STT_DEBUG) showSttDebug(el);
  }

  function showSttDebug(afterEl) {
    if (!sttDebug || container.querySelector('#stt-debug')) return;
    const sec = (ms) => (ms / 1000).toFixed(2) + '초';
    const lines = [`힌트: ${hintText || '(없음)'}`, `힌트 ${sttDebug.hint_used ? '사용' : '없음'} (${sec(sttDebug.ms)}): ${sttDebug.text}`];
    if ('text_nohint' in sttDebug) lines.push(`힌트 없이 (${sec(sttDebug.ms_nohint)}): ${sttDebug.text_nohint}`);
    const pre = document.createElement('pre');
    pre.id = 'stt-debug';
    pre.style.cssText = 'white-space:pre-wrap;font-size:12px;line-height:1.5;background:#222;color:#0f0;padding:8px;border-radius:6px;margin:8px 0;text-align:left;';
    pre.textContent = lines.join('\n');
    afterEl.after(pre);
  }

  function renderError() {
    hideHeader();
    if (retakeMessage) {
      renderRetake();
      return;
    }
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <img src="image/error_icon.png" alt="" aria-hidden="true" class="result-icon shake" />
        <p>말씀을 이해하지 못했어요.<br />다시 말씀해주세요.</p>
        <button class="btn btn-secondary" id="retry-btn" type="button">다시 녹음하기</button>
        <button class="link-btn" id="home-btn" type="button">처음으로 돌아가기</button>
      </section>
    `;
    container.querySelector('#retry-btn').addEventListener('click', () => {
      step = 'ready';
      render();
    });
    container.querySelector('#home-btn').addEventListener('click', () => {
      setState({ photo: null, question: null });
      navigate('/menu');
    });
  }

  // 해설 요청이 retake로 끝났을 때: 사진을 다시 찍어야 하므로 카메라로 돌려보낸다
  function renderRetake() {
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <img src="image/error_icon.png" alt="" aria-hidden="true" class="result-icon shake" />
        <p class="pre-line">${retakeMessage}</p>
        <button class="btn btn-secondary" id="retake-btn" type="button">사진 다시 찍기</button>
        <button class="link-btn" id="home-btn" type="button">처음으로 돌아가기</button>
      </section>
    `;
    container.querySelector('#retake-btn').addEventListener('click', () => {
      retakeMessage = '';
      setState({ photo: null, question: null });
      navigate('/camera');
    });
    container.querySelector('#home-btn').addEventListener('click', () => {
      setState({ photo: null, question: null });
      navigate('/menu');
    });
  }

  render();
}