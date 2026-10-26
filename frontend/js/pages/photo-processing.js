import { navigate } from '../router.js';
import { getState, setState } from '../state.js';
import { startLoading, endLoading } from '../loading-guard.js';

const DEBUG_STEPS = ['guide', 'loading', 'success', 'error'];

function getDebugStep() {
  const query = window.location.hash.split('?')[1];
  const step = new URLSearchParams(query).get('step');
  return DEBUG_STEPS.includes(step) ? step : null;
}

export function renderPhotoProcessing(container) {
  const pickedPhoto = getState().photo;
  let step = getDebugStep() || (pickedPhoto && pickedPhoto.blob ? 'loading' : 'guide');
  let stream = null;
  let torchOn = false;
  let errorMessage = '사진을 인식하지 못했어요.\n다시 찍어주세요';

  function render() {
    if (step === 'guide') renderGuide();
    else if (step === 'loading') renderLoading();
    else if (step === 'success') renderSuccess();
    else renderError();
  }

  function stopStream() {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
  }

  async function renderGuide() {
    container.innerHTML = `
      <section class="camera-screen">
        <video id="camera-video" autoplay playsinline muted></video>

        <div class="camera-topbar">
          <button class="camera-back-btn" id="camera-back-btn" type="button" aria-label="뒤로 가기">
            <img src="image/back_btn.svg" alt="" aria-hidden="true" />
            뒤로 가기
          </button>
          <button class="camera-flash-btn" id="flash-btn" type="button" aria-label="플래시" hidden>
            <img src="image/flash_btn.svg" alt="" aria-hidden="true" />
          </button>
        </div>

        <p class="camera-instruction">표시에 맞춰 문제를 찍어주세요</p>
        <div class="camera-frame" id="camera-frame">
          <span class="corner corner-tl"></span>
          <span class="corner corner-tr"></span>
          <span class="corner corner-bl"></span>
          <span class="corner corner-br"></span>
        </div>
        <button class="shutter-btn" id="shutter-btn" type="button" aria-label="촬영"></button>
      </section>
    `;

    container.querySelector('#camera-back-btn').addEventListener('click', () => {
      stopStream();
      window.history.back();
    });

    const video = container.querySelector('#camera-video');

    try {
      // 해상도를 안 정하면 브라우저 기본값(보통 640x480)으로 찍혀서 글자가 뭉개짐
      // ideal만 쓰면 기기가 지원하는 가장 가까운 해상도로 맞춰줌 (지원 안 해도 에러 안 남)
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment',
          width: { ideal: 3840 },
          height: { ideal: 2160 },
        },
        audio: false,
      });
      video.srcObject = stream;

      const [track] = stream.getVideoTracks();
      const capabilities = track.getCapabilities ? track.getCapabilities() : {};
      // 안드로이드 크롬: 연속 자동초점 (아이폰은 기본 동작이라 해당 없음)
      if (capabilities.focusMode && capabilities.focusMode.includes('continuous')) {
        track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {});
      }
      video.addEventListener('loadedmetadata', () => {
        console.log(`📷 카메라 해상도: ${video.videoWidth}x${video.videoHeight}`);
      }, { once: true });

      if (capabilities.torch) {
        const flashBtn = container.querySelector('#flash-btn');
        flashBtn.hidden = false;
        flashBtn.addEventListener('click', async () => {
          torchOn = !torchOn;
          try {
            await track.applyConstraints({ advanced: [{ torch: torchOn }] });
            flashBtn.classList.toggle('active', torchOn);
          } catch (err) {
            console.error('플래시 제어 실패:', err);
          }
        });
      }
    } catch (err) {
      console.error('카메라 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    container.querySelector('#shutter-btn').addEventListener('click', () => capture(video));
  }

  function capture(video) {
    const flash = document.createElement('div');
    flash.className = 'camera-flash';
    container.querySelector('.camera-screen').appendChild(flash);
    setTimeout(() => flash.remove(), 250);

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      const previewUrl = URL.createObjectURL(blob);
      setState({ photo: { blob, previewUrl } });

      stopStream();

      setTimeout(() => {
        step = 'loading';
        render();
        uploadPhoto(blob);
      }, 150);
    }, 'image/jpeg', 0.9);
  }

  const API_BASE = 'https://yahak-backend-815747505478.asia-northeast3.run.app';

  function blobToDataUri(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function uploadPhoto(blob) {
    const signal = startLoading(() => {
      setState({ photo: null, question: null });
      window.history.back();
    });
    const next = await analyzePhoto(blob, signal);
    if (next) endLoading(next); // null이면 사용자가 나간 것
  }

  // 서버 응답을 기다린 뒤, "가드가 치워진 다음에 실행할 동작"을 돌려준다
  async function analyzePhoto(blob, signal) {
    const showError = (message) => () => {
      errorMessage = message;
      step = 'error';
      render();
    };

    let dataUri;
    try {
      dataUri = await blobToDataUri(blob);
      // 나중에 음성 페이지(voice-processing.js)에서 이미지와 음성을 동시에 보낼 수 있도록 dataUri 저장!
      const currentPhoto = getState().photo || {};
      // check는 이전 사진의 검사 결과이므로 새 사진에선 비운다
      setState({ photo: { ...currentPhoto, blob, dataUri, check: null } });
    } catch (err) {
      console.error('이미지 변환 실패:', err);
      return showError('사진을 처리하지 못했어요.\n다시 찍어주세요');
    }

    let res;
    try {
      res = await fetch(API_BASE + '/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUri, checkOnly: true }),
        signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') return null;
      console.error('네트워크 오류:', err);
      return showError('서버에 연결할 수 없어요.\n잠시 후 다시 시도해주세요');
    }

    if (!res.ok) {
      const detail = await res.text();
      console.error('HTTP ' + res.status, detail);
      return showError('잠시 문제가 생겼어요.\n다시 시도해주세요');
    }

    let data;
    try {
      data = await res.json();
    } catch (err) {
      if (err.name === 'AbortError') return null;
      return showError('잠시 문제가 생겼어요.\n다시 시도해주세요');
    }

    switch (data.status) {
      case 'checked':
        // 화질 검증 통과 -> 아직 제미나이는 안 돌렸으므로 question은 비워두고 음성 페이지로 이동
        // 검사 결과(손끝 위치)는 저장해뒀다가 해설 요청 때 같이 보낸다 - 서버가 같은 검사를 다시 안 하도록
        return () => {
          const photo = getState().photo || {};
          setState({
            question: null,
            photo: { ...photo, check: { finger_detected: data.finger_detected, x: data.x, y: data.y } },
          });
          step = 'success';
          render();
          setTimeout(() => navigate('/voice'), 700);
        };

      case 'success':
        // 구버전 서버 응답인 경우 일단 저장해두되, 음성 질문을 하면 다시 덮어씀
        return () => {
          setState({ question: data });
          step = 'success';
          render();
          setTimeout(() => navigate('/voice'), 700);
        };

      case 'retake':
        return showError(data.message || '사진을 인식하지 못했어요.\n다시 찍어주세요');

      case 'unsupported_subject':
        return showError(data.message || '아직 지원하지 않는 과목이에요.\n다른 과목으로 시도해주세요');

      case 'error':
      default:
        console.error(data);
        return showError('잠시 문제가 생겼어요.\n다시 시도해주세요');
    }
  }

  function renderLoading() {
    container.innerHTML = `
      <section class="camera-screen state-screen">
        <p class="loading-text">문제를 읽고 있어요.<br />잠시만 기다려주세요<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></p>
        <div class="spinner" aria-hidden="true"></div>
      </section>
    `;
  }

  function renderSuccess() {
    container.innerHTML = `
      <section class="camera-screen state-screen">
        <p class="success-text">문제 읽기 성공!</p>
        <img src="image/success_icon.png" alt="" aria-hidden="true" class="result-icon" />
      </section>
    `;
  }

  function renderError() {
    container.innerHTML = `
      <section class="camera-screen state-screen">
        <img src="image/error_icon.png" alt="" aria-hidden="true" class="result-icon shake" />
        <p class="error-text pre-line">${errorMessage}</p>
        <button class="btn btn-secondary" id="retry-btn" type="button">다시 찍기</button>
      </section>
    `;
    container.querySelector('#retry-btn').addEventListener('click', () => {
      step = 'guide';
      render();
    });
  }

  render();

  if (step === 'loading' && pickedPhoto && pickedPhoto.blob) {
    uploadPhoto(pickedPhoto.blob);
  }
}