import { navigate } from '../router.js';
import { openSettingsModal } from '../components/settings-modal.js';

export function renderHome(container) {
  container.innerHTML = `
    <section class="home-screen">
      <button class="how-to-btn" type="button" aria-label="사용방법 보기">
        <img src="image/question-mark.png" alt="물음표" />
        사용방법
      </button>

      <div class="cat-main">
        <img src="image/main_icon.png" alt="검고심 캐릭터" />
      </div>

      <h1>검고심</h1>
      <p class="subtitle">검정고시 학습 도우미</p>

      <button class="start-btn" type="button" aria-label="시작하기">
        시작하기
        <img src="image/right-arrow.png" alt="화살표" />
      </button>
    </section>
  `;

  container.querySelector('.start-btn').addEventListener('click', () => navigate('/menu'));
  container.querySelector('.how-to-btn').addEventListener('click', () => {
    // TODO: 사용방법 화면/모달 연결
    console.log('사용방법 보기');
  });
}