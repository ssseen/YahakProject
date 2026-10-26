import { navigate } from '../router.js';
import { getState, setState, getUserLevelForRequest } from '../state.js';
import { renderHeader } from '../components/header.js';
import { startLoading, endLoading } from '../loading-guard.js';
import { speak, stopSpeaking } from '../tts.js';

const GUIDE_VOICE = '마이크 버튼을 누르고 질문해 주세요. 말씀이 끝나면 버튼을 한 번 더 눌러 주세요.';

const DEBUG_STEPS = ['ready', 'recording', 'recognizing', 'understanding', 'error'];
const API_BASE = 'https://yahak-backend-815747505478.asia-northeast3.run.app';
// Whisper STT 서버 (whisper/ 폴더를 Cloud Run에 따로 배포한 서비스)
// 배포 후 나온 서비스 URL로 바꿔 넣기. 로컬에서 열면 로컬 백엔드(main.py)의 /transcribe 사용
const STT_BASE = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  ? 'http://localhost:8000'
  : 'https://yahak-stt-815747505478.asia-northeast3.run.app';
const STT_URL = STT_BASE + '/transcribe';

// 로딩 중 "나가기"를 눌렀을 때: 사진/질문 상태를 비우고 이전 화면으로
const LEAVE = () => {
  setState({ photo: null, question: null });
  window.history.back();
};

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
  let retakeMessage = ''; // 해설 요청이 retake(사진 다시 찍기)로 끝났을 때 보여줄 서버 안내 문구

  function render() {
    if (step === 'ready') renderReady();
    else if (step === 'recording') renderRecording();
    else if (step === 'recognizing') renderRecognizing();
    else if (step === 'understanding') renderUnderstanding();
    else renderError();
  }

  function stopLiveCaption() {
    if (recognition) {
      try {
        recognition.onend = null;
        recognition.stop();
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
    recognition.onerror = (e) => console.warn('실시간 자막 경고:', e.error);

    try {
      recognition.start();
    } catch (e) {
      console.warn('실시간 자막 시작 실패:', e);
    }
  }

  function stopAudioStream() {
    leftPage = true;
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

  async function startRecording() {
    stopSpeaking();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error('마이크 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    audioChunks = [];
    recognizedText = '';
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    });

    mediaRecorder.addEventListener('stop', () => {
      if (leftPage) return;
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      uploadVoice(blob);
    });

    mediaRecorder.start();

    step = 'recording';
    render();
    startVolumeMeter();
    startLiveCaption();
  }

  function startVolumeMeter() {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
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
          말씀하시는 내용이 여기에 실시간으로 표시됩니다...
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
        mediaRecorder.stop();
      }
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
      if (audioContext) {
        audioContext.close();
        audioContext = null;
      }
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
          window.history.back();
        },
      }));
    }
  }

  function renderRecognizing() {
    hideHeader();
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <p>음성 인식 성공!</p>
        ${recognizedText ? '<p style="font-size: 0.8rem; color: var(--color-math-accent); margin: -20px 24px 0; text-align: center;">"' + recognizedText + '"</p>' : ''}
        <img src="image/success_icon.png" alt="" aria-hidden="true" class="result-icon" />
      </section>
    `;
  }

  async function uploadVoice(blob) {
    const signal = startLoading(LEAVE); // 녹음이 끝나고 처리 시작할 때 1번

    const formData = new FormData();
    formData.append('audio_file', blob, 'record.webm');

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
        console.log('🎯 Whisper 변환 텍스트:', finalText);
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

    // 1) 음성 인식 성공 화면 잠깐 보여주기 (인식된 텍스트 함께 표시)
    step = 'recognizing';
    render();

    // 2) 0.8초 뒤 '질문을 이해하고 있어요' 화면으로 전환하며 이미지+음성을 동시에 제미나이로 전송!
    setTimeout(() => {
      requestAnalyzeWithImageAndVoice(finalText, signal); // 같은 로딩으로 이어가기 위해 signal 전달
    }, 800);
  }

  // ★ 9번 핵심: 사진(image)과 음성 질문(userQuestion)을 동시에 백엔드(/api/analyze)로 전달 ★
  async function requestAnalyzeWithImageAndVoice(questionText, existingSignal) {
    const signal = existingSignal || startLoading(LEAVE);
    if (signal.aborted) return; // 인식 성공 화면(0.8초) 동안 나갔으면 중단

    step = 'understanding';
    render();

    const photoState = getState().photo;
    if (!photoState || !photoState.dataUri) {
      // 만약 사진 없이 음성 페이지로만 테스트 들어온 경우
      endLoading(() => navigate('/solve'));
      return;
    }

    // sessionId가 있으면 사진을 다시 보내지 않는다 - 서버가 녹음하는 동안 미리 처리해둔 결과로 바로 해설.
    // 없으면(구버전 서버 등) 예전처럼 사진 + 촬영 검사 결과를 보낸다.
    const body = photoState.sessionId
      ? {
          sessionId: photoState.sessionId,
          userQuestion: questionText,
          userLevel: getUserLevelForRequest(),
        }
      : {
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
        endLoading(() => navigate('/solve'));
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

  function renderUnderstanding() {
    hideHeader();
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <p>질문을 이해하고 있어요.<br />잠시만 기다려주세요<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
        ${recognizedText ? '<p style="font-size: 0.85rem; color: var(--color-text-muted); margin: -20px 24px 0; text-align: center;">질문: "' + recognizedText + '"</p>' : ''}
        <div class="spinner" aria-hidden="true"></div>
      </section>
    `;
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
    container.querySelector('#home-btn').addEventListener('click', () => navigate('/'));
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
    container.querySelector('#home-btn').addEventListener('click', () => navigate('/'));
  }

  render();
}