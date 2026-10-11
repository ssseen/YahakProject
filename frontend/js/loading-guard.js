let loading = false;
let controller = null;
let ignorePop = false;
let afterClear = null;
let leaveAction = null;
let dialog = null;

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement('div');
  dialog.className = 'exit-dialog';
  dialog.hidden = true;
  dialog.innerHTML = `
    <div class="exit-box">
      <p class="exit-msg">정말 나가시겠습니까?</p>
      <button class="exit-btn primary" data-act="wait" type="button">계속 기다리기</button>
      <button class="exit-btn" data-act="leave" type="button">나가기</button>
    </div>`;
  dialog.querySelector('[data-act="wait"]').onclick = hideDialog;
  dialog.querySelector('[data-act="leave"]').onclick = leave;
  document.body.appendChild(dialog); // #app 밖에 둬야 transform 영향 안 받음
  return dialog;
}

function showDialog() { ensureDialog().hidden = false; }
function hideDialog() { if (dialog) dialog.hidden = true; }

function leave() {
  controller.abort();          // 요청 취소
  endLoading(leaveAction);     // 가드 치우고 나서 나가기 동작 실행
}

// 로딩 시작: fetch에 넘길 AbortController signal을 돌려줌
export function startLoading(onLeave) {
  loading = true;
  leaveAction = onLeave || (() => history.back());
  controller = new AbortController();
  history.pushState({ guard: true }, ''); // 같은 URL로 가드 1개
  return controller.signal;
}

// 로딩 끝: 가드 치운 뒤 then 실행 (화면 이동은 여기서)
export function endLoading(then) {
  if (!loading) { then && then(); return; }
  loading = false;
  hideDialog();
  ignorePop = true;
  afterClear = then || null;
  history.go(-1);
}

window.addEventListener('popstate', () => {
  if (ignorePop) {
    ignorePop = false;
    const f = afterClear;
    afterClear = null;
    f && f();
    return;
  }
  if (loading) {
    history.pushState({ guard: true }, ''); // 다시 막기
    showDialog();
  }
});