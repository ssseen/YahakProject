import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';

export function renderPractice(container) {
  const state = getState();
  const similarQuestions = (state.question?.similar_questions || []).slice(0, 3);

  if (similarQuestions.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:120px 0; color:var(--color-text-muted); font-size:0.8rem;">
        문제 데이터를 불러오는 중입니다...
        <br><br>
        <button id="btn-back-empty" style="padding:8px 16px; background:#fff; border:1px solid #ccc; border-radius:4px; cursor:pointer;">돌아가기</button>
      </div>
    `;
    container.querySelector('#btn-back-empty').addEventListener('click', () => navigate('/solve'));
    return;
  }

  let currentIndex = 0;

  // 전 과목 보기(①~④) 추출 및 문제 지문 분리 헬퍼 함수
  function parseQuestionAndChoices(q) {
    let questionText = q.question || '';
    let choicesArray = [];

    // 1) q.choices 필드에 데이터가 있는 경우
    if (Array.isArray(q.choices) && q.choices.length > 0) {
      choicesArray = q.choices.map(c => String(c).trim()).filter(Boolean);
    } else if (typeof q.choices === 'string' && q.choices.trim() !== '') {
      if (q.choices.includes('||')) {
        choicesArray = q.choices.split('||').map(c => c.trim()).filter(Boolean);
      } else if (/[①②③④]/.test(q.choices)) {
        choicesArray = q.choices.split(/(?=[①②③④])/).map(c => c.trim()).filter(Boolean);
      } else {
        choicesArray = q.choices.split('\n').map(c => c.trim()).filter(Boolean);
      }
    }

    // 2) q.choices가 비어있고 question 지문 안에 ①~④ 보기가 포함된 경우 (타 과목 대응)
    if (choicesArray.length === 0 && /①/.test(questionText)) {
      const firstChoiceIdx = questionText.indexOf('①');
      const extractedChoicesStr = questionText.slice(firstChoiceIdx);
      const splitChoices = extractedChoicesStr.split(/(?=[①②③④⑤])/).map(c => c.trim()).filter(Boolean);

      if (splitChoices.length >= 2) {
        choicesArray = splitChoices;
        questionText = questionText.slice(0, firstChoiceIdx).trim();
      }
    }

    // 원문자(①~④)가 없는 보기에 번호 붙여주기
    const circleNums = ['①', '②', '③', '④', '⑤'];
    choicesArray = choicesArray.map((c, idx) => {
      if (/^[①②③④⑤]/.test(c)) return c;
      return `${circleNums[idx] || (idx + 1) + '.'} ${c}`;
    });

    return { questionText, choicesArray };
  }

  function renderCurrentQuestion() {
    const q = similarQuestions[currentIndex];
    const isLastQuestion = currentIndex === similarQuestions.length - 1;

    const { questionText, choicesArray } = parseQuestionAndChoices(q);
    const formattedQuestion = questionText.replace(/\s*(A:|B:)/g, '\n$1').trim().replace(/\n+/g, '<br>');
    const imageHtml = q.has_image ? `<div class="passage-image-wrap"><img src="${q.image_path}" alt="문제 이미지" class="passage-image" /></div>` : '';

    const correctIdx = parseInt(q.answer);
    const answerText = choicesArray[correctIdx - 1] || q.answer;

    container.innerHTML = `
      <section class="solve-screen" style="padding-bottom: 90px;">
        
        <div class="solve-header">
          <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
          <span>비슷한 문제 풀어보기</span>
        </div>

        <!-- 1. 문제 아코디언 -->
        <div class="accordion open">
          <button class="accordion-toggle" type="button" style="pointer-events: none; padding-bottom: 4px;">
            <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
          </button>
          
          <div class="accordion-body" style="border-top: none; padding-top: 2px;">
            ${q.year ? `<p style="font-size: 0.68rem; color: var(--color-text-muted); margin-top: 0; margin-bottom: 10px; line-height: 1.2;">${q.year}년 ${q.exam_round}회 검정고시 기출</p>` : ''}
            
            <p class="pre-line" style="margin-bottom: 15px;">${formattedQuestion}</p>
            ${imageHtml}
            
            <div class="choice-list" id="practice-choices">
              ${choicesArray.map((choiceText, i) => `
                <div class="choice" data-index="${i + 1}">
                  ${choiceText}
                </div>
              `).join('')}
            </div>
            
            <p class="tap-hint" id="tap-hint" style="margin-top: 15px;">
              <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 정답을 골라서 눌러보세요.
            </p>
          </div>
        </div>

        <!-- 2. 정답 및 해설 (전체 해석 보기 칸 삭제 완료) -->
        <div id="explanation-section" style="display: none;">
          <div class="explanation-box">
            <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
            <p>${q.explanation || '해설을 불러오지 못했습니다.'}</p>
          </div>

          <div class="answer-box visible">
            <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
            <p class="answer-value">${answerText}</p>
          </div>
        </div>

        <!-- 3. 하단 네비게이션 바 (화면 하단 고정) -->
        <div class="bottom-nav-bar" style="position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 360px; background: var(--color-bg); z-index: 40; display: flex; justify-content: space-around; padding: 10px 0 16px; border-top: 1px solid var(--color-border);">
          <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
            <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
            <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
          </button>
          
          ${!isLastQuestion ? `
          <button id="nav-next" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer; opacity: 0.3; pointer-events: none;">
            <img src="image/smile_plus_icon.png" alt="" style="width: 24px; height: 24px;" />
            <span style="font-size: 0.8rem; margin-top: 4px;">더 풀어보기</span>
          </button>
          ` : ''}
        </div>

      </section>
    `;

    attachEventListeners(q);
  }

  function attachEventListeners(q) {
    // 하단 바 이동 이벤트
    container.querySelector('#nav-home').addEventListener('click', () => {
      resetQuestionFlow();
      navigate('/');
    });

    const nextBtn = container.querySelector('#nav-next');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        currentIndex++; 
        renderCurrentQuestion(); 
        window.scrollTo(0, 0); 
      });
    }

    // 문제 채점 이벤트
    const choices = container.querySelectorAll('.choice');
    const explanationSection = container.querySelector('#explanation-section');
    const tapHint = container.querySelector('#tap-hint');
    let isAnswered = false;

    choices.forEach(choice => {
      choice.addEventListener('click', function() {
        if (isAnswered) return; 
        isAnswered = true;
        
        const selectedIdx = parseInt(this.dataset.index);
        const correctIdx = parseInt(q.answer);

        const correctEl = container.querySelector(`.choice[data-index="${correctIdx}"]`);
        if (correctEl) {
          correctEl.classList.add('correct'); 
        }

        if (selectedIdx !== correctIdx) {
          this.style.backgroundColor = '#f8d7da';
          this.style.borderColor = '#f5c6cb';
          this.style.color = '#721c24';
        }

        if (tapHint) tapHint.style.display = 'none';
        explanationSection.style.display = 'block';
        
        if (nextBtn) {
          nextBtn.style.opacity = '1';
          nextBtn.style.pointerEvents = 'auto';
        }
      });
    });
  }

  renderCurrentQuestion();
}