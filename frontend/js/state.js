// 앱 전체에서 공유하는 상태.
// photo-processing.js / voice-processing.js가 각각 채워넣고,
// solve.js가 둘 다 준비됐을 때 읽어서 백엔드로 보낸다.

const state = {
  photo: null,        // { blob, previewUrl }
  question: null,      // 백엔드가 사진에서 인식한 문제 데이터 { subject, text, choices, ... }
  voiceQuestionText: null, // 음성 인식 결과 텍스트
  solveResult: null,   // 백엔드가 반환한 해설 데이터
  settings: {
    fontSize: localStorage.getItem('fontSize') || 'medium', // 이전에 저장한 값이 있으면 그걸로, 없으면 기본값
    speechRate: localStorage.getItem('speechRate') || 'normal',
  },
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// 설정 변경 시 CSS 변수에도 즉시 반영
const FONT_SCALE = { small: 0.9, medium: 1, large: 1.2 };

export function applyFontSize(size) {
  document.documentElement.style.setProperty('--font-size-scale', FONT_SCALE[size] ?? 1);
  localStorage.setItem('fontSize', size); // 다음에 앱 켰을 때도 기억하도록 저장
  setState({ settings: { ...state.settings, fontSize: size } });
}

export function applySpeechRate(rate) {
  localStorage.setItem('speechRate', rate);
  setState({ settings: { ...state.settings, speechRate: rate } });
}

export function resetQuestionFlow() {
  setState({ photo: null, question: null, voiceQuestionText: null, solveResult: null });
}