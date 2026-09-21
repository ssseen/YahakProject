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

const CIRCLED = ['①', '②', '③', '④'];
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

// 수학은 아직 백엔드가 없어서, 디버그용으로만 mock을 볼 수 있게 함.
// 주소창에 #/solve?mock=math 를 직접 입력하면 실제 상태값 대신 이 데이터로 화면을 확인할 수 있다.
const MOCK_MATH = {
  status: 'success',
  type: 'math',
  subject: '수학',
  problem_type: '도형 > 원의 넓이',
  problem_text: '아래 그림과 같이 반지름이 5cm인 원이 있다.\n이 원의 넓이를 구하시오. (단, 원주율은 3이다.)',
  questionImage: null, // 문제 자체에 이미지 있으면 여기에 URL (308x150 테두리박스)
  explanationImage: null, // 그림 해설 필요하면 여기에 URL (310x190 테두리박스, 문제-풀이단계 사이 항상 노출)
  steps: [
    { text: '원의 넓이 공식은 반지름 × 반지름 × 원주율입니다.' },
    { text: '반지름 5cm를 대입하면 5 × 5 × 3 = 75 입니다.' },
    { text: '따라서 원의 넓이는 75cm² 입니다.' },
  ],
  answer: { number: 1, text: '75cm²' },
};

function getDebugMock() {
  const query = window.location.hash.split('?')[1];
  const mock = new URLSearchParams(query).get('mock');
  return mock === 'math' ? MOCK_MATH : null;
}

