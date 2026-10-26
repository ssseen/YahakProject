// 브라우저 TTS(speechSynthesis) 공용 함수 - 해설 읽기, 안내 음성, 설정의 "들어보기"가 같이 씀
import { getState } from './state.js';

// 설정값 -> 실제 속도 (어르신 기본값은 'slow')
const RATE_VALUE = { slow: 0.8, normal: 0.95, fast: 1.15 };

export function getSpeechRateValue() {
  return RATE_VALUE[getState().settings?.speechRate] ?? RATE_VALUE.slow;
}

// 기기마다 깔린 한국어 목소리 중 덜 기계적인 것부터 고른다
// (Edge의 Natural 계열, 아이폰 향상된 목소리, 크롬의 구글 목소리 순)
const PREFERRED = [/natural/i, /online/i, /premium|enhanced|향상/i, /google/i, /yuna|유나/i, /siri/i];
let cachedVoice = null;

function pickKoreanVoice() {
  if (!('speechSynthesis' in window)) return null;
  const ko = window.speechSynthesis.getVoices().filter((v) => (v.lang || '').toLowerCase().startsWith('ko'));
  if (!ko.length) return null;
  for (const re of PREFERRED) {
    const v = ko.find((voice) => re.test(voice.name));
    if (v) return v;
  }
  return ko[0];
}

if ('speechSynthesis' in window) {
  cachedVoice = pickKoreanVoice();
  window.speechSynthesis.addEventListener?.('voiceschanged', () => {
    cachedVoice = pickKoreanVoice();
  });
}

// 아이폰(사파리/iOS 크롬)은 "사용자가 화면을 누른 순간"에 한 번 소리를 내야 그 뒤 자동 재생을 허용함.
// 녹음 화면 안내 음성은 사진 분석이 끝난 뒤(터치와 상관없는 시점)에 나오므로,
// 페이지를 연 뒤 첫 터치 때 무음 발화를 한 번 해서 미리 풀어둔다.
function unlockOnFirstTouch() {
  if (!('speechSynthesis' in window)) return;
  const unlock = () => {
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0;
    window.speechSynthesis.speak(u);
    document.removeEventListener('click', unlock, true);
    document.removeEventListener('touchend', unlock, true);
  };
  document.addEventListener('click', unlock, true);
  document.addEventListener('touchend', unlock, true);
}
unlockOnFirstTouch();

// 한국어 발화 객체 생성 (목소리/속도 적용). 재생은 호출한 쪽에서 speechSynthesis.speak()
export function makeUtterance(text) {
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = getSpeechRateValue();
  const voice = cachedVoice || pickKoreanVoice();
  if (voice) u.voice = voice;
  return u;
}

// 짧은 안내 음성용: 이전 음성을 끊고 바로 읽음
export function speak(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.resume(); // 아이폰에서 가끔 '일시정지' 상태로 멈춰 있는 경우 대비
  window.speechSynthesis.speak(makeUtterance(text));
}

export function stopSpeaking() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}
