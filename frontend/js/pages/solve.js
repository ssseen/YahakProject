import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';
import { openWordPopup } from '../components/word-popup.js';

function assembleTokens(tokens) {
  if (!tokens || tokens.length === 0) return '';
  return tokens
    .map((tok) => {
      if (tok.meaning) {
        return `<span class="lookup-word" data-word="${escapeHtml(tok.text)}" data-meaning="${escapeHtml(tok.meaning)}">${escapeHtml(tok.text)}</span>`;
      }
      return escapeHtml(tok.text);
    })
    .join('');
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const CIRCLED = ['①', '②', '③', '④', '⑤'];
function formatAnswer(answer) {
  if (!answer) return '불러오는 중입니다.';
  if (answer.number != null && CIRCLED[answer.number - 1]) {
    return `${CIRCLED[answer.number - 1]} ${answer.text}`;
  }
  return answer.text || '불러오는 중입니다.';
}

function renderIllustration(illustration) {
  if (!illustration) return '';
  return `
    <div class="passage-image-wrap">
      <img src="${illustration}" alt="문제 관련 이미지" class="passage-image" />
    </div>
  `;
}

export function renderSolve(container) {
  const state = getState();
  const data = state.question; // 가짜 데이터(MOCK) 연결 해제, 오직 실제 상태값만 바라봄!

  // 백엔드 데이터가 아직 도착하지 않았을 때 로딩 문구 띄우기
  if (!data) {
    container.innerHTML = `
      <div style="text-align:center; padding:100px 0; color:var(--color-text-muted); font-size:0.8rem;">
        문제 데이터를 불러오는 중입니다...
      </div>`;
    return;
  }

  container.innerHTML = `
    <section class="solve-screen">
      <div class="solve-header">
        <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
        <span>함께 풀어봐요!</span>
      </div>

      ${data.type === 'english' ? renderEnglish(data) : renderGuksagwa(data)}
      
      <!-- (이하 기존 네비게이션 버튼 코드 동일) -->
  `;

  container.querySelectorAll('.accordion').forEach((acc) => {
    const toggle = acc.querySelector('.accordion-toggle');
    const chevron = acc.querySelector('.accordion-chevron');
    toggle.addEventListener('click', () => {
      acc.classList.toggle('open');
      chevron.src = acc.classList.contains('open') ? 'image/hide_btn.svg' : 'image/view_btn.svg';
    });
  });

  container.querySelectorAll('.lookup-word').forEach((el) => {
    el.addEventListener('click', () => {
      openWordPopup({ word: el.dataset.word, meaning: el.dataset.meaning });
    });
  });

  container.querySelector('#nav-home').addEventListener('click', () => {
    resetQuestionFlow();
    navigate('/');
  });

  const playToggleBtn = container.querySelector('#nav-play-toggle');
  const playIcon = container.querySelector('#play-icon');
  const playText = container.querySelector('#play-text');
  let isPlaying = false; 

  playToggleBtn.addEventListener('click', () => {
    isPlaying = !isPlaying; 
    if (isPlaying) {
      playIcon.src = 'image/pause_btn.png';
      playText.textContent = '일시 정지';
      console.log('음성 재생 시작');
    } else {
      playIcon.src = 'image/play_btn.png';
      playText.textContent = '음성 재생';
      console.log('음성 일시 정지');
    }
  });

  container.querySelector('#nav-replay').addEventListener('click', () => {
    console.log('다시 듣기');
  });

  // 비슷한 문제 풀어보기 클릭 이벤트
  container.querySelector('#btn-similar').addEventListener('click', () => {
    navigate('/practice'); // 페이지 이동!
  });
}
function renderGuksagwa(data) {
  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${escapeHtml(data.problem_text || '문제를 불러오는 중입니다.')}</p>
        ${renderIllustration(data.illustration)}
      </div>
    </div>

    <div class="explanation-box">
      <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
      <p>${data.explanation || '해설을 불러오는 중입니다.'}</p>
    </div>

    <div class="answer-box visible" id="answer-section">
      <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
      <p class="answer-value">${formatAnswer(data.answer)}</p>
    </div>
  `;
}

function renderEnglish(data) {
  const hasOptions = data.options && data.options.length > 0;
  const hasTranslation = data.translation && (data.translation.passage || (data.translation.options && data.translation.options.length > 0));

  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${assembleTokens(data.passage && data.passage.tokens)}</p>
        ${hasOptions ? `
        <div class="choice-list">
          ${data.options.map((opt) => `
            <div class="choice ${data.answer && data.answer.number === opt.no ? 'correct' : ''}">
              ${CIRCLED[opt.no - 1] || opt.no}
              <span class="pre-line">${assembleTokens(opt.tokens)}</span>
            </div>
          `).join('')}
        </div>
        <p class="tap-hint">
          <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 뜻이 궁금한 단어를 눌러보세요!
        </p>
        ` : ''}
        ${renderIllustration(data.illustration)}
      </div>
    </div>

    ${hasTranslation ? `
    <div class="accordion accordion-translation">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/translate_icon.svg" alt="" aria-hidden="true" /> 전체 해석 보기</span>
        <img src="image/view_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="translation-heading">지문 해석</p>
        <p class="pre-line">${escapeHtml(data.translation.passage || '해석을 불러오는 중입니다.')}</p>
        ${data.translation.options && data.translation.options.length > 0 ? `
        <p class="translation-heading">보기 해석</p>
        <div class="choice-translation-list">
          ${data.translation.options.map((opt) => `<p>${CIRCLED[opt.no - 1] || opt.no} ${escapeHtml(opt.text)}</p>`).join('')}
        </div>
        ` : ''}
      </div>
    </div>
    ` : ''}

    <div class="explanation-box">
      <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
      <p>${data.explanation || '해설을 불러오는 중입니다.'}</p>
    </div>

    <div class="answer-box visible" id="answer-section">
      <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
      <p class="answer-value">${formatAnswer(data.answer)}</p>
    </div>
  `;
}

function renderAccordionHint() {
  return `
    <p class="accordion-hint">
      <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 전체를 보시려면 화살표를 눌러주세요.
    </p>
  `;
}