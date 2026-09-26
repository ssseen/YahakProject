import { navigate } from '../router.js';
import { getState, setState } from '../state.js';

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
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
      video.srcObject = stream;

      const [track] = stream.getVideoTracks();
      const capabilities = track.getCapabilities ? track.getCapabilities() : {};
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
    let dataUri;
    try {
      dataUri = await blobToDataUri(blob);
      // 나중에 음성 페이지(voice-processing.js)에서 이미지와 음성을 동시에 보낼 수 있도록 dataUri 저장!
      const currentPhoto = getState().photo || {};
      setState({ photo: { ...currentPhoto, blob, dataUri } });
    } catch (err) {
      console.error('이미지 변환 실패:', err);
      errorMessage = '사진을 처리하지 못했어요.\n다시 찍어주세요';
      step = 'error';
      render();
      return;
    }

    let res;
    try {
      res = await fetch(API_BASE + '/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUri, checkOnly: true }),
      });
    } catch (err) {
      console.error('네트워크 오류:', err);
      errorMessage = '서버에 연결할 수 없어요.\n잠시 후 다시 시도해주세요';
      step = 'error';
      render();
      return;
    }

    if (!res.ok) {
      const detail = await res.text();
      console.error('HTTP ' + res.status, detail);
      errorMessage = '잠시 문제가 생겼어요.\n다시 시도해주세요';
      step = 'error';
      render();
      return;
    }

    const data = await res.json();

    switch (data.status) {
      case 'checked':
        // 화질 검증 통과 -> 아직 제미나이는 안 돌렸으므로 question은 비워두고 음성 페이지로 이동
        setState({ question: null });
        step = 'success';
        render();
        setTimeout(() => navigate('/voice'), 700);
        break;

      case 'success':
        // 구버전 서버 응답인 경우 일단 저장해두되, 음성 질문을 하면 다시 덮어씀
        setState({ question: data });
        step = 'success';
        render();
        setTimeout(() => navigate('/voice'), 700);
        break;

      case 'retake':
        errorMessage = data.message || '사진을 인식하지 못했어요.\n다시 찍어주세요';
        step = 'error';
        render();
        break;

      case 'unsupported_subject':
        errorMessage = data.message || '아직 지원하지 않는 과목이에요.\n다른 과목으로 시도해주세요';
        step = 'error';
        render();
        break;

      case 'error':
      default:
        console.error(data);
        errorMessage = '잠시 문제가 생겼어요.\n다시 시도해주세요';
        step = 'error';
        render();
        break;
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