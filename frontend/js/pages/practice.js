import { navigate } from '../router.js';
import { getState } from '../state.js';

export function renderPractice(container) {
  const state = getState();
  const similarQuestions = state.question?.similar_questions || [];

  // 데이터가 없을 경우 예외 처리
  if (similarQuestions.length === 0) {
    container.innerHTML = `
      <div style="padding: 20px; text-align: center;">
        <p>유사 문제를 불러오지 못했습니다.</p>
        <button id="btn-back-empty" style="margin-top:20px; padding:10px 20px;">돌아가기</button>
      </div>
    `;
    container.querySelector('#btn-back-empty').addEventListener('click', () => navigate('/solve'));
    return;
  }

// 유사 문제 리스트 HTML 생성
  const listHtml = similarQuestions.map((q, index) => {
    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    const choicesHtml = choicesArray.map(c => `<div style="margin-bottom: 5px;">${c}</div>`).join('');
    const imageHtml = q.has_image ? `<img src="${q.image_path}" alt="문제 이미지" style="width: 100%; max-width: 400px; margin: 10px 0;" />` : '';

    // 백엔드에서 온 텍스트의 'A:', 'B:' 앞에 줄바꿈을 추가하고, 기존 줄바꿈(\n)도 HTML 태그로 변환
    const formattedQuestion = q.question
      .replace(/(A:|B:)/g, '<br>$1') 
      .replace(/\n/g, '<br>');

    return `
      <div class="similar-card" style="border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; margin-bottom: 20px; background: #fff;">
        <p style="font-size: 0.85rem; color: #888; margin-bottom: 10px;">
          ${q.year}년 ${q.exam_round}회 검정고시 기출
        </p>
        <p style="font-weight: bold; margin-bottom: 15px; line-height: 1.6;">
          ${index + 1}. ${formattedQuestion}
        </p>
        
        ${imageHtml}
        
        <div class="choices-container" style="margin-bottom: 20px;">
          ${choicesHtml}
        </div>

        <details style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
          <summary style="cursor: pointer; font-weight: bold; color: #4a7cff; outline: none;">정답 및 해설 보기</summary>
          <div style="margin-top: 15px; border-top: 1px dashed #ccc; padding-top: 15px;">
            <p style="color: #28a745; font-weight: bold; margin-bottom: 8px;">정답: ${q.answer}번</p>
            <p style="font-size: 0.95rem; line-height: 1.5;">${q.explanation}</p>
          </div>
        </details>
      </div>
    `;
  }).join('');

  container.innerHTML = `
    <div class="practice-screen" style="padding: 70px 20px 100px 20px; background: #f0f4f8; min-height: 100vh;">
      <h2 style="margin: 0 0 25px 0; font-size: 1.2rem; text-align: left; font-weight: bold;">비슷한 문제 풀어보기</h2>
      ${listHtml}
    </div>

    <div class="bottom-nav-bar" style="position: fixed; bottom: 0; left: 0; right: 0; background: #fff; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid #eee; z-index: 1000;">
      
      <button id="nav-home" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
        <img src="image/home_btn.svg" alt="" style="width: 24px; height: 24px;" />
        <span style="font-size: 0.8rem; margin-top: 4px;">처음으로</span>
      </button>
      
      <button id="nav-play-toggle" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
        <img id="play-icon" src="image/play_btn.png" alt="" style="width: 24px; height: 24px;" />
        <span id="play-text" style="font-size: 0.8rem; margin-top: 4px;">음성 재생</span>
      </button>

      <button id="nav-replay" style="display: flex; flex-direction: column; align-items: center; background: none; border: none; cursor: pointer;">
        <img src="image/replay_btn.svg" alt="" style="width: 24px; height: 24px;" />
        <span style="font-size: 0.8rem; margin-top: 4px;">다시 듣기</span>
      </button>

    </div>
  `;
  container.querySelector('#nav-home').addEventListener('click', () => {
    navigate('/');
  });
}