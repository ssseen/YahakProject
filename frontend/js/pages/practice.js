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
    // 백엔드에서 '||' 기호로 붙여준 선택지를 배열로 분리하여 렌더링
    const choicesArray = q.choices ? q.choices.split('||').map(c => c.trim()) : [];
    const choicesHtml = choicesArray.map(c => `<div style="margin-bottom: 5px;">${c}</div>`).join('');

    // 이미지가 있는 문제일 경우 이미지 태그 추가
    const imageHtml = q.has_image ? `<img src="${q.image_path}" alt="문제 이미지" style="width: 100%; max-width: 400px; margin: 10px 0;" />` : '';

    return `
      <div class="similar-card" style="border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; margin-bottom: 20px; background: #fff;">
        <p style="font-size: 0.85rem; color: #888; margin-bottom: 10px;">
          ${q.year}년 ${q.exam_round}회 검정고시 기출
        </p>
        <p style="font-weight: bold; margin-bottom: 15px;">${index + 1}. ${q.question}</p>
        
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
    <div class="practice-screen" style="padding: 20px; background: #f0f4f8; min-height: 100vh;">
      <div style="display: flex; align-items: center; margin-bottom: 25px;">
        <button id="btn-back" style="background: none; border: none; font-size: 1.2rem; cursor: pointer; padding-right: 15px;">
          ❮ 뒤로 가기
        </button>
        <h2 style="margin: 0; font-size: 1.2rem;">비슷한 문제 풀어보기</h2>
      </div>
      
      ${listHtml}
    </div>
  `;

  // 뒤로 가기 버튼 이벤트 (해설 화면으로 복귀)
  container.querySelector('#btn-back').addEventListener('click', () => {
    navigate('/solve');
  });
}