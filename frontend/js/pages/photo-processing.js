import { navigate } from '../router.js';
import { getState, setState } from '../state.js';

// 이 페이지는 촬영 가이드 → (플래시) → 로딩 → 성공/실패의 4단계를 자체 상태로 관리한다.

const DEBUG_STEPS = ['guide', 'loading', 'success', 'error'];

function getDebugStep() {
  const query = window.location.hash.split('?')[1];
  const step = new URLSearchParams(query).get('step');
  return DEBUG_STEPS.includes(step) ? step : null;
}

export function renderPhotoProcessing(container) {
  // 메뉴에서 "문제 사진 가져오기"로 이미 파일을 골라둔 상태면, 카메라를 켤 필요 없이
  // 바로 로딩(인식) 단계로 건너뛴다. "문제 사진 찍기"를 눌렀으면 photo는 null이라
  // 정상적으로 guide(카메라 화면)부터 시작한다.
  const pickedPhoto = getState().photo;
  let step = getDebugStep() || (pickedPhoto && pickedPhoto.blob ? 'loading' : 'guide');
  let stream = null; // 현재 켜진 카메라 스트림 - 화면 벗어날 때 반드시 꺼줘야 함
  let torchOn = false;
  let errorMessage = '사진을 인식하지 못했어요.\n다시 찍어주세요'; // 백엔드가 준 message로 매번 갱신됨

  function render() {
    if (step === 'guide') renderGuide();
    else if (step === 'loading') renderLoading();
    else if (step === 'success') renderSuccess();
    else renderError();
  }

  // 스트림을 반드시 꺼주는 헬퍼 - guide 단계를 벗어날 때마다 호출
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
        video: { facingMode: 'environment' }, // 모바일에서 후면 카메라 우선
        audio: false,
      });
      video.srcObject = stream;

      // 플래시(torch) 지원 여부 확인 - 지원 기기(주로 안드로이드 크롬)에서만 버튼 노출
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
      // 카메라 권한 거부 / 카메라 없음 등 - 바로 에러 화면으로
      console.error('카메라 접근 실패:', err);
      step = 'error';
      render();
      return;
    }

    container.querySelector('#shutter-btn').addEventListener('click', () => capture(video));
  }

  function capture(video) {
    // 촬영 순간 플래시
    const flash = document.createElement('div');
    flash.className = 'camera-flash';
    container.querySelector('.camera-screen').appendChild(flash);
    setTimeout(() => flash.remove(), 250);

    // 현재 비디오 프레임을 캔버스에 그려서 이미지로 추출
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      const previewUrl = URL.createObjectURL(blob);
      setState({ photo: { blob, previewUrl } });

      stopStream(); // 캡처 끝났으니 카메라 스트림은 바로 꺼줌

      setTimeout(() => {
        step = 'loading';
        render();
        // TODO: 실제 사진 업로드 + 인식 API 호출
        uploadPhoto(blob);
      }, 150);
    }, 'image/jpeg', 0.9);
  }

  const API_BASE = 'http://localhost:8000'; // TODO: 배포 시 실제 서버 주소로 변경

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
    } catch (err) {
      console.error('이미지 변환 실패:', err);
      errorMessage = '사진을 처리하지 못했어요.\n다시 찍어주세요';
      step = 'error';
      render();
      return;
    }

    let res;
    try {
      res = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // userQuestion은 STT 미연동 상태라 생략 (백엔드 기본 문구 사용)
        body: JSON.stringify({ image: dataUri }),
      });
    } catch (err) {
      // 네트워크 오류 / CORS / 서버 미기동
      console.error('네트워크 오류:', err);
      errorMessage = '서버에 연결할 수 없어요.\n잠시 후 다시 시도해주세요';
      step = 'error';
      render();
      return;
    }

    // ① HTTP 상태 먼저 확인 (422/500은 body에 status 필드가 없음)
    if (!res.ok) {
      const detail = await res.text();
      console.error(`HTTP ${res.status}`, detail);
      errorMessage = '잠시 문제가 생겼어요.\n다시 시도해주세요';
      step = 'error';
      render();
      return;
    }

    const data = await res.json();

    // ② status 필드로 분기
    switch (data.status) {
      case 'success':
        setState({ question: data }); // guksagwa/english 원본 구조 그대로 저장 - solve.js가 이 형태를 직접 소비함
        step = 'success';
        render();
        setTimeout(() => navigate('/voice'), 700);
        break;

      case 'retake':
        errorMessage = data.message; // "사진이 너무 흔들렸어요..." 등 - blur_score는 읽지 않음
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

  // 이미 골라둔 사진이 있어서 loading으로 바로 시작한 경우, 인식 요청도 바로 시작
  if (step === 'loading' && pickedPhoto && pickedPhoto.blob) {
    uploadPhoto(pickedPhoto.blob);
  }
}