import { navigate } from '../router.js';
import { setState } from '../state.js';
import { renderHeader } from '../components/header.js';

const DEBUG_STEPS = ['ready', 'recording', 'recognizing', 'understanding', 'error'];

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

  function render() {
    if (step === 'ready') renderReady();
    else if (step === 'recording') renderRecording();
    else if (step === 'recognizing') renderRecognizing();
    else if (step === 'understanding') renderUnderstanding();
    else renderError();
  }

  function stopAudioStream() {
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
    container.querySelector('#skip-voice-btn').addEventListener('click', () => {
      setState({ voiceQuestionText: null });
      navigate('/solve');
    });
  }

  async function startRecording() {
    try {
      // 1. 마이크 접근 권한 요청[cite: 6]
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error('마이크 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    
    // 2. 녹음 중일 때 소리 조각 수집[cite: 6]
    mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    });
    
    // 3. 녹음 종료 시 실행 로직[cite: 6]
    mediaRecorder.addEventListener('stop', () => {
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      step = 'recognizing';
      render();
      uploadVoice(blob);
    });
    
    mediaRecorder.start();

    step = 'recording';
    render();
    startVolumeMeter();
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
        bar.style.height = `${height}px`;
      });

      animationFrameId = requestAnimationFrame(tick);
    }
    tick();
  }

  function renderRecording() {
    showHeader();
    container.innerHTML = `
      <section class="voice-screen">
        <p>말씀이 끝나시면<br />버튼을 눌러주세요</p>
        <div class="wave-bars" aria-hidden="true">
          ${Array.from({ length: 5 }).map(() => `<span class="wave-bar"></span>`).join('')}
        </div>
        <button class="stop-btn" id="stop-btn" type="button" aria-label="녹음 종료">
          <img src="image/stop_btn.svg" alt="" aria-hidden="true" class="stop-icon" />
        </button>
      </section>
    `;
    container.querySelector('#stop-btn').addEventListener('click', () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
      mediaRecorder.stop(); // 녹음 중지 시 자동으로 onstop 로직 실행[cite: 6]
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
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
        <img src="image/success_icon.png" alt="" aria-hidden="true" class="result-icon" />
      </section>
    `;
  }

  async function uploadVoice(blob) {
    // 백엔드로 보낼 FormData 조립[cite: 6]
    const formData = new FormData();
    formData.append('audio_file', blob, 'record.webm');

    console.log("🚀 서버로 음성 파일 배달 시작!"); //[cite: 6]

    let res;
    try {
      // API 전송[cite: 6]
      res = await fetch('http://localhost:8000/transcribe', {
        method: 'POST',
        body: formData,
      });
    } catch (err) {
      console.error('네트워크 오류:', err);
      step = 'error';
      render();
      return;
    }

    if (!res.ok) {
      console.error(`HTTP ${res.status}`);
      step = 'error';
      render();
      return;
    }

    // 결과 수신[cite: 6]
    const result = await res.json();
    console.log("🎯 변환된 사투리 텍스트:", result.text); //[cite: 6]
    
    setState({ voiceQuestionText: result.text });
    navigate('/solve');
  }

  function renderUnderstanding() {
    hideHeader();
    container.innerHTML = `
      <section class="voice-screen state-screen">
        <p>질문을 이해하고 있어요.<br />잠시만 기다려주세요.</p>
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