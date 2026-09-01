import { openSettingsModal } from './settings-modal.js';

export function renderHeader({ onBack }) {
  const header = document.createElement('header');
  header.className = 'app-header';
  header.innerHTML = `
    <button class="back-btn" type="button" aria-label="뒤로 가기">
      <img src="image/back_btn.svg" alt="" aria-hidden="true" />
      뒤로 가기
    </button>
    
    <button class="icon-btn" type="button" aria-label="설정">
      <img src="image/setting_btn.svg" alt="" aria-hidden="true" />
    </button>
  `;

  header.querySelector('.back-btn').addEventListener('click', onBack);
  header.querySelector('.icon-btn').addEventListener('click', openSettingsModal);

  return header;
}
