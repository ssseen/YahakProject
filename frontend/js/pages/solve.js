import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';
import { openWordPopup } from '../components/word-popup.js';

const MOCK = {
  status: 'success',
  type: 'english',
  subject: '영어',
  problem_type: '미분류 > 미분류',
  passage: {
    text: 'A: Everything on the menu looks so delicious!\nB: Yeah. This is one of my favorite restaurants.\nA: Great! ______?\nB: How about the spaghetti with cream sauce? It\'s one of their best dishes.',
    tokens: [
      { text: 'A: Everything on the menu looks so ', meaning: null },
      { text: 'delicious', meaning: '아주 맛있는' },
      { text: '!\nB: Yeah. This is one of my favorite ', meaning: null },
      { text: 'restaurants', meaning: '식당들' },
      { text: '.\nA: Great! ______?\nB: How about the spaghetti with cream sauce? It\'s one of their best ', meaning: null },
      { text: 'dishes', meaning: '요리들' },
      { text: '.', meaning: null },
    ],
  },
  options: [
    { no: 1, text: 'Can you recommend a dish for me', tokens: [{ text: 'Can you recommend a dish for me', meaning: null }] },
    { no: 2, text: 'What is your favorite restaurant', tokens: [{ text: 'What is your favorite restaurant', meaning: null }] },
    { no: 3, text: 'Why do you like Italian fashion', tokens: [{ text: 'Why do you like Italian fashion', meaning: null }] },
    { no: 4, text: 'Have you ever been to Italy', tokens: [{ text: 'Have you ever been to Italy', meaning: null }] },
  ],
  translation: {
    passage: 'A: 메뉴에 있는 모든 게 정말 맛있어 보여요!\nB: 네. 여기는 제가 제일 좋아하는 식당 중 하나예요.\nA: 잘됐네요! ______?\nB: 크림소스 스파게티는 어때요? 여기서 제일 잘하는 요리 중 하나예요.',
    options: [
      { no: 1, text: '저에게 요리를 추천해 주실 수 있나요' },
      { no: 2, text: '가장 좋아하는 식당이 어디인가요' },
      { no: 3, text: '왜 이탈리아 패션을 좋아하나요' },
      { no: 4, text: '이탈리아에 가본 적 있나요' },
    ],
  },
  explanation: '빈칸 다음에 B가 구체적인 메뉴를 추천하고 있으므로, 빈칸에는 추천을 요청하는 표현이 들어가야 합니다.',
  answer: { number: 1, text: 'Can you recommend a dish for me' },
  finger_detected: true,
  has_illustration: false,
  illustration_attached: false,
  illustration: null,
  illustration_bbox: null,
};

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
  const data = state.question ?? MOCK;

  container.innerHTML = `
    <section class="solve-screen">
      <div class="solve-header">
        <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
        <span>함께 풀어봐요!</span>
      </div>

      ${data.type === 'english' ? renderEnglish(data) : renderGuksagwa(data)}

      <!-- 비슷한 문제 풀어보기 버튼 추가 -->
      <button type="button" class="btn-similar-problem" id="btn-similar">
        비슷한 문제 풀어보기
      </button>

      <nav class="solve-nav">
        <button class="nav-item" id="nav-home" type="button">
          <img src="image/home_btn.svg" alt="" aria-hidden="true" /><span>처음으로</span>
        </button>
        <button class="nav-item" id="nav-play-toggle" type="button">
          <img src="image/play_btn.png" alt="" aria-hidden="true" id="play-icon" />
          <span id="play-text">음성 재생</span>
        </button>
        <button class="nav-item" id="nav-replay" type="button">
          <img src="image/replay_btn.svg" alt="" aria-hidden="true" /><span>다시 듣기</span>
        </button>
      </nav>
    </section>
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
    console.log('비슷한 문제 풀어보기 클릭됨');
    // 추후 비슷한 문제 페이지로 이동하는 navigate('/...') 코드를 여기에 작성하시면 됩니다!
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