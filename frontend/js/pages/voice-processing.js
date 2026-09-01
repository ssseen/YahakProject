import { navigate } from '../router.js';
import { setState } from '../state.js';
import { renderHeader } from '../components/header.js';

// 디버그용: 주소창에 #/voice?step=recognizing (또는 understanding / error / recording)를
// 직접 입력하면 해당 화면으로 바로 진입해서 자동 타이머 없이 그 자리에 멈춰있는다.
// 예: index.html#/voice?step=understanding
const DEBUG_STEPS = ['ready', 'recording', 'recognizing', 'understanding', 'error'];

function getDebugStep() {
  const query = window.location.hash.split('?')[1];
  const step = new URLSearchParams(query).get('step');
  return DEBUG_STEPS.includes(step) ? step : null;
}

export function renderVoiceProcessing(container) {
  let step = getDebugStep() || 'ready'; // 'ready' | 'recording' | 'recognizing' | 'understanding' | 'error'

  // 마이크 녹음 관련 상태 - 화면 벗어나거나 녹음 끝나면 반드시 정리해야 함
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

  // 마이크 스트림 + 오디오 분석기 + 녹음기를 전부 정리하는 헬퍼
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
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      // 마이크 권한 거부 / 마이크 없음 등 - 바로 에러 화면으로
      console.error('마이크 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    });
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

  // Web Audio API로 마이크 실시간 볼륨을 뽑아서 .wave-bar 높이에 매핑
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
      // 전체 평균 볼륨(0~255)을 0~1로 정규화
      const average = dataArray.reduce((sum, v) => sum + v, 0) / dataArray.length;
      const level = Math.min(average / 128, 1);

      bars.forEach((bar, i) => {
        // 막대마다 살짝 다른 배율을 줘서 획일적이지 않고 자연스럽게 움직이게 함
        const variance = 0.7 + (i % 3) * 0.15;
        const height = 12 + level * 32 * variance; // 최소 12px ~ 최대 약 44px
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
      stream.getTracks().forEach((track) => track.stop()); // 마이크는 바로 꺼줌
      stream = null;
      if (audioContext) {
        audioContext.close();
        audioContext = null;
      }
      mediaRecorder.stop(); // 'stop' 이벤트 리스너가 알아서 recognizing으로 넘겨줌
    });
  }

  // 로딩/성공/에러(state-screen) 3개 화면은 잠시 뜨고 넘어가는 화면이라
  // 뒤로가기가 필요 없어서, 공용 헤더를 자체적으로 숨긴다.
  function hideHeader() {
    const headerRoot = document.getElementById('header-root');
    if (headerRoot) headerRoot.innerHTML = '';
  }
  // 대기/녹음중 화면으로 돌아올 땐(예: 에러 후 재시도) 헤더를 다시 붙인다.
  function showHeader() {
    const headerRoot = document.getElementById('header-root');
    if (headerRoot) {
      headerRoot.innerHTML = '';
      headerRoot.appendChild(renderHeader({
        onBack: () => {
          stopAudioStream(); // 녹음 중에 뒤로가기 눌러도 마이크는 반드시 꺼줌
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
    const formData = new FormData();
    formData.append('audio_file', blob, 'record.webm');

    let res;
    try {
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

    const result = await res.json();
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

  function fakeUnderstand() {
    setTimeout(() => {
      const ok = true; // TODO: 실제 STT/이해 API 응답으로 대체
      if (ok) {
        setState({ voiceQuestionText: '(인식된 질문 텍스트)' });
        navigate('/solve');
      } else {
        step = 'error';
        render();
      }
    }, 1200);
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