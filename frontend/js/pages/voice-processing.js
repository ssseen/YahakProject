import { navigate } from '../router.js';
import { getState, setState } from '../state.js';
import { renderHeader } from '../components/header.js';

const DEBUG_STEPS = ['ready', 'recording', 'recognizing', 'understanding', 'error'];
const API_BASE = 'https://yahak-backend-815747505478.asia-northeast3.run.app';
const STT_URL = 'http://localhost:8000/transcribe';

function getDebugStep() {
  const query = window.location.hash.split('?')[1];
  const step = new URLSearchParams(query).get('step');
  return DEBUG_STEPS.includes(step) ? step : null;
}

export function renderVoiceProcessing(container) {
  let step = getDebugStep() || 'ready';

  let stream = null;
  let mediaRecorder = null;
  let audioChunks = [];
  let audioContext = null;
  let analyser = null;
  let animationFrameId = null;

  // 실시간 STT (Web Speech API) 상태
  let recognition = null;
  let liveTranscript = '';
  let recognizedText = '';

  function render() {
    if (step === 'ready') renderReady();
    else if (step === 'recording') renderRecording();
    else if (step === 'recognizing') renderRecognizing();
    else if (step === 'understanding') renderUnderstanding();
    else renderError();
  }

  function stopSpeechRecognition() {
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

  function stopAudioStream() {
    stopSpeechRecognition();
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
    container.querySelector('#skip-voice-btn').addEventListener('click', async () => {
      setState({ voiceQuestionText: null });
      // 이미 사진 단계에서 해설이 준비되어 있으면 바로 이동, 아니면 기본 질문으로 분석 호출
      if (getState().question) {
        navigate('/solve');
      } else {
        await requestAnalyzeWithImageAndVoice('이 문제 좀 알려줘');
      }
    });
  }

  function startLiveSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    liveTranscript = '';
    recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let finalStr = '';
      let interimStr = '';
      for (let i = 0; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalStr += transcript + ' ';
        } else {
          interimStr += transcript;
        }
      }
      liveTranscript = (finalStr + interimStr).trim();
      const liveBox = container.querySelector('#live-stt-text');
      if (liveBox && liveTranscript) {
        liveBox.textContent = '"' + liveTranscript + '"';
        liveBox.style.color = 'var(--color-text)';
      }
    };

    recognition.onerror = (e) => {
      console.warn('실시간 STT 경고:', e.error);
    };

    try {
      recognition.start();
    } catch (e) {
      console.warn('실시간 STT 시작 실패:', e);
    }
  }

  async function startRecording() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error('마이크 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    audioChunks = [];
    liveTranscript = '';
    recognizedText = '';
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    });

    mediaRecorder.addEventListener('stop', () => {
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      uploadVoice(blob);
    });

    mediaRecorder.start();

    step = 'recording';
    render();
    startVolumeMeter();
    startLiveSpeechRecognition();
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
      <section class="voice-screen">
        <p>말씀이 끝나시면<br />버튼을 눌러주세요</p>
        <div class="wave-bars" aria-hidden="true">
          ${barsHtml}
        </div>
        <!-- 1번: 실시간으로 말하는 텍스트가 뜨는 영역 -->
        <p id="live-stt-text" style="min-height: 48px; margin: 12px 24px; padding: 10px 14px; background: #F5F5F5; border-radius: 10px; font-size: 0.75rem; color: var(--color-text-muted); text-align: center; word-break: keep-all;">
          말씀하시는 내용이 여기에 실시간으로 표시됩니다...
        </p>
        <button class="stop-btn" id="stop-btn" type="button" aria-label="녹음 종료">
          <img src="image/stop_btn.svg" alt="" aria-hidden="true" class="stop-icon" />
        </button>
      </section>
    `;
    container.querySelector('#stop-btn').addEventListener('click', () => {
      stopSpeechRecognition();
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
    const formData = new FormData();
    formData.append('audio_file', blob, 'record.webm');

    let finalText = '';

    try {
      const res = await fetch(STT_URL, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        const result = await res.json();
        finalText = (result.text || '').trim();
        console.log('🎯 Whisper 변환 텍스트:', finalText);
      }
    } catch (err) {
      console.warn('로컬 Whisper 서버 미연결 - 실시간 STT 텍스트를 사용합니다:', err);
    }

    // 로컬 Whisper 결과가 비어있거나 서버가 꺼져 있으면 실시간 STT(liveTranscript)로 폴백
    if (!finalText && liveTranscript) {
      finalText = liveTranscript.trim();
    }

    if (!finalText) {
      step = 'error';
      render();
      return;
    }

    recognizedText = finalText;
    setState({ voiceQuestionText: finalText });

    // 1) 음성 인식 성공 화면 잠깐 보여주기 (인식된 텍스트 함께 표시)
    step = 'recognizing';
    render();

    // 2) 0.8초 뒤 '질문을 이해하고 있어요' 화면으로 전환하며 이미지+음성을 동시에 제미나이로 전송!
    setTimeout(() => {
      requestAnalyzeWithImageAndVoice(finalText);
    }, 800);
  }

  // ★ 9번 핵심: 사진(image)과 음성 질문(userQuestion)을 동시에 백엔드(/api/analyze)로 전달 ★
  async function requestAnalyzeWithImageAndVoice(questionText) {
    step = 'understanding';
    render();

    const photoState = getState().photo;
    if (!photoState || !photoState.dataUri) {
      // 만약 사진 없이 음성 페이지로만 테스트 들어온 경우
      navigate('/solve');
      return;
    }

    try {
      const res = await fetch(API_BASE + '/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: photoState.dataUri,
          userQuestion: questionText,
        }),
      });

      if (!res.ok) {
        console.error('Analyze API 오류:', res.status);
        step = 'error';
        render();
        return;
      }

      const data = await res.json();
      if (data.status === 'success') {
        setState({ question: data });
        navigate('/solve');
      } else {
        step = 'error';
        render();
      }
    } catch (err) {
      console.error('제미나이 연동 네트워크 오류:', err);
      step = 'error';
      render();
    }
  }

  function renderUnderstanding() {
    hideHeader();
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <p>질문을 이해하고 있어요.<br />잠시만 기다려주세요<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
        ${recognizedText ? '<p style="font-size: 0.75rem; color: var(--color-text-muted); margin: -20px 24px 0; text-align: center;">질문: "' + recognizedText + '"</p>' : ''}
        <div class="spinner" aria-hidden="true"></div>
      </section>
    `;
  }

  function renderError() {
    hideHeader();
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

  render();
}