import { navigate } from '../router.js';
import { getState, resetQuestionFlow, subscribe } from '../state.js';
import { openWordPopup } from '../components/word-popup.js';

function assembleTokens(tokens) {
  if (!tokens || tokens.length === 0) return '';
  return tokens
    .map((tok) => {
      if (tok.meaning) {
        return '<span class="lookup-word" data-word="' + escapeHtml(tok.text) + '" data-meaning="' + escapeHtml(tok.meaning) + '">' + escapeHtml(tok.text) + '</span>';
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
    return CIRCLED[answer.number - 1] + ' ' + answer.text;
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

// 해설 텍스트를 문장 단위(<span class="tts-sentence">)로 감싸주는 함수
function splitIntoSentences(text) {
  if (!text) return [];
  const raw = String(text).trim();
  const matches = raw.match(/[^.!?。\n]+[.!?。]?/g);
  if (!matches) return [raw];
  return matches.map((s) => s.trim()).filter(Boolean);
}

function renderTtsSentencesHtml(text) {
  const sentences = splitIntoSentences(text);
  if (sentences.length === 0) return '';
  return sentences
    .map((sentence, idx) => {
      return '<span class="tts-sentence" data-tts-idx="' + idx + '">' + escapeHtml(sentence) + '</span>';
    })
    .join(' ');
}

// TTS 발음을 자연스럽게 읽기 위한 텍스트 전처리 (원문자 -> 1번, 2번 등)
function cleanTextForSpeech(text) {
  return String(text)
    .replace(/①/g, ' 1번, ')
    .replace(/②/g, ' 2번, ')
    .replace(/③/g, ' 3번, ')
    .replace(/④/g, ' 4번, ')
    .replace(/⑤/g, ' 5번, ')
    .replace(/㉠/g, '기역')
    .replace(/㉡/g, '니은')
    .replace(/㉢/g, '디귿')
    .replace(/㉣/g, '리을');
}

function getSpeechRateValue() {
  const rateSetting = getState().settings?.speechRate || 'normal';
  if (rateSetting === 'slow') return 0.75;
  if (rateSetting === 'fast') return 1.2;
  return 0.95;
}

const MOCK_MATH = {
  status: 'success',
  type: 'math',
  subject: '수학',
  problem_type: '도형 > 원의 넓이',
  problem_text: '아래 그림과 같이 반지름이 5cm인 원이 있다.\n이 원의 넓이를 구하시오. (단, 원주율은 3이다.)',
  questionImage: null,
  explanationImage: null,
  steps: [
    { text: '원의 넓이 공식은 반지름 × 반지름 × 원주율입니다.' },
    { text: '반지름 5cm를 대입하면 5 × 5 × 3 = 75 입니다.' },
    { text: '따라서 원의 넓이는 75cm² 입니다.' },
  ],
  answer: { number: 1, text: '75cm²' },
};

function getDebugMock() {
  const query = window.location.hash.split('?')[1];
  if (!query) return null;
  const mock = new URLSearchParams(query).get('mock');
  return mock === 'math' ? MOCK_MATH : null;
}

export function renderSolve(container) {
  const state = getState();
  const data = getDebugMock() || state.question;

  if (!data) {
    container.innerHTML = `
      <div style="text-align:center; padding:120px 0; color:var(--color-text-muted); font-size:0.8rem;">
        문제 데이터를 불러오는 중입니다...
      </div>`;
    return;
  }

  const isMathMultiStep = data.type === 'math' && normalizeSteps(data.steps).length > 1;
  const similarBtnStyle = isMathMultiStep ? 'display: none;' : '';
  const bodyContent = data.type === 'english' ? renderEnglish(data) : data.type === 'math' ? renderMath(data) : renderGuksagwa(data);

  container.innerHTML = `
    <section class="solve-screen">
      <div class="solve-header">
        <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
        <span>함께 풀어봐요!</span>
      </div>

      ${bodyContent}
      
      <button type="button" class="btn-similar-problem" id="btn-similar" style="${similarBtnStyle}">
        비슷한 문제 풀어보기
      </button>

      <div class="bottom-nav-bar">
        <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
          <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
        </button>

        <button id="nav-play-toggle" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
          <img id="play-icon" src="image/pause_btn.png" alt="" style="width: 24px; height: 24px;" />
          <span id="play-text" style="font-size: 0.8rem; margin-top: 4px;">일시 정지</span>
        </button>

        <button id="nav-replay" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
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

  // ===== TTS 컨트롤러 (문장 하이라이트 & 클릭한 문장부터 재생) =====
  const playToggleBtn = container.querySelector('#nav-play-toggle');
  const playIcon = container.querySelector('#play-icon');
  const playText = container.querySelector('#play-text');

  let isPlaying = false;
  let currentSentenceIdx = 0;
  let activeUtterance = null;

  function updatePlayButtonUI(playing) {
    isPlaying = playing;
    if (!playIcon || !playText) return;
    if (playing) {
      playIcon.src = 'image/pause_btn.png';
      playText.textContent = '일시 정지';
    } else {
      playIcon.src = 'image/play_btn.png';
      playText.textContent = '음성 재생';
    }
  }

  function highlightSentence(idx) {
    const spans = container.querySelectorAll('.tts-sentence');
    spans.forEach((span, i) => {
      span.classList.toggle('active', i === idx);
    });
  }

  function stopTts(resetHighlight = false) {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    activeUtterance = null;
    updatePlayButtonUI(false);
    if (resetHighlight) {
      highlightSentence(-1);
    }
  }

  function speakFrom(startIdx) {
    if (!('speechSynthesis' in window)) return;
    const spans = Array.from(container.querySelectorAll('.tts-sentence'));
    if (spans.length === 0) return;

    if (startIdx < 0 || startIdx >= spans.length) {
      stopTts(true);
      currentSentenceIdx = 0;
      return;
    }

    window.speechSynthesis.cancel();
    currentSentenceIdx = startIdx;
    updatePlayButtonUI(true);
    highlightSentence(currentSentenceIdx);

    const textToRead = cleanTextForSpeech(spans[currentSentenceIdx].textContent);
    const utterance = new SpeechSynthesisUtterance(textToRead);
    utterance.lang = 'ko-KR';
    utterance.rate = getSpeechRateValue();
    activeUtterance = utterance;

    utterance.onend = () => {
      if (activeUtterance !== utterance || !isPlaying) return;
      if (currentSentenceIdx + 1 < spans.length) {
        speakFrom(currentSentenceIdx + 1);
      } else {
        // 마지막 문장까지 다 읽었을 때
        highlightSentence(-1);
        updatePlayButtonUI(false);
        currentSentenceIdx = 0;
      }
    };

    utterance.onerror = () => {
      if (activeUtterance !== utterance) return;
      updatePlayButtonUI(false);
    };

    window.speechSynthesis.speak(utterance);
  }

  function bindTtsSentenceClicks() {
    const spans = container.querySelectorAll('.tts-sentence');
    spans.forEach((span, idx) => {
      span.addEventListener('click', () => {
        speakFrom(idx);
      });
    });
  }

  // 수학 단계 이동 시에도 TTS 바인딩 및 자동 읽기가 동작하도록 전달
  if (data.type === 'math') {
    setupMathSteps(container, data, () => {
      bindTtsSentenceClicks();
      speakFrom(0);
    });
  } else {
    bindTtsSentenceClicks();
    setTimeout(() => speakFrom(0), 250);
  }

  // 설정 모달에서 읽기 속도를 바꾸면 현재 문장부터 새 속도로 즉시 반영
  let lastSpeechRate = getState().settings?.speechRate;
  const unsubscribe = subscribe((newState) => {
    const newRate = newState.settings?.speechRate;
    if (newRate !== lastSpeechRate) {
      lastSpeechRate = newRate;
      if (isPlaying) {
        speakFrom(currentSentenceIdx);
      }
    }
  });

  // 페이지 벗어날 때 음성 중지
  window.addEventListener('hashchange', () => {
    stopTts(true);
    unsubscribe();
  }, { once: true });

  container.querySelector('#nav-home').addEventListener('click', () => {
    stopTts(true);
    unsubscribe();
    resetQuestionFlow();
    navigate('/');
  });

  playToggleBtn.addEventListener('click', () => {
    if (isPlaying) {
      stopTts(false);
    } else {
      speakFrom(currentSentenceIdx);
    }
  });

  container.querySelector('#nav-replay').addEventListener('click', () => {
    speakFrom(0);
  });

  container.querySelector('#btn-similar').addEventListener('click', () => {
    stopTts(true);
    unsubscribe();
    navigate('/practice');
  });
}

function renderGuksagwa(data) {
  const rawText = data.problem_text || '문제를 불러오는 중입니다.';
  let questionOnly = rawText;
  let choicesArray = [];

  if (/①/.test(rawText) && /②/.test(rawText)) {
    const firstChoiceIdx = rawText.indexOf('①');
    const extractedChoices = rawText
      .slice(firstChoiceIdx)
      .split(/(?=[①②③④⑤])/)
      .map((c) => c.trim())
      .filter(Boolean);

    if (extractedChoices.length >= 2) {
      choicesArray = extractedChoices;
      questionOnly = rawText.slice(0, firstChoiceIdx).trim();
    }
  }

  let choicesHtml = '';
  if (choicesArray.length > 0) {
    const correctNum = data.answer && data.answer.number != null ? Number(data.answer.number) : null;
    const items = choicesArray
      .map((choiceText, idx) => {
        const isCorrect = correctNum === idx + 1 ? 'correct' : '';
        return '<div class="choice ' + isCorrect + '">' + escapeHtml(choiceText) + '</div>';
      })
      .join('');
    choicesHtml = '<div class="choice-list">' + items + '</div>';
  }

  const explanationSentencesHtml = renderTtsSentencesHtml(data.explanation || '해설을 불러오는 중입니다.');

  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${escapeHtml(questionOnly)}</p>
        ${choicesHtml}
        ${renderIllustration(data.illustration)}
      </div>
    </div>

    <div class="explanation-box">
      <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
      <p id="tts-explanation">${explanationSentencesHtml}</p>
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

  let optionsHtml = '';
  if (hasOptions) {
    const items = data.options.map((opt) => {
      const isCorrect = data.answer && data.answer.number === opt.no ? 'correct' : '';
      const circle = CIRCLED[opt.no - 1] || opt.no;
      return '<div class="choice ' + isCorrect + '">' + circle + '<span class="pre-line">' + assembleTokens(opt.tokens) + '</span></div>';
    }).join('');

    optionsHtml = `
      <div class="choice-list">${items}</div>
      <p class="tap-hint">
        <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 뜻이 궁금한 단어를 눌러보세요!
      </p>
    `;
  }

  let translationHtml = '';
  if (hasTranslation) {
    let transOptionsHtml = '';
    if (data.translation.options && data.translation.options.length > 0) {
      const transItems = data.translation.options.map((opt) => {
        const circle = CIRCLED[opt.no - 1] || opt.no;
        return '<p>' + circle + escapeHtml(opt.text) + '</p>';
      }).join('');
      transOptionsHtml = '<p class="translation-heading">보기 해석</p><div class="choice-translation-list">' + transItems + '</div>';
    }

    translationHtml = `
      <div class="accordion accordion-translation">
        <button class="accordion-toggle" type="button">
          <span class="accordion-title"><img src="image/translate_icon.svg" alt="" aria-hidden="true" /> 전체 해석 보기</span>
          <img src="image/view_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
        </button>
        ${renderAccordionHint()}
        <div class="accordion-body">
          <p class="translation-heading">지문 해석</p>
          <p class="pre-line">${escapeHtml(data.translation.passage || '해석을 불러오는 중입니다.')}</p>
          ${transOptionsHtml}
        </div>
      </div>
    `;
  }

  const explanationSentencesHtml = renderTtsSentencesHtml(data.explanation || '해설을 불러오는 중입니다.');

  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${assembleTokens(data.passage && data.passage.tokens)}</p>
        ${optionsHtml}
        ${renderIllustration(data.illustration)}
      </div>
    </div>
    ${translationHtml}
    <div class="explanation-box">
      <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
      <p id="tts-explanation">${explanationSentencesHtml}</p>
    </div>
    <div class="answer-box visible" id="answer-section">
      <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
      <p class="answer-value">${formatAnswer(data.answer)}</p>
    </div>
  `;
}

function renderMath(data) {
  const steps = normalizeSteps(data.steps);
  const hasSteps = steps.length > 0;
  const startsRevealed = !hasSteps || steps.length === 1;
  const answerVisibleClass = startsRevealed ? 'visible' : '';

  const rawText = data.problem_text || '문제를 불러오는 중입니다.';
  let questionOnly = rawText;
  let choicesArray = [];

  if (Array.isArray(data.options) && data.options.length > 0) {
    choicesArray = data.options.map((opt, idx) => {
      const text = typeof opt === 'string' ? opt : (opt.text || '');
      const circle = CIRCLED[idx] || (idx + 1);
      return /^[①②③④⑤]/.test(text.trim()) ? text.trim() : circle + ' ' + text.trim();
    });
  } else if (/①/.test(rawText) && /②/.test(rawText)) {
    const firstChoiceIdx = rawText.indexOf('①');
    const extractedChoices = rawText
      .slice(firstChoiceIdx)
      .split(/(?=[①②③④⑤])/)
      .map((c) => c.trim())
      .filter(Boolean);

    if (extractedChoices.length >= 2) {
      choicesArray = extractedChoices;
      questionOnly = rawText.slice(0, firstChoiceIdx).trim();
    }
  }

  let choicesHtml = '';
  if (choicesArray.length > 0) {
    const correctNum = data.answer && data.answer.number != null ? Number(data.answer.number) : null;
    const items = choicesArray
      .map((choiceText, idx) => {
        const isCorrect = startsRevealed && correctNum === idx + 1 ? 'correct' : '';
        return '<div class="choice ' + isCorrect + '" data-choice-idx="' + (idx + 1) + '">' + escapeHtml(choiceText) + '</div>';
      })
      .join('');
    choicesHtml = '<div class="choice-list">' + items + '</div>';
  }

  let stepCardHtml = '';
  if (hasSteps) {
    const dotsHtml = steps.map((_, i) => '<span class="step-dot" data-i="' + i + '"></span>').join('');
    stepCardHtml = `
      <div class="step-card">
        <p class="step-label">
          <img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 풀이 단계 <span id="step-counter">1 / ${steps.length}</span>
        </p>
        <div class="step-progress">${dotsHtml}</div>
        <p class="step-text" id="step-text">${renderTtsSentencesHtml(steps[0].text)}</p>
        <div class="step-controls">
          <button class="btn btn-secondary" id="step-prev" type="button">← 이전</button>
          <button class="btn btn-secondary" id="step-next" type="button">다음 →</button>
        </div>
      </div>
    `;
  } else {
    stepCardHtml = `
      <div class="step-card">
        <p class="step-label">
          <img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 풀이 단계
        </p>
        <p class="step-text">풀이를 불러오는 중입니다.</p>
      </div>
    `;
  }

  return `
    <div class="accordion open">
      <button class="accordion-toggle" type="button">
        <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
        <img src="image/hide_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
      </button>
      ${renderAccordionHint()}
      <div class="accordion-body">
        <p class="pre-line">${escapeHtml(questionOnly)}</p>
        ${renderMathQuestionImage(data.questionImage)}
        ${choicesHtml}
      </div>
    </div>

    ${renderMathExplanationImageBox(data.explanationImage)}
    ${stepCardHtml}

    <div class="answer-box ${answerVisibleClass}" id="answer-section">
      <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
      <p class="answer-value">${formatAnswer(data.answer)}</p>
    </div>
  `;
}

function setupMathSteps(container, data, onStepRendered) {
  const steps = normalizeSteps(data.steps);
  if (steps.length === 0) return;

  let stepIndex = 0;
  const stepText = container.querySelector('#step-text');
  const stepCounter = container.querySelector('#step-counter');
  const dots = container.querySelectorAll('.step-dot');
  const answerSection = container.querySelector('#answer-section');
  const similarBtn = container.querySelector('#btn-similar');
  const correctNum = data.answer && data.answer.number != null ? Number(data.answer.number) : null;

  function updateStep() {
    stepText.innerHTML = renderTtsSentencesHtml(steps[stepIndex].text);
    stepCounter.textContent = (stepIndex + 1) + ' / ' + steps.length;
    dots.forEach((d, i) => d.classList.toggle('active', i <= stepIndex));
    const isLastStep = stepIndex === steps.length - 1;

    answerSection.classList.toggle('visible', isLastStep);
    if (similarBtn) {
      similarBtn.style.display = isLastStep ? 'flex' : 'none';
    }
    if (correctNum != null) {
      const correctChoiceEl = container.querySelector('.choice[data-choice-idx="' + correctNum + '"]');
      if (correctChoiceEl) {
        correctChoiceEl.classList.toggle('correct', isLastStep);
      }
    }

    container.querySelector('#step-next').classList.toggle('is-last', isLastStep);
    stepCounter.classList.toggle('is-last', isLastStep);

    if (onStepRendered) {
      onStepRendered();
    }
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

function normalizeSteps(steps) {
  if (!steps || steps.length === 0) return [];
  return steps.map((s) => (typeof s === 'string' ? { text: s } : { text: s.text ?? '' }));
}

function renderMathQuestionImage(imageUrl) {
  if (!imageUrl) return '';
  return `
    <div class="math-image-wrap">
      <img src="${imageUrl}" alt="문제 관련 이미지" class="math-question-image" />
    </div>
  `;
}

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