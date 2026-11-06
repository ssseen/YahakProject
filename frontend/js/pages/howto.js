import { navigate } from '../router.js';
import { speak, stopSpeaking } from '../tts.js';

// 사용방법: 한 장씩 넘겨 보는 화면 (이전 / 다음, 옆으로 밀어서도 넘김)
//
// 그림 넣는 법: frontend/image/ 에 howto1.png, howto2.png, howto3.png ... 순서대로 넣으면 끝.
//   - 몇 장이든 1번부터 빠진 번호 없이 이어진 만큼 자동으로 보여 준다 (최대 MAX_IMAGES장)
//   - 그림이 하나도 없으면 아래 STEPS 글 안내를 한 장씩 보여 준다
//
// 설명 문장: 아래 IMAGE_TEXT에 그림 순서대로 한 줄씩 적는다.
//   - 그림 아래에 글로 보이고(설정의 글자 크기를 따라감), '소리로 듣기'를 누르면 같은 문장을 읽어 준다
//   - 따옴표 '' 안에 적고 끝에 쉼표(,). 문장 안에 ' 를 쓰고 싶으면 \' 로 적기
//   - 비워 두거나 줄이 모자라면 그 장은 그림만 나옴
const MAX_IMAGES = 20;
const IMAGE_TEXT = [
  '처음에 학력을 골라 주세요. 나중에 설정에서 바꿀 수 있어요.', // 1 학력 선택
  '미리 찍어 둔 문제 사진이 있으면 \'문제 사진 가져오기\'를 누르세요.', // 2
  '지금 찍으려면 \'문제 사진 찍기\'를 누르세요.', // 3
  '모르는 문제를 손가락으로 짚고, 아래 동그라미 버튼을 눌러 찍으세요.', // 4 촬영
  '궁금한 것을 말씀하세요. 다 말씀하시면 네모 버튼을 누르세요.', // 5 녹음
  '해설을 기다리는 동안 퀴즈를 풀어 보세요.', // 6 대기 퀴즈
  '해설이 준비되면 \'해설 보기\'를 누르세요.', // 7 팝업
  '해설을 천천히 읽어 드려요. 다시 듣고 싶은 문장은 손가락으로 누르세요.', // 8 해설
  '오른쪽 위 \'설정\'에서 글자 크기, 읽어주는 속도, 학력을 바꿀 수 있어요.', // 9 설정
  '\'비슷한 문제 풀어보기\'를 누르면 같은 유형의 기출 문제를 풀 수 있어요.', // 10
  '더 풀고 싶으면 \'더 풀어보기\'를 누르세요.', // 11
  '다 풀었으면 \'처음으로\'를 눌러 새 문제를 찍으세요.', // 12
  '영어 문제에서 모르는 단어를 누르면 뜻을 알려 드려요.', // 13 영어 단어
  '수학 문제는 한 단계씩 풀어 드려요. \'다음\'을 눌러 넘기세요.', // 14 수학 단계
];

const STEPS = [
  {
    title: '문제 사진 찍기',
    body: "'문제 사진 찍기'를 누르세요. 모르는 문제를 손가락으로 짚은 채로, 네모 칸 안에 문제가 들어오게 찍어요.",
    tip: "밝은 곳에서 찍으면 더 잘 알아봐요. 미리 찍어 둔 사진은 '문제 사진 가져오기'로 불러와요.",
  },
  {
    title: '말로 물어보기',
    body: '마이크 버튼을 누르고 궁금한 것을 편하게 말하세요. 말씀이 끝나면 버튼을 한 번 더 누르세요.',
    tip: "예: '이거 왜 답이 3번이야?'",
  },
  {
    title: '해설 듣기',
    body: '해설을 천천히 읽어 드려요. 다시 듣고 싶은 문장은 손가락으로 누르세요.',
    tip: '해설을 기다리는 동안 퀴즈를 풀 수 있어요.',
  },
  {
    title: '비슷한 문제 풀기',
    body: "'비슷한 문제 풀어보기'를 누르면 같은 유형의 기출 문제를 풀어 볼 수 있어요.",
    tip: "'처음으로'를 누르면 새 문제를 찍을 수 있어요. 오른쪽 위 '설정'에서 글자 크기, 읽어주는 속도, 학력을 바꿀 수 있어요.",
  },
];

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// 화면에 보일 때만: 따옴표로 묶은 버튼 이름('문제 사진 찍기' 등)은 중간에서 줄이 안 갈리게
function keepQuoted(s) {
  return s.replace(/'[^']+'/g, (m) => m.replace(/ /g, ' '));
}

