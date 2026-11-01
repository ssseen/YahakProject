// 해설을 기다리는 동안 푸는 퀴즈 (영어 단어 뜻 / 수학 공식, 4지선다)
// 제한 시간·점수 없음. 틀려도 정답만 보여주고 "다음 문제"로 넘어감.
import { getState } from '../state.js';
import { speak, stopSpeaking } from '../tts.js';
import { ENGLISH_WORDS, MATH_QUESTIONS } from '../data/wait-quiz-data.js';

const DEFAULT_LEVEL = '중졸';

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// 학력에 맞는 문제를 영어/수학 번갈아 섞어서 만든다
function buildDeck(level) {
  const words = ENGLISH_WORDS[level] || ENGLISH_WORDS[DEFAULT_LEVEL];
  const maths = MATH_QUESTIONS[level] || MATH_QUESTIONS[DEFAULT_LEVEL];

  const english = shuffle(words).map(([word, meaning]) => {
    const wrong = shuffle(words.filter(([, m]) => m !== meaning)).slice(0, 3).map(([, m]) => m);
    const options = shuffle([meaning, ...wrong]);
    return {
      label: '영어 단어',
      q: `${word} 의 뜻은?`,
      options,
      answer: options.indexOf(meaning) + 1,
      tip: `${word} = ${meaning}`,
    };
  });
  const math = shuffle(maths).map((m) => ({ label: '수학 공식', ...m }));

  const deck = [];
  for (let i = 0; i < Math.max(english.length, math.length); i++) {
    if (english[i]) deck.push(english[i]);
    if (math[i]) deck.push(math[i]);
  }
  return deck;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// el 안에 퀴즈를 그린다. 반환값 touched(): 사용자가 퀴즈를 한 번이라도 눌렀는지
export function mountWaitQuiz(el) {
  const level = getState().settings?.userLevel;
  const deck = buildDeck(['초졸', '중졸', '고졸'].includes(level) ? level : DEFAULT_LEVEL);
  let index = 0;
  let touched = false;

  function renderCard() {
    const item = deck[index % deck.length];
    el.innerHTML = `
      <div class="wait-quiz-card">
        <p class="wait-quiz-label">${item.label}</p>
        <p class="wait-quiz-q">${escapeHtml(item.q)}</p>
        <div class="wait-quiz-options">
          ${item.options.map((o, i) => `<button type="button" class="wait-quiz-option" data-no="${i + 1}">${escapeHtml(o)}</button>`).join('')}
        </div>
        <p class="wait-quiz-feedback" hidden></p>
        <button type="button" class="btn btn-primary wait-quiz-next" hidden>다음 문제</button>
      </div>
    `;
    const buttons = el.querySelectorAll('.wait-quiz-option');
    buttons.forEach((btn) => btn.addEventListener('click', () => {
      touched = true;
      const picked = Number(btn.dataset.no);
      const correct = picked === item.answer;
      buttons.forEach((b) => {
        b.disabled = true;
        if (Number(b.dataset.no) === item.answer) b.classList.add('correct');
      });
      if (!correct) btn.classList.add('wrong');
      const fb = el.querySelector('.wait-quiz-feedback');
      fb.textContent = (correct ? '맞았어요! ' : '아쉬워요. ') + item.tip;
      fb.hidden = false;
      el.querySelector('.wait-quiz-next').hidden = false;
    }));
    el.querySelector('.wait-quiz-next').addEventListener('click', () => {
      index += 1;
      renderCard();
    });
  }

  renderCard();
  return { touched: () => touched };
}

// 해설이 준비됐을 때 퀴즈 위에 띄우는 팝업 (배경은 반투명 검정)
export function showReadyPopup(onGo) {
  const root = document.getElementById('modal-root');
  if (!root) { onGo(); return; }
  root.innerHTML = `
    <div class="ready-overlay">
      <div class="ready-box">
        <img src="image/success_icon.png" alt="" aria-hidden="true" class="ready-icon" />
        <p class="ready-msg">해설이 준비됐어요!</p>
        <button type="button" class="btn btn-primary ready-go">해설 보기</button>
      </div>
    </div>
  `;
  speak('해설이 준비됐어요. 해설 보기 버튼을 눌러 주세요.');

  const close = () => {
    root.innerHTML = '';
    window.removeEventListener('hashchange', close);
  };
  // 뒤로가기 등으로 화면을 떠나면 팝업도 치움
  window.addEventListener('hashchange', close);
  root.querySelector('.ready-go').addEventListener('click', () => {
    stopSpeaking();
    close();
    onGo();
  });
}
