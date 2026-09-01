import { getState, applyFontSize, applySpeechRate } from '../state.js';

const FONT_OPTIONS = [
  { value: 'small', label: '작게' },
  { value: 'medium', label: '보통' },
  { value: 'large', label: '크게' },
];
const RATE_OPTIONS = [
  { value: 'slow', label: '느리게' },
  { value: 'normal', label: '보통' },
  { value: 'fast', label: '빠르게' },
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

  root.querySelector('#test-speed-btn').addEventListener('click', () => {
    // TODO: 실제 TTS 미리듣기 연동
    console.log('TTS 미리듣기:', getState().settings.speechRate);
  });

  const close = () => {
    overlay.classList.remove('open');
    setTimeout(() => { root.innerHTML = ''; }, 200);
  };
  root.querySelector('#close-modal-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}