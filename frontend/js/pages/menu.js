import { navigate } from '../router.js';
import { setState } from '../state.js';

export function renderMenu(container) {
  container.innerHTML = `
    <section class="menu-screen">
      <div class="cat-main-small">
        <img src="image/main_icon.png" alt="검고심 캐릭터" />
      </div>

      <p class="menu-label">미리 찍어둔 사진을 가져와요.</p>
      <button class="img-btn" id="pick-photo-btn" type="button" aria-label="문제 사진 가져오기">
        <img src="image/photo_import_btn.svg" alt="문제 사진 가져오기" />
      </button>

      <p class="menu-label">문제 사진을 지금 찍어요.</p>
      <button class="img-btn" id="take-photo-btn" type="button" aria-label="문제 사진 찍기">
        <img src="image/photo_capture_btn.svg" alt="문제 사진 찍기" />
      </button>

      <button class="link-btn" id="how-to-btn" type="button" aria-label="사용방법 보기">사용방법 보기</button>

      <input type="file" id="file-input" accept="image/*" hidden />
    </section>
  `;

  container.querySelector('#take-photo-btn').addEventListener('click', () => {
    setState({ photo: null }); // 예전에 골랐던 파일이 남아있지 않게 초기화 - 진짜 카메라로 가야 함
    navigate('/camera');
  });
  container.querySelector('#pick-photo-btn').addEventListener('click', () => {
    container.querySelector('#file-input').click();
  });
  container.querySelector('#file-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setState({ photo: { blob: file, previewUrl: URL.createObjectURL(file) } });
    navigate('/camera'); // photo-processing.js가 이미 사진이 있는 걸 보고 카메라 없이 바로 인식 단계로 넘어감
  });
  container.querySelector('#how-to-btn').addEventListener('click', () => {
    console.log('사용방법 보기');
  });
}