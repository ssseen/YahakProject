import { navigate } from '../router.js';
import { speak, stopSpeaking } from '../tts.js';

// 사용방법: 4단계 + 설정 안내. "소리로 듣기"를 누르면 전체를 읽어 준다
const STEPS = [
  {
    title: '문제 사진 찍기',
    body: "'문제 사진 찍기'를 누르세요. 모르는 문제를 손가락으로 짚은 채로, 네모\u00A0칸 안에 문제가 들어오게 찍어요.",
    tip: "밝은 곳에서 찍으면 더 잘 알아봐요. 미리 찍어 둔 사진은 '문제 사진 가져오기'로 불러와요.",
  },
  {
    title: '말로 물어보기',
    body: '마이크 버튼을 누르고 궁금한 것을 편하게 말하세요. 말씀이 끝나면 버튼을 한 번 더 누르세요.',
    tip: "예: '이거 왜 답이 3번이야?'",
  },
  {
    title: '해설 듣기',
    body: '해설을 천천히 읽어 드려요. 다시 듣고 싶은 문장은 손가락으로 누르세요.',
    tip: '해설을 기다리는 동안 퀴즈를 풀 수 있어요.',
  },
  {
    title: '비슷한 문제 풀기',
    body: "'비슷한 문제 풀어보기'를 누르면 같은 유형의 기출 문제를 풀어 볼 수 있어요.",
    tip: "'처음으로'를 누르면 새 문제를 찍을 수 있어요.",
  },
];
const SETTINGS_TEXT = "오른쪽 위 '설정'에서 글자 크기, 읽어주는 속도, 학력을 바꿀 수 있어요.";

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// 화면에 보일 때만: 따옴표로 묶은 버튼 이름('문제 사진 찍기' 등)은 중간에서 줄이 안 갈리게
function keepQuoted(s) {
  return s.replace(/'[^']+'/g, (m) => m.replace(/ /g, '\u00A0'));
}

function fullText() {
  const steps = STEPS.map((s, i) => `${i + 1}번, ${s.title}. ${s.body} ${s.tip}`).join(' ');
  return `검고심 사용방법입니다. ${steps} ${SETTINGS_TEXT}`;
}

export function renderHowto(container) {
  container.innerHTML = `
    <section class="howto-screen">
      <h1 class="howto-title">사용방법</h1>
      <button type="button" class="howto-listen" id="howto-listen">소리로 듣기</button>

      <!-- 사용방법 안내 그림 (세로로 긴 이미지, 화면을 내려서 봄). 그림이 없으면 아래 글 안내를 보여 줌 -->
      <img class="howto-image" src="image/howto.png" alt="검고심 사용방법 안내 그림" />

      <ol class="howto-steps" hidden>
        ${STEPS.map((s, i) => `
          <li class="howto-step">
            <div class="howto-step-head">
              <span class="howto-num">${i + 1}</span>
              <h2>${escapeHtml(s.title)}</h2>
            </div>
            <p>${escapeHtml(keepQuoted(s.body))}</p>
            <p class="howto-tip">${escapeHtml(keepQuoted(s.tip))}</p>
          </li>
        `).join('')}
      </ol>

      <p class="howto-settings" hidden>${escapeHtml(SETTINGS_TEXT)}</p>

      <button type="button" class="howto-start" id="howto-start">시작하기</button>
    </section>
  `;

  // 그림을 못 불러오면(아직 안 넣었거나 경로가 틀리면) 글 안내로 대신 보여 줌
  const image = container.querySelector('.howto-image');
  const steps = container.querySelector('.howto-steps');
  image.addEventListener('error', () => {
    image.remove();
    steps.hidden = false;
    container.querySelector('.howto-settings').hidden = false;
  });

  const listenBtn = container.querySelector('#howto-listen');
  let playing = false;
  listenBtn.addEventListener('click', () => {
    if (playing) {
      stopSpeaking();
      playing = false;
      listenBtn.textContent = '소리로 듣기';
      return;
    }
    speak(fullText());
    playing = true;
    listenBtn.textContent = '그만 듣기';
  });

  // 화면을 떠나면 읽기 중지
  window.addEventListener('hashchange', stopSpeaking, { once: true });

  container.querySelector('#howto-start').addEventListener('click', () => navigate('/menu'));
}
