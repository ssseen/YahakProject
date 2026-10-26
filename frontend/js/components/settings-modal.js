import { getState, applyFontSize, applySpeechRate, applyUserLevel } from '../state.js';
import { speak } from '../tts.js';

const FONT_OPTIONS = [
  { value: 'small', label: '작게' },
  { value: 'medium', label: '보통' },
  { value: 'large', label: '크게' },
];
const RATE_OPTIONS = [
  { value: 'slow', label: '천천히' },
  { value: 'normal', label: '보통' },
  { value: 'fast', label: '빠르게' },
];
const LEVEL_OPTIONS = [
  { value: '초졸', label: '초졸' },
  { value: '중졸', label: '중졸' },
  { value: '고졸', label: '고졸' },
  { value: 'skip', label: '선택 안 함' },
];

function optionButtons(options, current, onSelect, groupClass) {
  return options
    .map(
      (o) => `
      <button type="button" class="${groupClass}-option ${o.value === current ? 'selected' : ''}" data-value="${o.value}">
        ${o.label}
      </button>`
    )
    .join('');
}

export function openSettingsModal() {
  const root = document.getElementById('modal-root');
  const { settings } = getState();

  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal-sheet">
        <img src="image/sheet_handle.svg" alt="" aria-hidden="true" class="sheet-handle" />

        <h3>글자 크기</h3>
        <div class="option-row" id="font-size-row">
          ${optionButtons(FONT_OPTIONS, settings.fontSize, null, 'font-size')}
        </div>

        <h3>읽어주는 속도</h3>
        <div class="option-row" id="speech-rate-row">
          ${optionButtons(RATE_OPTIONS, settings.speechRate, null, 'speech-rate')}
        </div>

        <h3>내 학력</h3>
        <div class="option-row" id="user-level-row">
          ${optionButtons(LEVEL_OPTIONS, settings.userLevel || 'skip', null, 'user-level')}
        </div>

        <button class="btn btn-secondary" id="test-speed-btn" type="button">
        <img src="image/replay_btn.svg" alt="" aria-hidden="true" /> 이 속도로 들어보기
        </button>
        <button class="btn btn-primary" id="close-modal-btn" type="button" style="margin-top: 12px;">닫기</button>
      </div>
    </div>
  `;

  const overlay = root.querySelector('.modal-overlay');
  requestAnimationFrame(() => overlay.classList.add('open'));

  root.querySelector('#font-size-row').addEventListener('click', (e) => {
    const btn = e.target.closest('.font-size-option');
    if (!btn) return;
    applyFontSize(btn.dataset.value);
    root.querySelectorAll('.font-size-option').forEach((b) => b.classList.toggle('selected', b === btn));
  });

  root.querySelector('#speech-rate-row').addEventListener('click', (e) => {
    const btn = e.target.closest('.speech-rate-option');
    if (!btn) return;
    applySpeechRate(btn.dataset.value);
    root.querySelectorAll('.speech-rate-option').forEach((b) => b.classList.toggle('selected', b === btn));
  });

    root.querySelector('#user-level-row').addEventListener('click', (e) => {
    const btn = e.target.closest('.user-level-option');
    if (!btn) return;
    applyUserLevel(btn.dataset.value);
    root.querySelectorAll('.user-level-option').forEach((b) => b.classList.toggle('selected', b === btn));
  });

  root.querySelector('#test-speed-btn').addEventListener('click', () => {
    speak('안녕하세요, 선택하신 속도로 문제 해설을 읽어드립니다.');
  });

  const close = () => {
    overlay.classList.remove('open');
    setTimeout(() => { root.innerHTML = ''; }, 200);
  };
  root.querySelector('#close-modal-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

export function openLevelPromptModal() {
  const root = document.getElementById('modal-root');
  if (!root) return;

  root.innerHTML = `
    <div class="modal-overlay">
      <div class="modal-sheet">
        <img src="image/sheet_handle.svg" alt="" aria-hidden="true" class="sheet-handle" />
        <h3>어떤 시험을 준비하세요?</h3>
        <p class="level-help">맞는 문제를 보여드리려고 여쭤봐요.<br />나중에 설정에서 바꿀 수 있어요.</p>
        <button type="button" class="btn btn-secondary level-choice-btn" data-value="초졸">초졸 (초등학교 졸업)</button>
        <button type="button" class="btn btn-secondary level-choice-btn" data-value="중졸">중졸 (중학교 졸업)</button>
        <button type="button" class="btn btn-secondary level-choice-btn" data-value="고졸">고졸 (고등학교 졸업)</button>
        <button type="button" class="level-skip-btn" data-value="skip">건너뛰기</button>
      </div>
    </div>
  `;

  const overlay = root.querySelector('.modal-overlay');
  requestAnimationFrame(() => overlay.classList.add('open'));

  root.querySelector('.modal-sheet').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-value]');
    if (!btn) return;
    applyUserLevel(btn.dataset.value);
    overlay.classList.remove('open');
    setTimeout(() => { root.innerHTML = ''; }, 200);
  });
}