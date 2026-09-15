import { navigate } from '../router.js';
import { getState, resetQuestionFlow } from '../state.js';

export function renderPractice(container) {
  const state = getState();
  // 파인콘 유사 문제를 최대 3개까지만 가져옵니다.
  const similarQuestions = (state.question?.similar_questions || []).slice(0, 3);

  if (similarQuestions.length === 0) {
    container.innerHTML = `
      <div style="padding: 120px 20px 0 20px; text-align: center;">
        <p>유사 문제를 불러오지 못했습니다.</p>
        <button id="btn-back-empty" style="margin-top:20px; padding:10px 20px; cursor:pointer;">돌아가기</button>
      </div>
    `;
    container.querySelector('#btn-back-empty').addEventListener('click', () => navigate('/solve'));
    return;
  }

  let currentIndex = 0; // 현재 풀고 있는 문제의 순서 (0, 1, 2)

  function renderCurrentQuestion() {
    const q = similarQuestions[currentIndex];
    const isLastQuestion = currentIndex === similarQuestions.length - 1;

    // 선택지 분리 및 줄바꿈 처리
    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    const formattedQuestion = q.question.replace(/(A:|B:)/g, '<br>$1').replace(/\n/g, '<br>');
    const imageHtml = q.has_image ? `<img src="${q.image_path}" alt="문제 이미지" style="width: 100%; max-width: 400px; margin: 10px 0;" />` : '';

    container.innerHTML = `
      <div class="practice-screen" style="padding: 70px 20px 100px 20px; background: #f0f4f8; min-height: 100vh;">
        
        <div class="solve-header" style="display: flex; align-items: center; margin-bottom: 20px;">
          <img src="image/smile_icon.svg" alt="" aria-hidden="true" style="width: 24px; height: 24px; margin-right: 8px;" />
          <h2 style="margin: 0; font-size: 1.2rem; font-weight: bold;">비슷한 문제 풀어보기</h2>
        </div>

        <div class="similar-card" style="border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; margin-bottom: 20px; background: #fff;">
          <p style="font-size: 0.85rem; color: #888; margin-bottom: 10px;">
            ${q.year}년 ${q.exam_round}회 검정고시 기출
          </p>
          <p class="pre-line" style="font-weight: bold; margin-bottom: 20px; line-height: 1.6;">
            ${currentIndex + 1}. ${formattedQuestion}
          </p>
          
          ${imageHtml}
          
          <div class="choice-list" id="practice-choices">
            ${choicesArray.map((choiceText, i) => `
              <div class="choice" data-index="${i + 1}" style="border: 1px solid #ccc; border-radius: 8px; padding: 12px; margin-bottom: 10px; cursor: pointer; background: #fff; transition: all 0.2s;">
                ${choiceText}
              </div>
            `).join('')}
          </div>

          <p id="tap-hint" style="margin-top: 15px; font-size: 0.85rem; color: #666; display: flex; align-items: center; gap: 5px;">
            <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" style="width:16px;" /> 정답을 골라서 눌러보세요.
          </p>
        </div>

        <!-- 정답 클릭 시 나타날 해설 및 정답 영역 -->
        <div id="explanation-section" style="display: none;">
          <div class="explanation-box" style="background: #e9ecef; border-radius: 12px; padding: 15px; margin-bottom: 15px;">
            <p style="font-weight: bold; margin-bottom: 8px;">
              <img src="image/solution_icon.svg" alt="" aria-hidden="true" style="width:16px; vertical-align:middle;" /> 문제 해설
            </p>
            <p style="font-size: 0.95rem; line-height: 1.5;">${q.explanation}</p>
          </div>

          <div class="answer-box" style="background: #a3cfb6; border-radius: 12px; padding: 15px; border: 1px solid #94bfa5;">
            <p style="color: #2e593f; font-weight: bold; margin-bottom: 5px;">✓ 정답</p>
            <p style="color: #2e593f; font-weight: bold; font-size: 1.05rem;">
              ${choicesArray[parseInt(q.answer) - 1] || q.answer}
            </p>
          </div>
        </div>

      </div>

      <!-- 동적 하단 네비게이션 바 -->
      <div class="bottom-nav-bar" style="position: fixed; bottom: 0; left: 0; right: 0; background: #fff; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid #eee; z-index: 1000;">
        <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer; flex: 1;">
          <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
        </button>
        
        ${!isLastQuestion ? `
        <button id="nav-next" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer; flex: 1; opacity: 0.3; pointer-events: none;">
          <img src="image/smile_plus_icon.png" alt="" style="width: 24px; height: 24px;" />
          <span style="font-size: 0.8rem; margin-top: 4px;">더 풀어보기</span>
        </button>
        ` : ''}
      </div>
    `;

    attachEventListeners(q);
  }

  function attachEventListeners(q) {
    // 1. 처음으로 버튼 이벤트
    container.querySelector('#nav-home').addEventListener('click', () => {
      resetQuestionFlow();
      navigate('/');
    });

    // 2. 더 풀어보기 버튼 이벤트 (존재할 경우만)
    const nextBtn = container.querySelector('#nav-next');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        currentIndex++;
        renderCurrentQuestion();
      });
    }

    // 3. 채점 로직
    const choices = container.querySelectorAll('.choice');
    const explanationSection = container.querySelector('#explanation-section');
    const tapHint = container.querySelector('#tap-hint');
    let isAnswered = false;

    choices.forEach(choice => {
      choice.addEventListener('click', function() {
        if (isAnswered) return; // 한 번 풀면 중복 클릭 방지
        isAnswered = true;
        
        const selectedIdx = parseInt(this.dataset.index);
        const correctIdx = parseInt(q.answer);

        if (selectedIdx === correctIdx) {
          // 정답일 때 (초록색)
          this.style.backgroundColor = '#d4edda';
          this.style.borderColor = '#c3e6cb';
          this.style.fontWeight = 'bold';
        } else {
          // 오답일 때 (빨간색) + 실제 정답에 초록색 표시
          this.style.backgroundColor = '#f8d7da';
          this.style.borderColor = '#f5c6cb';
          this.style.fontWeight = 'bold';
          
          const correctEl = container.querySelector(`.choice[data-index="${correctIdx}"]`);
          if (correctEl) {
            correctEl.style.backgroundColor = '#d4edda';
            correctEl.style.borderColor = '#c3e6cb';
            correctEl.style.fontWeight = 'bold';
          }
        }

        // 힌트 문구 숨기고 해설/정답 영역 표시
        if (tapHint) tapHint.style.display = 'none';
        explanationSection.style.display = 'block';
        
        // 정답을 맞힌 후 '더 풀어보기' 버튼 활성화
        if (nextBtn) {
          nextBtn.style.opacity = '1';
          nextBtn.style.pointerEvents = 'auto';
        }
      });
    });
  }

  // 화면 진입 시 첫 번째 문제 렌더링
  renderCurrentQuestion();
}