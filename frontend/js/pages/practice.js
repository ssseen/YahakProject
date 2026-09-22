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

  function renderCurrentQuestion() {
    const q = similarQuestions[currentIndex];
    const isLastQuestion = currentIndex === similarQuestions.length - 1;

    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    const formattedQuestion = (q.question || '').replace(/\s*(A:|B:)/g, '\n$1').trim().replace(/\n+/g, '<br>');
    const imageHtml = q.has_image ? `<div class="passage-image-wrap"><img src="${q.image_path}" alt="문제 이미지" class="passage-image" /></div>` : '';

    const correctIdx = parseInt(q.answer);
    const answerText = choicesArray[correctIdx - 1] || q.answer;

    container.innerHTML = `
      <section class="solve-screen">
        
        <div class="solve-header">
          <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
          <span>비슷한 문제 풀어보기</span>
        </div>

        <!-- 1. 문제 아코디언 -->
        <div class="accordion open">
          <button class="accordion-toggle" type="button" style="pointer-events: none;">
            <span class="accordion-title"><img src="image/quiz_icon.svg" alt="" aria-hidden="true" /> 문제</span>
          </button>
          
          <div class="accordion-body" style="border-top: none; padding-top: 10px;">
            ${q.year ? `<p style="font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 12px;">${q.year}년 ${q.exam_round}회 검정고시 기출</p>` : ''}
            
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

<!-- 전체 해석 보기 아코디언 -->
        <div id="translation-section" class="accordion accordion-translation" style="display: none;">
          <button class="accordion-toggle" type="button">
            <span class="accordion-title"><img src="image/translate_icon.svg" alt="" aria-hidden="true" /> 전체 해석 보기</span>
            <img src="image/view_btn.svg" alt="" aria-hidden="true" class="accordion-chevron" />
          </button>
          <p class="accordion-hint">
            <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 전체를 보시려면 화살표를 눌러주세요.
          </p>
          <div class="accordion-body">
            <p class="translation-heading">지문 해석</p>
            <p class="pre-line">${q.translation || '해석을 제공하지 않는 문제입니다.'}</p>
          </div>
        </div>
        <!-- 3. 정답 및 해설 -->
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

        <!-- 4. 하단 네비게이션 바 -->
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

    // ★ 전체 해석 보기 아코디언 열고 닫기 이벤트 연결 ★
    container.querySelectorAll('.accordion').forEach((acc) => {
      const toggle = acc.querySelector('.accordion-toggle');
      const chevron = acc.querySelector('.accordion-chevron');
      if (toggle && chevron) { 
        toggle.addEventListener('click', () => {
          acc.classList.toggle('open');
          chevron.src = acc.classList.contains('open') ? 'image/hide_btn.svg' : 'image/view_btn.svg';
        });
      }
    });

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
        
        // 추가: 정답을 고르면 전체 해석 보기 아코디언도 나타나게 함!
        const translationSection = container.querySelector('#translation-section');
        if (translationSection) translationSection.style.display = 'block';
        
        if (nextBtn) {
          nextBtn.style.opacity = '1';
          nextBtn.style.pointerEvents = 'auto';
        }
      });
    });
  }

  renderCurrentQuestion();
}