// howto1.png부터 차례로 있는지 확인해서, 빠진 번호 앞까지의 장수를 돌려준다
function countImages() {
  const probe = (n) => new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src = `image/howto${n}.png`;
  });
  const checks = Array.from({ length: MAX_IMAGES }, (_, i) => probe(i + 1));
  return Promise.all(checks).then((found) => {
    const firstMissing = found.indexOf(false);
    return firstMissing === -1 ? MAX_IMAGES : firstMissing;
  });
}

export function renderHowto(container) {
  container.innerHTML = `
    <section class="howto-screen">
      <h1 class="howto-title">사용방법</h1>
      <p class="howto-loading">불러오는 중...</p>
    </section>
  `;
  window.addEventListener('hashchange', stopSpeaking, { once: true }); // 화면을 떠나면 읽기 중지

  countImages().then((imageCount) => {
    if (!container.querySelector('.howto-loading')) return; // 그새 다른 화면으로 갔음
    const pages = imageCount > 0
      ? Array.from({ length: imageCount }, (_, i) => ({ image: `image/howto${i + 1}.png`, text: IMAGE_TEXT[i] || '', voice: IMAGE_TEXT[i] || '' }))
      : STEPS.map((s, i) => ({ step: s, num: i + 1, voice: `${i + 1}번, ${s.title}. ${s.body} ${s.tip}` }));
    mountPager(container, pages);
  });
}

function mountPager(container, pages) {
  let index = 0;
  let playing = false;

  container.innerHTML = `
    <section class="howto-screen">
      <h1 class="visually-hidden">사용방법</h1>
      <div class="howto-page" id="howto-page"></div>
      <div class="howto-meta">
        <button type="button" class="howto-listen" id="howto-listen">소리로 듣기</button>
        <p class="howto-count" id="howto-count"></p>
      </div>
      <div class="howto-nav">
        <button type="button" class="howto-prev" id="howto-prev">이전</button>
        <button type="button" class="howto-next" id="howto-next">다음</button>
      </div>
    </section>
  `;

  const pageEl = container.querySelector('#howto-page');
  const listenBtn = container.querySelector('#howto-listen');
  const countEl = container.querySelector('#howto-count');
  const prevBtn = container.querySelector('#howto-prev');
  const nextBtn = container.querySelector('#howto-next');

  function stopVoice() {
    if (playing) stopSpeaking();
    playing = false;
    listenBtn.textContent = '소리로 듣기';
  }

  function show() {
    stopVoice();
    const page = pages[index];
    if (page.image) {
      pageEl.innerHTML = `
        <img class="howto-image" src="${page.image}" alt="사용방법 ${index + 1}번째 그림" />
        ${page.text ? `<p class="howto-caption">${escapeHtml(keepQuoted(page.text))}</p>` : ''}
      `;
    } else {
      const s = page.step;
      pageEl.innerHTML = `
        <div class="howto-step">
          <div class="howto-step-head">
            <span class="howto-num">${page.num}</span>
            <h2>${escapeHtml(s.title)}</h2>
          </div>
          <p>${escapeHtml(keepQuoted(s.body))}</p>
          <p class="howto-tip">${escapeHtml(keepQuoted(s.tip))}</p>
        </div>
      `;
    }
    listenBtn.hidden = !page.voice;
    countEl.textContent = `${index + 1} / ${pages.length}`;
    prevBtn.style.visibility = index === 0 ? 'hidden' : 'visible'; // 자리는 남겨서 다음 버튼 위치 고정
    const last = index === pages.length - 1;
    nextBtn.textContent = last ? '시작하기' : '다음';
    nextBtn.classList.toggle('is-start', last);
  }

  function go(delta) {
    const next = index + delta;
    if (next < 0) return;
    if (next >= pages.length) {
      stopVoice();
      navigate('/menu');
      return;
    }
    index = next;
    show();
    window.scrollTo(0, 0);
  }

  prevBtn.addEventListener('click', () => go(-1));
  nextBtn.addEventListener('click', () => go(1));

  listenBtn.addEventListener('click', () => {
    if (playing) {
      stopVoice();
      return;
    }
    speak(pages[index].voice);
    playing = true;
    listenBtn.textContent = '그만 듣기';
  });

  // 옆으로 밀어서 넘기기 (세로 움직임이 더 크면 무시 - 스크롤과 헷갈리지 않게)
  let startX = null;
  let startY = null;
  pageEl.addEventListener('touchstart', (e) => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }, { passive: true });
  pageEl.addEventListener('touchend', (e) => {
    if (startX === null) return;
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    startX = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0 && index < pages.length - 1) go(1); // 마지막 장에서 밀어도 메뉴로 나가지는 않음
      else if (dx > 0) go(-1);
    }
  });

  show();
}
