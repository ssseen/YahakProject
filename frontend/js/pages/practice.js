import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';

export function renderPractice(container) {
  const state = getState();
  const similarQuestions = (state.question?.similar_questions || []).slice(0, 3);

  // 1. 에러 문구 폰트 및 여백을 solve.js와 완벽히 통일
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

  function renderCurrentQuestion() {
    const q = similarQuestions[currentIndex];
    const isLastQuestion = currentIndex === similarQuestions.length - 1;

    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    const formattedQuestion = (q.question || '').replace(/\s*(A:|B:)/g, '\n$1').trim().replace(/\n+/g, '<br>');
    const imageHtml = q.has_image ? `<div class="passage-image-wrap"><img src="${q.image_path}" alt="문제 이미지" class="passage-image" /></div>` : '';

    const correctIdx = parseInt(q.answer);
    const answerText = choicesArray[correctIdx - 1] || q.answer;

    // 2. solve-screen 껍데기를 씌워 가로 폭과 배경색을 통일
    // 3. solve.js와 완전히 똑같은 accordion, explanation-box, answer-box 클래스 사용
    container.innerHTML = `
      <section class="solve-screen">
        
        <div class="solve-header">
          <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
          <span>비슷한 문제 풀어보기</span>
        </div>

        <div class="accordion open">
          <button class="accordion-toggle" type="button" style="pointer-events: none;">
            <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
          </button>
          
          <div class="accordion-body">
            ${q.year ? `<p style="font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 10px;">${q.year}년 ${q.exam_round}회 검정고시 기출</p>` : ''}
            
            <p class="pre-line" style="margin-bottom: 15px;">${formattedQuestion}</p>
            ${imageHtml}
            
            <div class="choice-list" id="practice-choices">
              ${choicesArray.map((choiceText, i) => `
                <div class="choice" data-index="${i + 1}">
                  ${choiceText}
                </div>
              `).join('')}
            </div>
            
            <p class="tap-hint" id="tap-hint">
              <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 정답을 골라서 눌러보세요.
            </p>
          </div>
        </div>

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

        <!-- 4. position: fixed를 빼고 solve-screen 내부에 위치시켜 폭을 똑같이 맞춤 -->
        <div class="bottom-nav-bar" style="display: flex; justify-content: space-around; margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee;">
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

        // solve.css의 .correct 클래스를 붙여 완벽히 동일한 초록색 정답 UI 적용
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