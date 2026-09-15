import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';

export function renderPractice(container) {
  const state = getState();
  
  // 파인콘 데이터에서 최대 3개의 문제만 가져옵니다.
  const similarQuestions = (state.question?.similar_questions || []).slice(0, 3);

  // 3. 에러 문구 폰트/크기를 solve.js와 완벽히 통일
  if (similarQuestions.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:100px 0; color:var(--color-text-muted); font-size:0.8rem;">
        <p style="margin-bottom: 20px;">유사 문제를 불러오지 못했습니다.</p>
        <button id="btn-back-empty" style="padding:8px 16px; background:#fff; border:1px solid #ccc; border-radius:4px; cursor:pointer;">돌아가기</button>
      </div>
    `;
    container.querySelector('#btn-back-empty').addEventListener('click', () => navigate('/solve'));
    return;
  }

  let currentIndex = 0; // 현재 문제 순서 (0, 1, 2)

  function renderCurrentQuestion() {
    const q = similarQuestions[currentIndex];
    
    // 마지막(3번째) 문제인지 확인
    const isLastQuestion = currentIndex === similarQuestions.length - 1;

    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    
    // 줄바꿈 로직
    let formattedQuestion = (q.question || '')
      .replace(/\s*(A:|B:)/g, '\n$1') 
      .trim()
      .replace(/\n+/g, '<br>');

    const imageHtml = q.has_image ? `<div class="passage-image-wrap"><img src="${q.image_path}" alt="문제 이미지" class="passage-image" /></div>` : '';

    // 2. 전체를 <section class="solve-screen">으로 감싸서 하단 바 폭출을 막고 solve 화면과 폭을 동일하게 맞춤
    container.innerHTML = `
      <section class="solve-screen">
        
        <div class="solve-header">
          <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
          <span>비슷한 문제 풀어보기</span>
        </div>

        <div class="accordion open" style="margin-top: 15px;">
          <div class="accordion-body" style="border-top: none; padding-top: 0;">
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

            <p id="tap-hint" class="tap-hint" style="margin-top: 15px;">
              <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 정답을 골라서 눌러보세요.
            </p>
          </div>
        </div>

        <!-- 1. solve.css의 디자인(explanation-box, answer-box visible)을 100% 동일하게 가져옴 -->
        <div id="explanation-section" style="display: none;">
          <div class="explanation-box">
            <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
            <p>${q.explanation || '해설을 불러오지 못했습니다.'}</p>
          </div>

          <div class="answer-box visible">
            <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
            <p class="answer-value">${choicesArray[parseInt(q.answer) - 1] || q.answer}</p>
          </div>
        </div>

        <!-- 하단 네비게이션 바 (solve-screen 내부 삽입으로 폭 자동 맞춤) -->
        <div class="bottom-nav-bar" style="display: flex; justify-content: space-around; margin-top: 20px; padding-top: 10px; border-top: 1px solid #eee;">
          
          <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
            <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
            <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
          </button>
          
          <!-- 마지막 문제가 아닐 때만 '더 풀어보기' 버튼 렌더링 -->
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
    // [처음으로] 버튼
    container.querySelector('#nav-home').addEventListener('click', () => {
      resetQuestionFlow();
      navigate('/');
    });

    // [더 풀어보기] 버튼
    const nextBtn = container.querySelector('#nav-next');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        currentIndex++; 
        renderCurrentQuestion(); 
        window.scrollTo(0, 0); 
      });
    }

    // 채점 및 해설 노출 로직
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

        // 실제 정답 요소에 solve.css의 .correct 클래스를 붙여서 초록색으로 만듦
        const correctEl = container.querySelector(`.choice[data-index="${correctIdx}"]`);
        if (correctEl) {
          correctEl.classList.add('correct'); 
        }

        // 틀린 보기를 눌렀을 때는 인라인으로 연한 빨간색 표시 (solve.css에 오답 클래스가 없으므로)
        if (selectedIdx !== correctIdx) {
          this.style.backgroundColor = '#f8d7da';
          this.style.borderColor = '#f5c6cb';
          this.style.color = '#721c24';
        }

        // 힌트 가리고 정답&해설 박스 노출!
        if (tapHint) tapHint.style.display = 'none';
        explanationSection.style.display = 'block';
        
        // 더 풀어보기 버튼 활성화
        if (nextBtn) {
          nextBtn.style.opacity = '1';
          nextBtn.style.pointerEvents = 'auto';
        }
      });
    });
  }

  // 첫 문제 렌더링
  renderCurrentQuestion();
}