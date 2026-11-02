import { navigate } from '../router.js';
import { getState, setState } from '../state.js';
import { startLoading, endLoading } from '../loading-guard.js';

const DEBUG_STEPS = ['guide', 'loading', 'success', 'error'];

// 카메라 진단 표시: 주소에 ?camdebug=1 (예: .../YahakProject/?camdebug=1)을 붙였을 때만 화면 위에
// 카메라 정보를 띄운다. 갤럭시처럼 원격 콘솔을 보기 어려운 폰에서 화질 원인을 찾으려고 넣음.
// 촬영 동작 자체는 바꾸지 않는다. (# 앞 쿼리라 화면을 옮겨 다녀도 유지됨)
const CAM_DEBUG = new URLSearchParams(window.location.search).get('camdebug') === '1';

function camDebug(line) {
  console.log('📷 ' + line);
  if (!CAM_DEBUG) return;
  let panel = document.getElementById('cam-debug-panel');
  if (!panel) {
    panel = document.createElement('pre');
    panel.id = 'cam-debug-panel';
    panel.style.cssText = 'position:fixed;left:0;right:0;bottom:0;max-height:45vh;overflow:auto;margin:0;'
      + 'padding:8px;background:rgba(0,0,0,.8);color:#0f0;font:12px/1.4 monospace;white-space:pre-wrap;'
      + 'z-index:99999;';
    panel.addEventListener('click', () => panel.remove()); // 누르면 닫힘
    document.body.appendChild(panel);
  }
  panel.textContent += line + '\n';
}

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

  // 해상도를 안 정하면 브라우저 기본값(보통 640x480)으로 찍혀서 글자가 뭉개짐
  // ideal만 쓰면 기기가 지원하는 가장 가까운 해상도로 맞춰줌 (지원 안 해도 에러 안 남)
  const VIDEO_SIZE = { width: { ideal: 3840 }, height: { ideal: 2160 } };

  function hasAutoFocus(track) {
    const caps = track.getCapabilities ? track.getCapabilities() : {};
    return Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous');
  }

  // 후면 카메라를 연다. 안드로이드는 후면 렌즈를 "camera 0, facing back", "camera 2, facing back"
  // 처럼 따로 보여줘서 facingMode만 주면 브라우저가 초광각을 고를 수 있다. 실측(갤럭시, 11-02):
  // camera 2가 골라졌는데 지원 초점이 ["manual"]뿐(자동초점 없음)이라 가까이 찍은 문제지가 흐렸다.
  // 그래서 고른 카메라에 자동초점이 없으면 다른 후면 카메라를 하나씩 열어 자동초점 되는 걸 쓴다.
  // 아이폰은 focusMode 정보를 안 줘서(iOS가 렌즈·초점을 알아서 처리) 그대로 둔다.
  async function openBackCamera() {
    const open = (video) => navigator.mediaDevices.getUserMedia({ video, audio: false });
    let s = await open({ facingMode: 'environment', ...VIDEO_SIZE });
    const first = s.getVideoTracks()[0];
    const caps = first.getCapabilities ? first.getCapabilities() : {};
    if (!Array.isArray(caps.focusMode) || hasAutoFocus(first)) return s;

    try {
      const firstId = first.getSettings().deviceId;
      const others = (await navigator.mediaDevices.enumerateDevices())
        .filter((d) => d.kind === 'videoinput' && /back/i.test(d.label) && d.deviceId !== firstId);
      camDebug(`자동초점 없음(${first.label}) - 다른 후면 카메라 확인: ${others.map((d) => d.label).join(' | ')}`);
      s.getTracks().forEach((t) => t.stop()); // 안드로이드는 카메라 두 개를 동시에 못 연다
      for (const d of others) {
        try {
          const cand = await open({ deviceId: { exact: d.deviceId }, ...VIDEO_SIZE });
          if (hasAutoFocus(cand.getVideoTracks()[0])) {
            camDebug(`자동초점 되는 카메라로 변경: ${d.label}`);
            return cand;
          }
          cand.getTracks().forEach((t) => t.stop());
        } catch (err) {
          camDebug(`${d.label} 열기 실패: ${err}`);
        }
      }
    } catch (err) {
      camDebug('카메라 목록 확인 실패: ' + err);
    }
    // 자동초점 되는 후면 카메라가 없으면 원래대로 브라우저가 고른 카메라
    camDebug('자동초점 되는 후면 카메라 없음 - 브라우저가 고른 카메라 사용');
    return open({ facingMode: 'environment', ...VIDEO_SIZE });
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
      stream = await openBackCamera();
      video.srcObject = stream;

      const [track] = stream.getVideoTracks();
      const capabilities = track.getCapabilities ? track.getCapabilities() : {};
      // 안드로이드 크롬: 연속 자동초점 (아이폰은 기본 동작이라 해당 없음)
      if (capabilities.focusMode && capabilities.focusMode.includes('continuous')) {
        track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {});
      }
      video.addEventListener('loadedmetadata', () => {
        camDebug(`카메라 해상도: ${video.videoWidth}x${video.videoHeight}`);
      }, { once: true });
      if (CAM_DEBUG) {
        camDebug(`기기: ${navigator.userAgent}`);
        camDebug(`지금 카메라: ${track.label}`);
        const st = track.getSettings ? track.getSettings() : {};
        camDebug(`설정: ${st.width}x${st.height} focus=${st.focusMode} zoom=${st.zoom} fps=${st.frameRate}`);
        camDebug(`지원 focus=${JSON.stringify(capabilities.focusMode)} zoom=${JSON.stringify(capabilities.zoom)} `
          + `최대=${capabilities.width && capabilities.width.max}x${capabilities.height && capabilities.height.max}`);
        navigator.mediaDevices.enumerateDevices()
          .then((ds) => camDebug('카메라 목록: ' + ds.filter((d) => d.kind === 'videoinput').map((d) => d.label).join(' | ')))
          .catch(() => {});
      }

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

  // 찍은 사진은 화면에 보이던 3:4 영역(가운데)만 잘라서 보낸다 - 보이는 대로 찍히게
  const PHOTO_RATIO = 3 / 4;      // 가로 : 세로
  const MAX_LONG_SIDE = 1960;     // 서버가 OCR·손끝 검출에 쓰는 크기(장축 1960px)와 같게 - 더 크게 보내도 서버가 줄임
  let capturing = false;

  // 안드로이드 크롬/삼성 인터넷: 영상 한 장면이 아니라 카메라의 "사진 촬영" 기능으로 찍는다
  // (영상 프레임은 화질이 낮은 기종이 많음). 아이폰 사파리는 ImageCapture가 없어서 영상 프레임 사용.
  async function grabSource(video) {
    const track = stream && stream.getVideoTracks()[0];
    if ('ImageCapture' in window && track) {
      try {
        const photoBlob = await new ImageCapture(track).takePhoto();
        const bitmap = await createImageBitmap(photoBlob);
        const videoPortrait = video.videoHeight > video.videoWidth;
        const photoPortrait = bitmap.height > bitmap.width;
        camDebug(`사진 촬영 ${bitmap.width}x${bitmap.height} (영상 ${video.videoWidth}x${video.videoHeight})`);
        if (videoPortrait === photoPortrait) return bitmap;
        // 방향이 화면과 다르게 나오는 기기는 회전 방향을 확신할 수 없으니 영상 프레임으로 대신함
        camDebug('사진 방향이 화면과 달라 영상 프레임으로 촬영');
      } catch (err) {
        camDebug('사진 촬영 기능 실패 - 영상 프레임으로 촬영: ' + err);
      }
    } else {
      camDebug('ImageCapture 없음 - 영상 프레임으로 촬영');
    }
    return video;
  }

  async function capture(video) {
    if (capturing) return; // 셔터 연타 방지
    capturing = true;

    const flash = document.createElement('div');
    flash.className = 'camera-flash';
    container.querySelector('.camera-screen').appendChild(flash);
    setTimeout(() => flash.remove(), 250);

    const src = await grabSource(video);
    const sw = src.videoWidth || src.width;
    const sh = src.videoHeight || src.height;

    // 가운데 3:4 영역 계산 (미리보기의 object-fit: cover와 같은 방식)
    let cw = sw, ch = Math.round(sw / PHOTO_RATIO);
    if (ch > sh) { ch = sh; cw = Math.round(sh * PHOTO_RATIO); }
    const sx = Math.round((sw - cw) / 2);
    const sy = Math.round((sh - ch) / 2);
    const scale = Math.min(1, MAX_LONG_SIDE / Math.max(cw, ch));

    const canvas = document.createElement('canvas');
    canvas.width = Math.round(cw * scale);
    canvas.height = Math.round(ch * scale);
    canvas.getContext('2d').drawImage(src, sx, sy, cw, ch, 0, 0, canvas.width, canvas.height);
    if (src.close) src.close(); // ImageBitmap 메모리 해제
    camDebug(`보낸 사진: ${canvas.width}x${canvas.height} (원본 ${sw}x${sh}에서 ${cw}x${ch} 잘라냄)`);

    canvas.toBlob((blob) => {
      capturing = false;
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
      // check/sessionId는 이전 사진의 검사 결과이므로 새 사진에선 비운다
      setState({ photo: { ...currentPhoto, blob, dataUri, check: null, sessionId: null } });
    } catch (err) {
      console.error('이미지 변환 실패:', err);
      return showError('사진을 처리하지 못했어요.\n다시 찍어주세요');
    }

    let res;
    try {
      res = await fetch(API_BASE + '/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // prepare: 검사를 통과하면 서버가 sessionId를 주고, 음성 녹음하는 동안 해설 앞단계(OCR 등)를 미리 처리
        body: JSON.stringify({ image: dataUri, checkOnly: true, prepare: true }),
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
        // sessionId는 해설 요청 때 사진 대신 보낸다(서버가 미리 처리한 결과 사용).
        // check(손끝 위치)는 sessionId가 없을 때(구버전 서버 등) 사진과 같이 보내는 예비용
        return () => {
          const photo = getState().photo || {};
          setState({
            question: null,
            photo: {
              ...photo,
              check: { finger_detected: data.finger_detected, x: data.x, y: data.y },
              sessionId: data.sessionId || null,
            },
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