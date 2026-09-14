import { navigate } from '../router.js';

export function renderPractice(container) {
  container.innerHTML = `
    <section class="solve-screen">
      <div class="solve-header">
        <img src="image/smile_icon.svg" alt="" aria-hidden="true" />
        <span>비슷한 문제 풀어보기</span>
      </div>

      <div class="accordion open">
        <div class="accordion-body" style="padding-top: 16px;">
          <p class="pre-line">A: Everything on the menu looks so delicious!
B: Yeah. This is one of my favorite restaurants.
A: Great! ______?
B: How about the spaghetti with cream sauce? It's one of their best dishes.</p>
          
          <div class="choice-list">
            <div class="choice" data-answer="true">① Can you recommend a dish for me</div>
            <div class="choice" data-answer="false">② What is your favorite restaurant</div>
            <div class="choice" data-answer="false">③ Why do you like Italian fashion</div>
            <div class="choice" data-answer="false">④ Have you ever been to Italy</div>
          </div>
          
          <p class="tap-hint" style="margin-top: 16px;">
            <img src="image/tap_hint_icon.svg" alt="" aria-hidden="true" /> 정답을 골라서 눌러보세요.
          </p>
        </div>
      </div>

      <!-- 처음에는 숨겨져 있는 해설 및 정답 박스 -->
      <div id="practice-result-section" style="display: none;">
        <div class="explanation-box">
          <p class="explanation-label"><img src="image/solution_icon.svg" alt="" aria-hidden="true" /> 문제 해설</p>
          <p>빈칸 다음에 B가 구체적인 메뉴를 추천하고 있으므로, 빈칸에는 추천을 요청하는 표현이 들어가야 합니다.</p>
        </div>

        <div class="answer-box visible">
          <p><img src="image/answer_icon.svg" alt="" aria-hidden="true" /> 정답</p>
          <p class="answer-value">① Can you recommend a dish for me</p>
        </div>
      </div>

      <nav class="solve-nav">
        <button class="nav-item" id="nav-home" type="button">
          <img src="image/home_btn.svg" alt="" aria-hidden="true" /><span>처음으로</span>
        </button>
        <button class="nav-item" type="button">
          <img src="image/smile_plus_icon.png" alt="" aria-hidden="true" /><span>더 풀어보기</span>
        </button>
      </nav>
    </section>
  `;

  // 보기 클릭 시 색상 변경 및 해설 표시 로직
  const choices = container.querySelectorAll('.choice');
  const resultSection = container.querySelector('#practice-result-section');

  choices.forEach(choice => {
    choice.addEventListener('click', function() {
      // 1. 모든 색상 초기화
      choices.forEach(c => c.classList.remove('correct', 'incorrect'));
      
      // 2. 정답/오답 판별하여 색상 적용
      if (this.dataset.answer === 'true') {
        this.classList.add('correct');
      } else {
        this.classList.add('incorrect');
      }

      // 3. 숨겨져 있던 해설과 정답 박스를 화면에 표시
      resultSection.style.display = 'block';
    });
  });

  container.querySelector('#nav-home').addEventListener('click', () => {
    navigate('/');
  });
}