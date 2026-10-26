function loadSavedQuestion() {
  try {
    const raw = sessionStorage.getItem('yahak_question');
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

const state = {
  photo: null,
  question: loadSavedQuestion(),
  voiceQuestionText: null,
  solveResult: null,
  settings: {
    fontSize: localStorage.getItem('fontSize') || 'medium',
    speechRate: localStorage.getItem('speechRate') || 'slow', // 어르신 기본값: 천천히
    userLevel: localStorage.getItem('userLevel') || '',
  },
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  if ('question' in patch) {
    try {
      if (patch.question) {
        sessionStorage.setItem('yahak_question', JSON.stringify(patch.question));
      } else {
        sessionStorage.removeItem('yahak_question');
      }
    } catch (e) {
      // 용량 초과 등 예외 무시
    }
  }
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// 기본(보통)부터 크게: 기본 글자 20px -> 23px, 크게 26px
const FONT_SCALE = { small: 1, medium: 1.15, large: 1.3 };

export function applyFontSize(size) {
  document.documentElement.style.setProperty('--font-size-scale', FONT_SCALE[size] ?? 1);
  localStorage.setItem('fontSize', size);
  setState({ settings: { ...state.settings, fontSize: size } });
}

export function applySpeechRate(rate) {
  localStorage.setItem('speechRate', rate);
  setState({ settings: { ...state.settings, speechRate: rate } });
}

export function applyUserLevel(level) {
  localStorage.setItem('userLevel', level);
  setState({ settings: {...state.settings, userLevel: level }})
}

export function getUserLevelForRequest() {
  const level = state.settings.userLevel;
  return level === '초졸' || level === '중졸' || level === '고졸' ? level : null;
}

export function resetQuestionFlow() {
  setState({ photo: null, question: null, voiceQuestionText: null, solveResult: null });
}