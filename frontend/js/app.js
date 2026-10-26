import { initRouter } from './router.js';
import { applyFontSize, getState } from './state.js';
import { openLevelPromptModal } from './components/settings-modal.js';
import './tts.js'; // 첫 터치 때 음성 재생 잠금 해제 (아이폰)

// 저장된(또는 기본) 설정값을 부팅 시 CSS에 반영
applyFontSize(getState().settings.fontSize);

initRouter();

// 학력 설정
if (!getState().settings.userLevel) openLevelPromptModal();

// PWA 서비스 워커 등록 (지원하는 브라우저에서만)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./service-worker.js').catch((err) => {
      console.error('Service worker 등록 실패:', err);
    });
  });
}