export function renderSolve(container) {
  const state = getState();
  const data = getDebugMock() || state.question; // ?mock=math로 디버그 확인, 아니면 오직 실제 상태값만

  // 백엔드 데이터가 아직 도착하지 않았을 때 로딩 문구 띄우기
  if (!data) {
    container.innerHTML = `
      <div style="text-align:center; padding:120px 0; color:var(--color-text-muted); font-size:0.8rem;">
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

      ${data.type === 'english' ? renderEnglish(data) : data.type === 'math' ? renderMath(data) : renderGuksagwa(data)}
      
      <button type="button" class="btn-similar-problem" id="btn-similar">
        비슷한 문제 풀어보기
      </button>

      <!-- 복구된 하단 네비게이션 바 -->
      <div class="bottom-nav-bar" style="display: flex; justify-content: space-around; margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee;">
        <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none;">
          <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
        </button>
        
        <button id="nav-voice" onclick="window.location.hash='#/voice'" style="display: flex; flex-direction: column; align-items: center; background: none; border: none;">
          <img src="image/mic_btn.svg" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">더 궁금해요</span>
        </button>

        <button id="nav-play-toggle" style="display: flex; flex-direction: column; align-items: center; background: none; border: none;">
          <img id="play-icon" src="image/play_btn.png" alt="" style="width: 24px; height: 24px;" />
          <span id="play-text" style="font-size: 0.8rem; margin-top: 4px;">음성 재생</span>
        </button>

        <button id="nav-replay" style="display: flex; flex-direction: column; align-items: center; background: none; border: none;">
          <img src="image/replay_btn.svg" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">다시 듣기</span>
        </button>
      </div>
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

  if (data.type === 'math') {
    setupMathSteps(container, data);
  }

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

// ============ 수학 ============
// 문제 → (필요 시 풀이용 그림 박스) → 풀이단계 → 정답 (마지막 단계에서만 정답 공개).
// 수학은 아직 백엔드가 없어서 응답 구조를 우리가 직접 정한다 (MOCK_MATH 참고).
//
// 이미지 3가지 경우:
// 1) 문제에 이미지 없고, 그림 해설도 필요 없음 → questionImage:null, explanationImage:null (기본 UI)
// 2) 문제에 이미지는 없지만, 그림 해설이 필요함 → explanationImage에 URL. 문제-풀이단계 사이에
//    310×190 박스(테두리 #9C9C9C, 굵기 0.5, radius 10)가 항상 보이는 채로 생김
// 3) 문제 자체에 이미지가 있음 → questionImage에 URL. 문제 아코디언 안, 308×150 박스(같은
//    테두리 스펙)로 표시, 아코디언 펼쳤을 때만 보임
function renderMath(data) {
  const steps = normalizeSteps(data.steps);
  const hasSteps = steps.length > 0;
  const startsRevealed = !hasSteps || steps.length === 1;

  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${escapeHtml(data.problem_text || '문제를 불러오는 중입니다.')}</p>
        ${renderMathQuestionImage(data.questionImage)}
      </div>
    </div>

    ${renderMathExplanationImageBox(data.explanationImage)}

    ${hasSteps ? `
    <div class="step-card">
      <p class="step-label">
        <img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 풀이 단계 <span id="step-counter">1 / ${steps.length}</span>
      </p>
      <div class="step-progress">
        ${steps.map((_, i) => `<span class="step-dot" data-i="${i}"></span>`).join('')}
      </div>
      <p class="step-text" id="step-text">${escapeHtml(steps[0].text)}</p>
      <div class="step-controls">
        <button class="btn btn-secondary" id="step-prev" type="button">← 이전</button>
        <button class="btn btn-secondary" id="step-next" type="button">다음 →</button>
      </div>
    </div>
    ` : `
    <div class="step-card">
      <p class="step-label">
        <img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 풀이 단계
      </p>
      <p class="step-text">풀이를 불러오는 중입니다.</p>
    </div>
    `}

    <div class="answer-box ${startsRevealed ? 'visible' : ''}" id="answer-section">
      <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
      <p class="answer-value">${formatAnswer(data.answer)}</p>
    </div>
  `;
}

function setupMathSteps(container, data) {
  const steps = normalizeSteps(data.steps);
  if (steps.length === 0) return;

  let stepIndex = 0;
  const stepText = container.querySelector('#step-text');
  const stepCounter = container.querySelector('#step-counter');
  const dots = container.querySelectorAll('.step-dot');
  const answerSection = container.querySelector('#answer-section');

  function updateStep() {
    stepText.textContent = steps[stepIndex].text;
    stepCounter.textContent = `${stepIndex + 1} / ${steps.length}`;
    dots.forEach((d, i) => d.classList.toggle('active', i <= stepIndex));
    const isLastStep = stepIndex === steps.length - 1;
    answerSection.classList.toggle('visible', isLastStep);
    container.querySelector('#step-next').classList.toggle('is-last', isLastStep);
    stepCounter.classList.toggle('is-last', isLastStep);
  }
  updateStep();

  container.querySelector('#step-prev').addEventListener('click', () => {
    stepIndex = Math.max(0, stepIndex - 1);
    updateStep();
  });
  container.querySelector('#step-next').addEventListener('click', () => {
    stepIndex = Math.min(steps.length - 1, stepIndex + 1);
    updateStep();
  });
}

// steps가 문자열 배열로 와도 { text } 형태로 통일
function normalizeSteps(steps) {
  if (!steps || steps.length === 0) return [];
  return steps.map((s) => (typeof s === 'string' ? { text: s } : { text: s.text ?? '' }));
}

// 수학 전용: 문제 자체에 이미지가 있는 경우 (아코디언 펼쳤을 때만 보임, 308x150, 테두리 있음)
function renderMathQuestionImage(imageUrl) {
  if (!imageUrl) return '';
  return `
    <div class="math-image-wrap">
      <img src="${imageUrl}" alt="문제 관련 이미지" class="math-question-image" />
    </div>
  `;
}

// 수학 전용: 문제엔 이미지 없지만 그림 해설이 필요한 경우 - 문제와 풀이단계 사이에
// 항상 보이는 채로 뜨는 박스 (310x190, 테두리 있음)
function renderMathExplanationImageBox(imageUrl) {
  if (!imageUrl) return '';
  return `
    <div class="math-explanation-image-box">
      <img src="${imageUrl}" alt="풀이 해설 그림" />
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