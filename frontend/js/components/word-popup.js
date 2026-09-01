// 지문 안 클릭 가능한 단어를 눌렀을 때 하단에 뜨는 팝업
// (단어 + 발음 재생 버튼 + 뜻 + 닫기)
//
// 발음은 별도 음성 파일 없이, 브라우저 내장 Web Speech API(speechSynthesis)로
// 그 자리에서 읽어준다. 단어(word)만 있으면 항상 스피커 버튼이 뜬다.
export function openWordPopup({ word, meaning }) {
  const root = document.getElementById('modal-root');

  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal-sheet word-popup-sheet">
        <img src="image/sheet_handle.svg" alt="" aria-hidden="true" class="sheet-handle" />
        <div class="word-popup-header">
          <span class="word-popup-word">${word}</span>
          <button class="word-popup-audio" id="word-audio-btn" type="button" aria-label="발음 듣기">
            <img src="image/replay_btn.svg" alt="" aria-hidden="true" />
          </button>
        </div>
        <p class="word-popup-meaning">${meaning || '뜻을 불러오는 중입니다.'}</p>
        <button class="btn btn-secondary" id="close-word-popup-btn" type="button">닫기</button>
      </div>
    </div>
  `;

  const overlay = root.querySelector('.modal-overlay');
  requestAnimationFrame(() => overlay.classList.add('open'));

  root.querySelector('#word-audio-btn').addEventListener('click', () => {
    if (!('speechSynthesis' in window)) return; // 지원 안 하는 브라우저는 조용히 무시
    speechSynthesis.cancel(); // 이전에 읽던 게 있으면 멈추고 새로 시작
    const utterance = new SpeechSynthesisUtterance(word);
    utterance.lang = 'en-US';
    speechSynthesis.speak(utterance);
  });

  const close = () => {
    overlay.classList.remove('open');
    setTimeout(() => { root.innerHTML = ''; }, 200);
  };
  root.querySelector('#close-word-popup-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}